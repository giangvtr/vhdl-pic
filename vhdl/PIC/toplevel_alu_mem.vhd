LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
USE work.alu_pkg.ALL;

entity toplevel_alu_mem is
    generic(
        DATA_WIDTH : integer := 8;
        ADDR_WIDTH : integer := 7
    );
    Port ( 
        clk:            in std_logic;
        addr:           in std_logic_vector(ADDR_WIDTH-1 downto 0);
        op:             in alu_op;
        w_in:           in std_logic_vector(DATA_WIDTH-1 downto 0);
        mem_re:         in std_logic;
        mem_we:         in std_logic;
        bit_select:     in std_logic_vector(2 downto 0);
        mem_data_out:   out std_logic_vector(DATA_WIDTH-1 downto 0)
    );
end toplevel_alu_mem;

architecture rtl of toplevel_alu_mem is
    -- Internal signals
    signal mem_dout      : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal status_aluout : std_logic_vector(2 downto 0);
    signal result_aluout : std_logic_vector(7 downto 0);
    signal status_dout   : std_logic_vector(2 downto 0);

    component alu is
        port(
            op         : in  alu_op;
            w_in       : in  std_logic_vector(7 downto 0);
            f_in       : in  std_logic_vector(7 downto 0);
            bit_sel    : in  std_logic_vector(2 downto 0);
            status_in  : in  std_logic_vector(2 downto 0);
            result     : out std_logic_vector(7 downto 0);
            status_out : out std_logic_vector(2 downto 0)
        );
    end component;

    component dpram is
        port(
            clk      : IN  std_logic;
            we       : IN  std_logic;
            re       : IN  std_logic;
            addr     : IN  std_logic_vector(6 DOWNTO 0);
            data_in  : IN  std_logic_vector(7 DOWNTO 0);
            d_status : IN  std_logic_vector(2 DOWNTO 0);
            data_out : OUT std_logic_vector(7 DOWNTO 0);
            status   : OUT std_logic_vector(2 DOWNTO 0)
        );
    end component;

begin
    alu_inst: alu 
    port map (
        op         => op,
        w_in       => w_in,
        f_in       => mem_dout,
        bit_sel    => bit_select,
        status_in  => status_dout,
        result     => result_aluout,
        status_out => status_aluout
    );

    dpram_inst: dpram 
    port map (
        clk      => clk,
        we       => mem_we,
        re       => mem_re,
        addr     => addr,
        data_in  => result_aluout,
        d_status => status_aluout,
        data_out => mem_dout,
        status   => status_dout
    );

    mem_data_out <= mem_dout;

end rtl;