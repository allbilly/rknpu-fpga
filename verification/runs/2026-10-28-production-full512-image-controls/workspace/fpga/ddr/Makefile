PYTHON ?= python3
RK_DDR_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: test
test:
	cd "$(RK_DDR_ROOT)" && $(PYTHON) -m unittest discover -s tests/ddr -v
