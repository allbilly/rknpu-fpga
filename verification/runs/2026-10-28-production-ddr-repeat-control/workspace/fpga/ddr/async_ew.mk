PYTHON ?= python3
RK_ASYNC_EW_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
.PHONY: iverilog verilator
iverilog:
	cd "$(RK_ASYNC_EW_ROOT)" && $(PYTHON) tools/ddr/run_async_ew.py --simulator iverilog --out "$(RK_ASYNC_EW_OUT)"
verilator:
	cd "$(RK_ASYNC_EW_ROOT)" && $(PYTHON) tools/ddr/run_async_ew.py --simulator verilator --out "$(RK_ASYNC_EW_OUT)"
