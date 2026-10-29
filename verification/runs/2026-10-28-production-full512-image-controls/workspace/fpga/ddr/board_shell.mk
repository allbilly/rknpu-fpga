PYTHON ?= python3
RK_DDR_SHELL_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: controls prepare
controls:
	cd "$(RK_DDR_SHELL_ROOT)" && $(PYTHON) -m unittest discover -s tests/ddr/board_shell -v
prepare:
	@test -n "$(RK_DDR_PLATFORM)" -a -n "$(RK_DDR_MIG_XDC)" -a -n "$(RK_DDR_SHELL_OUT)"
	cd "$(RK_DDR_SHELL_ROOT)" && $(PYTHON) tools/ddr/prepare_ypcb_shell.py --platform "$(RK_DDR_PLATFORM)" --mig-xdc "$(RK_DDR_MIG_XDC)" --out "$(RK_DDR_SHELL_OUT)"
