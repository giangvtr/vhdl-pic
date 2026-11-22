LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
USE ieee.numeric_std.ALL;
USE work.alu_pkg.ALL;

ENTITY PIC IS
    PORT (
        clk                : IN  std_logic;
        reset              : IN  std_logic;                                     -- MCLR (Active High)
        opcode             : IN  std_logic_vector(13 DOWNTO 0);
        status             : OUT std_logic_vector(2 DOWNTO 0);
        program_counter    : OUT std_logic_vector(12 DOWNTO 0);                
        instruction_return : OUT std_logic;                                    
        work_reg_dbg       : OUT std_logic_vector(7 DOWNTO 0)                    -- verification-only: exposes W
    );
END ENTITY PIC;

ARCHITECTURE rtl OF PIC IS

    -- Internal Architectural Registers
    SIGNAL pc_reg         : unsigned(12 DOWNTO 0) := (OTHERS => '0');
    SIGNAL work_reg       : std_logic_vector(7 DOWNTO 0) := (OTHERS => '0');
    SIGNAL status_reg     : std_logic_vector(2 DOWNTO 0) := (OTHERS => '0'); -- {Z, DC, C}

    -- Stack Signals (8-level deep, 13-bit wide)
    TYPE stack_type IS ARRAY (0 TO 7) OF unsigned(12 DOWNTO 0);
    SIGNAL stack      : stack_type := (OTHERS => (OTHERS => '0'));
    SIGNAL stack_ptr  : integer RANGE 0 TO 7 := 0;

    -- Interconnects from state machine
    SIGNAL sm_op        : alu_op;
    SIGNAL sm_addr      : std_logic_vector(6 DOWNTO 0);
    SIGNAL sm_jump_addr : std_logic_vector(10 DOWNTO 0);
    SIGNAL sm_lit       : std_logic_vector(7 DOWNTO 0);
    SIGNAL sm_bit_sel   : std_logic_vector(2 DOWNTO 0);
    SIGNAL sm_we_mem    : std_logic;
    SIGNAL sm_re_mem    : std_logic;
    SIGNAL sm_we_w      : std_logic;
    SIGNAL sm_instr_ret : std_logic;

    SIGNAL alu_result   : std_logic_vector(7 DOWNTO 0);
    SIGNAL alu_status   : std_logic_vector(2 DOWNTO 0);
    SIGNAL ram_dout     : std_logic_vector(7 DOWNTO 0);
    SIGNAL ram_status   : std_logic_vector(2 DOWNTO 0); -- unused but keeps dpram interface

    -- Control Signals
    SIGNAL force_nop    : std_logic := '0';
    SIGNAL alu_f_in     : std_logic_vector(7 DOWNTO 0);

