LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
USE ieee.numeric_std.ALL;
USE work.alu_pkg.ALL;

ENTITY state_machine IS
    PORT (
        clk        : IN  std_logic;
        reset      : IN  std_logic;
        opcode     : IN  std_logic_vector(13 DOWNTO 0);
        force_nop  : IN  std_logic;

        -- Control Outputs (registered instruction fields plus combinatorial stage flags)
        op         : OUT alu_op;
        addr       : OUT std_logic_vector(6 DOWNTO 0);   -- 7-bit file register address
        jump_addr  : OUT std_logic_vector(10 DOWNTO 0);  -- 11-bit branch target (GOTO/CALL)
        lit        : OUT std_logic_vector(7 DOWNTO 0);   -- Literal k field for MOVLW/ADDLW/etc.
        bit_sel    : OUT std_logic_vector(2 DOWNTO 0);
        we_mem     : OUT std_logic;
        re_mem     : OUT std_logic;
        we_w       : OUT std_logic;
        instr_ret  : OUT std_logic
    );
END state_machine;

ARCHITECTURE behavioral OF state_machine IS
    TYPE state_type IS (iFetch, Mread, Execute, Mwrite);
    SIGNAL current_state, next_state : state_type;

    SIGNAL reg_op       : alu_op   := OP_NOP;
    SIGNAL reg_addr     : std_logic_vector(6  DOWNTO 0) := (OTHERS => '0');
    SIGNAL reg_jump     : std_logic_vector(10 DOWNTO 0) := (OTHERS => '0');
    SIGNAL reg_bit_sel  : std_logic_vector(2  DOWNTO 0) := (OTHERS => '0');
    SIGNAL reg_d        : std_logic := '0';
    SIGNAL reg_literal  : std_logic_vector(7  DOWNTO 0) := (OTHERS => '0');

    FUNCTION decode_op(inst : std_logic_vector(13 DOWNTO 0)) RETURN alu_op IS
        VARIABLE msbs  : std_logic_vector(5 DOWNTO 0);
        VARIABLE b1312 : std_logic_vector(1 DOWNTO 0);
        VARIABLE b1311 : std_logic_vector(2 DOWNTO 0);
        VARIABLE b1310 : std_logic_vector(3 DOWNTO 0);
        VARIABLE b118  : std_logic_vector(3 DOWNTO 0);
    BEGIN
        msbs  := inst(13 DOWNTO 8);
        b1312 := inst(13 DOWNTO 12);
        b1311 := inst(13 DOWNTO 11);
        b1310 := inst(13 DOWNTO 10);
        b118  := inst(11 DOWNTO 8);

        -- Byte-oriented (bits 13-8, and bit 7 for disambiguation)
        IF    msbs = "000111"                          THEN RETURN OP_ADDWF;
        ELSIF msbs = "000101"                          THEN RETURN OP_ANDWF;
        ELSIF msbs = "000000" AND inst(7) = '1'        THEN RETURN OP_MOVWF;  -- 00 0000 1fff ffff
        ELSIF msbs = "000001" AND inst(7) = '1'        THEN RETURN OP_CLRF;   -- 00 0001 1fff ffff
        ELSIF msbs = "000001" AND inst(7) = '0'        THEN RETURN OP_CLRW;   -- 00 0001 0xxx xxxx
        ELSIF msbs = "001001"                          THEN RETURN OP_COMF;
        ELSIF msbs = "000011"                          THEN RETURN OP_DECF;
        ELSIF msbs = "001011"                          THEN RETURN OP_DECFSZ;
        ELSIF msbs = "001010"                          THEN RETURN OP_INCF;
        ELSIF msbs = "001111"                          THEN RETURN OP_INCFSZ;
        ELSIF msbs = "000100"                          THEN RETURN OP_IORWF;
        ELSIF msbs = "001000"                          THEN RETURN OP_MOVF;
        ELSIF msbs = "001101"                          THEN RETURN OP_RLF;
        ELSIF msbs = "001100"                          THEN RETURN OP_RRF;
        ELSIF msbs = "000010"                          THEN RETURN OP_SUBWF;
        ELSIF msbs = "001110"                          THEN RETURN OP_SWAPF;
        ELSIF msbs = "000110"                          THEN RETURN OP_XORWF;
        -- Bit-oriented (bits 13-10)
        ELSIF b1310 = "0100"                           THEN RETURN OP_BCF;
        ELSIF b1310 = "0101"                           THEN RETURN OP_BSF;
        ELSIF b1310 = "0110"                           THEN RETURN OP_BTFSC;
        ELSIF b1310 = "0111"                           THEN RETURN OP_BTFSS;
        -- Literal / control (bits 13-12 = "11")
        ELSIF b1312 = "11" THEN
            CASE b118 IS
                WHEN "1110" | "1111"                   => RETURN OP_ADDLW;
                WHEN "1001"                            => RETURN OP_ANDLW;
                WHEN "1000"                            => RETURN OP_IORLW;
                WHEN "0000"|"0001"|"0010"|"0011"       => RETURN OP_MOVLW;
                WHEN "0100"|"0101"|"0110"|"0111"       => RETURN OP_RETLW;
                WHEN "1100" | "1101"                   => RETURN OP_SUBLW;
                WHEN "1010"                            => RETURN OP_XORLW;
                WHEN OTHERS                            => RETURN OP_NOP;
            END CASE;
        ELSIF b1311 = "101"                            THEN RETURN OP_GOTO;
        ELSIF b1311 = "100"                            THEN RETURN OP_CALL;
        ELSIF inst  = "00000000001000"                 THEN RETURN OP_RETURN;
        ELSE                                                RETURN OP_NOP;
        END IF;
    END FUNCTION;

    FUNCTION op_needs_memread(op_in : alu_op) RETURN boolean IS
    BEGIN
        RETURN op_in /= OP_MOVLW  AND op_in /= OP_ADDLW  AND
               op_in /= OP_ANDLW  AND op_in /= OP_IORLW  AND
               op_in /= OP_SUBLW  AND op_in /= OP_XORLW  AND
               op_in /= OP_RETLW  AND op_in /= OP_GOTO   AND
               op_in /= OP_CALL   AND op_in /= OP_RETURN  AND
               op_in /= OP_CLRW   AND op_in /= OP_NOP;
    END FUNCTION;

