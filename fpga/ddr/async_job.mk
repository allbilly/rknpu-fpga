PYTHON ?= python3
RK_ASYNC_JOB_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
.PHONY: iverilog verilator
iverilog:
	cd "$(RK_ASYNC_JOB_ROOT)" && $(PYTHON) tools/ddr/run_async_job.py --simulator iverilog --out "$(RK_ASYNC_JOB_OUT)"
verilator:
	cd "$(RK_ASYNC_JOB_ROOT)" && $(PYTHON) tools/ddr/run_async_job.py --simulator verilator --out "$(RK_ASYNC_JOB_OUT)"
