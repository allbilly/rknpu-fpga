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
JTAG_HOST_RTL = $(DMA_RTL) rtl/rk_bram.sv rtl/rk_job_control.sv rtl/host/rk_jtag_backend.sv rtl/host/rk_jtag_ew_bram.sv
CMAC_RTL = rtl/rk_cmac_profile.sv rtl/rk_cmac_address.sv rtl/rk_cmac_reader.sv rtl/rk_cmac_operand_front.sv rtl/rk_fp16_product.sv rtl/rk_cmac_product_front.sv
DEMO_RTL = $(CORE_RTL) rtl/rk_bram.sv rtl/rk_demo_rom.sv rtl/rk_ew_demo.sv
DMA_DEMO_RTL = $(DMA_RTL) rtl/rk_bram.sv rtl/rk_demo_memory.sv rtl/rk_dma_demo_rom.sv rtl/rk_ew_dma_demo.sv
STARTUP_DEMO_RTL = $(DMA_DEMO_RTL) rtl/rk_startup_reset.sv fpga/ypcb_ew_startup_top.sv
PPU_MAX_RTL = rtl/ppu/rk_ppu_pool_max2x2s1_c8.sv
PPU_MAX_PAD1_RTL = rtl/ppu/rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2.sv

.PHONY: all test model-test generated generated-check vectors rtl-test four-state-test cmac-vectors cmac-test cmac-four-state-test conv-first-case-test ppu-max-test ppu-max-four-state-test ppu-max-pad1-test ppu-max-pad1-four-state-test ppu-max-lint synth-check host-synth-check host-mapped-check openxc7-check lint demo-replay fpga clean
all: model-test
# "test" deliberately requires RTL simulation; missing tools do NOT yield a pass.
test: model-test lint rtl-test four-state-test cmac-test cmac-four-state-test conv-first-case-test ppu-max-test ppu-max-four-state-test ppu-max-pad1-test ppu-max-pad1-four-state-test host-jtag-test host-jtag-four-state-test host-jtag-preparation-test debug-control-test full512-startup-control-test tinystories-preparation-test tinystories-memory-test ddr-endpoint-controls ddr-host-controls ddr-dual-controls ddr-capacity-controls ddr-capacity-parent-controls backend-layout-test host-frame-mailbox-test host-frame-mailbox-admission-test host-frame-owner-test host-frame-frontend-test host-transport-epoch-test host-pcie-bridge-reset-test host-pcie-components-test host-retained-mailbox-test ddr-session-quiet-test ddr-whole-reset-control-test ddr-fi-client-controls ddr-dual-host-npu-test process-controls
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
conv-first-case-test:
	$(PYTHON) tools/conv/test_first_case.py --simulator all
synth-check: generated-check
	$(PYTHON) tools/run_synth.py
	$(PYTHON) tools/run_host_synth.py
host-synth-check: generated-check
	$(PYTHON) tools/run_host_synth.py
host-mapped-check: generated-check
	$(PYTHON) tools/run_host_mapped.py
# Standalone PPU increments: exact captured RK3588 whole-BO replay, simulators only.
ppu-max-test: generated-check
	$(PYTHON) tools/ppu/run_pool_max.py --simulator verilator
