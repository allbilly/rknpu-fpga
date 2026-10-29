PYTHON ?= python3
RK_FABRIC_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: test controls verilator iverilog full-span
test: controls verilator iverilog
controls:
	cd "$(RK_FABRIC_ROOT)" && $(PYTHON) -m unittest discover -s tests/ddr/fabric -v
verilator:
	cd "$(RK_FABRIC_ROOT)" && $(PYTHON) tools/ddr/run_fabric.py --simulator verilator
iverilog:
	cd "$(RK_FABRIC_ROOT)" && $(PYTHON) tools/ddr/run_fabric.py --simulator iverilog
full-span:
	cd "$(RK_FABRIC_ROOT)" && $(PYTHON) tools/ddr/run_fabric.py --simulator verilator --mode full-span
