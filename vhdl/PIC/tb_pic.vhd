LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
USE ieee.numeric_std.ALL;
USE std.textio.ALL;
USE ieee.std_logic_textio.ALL;

ENTITY tb_pic IS
END ENTITY tb_pic;

ARCHITECTURE test OF tb_pic IS
    -- Signals to connect to the PIC
    SIGNAL clk    : std_logic := '0';
    SIGNAL reset  : std_logic := '0';
    SIGNAL opcode : std_logic_vector(13 DOWNTO 0) := (OTHERS => '0');
    
    
    SIGNAL program_counter    : std_logic_vector(12 DOWNTO 0);
    SIGNAL instruction_return : std_logic;

    -- File handles
    FILE file_INPUT  : text;
    FILE file_OUTPUT : text;

    -- Clock generation (e.g., 10MHz)
    CONSTANT clk_period : time := 100 ns;

BEGIN

    -- Instantiate the Unit Under Test (UUT)
    UUT: ENTITY work.PIC
        PORT MAP (
            clk                => clk,
            reset              => reset,
            opcode             => opcode,
            program_counter    => program_counter,
            instruction_return => instruction_return
        );

    -- Clock Process
    clk_process : PROCESS
    BEGIN
        clk <= '0';
        WAIT FOR clk_period/2;
        clk <= '1';
        WAIT FOR clk_period/2;
    END PROCESS;

    -- Stimulus Process
    STIMULUS : PROCESS
        VARIABLE v_iline  : line;
        VARIABLE v_oline  : line;
        VARIABLE v_opcode : std_logic_vector(13 DOWNTO 0);
    BEGIN
        reset  <= '1';
        opcode <= (OTHERS => '0');
        WAIT FOR 100 ns; 
        reset <= '0';
        WAIT UNTIL rising_edge(clk);

        FILE_OPEN(file_INPUT, "input.txt", READ_MODE);
        FILE_OPEN(file_OUTPUT, "output.txt", WRITE_MODE);

        WHILE NOT endfile(file_INPUT) LOOP
            readline(file_INPUT, v_iline);
            -- Skip empty lines or comments starting with #
            IF v_iline.all'length = 0 OR v_iline.all(1) = '#' THEN 
                NEXT; 
            END IF;

            read(v_iline, v_opcode);
            opcode <= v_opcode;
            
            -- Wait for the 4-cycle execution to finish signaled by instruction_return
            WAIT UNTIL (rising_edge(clk) AND instruction_return = '1') FOR 1 ms;
            WAIT FOR 1 ns; -- Let signals settle for logging

            write(v_oline, string'("OPCODE="));
            write(v_oline, v_opcode);
            write(v_oline, string'(" PC="));
            write(v_oline, to_integer(unsigned(program_counter)));
            writeline(file_OUTPUT, v_oline);
        END LOOP;

        FILE_CLOSE(file_INPUT);
        FILE_CLOSE(file_OUTPUT);
        REPORT "Simulation complete!";
        WAIT;
    END PROCESS;

END ARCHITECTURE test;