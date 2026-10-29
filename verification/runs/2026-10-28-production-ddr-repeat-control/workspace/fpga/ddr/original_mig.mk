PYTHON ?= python3
RK_ORIGINAL_MIG_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: controls prepare verify
controls:
	cd "$(RK_ORIGINAL_MIG_ROOT)" && $(PYTHON) -m unittest discover -s tests/ddr/original_mig -v
prepare:
	cd "$(RK_ORIGINAL_MIG_ROOT)" && $(PYTHON) tools/ddr/prepare_original_mig.py prepare --source-root "$(RK_ORIGINAL_YPCB_ROOT)" --out "$(RK_ORIGINAL_MIG_PACKAGE)"
verify:
	cd "$(RK_ORIGINAL_MIG_ROOT)" && $(PYTHON) tools/ddr/prepare_original_mig.py verify --package "$(RK_ORIGINAL_MIG_PACKAGE)"
