PYTHON ?= python3
RK_MONITOR_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: test controls portable-verilator portable-iverilog vendor-test vendor-verilator vendor-iverilog
test: controls portable-verilator portable-iverilog
controls:
	cd "$(RK_MONITOR_ROOT)" && $(PYTHON) -m unittest discover -s tests/ddr/monitor -v
portable-verilator:
	cd "$(RK_MONITOR_ROOT)" && $(PYTHON) tools/ddr/run_monitor.py --simulator verilator
portable-iverilog:
	cd "$(RK_MONITOR_ROOT)" && $(PYTHON) tools/ddr/run_monitor.py --simulator iverilog
vendor-test: controls vendor-verilator vendor-iverilog
vendor-verilator:
	@test -n "$(MIG_ARCHIVE)" || { echo 'Set MIG_ARCHIVE to the pinned existing XDMA ZIP.' >&2; exit 2; }
	cd "$(RK_MONITOR_ROOT)" && $(PYTHON) tools/ddr/run_monitor.py --simulator verilator --archive "$(MIG_ARCHIVE)"
vendor-iverilog:
	@test -n "$(MIG_ARCHIVE)" || { echo 'Set MIG_ARCHIVE to the pinned existing XDMA ZIP.' >&2; exit 2; }
	cd "$(RK_MONITOR_ROOT)" && $(PYTHON) tools/ddr/run_monitor.py --simulator iverilog --archive "$(MIG_ARCHIVE)"
