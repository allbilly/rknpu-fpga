PYTHON ?= python3
RK_ASYNC_MEM_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
.PHONY: iverilog verilator
iverilog:
	cd "$(RK_ASYNC_MEM_ROOT)" && $(PYTHON) tools/ddr/run_async_mem.py --simulator iverilog --out "$(RK_ASYNC_MEM_OUT)"
verilator:
	cd "$(RK_ASYNC_MEM_ROOT)" && $(PYTHON) tools/ddr/run_async_mem.py --simulator verilator --out "$(RK_ASYNC_MEM_OUT)"
