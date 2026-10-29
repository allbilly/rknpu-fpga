PYTHON ?= python3
RK_LIFECYCLE_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: test controls verilator iverilog
test: controls verilator iverilog
controls:
	cd "$(RK_LIFECYCLE_ROOT)" && $(PYTHON) -m unittest discover -s tests/ddr/lifecycle -v
verilator:
	cd "$(RK_LIFECYCLE_ROOT)" && $(PYTHON) tools/ddr/run_lifecycle.py --simulator verilator
iverilog:
	cd "$(RK_LIFECYCLE_ROOT)" && $(PYTHON) tools/ddr/run_lifecycle.py --simulator iverilog
