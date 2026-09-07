LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
USE ieee.numeric_std.ALL;

PACKAGE alu_pkg IS
    -- Complete PIC instruction set operation types (35 instructions)
    TYPE alu_op IS (
        -- Byte-Oriented File Register Operations (14 instructions)
        OP_ADDWF, OP_ANDWF, OP_CLRF,   OP_CLRW,  OP_COMF,  OP_DECF,
        OP_DECFSZ, OP_INCF, OP_INCFSZ, OP_IORWF, OP_MOVF,  OP_MOVWF,
        OP_RLF,   OP_RRF,   OP_SUBWF,  OP_SWAPF, OP_XORWF,
        
        -- Bit-Oriented File Register Operations (4 instructions)
        OP_BCF,   OP_BSF,   OP_BTFSC,  OP_BTFSS,
        
        -- Literal and Control Operations (12 instructions)
        OP_ADDLW, OP_ANDLW, OP_IORLW,  OP_MOVLW, OP_SUBLW, OP_XORLW,
        OP_GOTO,  OP_CALL,  OP_RETURN, OP_RETLW, OP_NOP
    );
END alu_pkg;

LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
USE ieee.numeric_std.ALL;
USE work.alu_pkg.ALL;

ENTITY alu IS
    PORT (
        op         : in  alu_op;                       -- Operation from decoder
        w_in       : in  std_logic_vector(7 downto 0);  -- Working Register input [cite: 62]
        f_in       : in  std_logic_vector(7 downto 0);  -- File Register or Literal input [cite: 102]
        bit_sel    : in  std_logic_vector(2 downto 0);  -- Bit position (bits 7-9 of opcode) [cite: 125]
        status_in  : in  std_logic_vector(2 downto 0);  -- Current {Z, DC, C} [cite: 63, 177]
        result     : out std_logic_vector(7 downto 0);  -- ALU result
        status_out : out std_logic_vector(2 downto 0)   -- Updated {Z, DC, C} [cite: 63, 177]
    );
END alu;

ARCHITECTURE Behavioral OF alu IS
BEGIN
    PROCESS (op, w_in, f_in, bit_sel, status_in)
        VARIABLE v_res      : unsigned(7 DOWNTO 0);
        VARIABLE v_status   : std_logic_vector(2 DOWNTO 0);
        VARIABLE v_add_res  : unsigned(8 DOWNTO 0);
        VARIABLE v_dc_sum   : unsigned(4 DOWNTO 0);
        VARIABLE v_bit_idx  : integer;
    BEGIN
        -- Defaults
        v_res     := (others => '0');
        v_status  := status_in; -- Default: status remains unchanged
        v_bit_idx := to_integer(unsigned(bit_sel));

        CASE op IS
            -- Byte-Oriented Operations
            
            -- Addition: ADDLW, ADDWF
            WHEN OP_ADDLW | OP_ADDWF =>
                v_add_res := unsigned('0' & w_in) + unsigned('0' & f_in);
                v_dc_sum  := unsigned('0' & w_in(3 downto 0)) + unsigned('0' & f_in(3 downto 0));
                v_res     := v_add_res(7 downto 0);
                
                v_status(0) := v_add_res(8);             -- Carry (C)
                v_status(1) := v_dc_sum(4);              -- Digit Carry (DC)
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF; -- Zero (Z)

            -- Subtraction: SUBLW, SUBWF
            -- Note: PIC subtraction is f - w, but SUBLW is k - w
            WHEN OP_SUBLW | OP_SUBWF =>
                v_add_res := unsigned('0' & f_in) - unsigned('0' & w_in);
                v_dc_sum  := unsigned('0' & f_in(3 downto 0)) - unsigned('0' & w_in(3 downto 0));
                v_res     := v_add_res(7 downto 0);
                
                v_status(0) := NOT v_add_res(8);         -- Borrow (C is inverted in PIC)
                v_status(1) := NOT v_dc_sum(4);          -- Digit Borrow (DC is inverted)
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            -- Logical: AND
            WHEN OP_ANDLW | OP_ANDWF =>
                v_res := unsigned(w_in AND f_in);
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            -- Logical: IOR (Inclusive OR)
            WHEN OP_IORLW | OP_IORWF =>
                v_res := unsigned(w_in OR f_in);
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            -- Logical: XOR
            WHEN OP_XORLW | OP_XORWF =>
                v_res := unsigned(w_in XOR f_in);
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            -- Clear/Move Operations
            WHEN OP_CLRF | OP_CLRW =>
                v_res := (others => '0');
                v_status(2) := '1'; -- Z flag is set

            WHEN OP_MOVF =>
                v_res := unsigned(f_in);
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            WHEN OP_MOVWF =>
                v_res := unsigned(w_in);
                -- MOVWF does not affect any flags

            WHEN OP_MOVLW =>
                v_res := unsigned(f_in);  -- f_in contains literal in this context

            -- Complement (Invert bits)
            WHEN OP_COMF =>
                v_res := unsigned(NOT f_in);
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            WHEN OP_INCF =>
                v_res := unsigned(f_in) + 1;
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            WHEN OP_INCFSZ =>
                v_res := unsigned(f_in) + 1;
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            WHEN OP_DECF =>
                v_res := unsigned(f_in) - 1;
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            WHEN OP_DECFSZ =>
                v_res := unsigned(f_in) - 1;
                IF v_res = 0 THEN v_status(2) := '1'; ELSE v_status(2) := '0'; END IF;

            -- Bit-Oriented Operations
            WHEN OP_BCF =>
                v_res := unsigned(f_in);
                v_res(v_bit_idx) := '0';

            WHEN OP_BSF =>
                v_res := unsigned(f_in);
                v_res(v_bit_idx) := '1';

            WHEN OP_BTFSC =>
                v_res := unsigned(f_in);
                -- Test decision made elsewhere, no result change

            WHEN OP_BTFSS =>
                v_res := unsigned(f_in);
                -- Test decision made elsewhere, no result change

            -- Rotate Operations
            WHEN OP_RLF =>
                v_res := unsigned(f_in(6 downto 0) & status_in(0));
                v_status(0) := f_in(7);

            WHEN OP_RRF =>
                v_res := unsigned(status_in(0) & f_in(7 downto 1));
                v_status(0) := f_in(0);

            -- Swap nibbles
            WHEN OP_SWAPF =>
                v_res := unsigned(f_in(3 downto 0) & f_in(7 downto 4));

            -- Return with Literal: load literal into W (like MOVLW) and pop PC
            WHEN OP_RETLW =>
                v_res := unsigned(f_in);  -- f_in contains literal

            -- Control Flow (these don't generate ALU results, handled at PC level)
            WHEN OP_GOTO | OP_CALL | OP_RETURN =>
                v_res := (others => '0');

            -- No Operation
            WHEN OP_NOP =>
                v_res := (others => '0');

            WHEN OTHERS =>
                v_res := (others => '0');
        END CASE;

        result     <= std_logic_vector(v_res);
        status_out <= v_status;
    END PROCESS;
END Behavioral;