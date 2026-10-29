PYTHON ?= python3
RK_ASYNC_ENDPOINT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: build run verify-build verify-run
build:
	cd "$(RK_ASYNC_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_async_endpoint.py build --archive "$(RK_ASYNC_DDR_ARCHIVE)" --primitive-library "$(RK_XECLIB)" --out "$(RK_ASYNC_DDR_PACKAGE)"
run:
	cd "$(RK_ASYNC_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_async_endpoint.py run --package "$(RK_ASYNC_DDR_PACKAGE)" --out "$(RK_ASYNC_DDR_RUN)"
verify-build:
	cd "$(RK_ASYNC_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_async_endpoint.py verify-build --package "$(RK_ASYNC_DDR_PACKAGE)"
verify-run:
	cd "$(RK_ASYNC_ENDPOINT_ROOT)" && $(PYTHON) tools/ddr/run_async_endpoint.py verify-run --report "$(RK_ASYNC_DDR_RUN)/report.json"
