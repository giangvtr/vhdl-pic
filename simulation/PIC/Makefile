# Makefile for running the GHDL simulation and analyze the resulting signals with GTKWave

# the path of the vhdl directory relative to the Makefile
VHDL_PATH = ../../vhdl/PIC/

# the vhdl files you want to compile, need to be in order, entity first, testbench second
FILES =	$(VHDL_PATH)alu.vhd \
	    $(VHDL_PATH)dpram.vhd \
		$(VHDL_PATH)toplevel_alu_mem.vhd \
		$(VHDL_PATH)state_machine.vhd \
		$(VHDL_PATH)pic.vhd \
		$(VHDL_PATH)tb_pic.vhd

# testbench parameters
WORKDIR = work

# GHDL config
GHDL_CMD 	= ghdl
GHDL_FLAGS 	= --std=08 --workdir=$(WORKDIR)

# wave viewer config
WAVEFORM_VIEWER = gtkwave

all: clean make run view

make:
ifeq ($(strip $(TESTBENCH)),)
	echo "TESTBENCH missing. Call with TESTBENCH=<tb_entity_name>."
	exit 1
endif

	mkdir -p $(WORKDIR)
	$(GHDL_CMD) -a $(GHDL_FLAGS) $(FILES)
	$(GHDL_CMD) -e $(GHDL_FLAGS) $(TESTBENCH)

run:
	$(GHDL_CMD) -r $(GHDL_FLAGS) --workdir=$(WORKDIR) $(TESTBENCH) --wave=$(TESTBENCH).ghw --stop-time=10us
	mv $(TESTBENCH).ghw $(WORKDIR)/

view:
	$(WAVEFORM_VIEWER) --dump=$(WORKDIR)/$(TESTBENCH).ghw

clean:
	rm -rf $(WORKDIR)
