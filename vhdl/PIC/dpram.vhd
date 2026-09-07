LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
USE ieee.numeric_std.ALL;

ENTITY dpram IS
    GENERIC(
        DATA_WIDTH : integer := 8;
        ADDR_WIDTH : integer := 7   -- 128 locations
    );
    PORT ( 
        clk      : IN  std_logic;
        we       : IN  std_logic;                         -- Write Enable
        re       : IN  std_logic;                         -- Read Enable
        addr     : IN  std_logic_vector(6 DOWNTO 0);      -- Address bus
        data_in  : IN  std_logic_vector(7 DOWNTO 0);      -- Data from ALU result
        d_status : IN  std_logic_vector(2 DOWNTO 0);      -- {Z, DC, C} from ALU
        data_out : OUT std_logic_vector(7 DOWNTO 0);      -- Synchronous Read
        status   : OUT std_logic_vector(2 DOWNTO 0)       -- Asynchronous Status output
    );
END dpram;

ARCHITECTURE rtl OF dpram IS
    TYPE ram_type IS ARRAY (0 TO (2**ADDR_WIDTH)-1) OF std_logic_vector(DATA_WIDTH-1 DOWNTO 0);
    SIGNAL ram : ram_type := (OTHERS => (OTHERS => '0'));
    
    -- Constant for the STATUS register address (0x03 in PIC16F84A)
    CONSTANT STATUS_ADDR : integer := 3;
BEGIN

    -- ---------------------------------------------------------
    -- Synchronous Write and Synchronous Read Logic
    -- ---------------------------------------------------------
    PROCESS(clk)
    BEGIN
        IF rising_edge(clk) THEN
            -- Write Logic
            IF we = '1' THEN
                ram(to_integer(unsigned(addr))) <= data_in;
                -- Only update Z, DC, C if we aren't explicitly overwriting the whole STATUS reg
                IF to_integer(unsigned(addr)) /= STATUS_ADDR THEN
                    ram(STATUS_ADDR)(2 DOWNTO 0) <= d_status;
                END IF;
            END IF;

            -- Synchronous Read Logic (Requirement: updated only when re=1)
            IF re = '1' THEN
                data_out <= ram(to_integer(unsigned(addr)));
            END IF;
        END IF;
    END PROCESS;

    status <= ram(STATUS_ADDR)(2 DOWNTO 0);

END ARCHITECTURE rtl;