ppu-max-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_max.py --simulator iverilog
ppu-max-pad1-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1.py --simulator verilator
ppu-max-pad1-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1.py --simulator iverilog
ppu-max-lint: generated-check
	@command -v verilator >/dev/null || { echo 'UNAVAILABLE: Verilator is required for RTL lint.' >&2; exit 2; }
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s1_c8 $(PPU_MAX_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2 $(PPU_MAX_PAD1_RTL)

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
	verilator --lint-only -Wall --top-module rk_jtag_ew_bram $(JTAG_HOST_RTL)
	verilator --lint-only -Wall --top-module ypcb_top $(DMA_DEMO_RTL) fpga/ypcb_top.sv
	verilator --lint-only -Wall --top-module ypcb_ew_startup_top $(STARTUP_DEMO_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s1_c8 $(PPU_MAX_RTL)

# Source snapshots and review templates only; neither target starts Vivado.
.PHONY: fpga-prepare fpga-prepare-startup
fpga-prepare: generated-check
	$(PYTHON) tools/prepare_ew_fpga.py prepare --profile external-r28
fpga-prepare-startup: generated-check
	$(PYTHON) tools/prepare_ew_fpga.py prepare --profile startup
.PHONY: host-jtag-test host-jtag-four-state-test host-jtag-preparation-test host-jtag-prepare
host-jtag-test: generated-check
	$(PYTHON) tools/host/run_rtl.py --simulator verilator
host-jtag-four-state-test: generated-check
	$(PYTHON) tools/host/run_rtl.py --simulator iverilog
host-jtag-preparation-test: generated-check
	$(PYTHON) -m unittest discover -s tests/host -v

.PHONY: tinystories-preparation-test tinystories-unity-check tinystories-memory-test
tinystories-preparation-test: generated-check
	$(PYTHON) -m unittest discover -s tests/tinystories -v
tinystories-unity-check: generated-check
	$(PYTHON) tools/tinystories/check_unity.py
tinystories-memory-test: generated-check
	$(PYTHON) tools/tinystories/run_memory.py

.PHONY: ddr-endpoint-controls ddr-host-controls ddr-frame-transport-controls ddr-channel-frozen-controls ddr-dual-controls
ddr-endpoint-controls: generated-check
	$(PYTHON) -m unittest discover -s tests/ddr/endpoint -v
# Byte-transport, preparation and independent-auditor controls only. These
# mocks never open a network connection, program hardware or qualify DDR RTL.
ddr-frame-transport-controls: generated-check
	$(PYTHON) -m unittest discover -s tests/ddr/frame_transport -v
	$(PYTHON) -O -m unittest discover -s tests/ddr/frame_transport -v
ddr-host-controls: generated-check ddr-frame-transport-controls
	$(PYTHON) -m unittest discover -s tests/ddr/transport -v
	$(PYTHON) -m unittest discover -s tests/ddr/dual_transport -v
	$(PYTHON) -m unittest discover -s tests/ddr/framework_transport -v
	$(PYTHON) -m unittest discover -s tests/ddr/framework_profile -v
	$(PYTHON) -m unittest discover -s tests/ddr/raw_test -v
	$(PYTHON) -m unittest discover -s tests/ddr/image -v
	$(PYTHON) -m unittest discover -s tests/ddr/full512_image -v
	$(PYTHON) -m unittest discover -s tests/ddr/channel_profile -v
	$(PYTHON) -m unittest discover -s tests/ddr/physical_audit -v
	$(PYTHON) -m unittest discover -s tests/ddr/trained_audit -v
	$(PYTHON) -m unittest discover -s tests/ddr/model_audit -v
# Source-bound CH1 package integration audit; not part of the default test target.
# Requires the prepared 122-real-HDL package and all of its frozen build inputs.
ddr-channel-frozen-controls:
	$(PYTHON) -c "import json; r=json.load(open('build/ypcb-ddr-shell/ch1-source-v1/report.json')); assert r['selected_physical_channel']==1 and len(r['real_hdl_sources'])==122 and len(set(r['real_hdl_sources']))==122 and r['stub_selected_for_real_design'] is False"
	$(PYTHON) -m unittest discover -s tests/ddr/channel_profile_frozen -v
ddr-dual-controls: generated-check
	$(PYTHON) tools/ddr/run_dual_controls.py
.PHONY: ddr-capacity-controls ddr-capacity-parent-controls ddr-session-quiet-test
ddr-capacity-controls: generated-check
	$(PYTHON) -m unittest discover -s tests/ddr/capacity -p 'test*.py' -v
	$(PYTHON) tools/ddr/run_capacity.py --simulator iverilog
	$(PYTHON) tools/ddr/run_capacity.py --simulator verilator
# Published parent-profile service/router/client controls only; no hardware claim.
ddr-capacity-parent-controls: generated-check
	$(PYTHON) tools/ddr/run_capacity_parent.py
# Dual-host session quiescence comparison; native candidate/reference test only.
ddr-session-quiet-test: generated-check
	$(PYTHON) tools/ddr/run_session_quiet.py --simulator both

# Standalone SYS-clock maintenance reset-control protocol; no board integration claim.
.PHONY: ddr-whole-reset-control-test
DDR_WHOLE_RESET_CONTROL_OUT ?=
ddr-whole-reset-control-test: generated-check
	$(PYTHON) tools/ddr/run_whole_reset_control.py $(if $(strip $(DDR_WHOLE_RESET_CONTROL_OUT)),--out "$(DDR_WHOLE_RESET_CONTROL_OUT)",)

# Callback-only RKFI management client controls; fake registers, no RTL or hardware.
.PHONY: ddr-fi-client-controls
ddr-fi-client-controls: generated-check
	$(PYTHON) -m unittest discover -s tests/ddr/fi_client -p 'test_*.py' -v
	$(PYTHON) -O -m unittest discover -s tests/ddr/fi_client -p 'test_*.py' -v

host-jtag-prepare: generated-check
	$(PYTHON) tools/host/prepare.py prepare

# Separate optional compiler integration: requires the pinned tinygrad checkout.
# The runner's injected link executes RTL locally and cannot open an XVC socket.
.PHONY: backend-test
backend-test: generated-check
	$(PYTHON) tools/backend/run.py

# Explicit full-DDR runtime protocol controls; requires the pinned tinygrad
# checkout. These byte-only mocks do not qualify RTL or a physical image.
.PHONY: backend-full-controls
backend-full-controls: generated-check
	$(PYTHON) -m unittest discover -s tests/backend_full -v
	$(PYTHON) -m unittest discover -s tests/ddr/framework_transport -v

# Portable compiler metadata and actual raw-QWORD layout DMA execution only.
# No external tinygrad checkout, Vivado or hardware connection is required.
.PHONY: backend-layout-test
backend-layout-test: generated-check
	$(PYTHON) -m unittest discover -s tests/backend_layout -v
	$(PYTHON) tools/backend/run_layout.py --simulator iverilog
	$(PYTHON) tools/backend/run_layout.py --simulator verilator

.PHONY: debug-control-test
debug-control-test: generated-check
	$(PYTHON) -m unittest discover -s tests/debug -v

# PCIe BAR-path packet component only; this does not instantiate PCIe IP.
.PHONY: host-frame-mailbox-test
host-frame-mailbox-test: generated-check
	$(PYTHON) -m unittest discover -s tests/host/frame_mailbox -v
	$(PYTHON) tools/host/run_frame_mailbox.py

.PHONY: host-frame-mailbox-admission-test
host-frame-mailbox-admission-test: generated-check
	$(PYTHON) tools/host/run_frame_mailbox.py --component admission

.PHONY: host-frame-owner-test
host-frame-owner-test: generated-check
	$(PYTHON) -m unittest discover -s tests/host/frame_owner -v
	$(PYTHON) -O -m unittest discover -s tests/host/frame_owner -v
	$(PYTHON) tools/host/run_frame_mailbox.py --component owner

.PHONY: host-frame-frontend-test
host-frame-frontend-test: generated-check
	$(PYTHON) tools/host/run_frame_mailbox.py --component frontend

.PHONY: host-transport-epoch-test
host-transport-epoch-test: generated-check
	$(PYTHON) tools/host/run_transport_epoch.py

# Standalone PCIe bridge reset startup-history component; no converter/IP or hardware.
.PHONY: host-pcie-bridge-reset-test
host-pcie-bridge-reset-test: generated-check
	$(PYTHON) tools/host/run_bridge_reset.py

# Public source-health and unsupported XDMA M_AXI DECERR components; native only.
.PHONY: host-pcie-components-test
PCIE_COMPONENTS_OUT ?=
PCIE_COMPONENTS_SIMULATOR ?= both
host-pcie-components-test: generated-check
	$(PYTHON) tools/host/run_pcie_components.py --simulator "$(PCIE_COMPONENTS_SIMULATOR)" $(if $(strip $(PCIE_COMPONENTS_OUT)),--out "$(PCIE_COMPONENTS_OUT)",)

# Retained USER2/UI and USER3/SYS mailbox native component only; no BSCANE2 or board.
.PHONY: host-retained-mailbox-test
RETAINED_MAILBOX_OUT ?=
host-retained-mailbox-test: generated-check
	$(PYTHON) tools/host/run_retained_mailbox.py $(if $(strip $(RETAINED_MAILBOX_OUT)),--out "$(RETAINED_MAILBOX_OUT)",)

# Optional commercial-vendor-source functional controls for the actual AMD
# AXI4-Lite async converter. This is intentionally not a dependency of `test`.
# Set RK_VIVADO_ROOT (or pass PCIE_ACTUAL_CONVERTER_VIVADO_ROOT) to an installed
# Vivado tree and choose a fresh output directory for each run.
.PHONY: host-pcie-actual-converter-test
PCIE_ACTUAL_CONVERTER_VIVADO_ROOT ?= $(RK_VIVADO_ROOT)
PCIE_ACTUAL_CONVERTER_OUT ?= build/pcie-actual-converter-public-v1
PCIE_ACTUAL_CONVERTER_SIMULATOR ?= both
host-pcie-actual-converter-test: generated-check
	$(PYTHON) tools/host/run_actual_converter.py --out "$(PCIE_ACTUAL_CONVERTER_OUT)" --simulator "$(PCIE_ACTUAL_CONVERTER_SIMULATOR)" $(if $(strip $(PCIE_ACTUAL_CONVERTER_VIVADO_ROOT)),--vivado-root "$(PCIE_ACTUAL_CONVERTER_VIVADO_ROOT)",)

.PHONY: full512-startup-control-test
full512-startup-control-test: generated-check
	$(PYTHON) -m unittest discover -s tests/cmac/startup -v
demo-replay:
	$(PYTHON) tools/replay_demo.py
fpga: generated-check
	@command -v vivado >/dev/null || { echo 'UNAVAILABLE: full Vivado is required for synthesis/implementation.' >&2; exit 2; }
	mkdir -p build/vivado
	vivado -mode batch -source fpga/build.tcl -log build/vivado/vivado.log -journal build/vivado/vivado.jou
clean:
	rm -rf build

# Full numerical NPU plus same-clock JTAG/PCIe packet handoff; native only.
.PHONY: ddr-dual-host-npu-test
ddr-dual-host-npu-test: generated-check
	$(PYTHON) tools/ddr/run_dual_host_npu.py --execute-reviewed-run

# OS-backed command/session cleanup and interruption controls; no hardware.
.PHONY: process-controls
process-controls: generated-check
	$(PYTHON) -m unittest discover -s tests/process -v
	$(PYTHON) -O -m unittest discover -s tests/process -v