BEGIN
    U_FSM: ENTITY work.state_machine
    PORT MAP (
        clk        => clk,
        reset      => reset,
        opcode     => opcode,
        force_nop  => force_nop,
        op         => sm_op,
        addr       => sm_addr,
        jump_addr  => sm_jump_addr,
        lit        => sm_lit,
        bit_sel    => sm_bit_sel,
        we_mem     => sm_we_mem,
        re_mem     => sm_re_mem,
        we_w       => sm_we_w,
        instr_ret  => sm_instr_ret
    );

    -- Mux for ALU input B
    alu_f_in <= sm_lit WHEN (sm_op = OP_MOVLW OR sm_op = OP_ADDLW OR
                                 sm_op = OP_SUBLW OR sm_op = OP_ANDLW OR
                                 sm_op = OP_IORLW OR sm_op = OP_XORLW OR
                                 sm_op = OP_RETLW)
                ELSE ram_dout;

    U_ALU: ENTITY work.alu
    PORT MAP (
        op         => sm_op,
        w_in       => work_reg,
        f_in       => alu_f_in,
        bit_sel    => sm_bit_sel,
        status_in  => status_reg,
        result     => alu_result,
        status_out => alu_status
    );

    U_RAM: ENTITY work.dpram
    PORT MAP (
        clk      => clk,
        we       => sm_we_mem,
        re       => sm_re_mem,
        addr     => sm_addr,
        data_in  => alu_result,
        d_status => alu_status,
        data_out => ram_dout,
        status   => ram_status
    );


    -- 2. Sequential Logic (PC, W-Reg, Status, Stack, Force-NOP)
    PROCESS(clk, reset)
        VARIABLE bit_test_result : std_logic;
        VARIABLE next_stack_ptr  : integer;
    BEGIN
        IF reset = '1' THEN
            pc_reg     <= (OTHERS => '0');
            stack_ptr  <= 0;
            force_nop  <= '0';
            status_reg <= (OTHERS => '0');

        ELSIF rising_edge(clk) THEN

    
            -- Write-back: update W register and/or status flags.
            -- sm_we_w / sm_we_mem are registered, guaranteed stable here.

            IF sm_we_w = '1' THEN
                work_reg   <= alu_result;
                status_reg <= alu_status;
            END IF;

            IF sm_we_mem = '1' THEN
                status_reg <= alu_status;
            END IF;

            -- Program Counter and control-flow logic.
            -- Triggered by sm_instr_ret
            IF sm_instr_ret = '1' THEN

                IF sm_op = OP_GOTO THEN
                    -- Unconditional branch: load target address, flush pipeline
                    pc_reg    <= unsigned("00" & sm_jump_addr);
                    force_nop <= '0';
                    
                ELSIF sm_op = OP_CALL THEN
                    -- Subroutine call: push return address, branch, flush
                    stack(stack_ptr) <= pc_reg + 1;
                    stack_ptr        <= (stack_ptr + 1) MOD 8;
                    pc_reg           <= unsigned("00" & sm_jump_addr);
                    force_nop        <= '0';
                ELSIF sm_op = OP_RETURN THEN
                    -- Return: pop stack
                    IF stack_ptr = 0 THEN
                        next_stack_ptr := 7;
                    ELSE
                        next_stack_ptr := stack_ptr - 1;
                    END IF;
                    stack_ptr <= next_stack_ptr;
                    pc_reg    <= stack(next_stack_ptr);
                    force_nop <= '0';

                ELSIF sm_op = OP_RETLW THEN
                    -- Return with literal: pop stack (W already loaded by ALU)
                    IF stack_ptr = 0 THEN
                        next_stack_ptr := 7;
                    ELSE
                        next_stack_ptr := stack_ptr - 1;
                    END IF;
                    stack_ptr <= next_stack_ptr;
                    pc_reg    <= stack(next_stack_ptr);
                    force_nop <= '0';

                ELSIF (sm_op = OP_DECFSZ OR sm_op = OP_INCFSZ) AND
                       alu_result = "00000000" THEN
                    -- Skip next instruction if result is zero
                    force_nop <= '1';
                    pc_reg    <= pc_reg + 2;

                ELSIF sm_op = OP_BTFSC THEN
                    -- Bit test, skip if clear
                    bit_test_result := ram_dout(to_integer(unsigned(sm_bit_sel)));
                    IF bit_test_result = '0' THEN
                        force_nop <= '1';
                        pc_reg    <= pc_reg + 2;
                    ELSE
                        force_nop <= '0';
                        pc_reg    <= pc_reg + 1;
                    END IF;

                ELSIF sm_op = OP_BTFSS THEN
                    -- Bit test, skip if set
                    bit_test_result := ram_dout(to_integer(unsigned(sm_bit_sel)));
                    IF bit_test_result = '1' THEN
                        force_nop <= '1';
                        pc_reg    <= pc_reg + 2;
                    ELSE
                        force_nop <= '0';
                        pc_reg    <= pc_reg + 1;
                    END IF;

                ELSE
                    -- Standard sequential instruction
                    pc_reg    <= pc_reg + 1;
                    force_nop <= '0';
                END IF;

            END IF;
        END IF;
    END PROCESS;

    -- Drive top-level ports from internal registers
    program_counter    <= std_logic_vector(pc_reg);
    status             <= status_reg;
    instruction_return <= sm_instr_ret;
    work_reg_dbg       <= work_reg;

END ARCHITECTURE rtl;