PYTHON ?= python3
RK_ENDPOINT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: controls build run verify-build verify-run
controls:
	cd "$(RK_ENDPOINT_ROOT)" && $(PYTHON) -m unittest discover -s tests/ddr/endpoint -p test_runner.py -v
build:
	cd "$(RK_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_endpoint.py build --archive "$(RK_DDR_ARCHIVE)" --primitive-library "$(RK_XECLIB)" --out "$(RK_DDR_PACKAGE)"
run:
	cd "$(RK_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_endpoint.py run --package "$(RK_DDR_PACKAGE)" --out "$(RK_DDR_RUN)"
verify-build:
	cd "$(RK_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_endpoint.py verify-build --package "$(RK_DDR_PACKAGE)"
verify-run:
	cd "$(RK_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_endpoint.py verify-run --report "$(RK_DDR_RUN)/report.json"