BEGIN

    -- -------------------------------------------------------------------
    -- Single registered process: state transitions + control output
    -- generation.  All outputs are flip-flop driven, eliminating any
    -- delta-cycle race conditions with the pic.vhd sequential process.
    -- -------------------------------------------------------------------
    PROCESS(clk, reset)
    BEGIN
        IF reset = '1' THEN
            current_state <= iFetch;
            reg_op        <= OP_NOP;
            reg_addr      <= (OTHERS => '0');
            reg_jump      <= (OTHERS => '0');
            reg_bit_sel   <= (OTHERS => '0');
            reg_d         <= '0';
            reg_literal   <= (OTHERS => '0');

        ELSIF rising_edge(clk) THEN
            current_state <= next_state;

            IF current_state = iFetch THEN
                IF force_nop = '1' THEN
                    reg_op <= OP_NOP;
                ELSE
                    reg_op      <= decode_op(opcode);
                    reg_addr    <= opcode(6 DOWNTO 0);
                    reg_jump    <= opcode(10 DOWNTO 0);
                    reg_bit_sel <= opcode(9 DOWNTO 7);
                    reg_d       <= opcode(7);
                    reg_literal <= opcode(7 DOWNTO 0);
                END IF;
            END IF;
        END IF;
    END PROCESS;

    -- Combinatorial control outputs based on the current pipeline stage
    PROCESS(current_state, reg_op, reg_d)
    BEGIN
        we_mem    <= '0';
        re_mem    <= '0';
        we_w      <= '0';
        instr_ret <= '0';

        CASE current_state IS
            WHEN Mread =>
                IF op_needs_memread(reg_op) THEN
                    re_mem <= '1';
                END IF;

            WHEN Mwrite =>
                instr_ret <= '1';
                IF reg_op /= OP_NOP THEN
                    CASE reg_op IS
                        WHEN OP_MOVLW | OP_ADDLW | OP_ANDLW | OP_IORLW |
                             OP_SUBLW  | OP_XORLW | OP_RETLW | OP_CLRW  =>
                            we_w <= '1';

                        WHEN OP_MOVWF | OP_CLRF =>
                            we_mem <= '1';

                        WHEN OP_ADDWF | OP_ANDWF | OP_COMF  | OP_DECF  |
                             OP_INCF  | OP_IORWF | OP_MOVF  | OP_RLF   |
                             OP_RRF   | OP_SUBWF | OP_SWAPF | OP_XORWF =>
                            IF reg_d = '1' THEN
                                we_mem <= '1';
                            ELSE
                                we_w <= '1';
                            END IF;

                        WHEN OP_BCF | OP_BSF =>
                            we_mem <= '1';

                        WHEN OP_DECFSZ | OP_INCFSZ =>
                            IF reg_d = '1' THEN
                                we_mem <= '1';
                            ELSE
                                we_w <= '1';
                            END IF;

                        WHEN OTHERS =>
                            NULL;
                    END CASE;
                END IF;

            WHEN OTHERS =>
                NULL;
        END CASE;
    END PROCESS;

    -- Pure combinatorial next-state logic
    PROCESS(current_state)
    BEGIN
        CASE current_state IS
            WHEN iFetch  => next_state <= Mread;
            WHEN Mread   => next_state <= Execute;
            WHEN Execute => next_state <= Mwrite;
            WHEN Mwrite  => next_state <= iFetch;
        END CASE;
    END PROCESS;

    -- Drive ports from registered instruction fields
    op        <= reg_op;
    addr      <= reg_addr;
    jump_addr <= reg_jump;
    lit       <= reg_literal;
    bit_sel   <= reg_bit_sel;

END behavioral;