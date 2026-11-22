# cocotb self-checking testbench for the PIC core.
# Complements (does not replace) the file-driven VHDL testbench in
# vhdl/PIC/tb_pic.vhd / simulation/PIC/Makefile.
#
# Usage:
#   pip install -r requirements.txt
#   make
#
# PIC_RANDOM_INSTRUCTIONS / PIC_RANDOM_SEED (env vars) tune the randomized
# stress test; see tests/test_pic.py.

SIM ?= ghdl
TOPLEVEL_LANG = vhdl

# GHDL's VPI re-embeds a Python interpreter that, on some systems (e.g. a
# conda/miniconda python3), does not see the user site-packages directory
# where `pip install --user` (or a plain `pip install` without a venv)
# puts cocotb -- causing "ModuleNotFoundError: No module named 'pygpi'" at
# runtime even though `pip show cocotb` succeeds. Force it onto the path.
export PYTHONPATH := $(shell python3 -c "import site; print(site.getusersitepackages())"):$(PYTHONPATH)

PIC_VHDL_DIR := $(abspath ../vhdl/PIC)

VHDL_SOURCES = \
	$(PIC_VHDL_DIR)/alu.vhd \
	$(PIC_VHDL_DIR)/dpram.vhd \
	$(PIC_VHDL_DIR)/state_machine.vhd \
	$(PIC_VHDL_DIR)/pic.vhd

TOPLEVEL = pic
MODULE = tests.test_pic

EXTRA_ARGS += --std=08

include $(shell cocotb-config --makefiles)/Makefile.sim
