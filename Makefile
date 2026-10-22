PYTHON ?= python3
CXX ?= c++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra -Werror
SHARED_FLAGS = -shared -fPIC
ifeq ($(shell uname -s),Darwin)
SHARED_FLAGS = -dynamiclib -fPIC
endif
CORE_RTL = rtl/rk_fp16_alu.sv rtl/rk_ew_regs.sv rtl/rk_ew_engine.sv rtl/rk_ew_core.sv
DMA_RTL = rtl/rk_fp16_alu.sv rtl/rk_ew_regs.sv rtl/rk_ew_engine.sv rtl/rk_ew_dma.sv
HOST_RTL = $(DMA_RTL) rtl/rk_axi_mem.sv rtl/rk_job_control.sv rtl/rk_ew_axi.sv
CMAC_RTL = rtl/rk_cmac_profile.sv rtl/rk_cmac_address.sv rtl/rk_cmac_reader.sv rtl/rk_cmac_operand_front.sv rtl/rk_fp16_product.sv rtl/rk_cmac_product_front.sv
DEMO_RTL = $(CORE_RTL) rtl/rk_bram.sv rtl/rk_demo_rom.sv rtl/rk_ew_demo.sv
DMA_DEMO_RTL = $(DMA_RTL) rtl/rk_bram.sv rtl/rk_demo_memory.sv rtl/rk_dma_demo_rom.sv rtl/rk_ew_dma_demo.sv

.PHONY: all test model-test generated generated-check vectors rtl-test four-state-test cmac-vectors cmac-test cmac-four-state-test synth-check host-synth-check host-mapped-check openxc7-check lint demo-replay fpga clean
all: model-test
# "test" deliberately requires RTL simulation; missing tools do NOT yield a pass.
test: model-test lint rtl-test four-state-test cmac-test cmac-four-state-test
build/half_datapath.so: model/half_datapath.cpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $(SHARED_FLAGS) $< -o $@
generated:
	$(PYTHON) tools/gen_regfile.py
	$(PYTHON) tools/gen_demo.py
generated-check:
	$(PYTHON) tools/gen_regfile.py --check
	$(PYTHON) tools/gen_demo.py --check
model-test: generated-check build/half_datapath.so
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) tools/test_numeric.py
vectors:
	$(PYTHON) tools/gen_vectors.py
	$(PYTHON) tools/dma_fixtures.py
rtl-test: generated-check vectors
	$(PYTHON) tools/run_rtl.py
four-state-test: generated-check vectors
	$(PYTHON) tools/run_rtl.py --simulator iverilog
cmac-vectors:
	$(PYTHON) tools/gen_cmac_vectors.py
	$(PYTHON) tools/gen_fp16_product_vectors.py
cmac-test: generated-check cmac-vectors
	$(PYTHON) tools/run_cmac.py --simulator verilator
cmac-four-state-test: generated-check cmac-vectors
	$(PYTHON) tools/run_cmac.py --simulator iverilog
synth-check: generated-check
	$(PYTHON) tools/run_synth.py
	$(PYTHON) tools/run_host_synth.py
host-synth-check: generated-check
	$(PYTHON) tools/run_host_synth.py
host-mapped-check: generated-check
	$(PYTHON) tools/run_host_mapped.py
# Characterization only: this never emits .bit or substitutes for physical signoff.
openxc7-check: generated-check
	$(PYTHON) tools/run_openxc7.py
lint: generated-check
	@command -v verilator >/dev/null || { echo 'UNAVAILABLE: Verilator is required for RTL lint.' >&2; exit 2; }
	verilator --lint-only -Wall --top-module rk_ew_core $(CORE_RTL)
	verilator --lint-only -Wall --top-module rk_ew_dma $(DMA_RTL)
	verilator --lint-only -Wall --top-module rk_axi_mem rtl/rk_axi_mem.sv
	verilator --lint-only -Wall --top-module rk_cmac_address rtl/rk_cmac_address.sv
	verilator --lint-only -Wall --top-module rk_cmac_product_front $(CMAC_RTL)
	verilator --lint-only -Wall --top-module rk_job_control rtl/rk_job_control.sv
	verilator --lint-only -Wall --top-module rk_ew_axi $(HOST_RTL)
	verilator --lint-only -Wall --top-module ypcb_top $(DMA_DEMO_RTL) fpga/ypcb_top.sv
demo-replay:
	$(PYTHON) tools/replay_demo.py
fpga: generated-check
	@command -v vivado >/dev/null || { echo 'UNAVAILABLE: full Vivado is required for synthesis/implementation.' >&2; exit 2; }
	mkdir -p build/vivado
	vivado -mode batch -source fpga/build.tcl -log build/vivado/vivado.log -journal build/vivado/vivado.jou
clean:
	rm -rf build
