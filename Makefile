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
PPU_AVG_RTL = rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv
PPU_MIN_RTL = rtl/ppu/rk_ppu_pool_min2x2s1_fp16_capture.sv
PPU_INDEX_RTL = rtl/ppu/rk_ppu_pool_max2x2s2_index_c8_h2w2.sv
PPU_C3_TAIL_RTL = rtl/ppu/rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv
PPU_C3_PROFILE_RTL = rtl/ppu/rk_ppu_pool_c3_raw_profile.sv
PPU_C8_PROFILE_RTL = rtl/ppu/rk_ppu_pool_c8_raw_profile.sv
PPU_PAD1_PROFILE_RTL = rtl/ppu/rk_ppu_pool_pad1_raw_profile.sv
PPU_MIN_PROFILE_RTL = rtl/ppu/rk_ppu_pool_min_raw_profile.sv
PPU_AVG_PROFILE_RTL = rtl/ppu/rk_ppu_pool_avg_raw_profile.sv
PPU_INDEX_PROFILE_RTL = rtl/ppu/rk_ppu_pool_index_raw_profile.sv
PPU_GLOBAL_PROFILE_RTL = rtl/ppu/rk_ppu_pool_global_raw_profile.sv
PPU_GLOBAL_LEAF_RTL = rtl/ppu/rk_ppu_pool_max16x16s16_c8.sv
PPU_GLOBAL_AVG_PROFILE_RTL = rtl/ppu/rk_ppu_pool_global_avg_raw_profile.sv
PPU_GLOBAL_AVG_LEAF_RTL = rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv
PPU_PAD1_LEAF_RTL = $(PPU_MAX_PAD1_RTL)
PPU_MIN_LEAF_RTL = $(PPU_MIN_RTL)
PPU_RAW_DMA_RTL = $(PPU_C3_PROFILE_RTL) $(PPU_C8_PROFILE_RTL) $(PPU_PAD1_PROFILE_RTL) $(PPU_MIN_PROFILE_RTL) $(PPU_AVG_PROFILE_RTL) $(PPU_INDEX_PROFILE_RTL) $(PPU_GLOBAL_PROFILE_RTL) $(PPU_GLOBAL_LEAF_RTL) $(PPU_GLOBAL_AVG_PROFILE_RTL) $(PPU_GLOBAL_AVG_LEAF_RTL) $(PPU_C3_TAIL_RTL) $(PPU_MAX_RTL) $(PPU_PAD1_LEAF_RTL) $(PPU_MIN_LEAF_RTL) $(PPU_AVG_RTL) $(PPU_INDEX_RTL) rtl/ppu/rk_ppu_pool_raw_dma.sv

.PHONY: all test model-test generated generated-check vectors rtl-test four-state-test cmac-vectors cmac-test cmac-four-state-test conv-first-case-test conv-3x3-valid-c4-test ppu-max-test ppu-max-four-state-test ppu-max-pad1-test ppu-max-pad1-four-state-test ppu-avg-test ppu-avg-four-state-test ppu-avg-contract-test ppu-min-test ppu-min-four-state-test ppu-min-contract-test ppu-index-test ppu-index-four-state-test ppu-index-contract-test ppu-c3-tail-test ppu-c3-tail-four-state-test ppu-c3-tail-contract-test ppu-c3-raw-profile-test ppu-c3-raw-profile-four-state-test ppu-c3-raw-profile-contract-test ppu-c8-raw-profile-test ppu-c8-raw-profile-four-state-test ppu-c8-raw-profile-contract-test ppu-pad1-raw-profile-test ppu-pad1-raw-profile-four-state-test ppu-pad1-raw-profile-contract-test ppu-min-raw-profile-test ppu-min-raw-profile-four-state-test ppu-min-raw-profile-contract-test ppu-avg-raw-profile-test ppu-avg-raw-profile-four-state-test ppu-avg-raw-profile-contract-test ppu-index-raw-profile-test ppu-index-raw-profile-four-state-test ppu-index-raw-profile-contract-test ppu-c3-raw-dma-test ppu-c3-raw-dma-four-state-test ppu-c3-raw-dma-contract-test ppu-c8-raw-dma-test ppu-c8-raw-dma-four-state-test ppu-c8-raw-dma-contract-test ppu-pad1-raw-dma-test ppu-pad1-raw-dma-four-state-test ppu-pad1-raw-dma-contract-test ppu-min-raw-dma-test ppu-min-raw-dma-four-state-test ppu-min-raw-dma-contract-test ppu-avg-raw-dma-test ppu-avg-raw-dma-four-state-test ppu-avg-raw-dma-contract-test ppu-index-raw-dma-test ppu-index-raw-dma-four-state-test ppu-index-raw-dma-contract-test ppu-c3-job-control-test ppu-c3-job-control-four-state-test ppu-c3-job-control-contract-test ppu-max-lint synth-check host-synth-check host-mapped-check openxc7-check lint demo-replay fpga clean
.PHONY: ppu-int-k2s2-test ppu-int-k2s2-four-state-test ppu-int-k2s2-contract-test
.PHONY: ppu-i8-dma-test ppu-i8-dma-four-state-test ppu-i8-dma-contract-test
.PHONY: ppu-int-avg-test ppu-int-avg-four-state-test ppu-pad-tail-test ppu-pad-tail-four-state-test ppu-pad-avg-contract-test
.PHONY: ppu-board-test ppu-board-four-state-test ppu-board-contract-test
.PHONY: ppu-board-lint ppu-image-render ppu-fixture-set-contract-test ppu-global-raw-dma-test ppu-global-raw-dma-four-state-test ppu-global-raw-dma-contract-test
.PHONY: ppu-avg-global3x5-test ppu-avg-global3x5-four-state-test ppu-avg-global3x5-contract-test
.PHONY: ppu-global-avg-raw-profile-test ppu-global-avg-raw-profile-four-state-test ppu-global-avg-raw-profile-contract-test
.PHONY: ppu-global-avg-raw-dma-test ppu-global-avg-raw-dma-four-state-test ppu-global-avg-raw-dma-contract-test
.PHONY: conv-3x3-stride2-c4-test conv-3x3-pad1-zero-frame-c4-test conv-3x3-c4-dma-test conv-3x3-grouped-c2-test conv-3x3-splitoc-c16-test conv-3x3-depthwise-c3-test
.PHONY: conv-simple-fixture-test conv-simple-fixture-refresh conv-simple-test conv-simple-four-state-test conv-simple-contract-test conv-simple-lint
.PHONY: conv-board-test conv-board-four-state-test conv-board-lint conv-image-render conv-image-vivado
.PHONY: conv-simple-dma-test conv-simple-dma-four-state-test
.PHONY: conv-gemm-vendor-fixture-test conv-gemm-vendor-fixture-refresh
.PHONY: dual-endpoint-contract-test dual-endpoint-test dual-endpoint-four-state-test axil-mem-bridge-test
.PHONY: jtag-axil-bridge-test jtag-dual-test jtag-dual-four-state-test jtag-dual-image
.PHONY: cmac-fp32-writer-test cmac-output-fp32-test cmac-gemm-fp32-test cmac-gemm-fp32-four-state-test
.PHONY: conv-simple-fp32-test axi-mem-slave-test gemm-fp32-axi-test
all: model-test
test: ppu-fixture-set-contract-test
test: ppu-int-k2s2-test
test: ppu-int-k2s2-four-state-test
test: ppu-int-k2s2-contract-test
test: ppu-i8-dma-contract-test
test: ppu-board-contract-test
test: conv-simple-contract-test
test: conv-gemm-vendor-fixture-test
test: dual-endpoint-contract-test
test: axil-mem-bridge-test
test: jtag-axil-bridge-test
test: cmac-fp32-writer-test
test: cmac-output-fp32-test
test: conv-simple-fp32-test
test: axi-mem-slave-test
test: conv-board-test
test: conv-simple-dma-four-state-test
test: ppu-pad-avg-contract-test
test: ppu-int-avg-four-state-test
test: ppu-pad-tail-four-state-test
test: board-electrical-evidence-test
test: ppu-global-raw-dma-test ppu-global-raw-dma-four-state-test ppu-global-raw-dma-contract-test
test: ppu-avg-global3x5-test ppu-avg-global3x5-four-state-test ppu-avg-global3x5-contract-test
test: ppu-global-avg-raw-profile-test ppu-global-avg-raw-profile-four-state-test ppu-global-avg-raw-profile-contract-test
test: ppu-global-avg-raw-dma-test ppu-global-avg-raw-dma-four-state-test ppu-global-avg-raw-dma-contract-test
test: conv-3x3-valid-c4-test
test: conv-3x3-stride2-c4-test
test: conv-3x3-pad1-zero-frame-c4-test
test: conv-3x3-c4-dma-test
test: conv-3x3-grouped-c2-test
test: conv-3x3-splitoc-c16-test
test: conv-3x3-depthwise-c3-test
# "test" deliberately requires RTL simulation; missing tools do NOT yield a pass.
test: model-test lint rtl-test four-state-test cmac-test cmac-four-state-test conv-first-case-test ppu-max-test ppu-max-four-state-test ppu-max-pad1-test ppu-max-pad1-four-state-test ppu-avg-test ppu-avg-four-state-test ppu-avg-contract-test ppu-min-test ppu-min-four-state-test ppu-min-contract-test ppu-index-test ppu-index-four-state-test ppu-index-contract-test ppu-c3-tail-test ppu-c3-tail-four-state-test ppu-c3-tail-contract-test ppu-c3-raw-profile-test ppu-c3-raw-profile-four-state-test ppu-c3-raw-profile-contract-test ppu-c8-raw-profile-test ppu-c8-raw-profile-four-state-test ppu-c8-raw-profile-contract-test ppu-pad1-raw-profile-test ppu-pad1-raw-profile-four-state-test ppu-pad1-raw-profile-contract-test ppu-min-raw-profile-test ppu-min-raw-profile-four-state-test ppu-min-raw-profile-contract-test ppu-avg-raw-profile-test ppu-avg-raw-profile-four-state-test ppu-avg-raw-profile-contract-test ppu-index-raw-profile-test ppu-index-raw-profile-four-state-test ppu-index-raw-profile-contract-test ppu-c3-raw-dma-test ppu-c3-raw-dma-four-state-test ppu-c3-raw-dma-contract-test ppu-c8-raw-dma-test ppu-c8-raw-dma-four-state-test ppu-c8-raw-dma-contract-test ppu-pad1-raw-dma-test ppu-pad1-raw-dma-four-state-test ppu-pad1-raw-dma-contract-test ppu-min-raw-dma-test ppu-min-raw-dma-four-state-test ppu-min-raw-dma-contract-test ppu-avg-raw-dma-test ppu-avg-raw-dma-four-state-test ppu-avg-raw-dma-contract-test ppu-index-raw-dma-test ppu-index-raw-dma-four-state-test ppu-index-raw-dma-contract-test ppu-c3-job-control-test ppu-c3-job-control-four-state-test ppu-c3-job-control-contract-test host-jtag-test host-jtag-four-state-test host-jtag-preparation-test debug-control-test full512-startup-control-test tinystories-preparation-test tinystories-memory-test ddr-endpoint-controls ddr-host-controls ddr-dual-controls ddr-capacity-controls ddr-capacity-parent-controls backend-layout-test host-frame-mailbox-test host-frame-mailbox-admission-test host-frame-owner-test host-frame-frontend-test host-transport-epoch-test host-pcie-bridge-reset-test host-pcie-components-test host-retained-mailbox-test ddr-session-quiet-test ddr-whole-reset-control-test ddr-fi-client-controls ddr-dual-host-npu-test process-controls
build/half_datapath.so: model/half_datapath.cpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $(SHARED_FLAGS) $< -o $@
generated:
	$(PYTHON) tools/gen_regfile.py
	$(PYTHON) tools/gen_demo.py
generated-check:
	$(PYTHON) tools/gen_regfile.py --check
	$(PYTHON) tools/gen_demo.py --check
	$(PYTHON) tools/conv/gen_conv_profiles.py --check
	$(PYTHON) tools/conv/gen_conv_simple_profiles.py --check
	$(PYTHON) tools/conv/gen_conv_demo.py --check
	$(PYTHON) tools/ppu/gen_pool_demo.py --check
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
conv-3x3-valid-c4-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_3x3_valid_c4_contract -v
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --simulator both
conv-3x3-stride2-c4-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_3x3_stride2_c4_contract -v
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --case conv_3x3_stride2_c4_h11_w11_oc4 --simulator both
conv-3x3-pad1-zero-frame-c4-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_3x3_pad1_zero_frame_c4_contract -v
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --case conv_3x3_pad1_zero_frame_c4_h9_w9_oc4 --simulator both
conv-3x3-c4-dma-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_3x3_c4_dma_contract -v
	$(PYTHON) tools/conv/run_3x3_c4_dma.py --case conv_3x3_valid_c4_h9_w9_oc4 --simulator both
	$(PYTHON) tools/conv/run_3x3_c4_dma.py --case conv_3x3_stride2_c4_h11_w11_oc4 --simulator both
	$(PYTHON) tools/conv/run_3x3_c4_dma.py --case conv_3x3_pad1_zero_frame_c4_h9_w9_oc4 --simulator both
conv-3x3-grouped-c2-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_3x3_grouped_c2_contract -v
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --case conv_grouped_3x3_c4_h5_w5_oc8_g2_task0 --simulator both
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --case conv_grouped_3x3_c4_h5_w5_oc8_g2_task1 --simulator both
conv-3x3-splitoc-c16-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_3x3_splitoc_c16_contract -v
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --case conv_splitoc_3x3_c16_h9_w9_oc16_task0 --simulator both
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --case conv_splitoc_3x3_c16_h9_w9_oc16_task1 --simulator both
conv-3x3-depthwise-c3-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_3x3_depthwise_c3_contract -v
	$(PYTHON) -m unittest tests.conv.test_conv_profiles_header_contract -v
	$(PYTHON) tools/conv/run_3x3_valid_c4.py --case conv_depthwise_3x3_c3_h11_w28_oc3 --simulator both
# Freezing reads the existing device captures; it never contacts hardware.
# Re-hashes the donor configuration-bank evidence; skips cleanly without it.
board-electrical-evidence-test: generated-check
	$(PYTHON) -m unittest tests.test_board_electrical_evidence -v
conv-gemm-vendor-fixture-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_conv_gemm_vendor_fixture_contract -v
conv-gemm-vendor-fixture-refresh:
	$(PYTHON) tools/conv/freeze_vendor_fixtures.py --all-admissible
axil-mem-bridge-test: generated-check
	iverilog -g2012 -Irtl -Itests -s tb_axil_mem_bridge -o build/tb_axil_mem_bridge.vvp \
		 rtl/rk_axil_mem_bridge.sv tests/tb_axil_mem_bridge.sv
	vvp build/tb_axil_mem_bridge.vvp
dual-endpoint-contract-test: generated-check
	$(PYTHON) -m unittest tests.test_dual_endpoint_contract -v
dual-endpoint-test: generated-check
	$(PYTHON) tools/dual/run_dual_endpoint.py --simulator verilator
dual-endpoint-four-state-test: generated-check
	$(PYTHON) tools/dual/run_dual_endpoint.py --simulator iverilog
jtag-axil-bridge-test: generated-check
	iverilog -g2012 -Irtl -Itests -s tb_jtag_axil_bridge -o build/tb_jtag_axil_bridge.vvp \
		 rtl/host/rk_jtag_axil_bridge.sv tests/host/tb_jtag_axil_bridge.sv
	vvp build/tb_jtag_axil_bridge.vvp
cmac-fp32-writer-test: generated-check
	iverilog -g2012 -Irtl -Itests -s tb_cmac_fp32_writer -o build/tb_cmac_fp32_writer.vvp \
		 rtl/cmac/rk_cmac_fp32_writer.sv tests/cmac/tb_cmac_fp32_writer.sv
	vvp build/tb_cmac_fp32_writer.vvp
cmac-output-fp32-test: generated-check
	iverilog -g2012 -Irtl -Itests -s tb_cmac_output_fp32 -o build/tb_cmac_output_fp32.vvp \
		 rtl/cmac/rk_cmac_fp32_writer.sv rtl/cmac/rk_cmac_output_fp32.sv \
		 tests/cmac/tb_cmac_output_fp32.sv
	vvp build/tb_cmac_output_fp32.vvp
cmac-gemm-fp32-test: generated-check
	$(PYTHON) tools/cmac/run_gemm_fp32.py --simulator verilator
cmac-gemm-fp32-four-state-test: generated-check
	$(PYTHON) tools/cmac/run_gemm_fp32.py --simulator iverilog
conv-simple-fp32-test: generated-check
	$(PYTHON) tools/conv/run_conv_simple_fp32.py --simulator both
axi-mem-slave-test: generated-check
	iverilog -g2012 -Irtl -Itests -s tb_axi_mem_slave -o build/tb_axi_mem_slave.vvp \
		 rtl/rk_axi_mem_slave.sv tests/host/tb_axi_mem_slave.sv
	vvp build/tb_axi_mem_slave.vvp
# The endpoint replay uses the k=1 fixture: it is the only shapes whose output
# is byte-exact, and the only one whose per-value write count is fully
# determined. Deeper shapes are validated by `cmac-gemm-fp32-test` through the
# bare DMA, where the address walk is the leaf under test.
gemm-fp32-axi-test: generated-check
	$(PYTHON) tools/cmac/run_gemm_fp32_axi.py --case gemm_m2_n2_k1 --simulator verilator
gemm-fp32-axi-four-state-test: generated-check
	$(PYTHON) tools/cmac/run_gemm_fp32_axi.py --case gemm_m2_n2_k1 --simulator iverilog
jtag-dual-test: generated-check
	$(PYTHON) tools/host/run_jtag_dual.py --simulator verilator
jtag-dual-four-state-test: generated-check
	$(PYTHON) tools/host/run_jtag_dual.py --simulator iverilog
jtag-dual-image: generated-check
	RK_CONFIRM_BOARD=YPCB_00338_1P1 RK_CONFIG_VOLTAGE=1.8 RK_CFGBVS=GND \
	RK_EMIT_BITSTREAM=1 RK_LED_ACTIVE_LOW=0 \
	$(PYTHON) tools/dual/vivado_jtag_dual.py run --out build/jtag-dual-image/$(shell date -u +%Y%m%dT%H%M%SZ)
conv-simple-fixture-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_conv_simple_contract -v
conv-simple-fixture-refresh:
	$(PYTHON) tools/conv/freeze_simple_fixtures.py --all-admissible
conv-simple-contract-test: generated-check
	$(PYTHON) -m unittest tests.conv.test_conv_simple_contract -v
conv-simple-test: generated-check
	$(PYTHON) tools/conv/run_conv_simple.py --profile 0 --simulator verilator
	$(PYTHON) tools/conv/run_conv_simple.py --profile 1 --simulator verilator
	$(PYTHON) tools/conv/run_conv_simple.py --profile 2 --simulator verilator
conv-simple-four-state-test: generated-check
	$(PYTHON) tools/conv/run_conv_simple.py --profile 0 --simulator iverilog
	$(PYTHON) tools/conv/run_conv_simple.py --profile 1 --simulator iverilog
	$(PYTHON) tools/conv/run_conv_simple.py --profile 2 --simulator iverilog
conv-simple-dma-test: generated-check
	$(PYTHON) tools/conv/run_conv_simple_dma.py --simulator verilator
conv-simple-dma-four-state-test: generated-check
	$(PYTHON) tools/conv/run_conv_simple_dma.py --simulator iverilog
conv-board-test: generated-check
	$(PYTHON) tools/conv/run_conv_board.py --simulator verilator
conv-board-four-state-test: generated-check
	$(PYTHON) tools/conv/run_conv_board.py --simulator iverilog
conv-board-lint: generated-check
	@command -v verilator >/dev/null || { echo 'UNAVAILABLE: Verilator is required for RTL lint.' >&2; exit 2; }
	verilator --lint-only -Wall -Wno-fatal -Irtl -Irtl/vendor/nvdla -DDESIGNWARE_NOEXIST \
	    -DASSERT_ON --top-module tb_ypcb_conv_i8_top \
	    rtl/vendor/nvdla/compat/nv_assert_never.v rtl/vendor/nvdla/compat/nv_assert_no_x.v \
	    rtl/vendor/nvdla/NV_DW_lsd.v rtl/vendor/nvdla/NV_DW02_tree.v \
	    rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v \
	    rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v rtl/vendor/nvdla/HLS_fp32_to_fp16.v \
	    rtl/cmac/rk_cmac_fp16_cell.sv rtl/cmac/rk_cmac_fp16_array.sv \
	    rtl/cmac/rk_nvdla_cacc.sv rtl/cmac/rk_cacc_fp16_array.sv \
	    rtl/cmac/rk_cmac_cacc_fp16_array.sv rtl/cmac/rk_nvdla_fp32_to_fp16.sv \
	    rtl/cmac/rk_cmac_writer.sv rtl/cmac/rk_cmac_output_nvdla.sv \
	    rtl/cmac/rk_cmac_frame_output.sv rtl/cmac/rk_cmac_rw_arbiter.sv \
	    rtl/cmac/rk_conv_output_atom.sv rtl/cmac/rk_conv_simple_profile.sv \
	    rtl/cmac/rk_conv_3x3_valid_c4_front.sv rtl/cmac/rk_conv_simple_core.sv \
	    rtl/cmac/rk_conv_simple_demo_rom.sv rtl/cmac/rk_conv_simple_self_test.sv \
	    rtl/rk_bram.sv rtl/rk_startup_reset.sv fpga/ypcb_conv_simple_top.sv \
	    tests/tb_ypcb_conv_simple.sv
conv-image-render: generated-check
	$(PYTHON) tools/conv/vivado_conv.py render
# Full synthesis/place/route of the conv image. Opt-in; never programs.
conv-image-vivado: generated-check
	@command -v vivado >/dev/null || { echo 'UNAVAILABLE: full Vivado is required.' >&2; exit 2; }
	@test -n "$(RK_CONFIRM_BOARD)" || { echo 'UNAVAILABLE: set RK_CONFIRM_BOARD=YPCB_00338_1P1.' >&2; exit 2; }
	$(PYTHON) tools/conv/vivado_conv.py run
conv-simple-lint: generated-check
	@command -v verilator >/dev/null || { echo 'UNAVAILABLE: Verilator is required for RTL lint.' >&2; exit 2; }
	verilator --lint-only -Wall -Wno-fatal -Irtl --top-module rk_conv_simple_profile \
	    rtl/cmac/rk_conv_simple_profile.sv
	verilator --lint-only -Wall -Wno-fatal -Irtl -Irtl/vendor/nvdla -DDESIGNWARE_NOEXIST \
	    -DASSERT_ON --top-module rk_conv_simple_core \
	    rtl/vendor/nvdla/compat/nv_assert_never.v rtl/vendor/nvdla/compat/nv_assert_no_x.v \
	    rtl/vendor/nvdla/NV_DW_lsd.v rtl/vendor/nvdla/NV_DW02_tree.v \
	    rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v \
	    rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v rtl/vendor/nvdla/HLS_fp32_to_fp16.v \
	    rtl/cmac/rk_cmac_fp16_cell.sv rtl/cmac/rk_cmac_fp16_array.sv \
	    rtl/cmac/rk_nvdla_cacc.sv rtl/cmac/rk_cacc_fp16_array.sv \
	    rtl/cmac/rk_cmac_cacc_fp16_array.sv rtl/cmac/rk_nvdla_fp32_to_fp16.sv \
	    rtl/cmac/rk_cmac_writer.sv rtl/cmac/rk_cmac_output_nvdla.sv \
	    rtl/cmac/rk_cmac_frame_output.sv rtl/cmac/rk_cmac_rw_arbiter.sv \
	    rtl/cmac/rk_conv_output_atom.sv rtl/cmac/rk_conv_simple_profile.sv \
	    rtl/cmac/rk_conv_3x3_valid_c4_front.sv rtl/cmac/rk_conv_simple_core.sv
synth-check: generated-check
	$(PYTHON) tools/run_synth.py
	$(PYTHON) tools/run_host_synth.py
host-synth-check: generated-check
	$(PYTHON) tools/run_host_synth.py
host-mapped-check: generated-check
	$(PYTHON) tools/run_host_mapped.py
# Standalone PPU increments: exact captured RK3588 whole-BO replay, simulators only.
ppu-fixture-set-contract-test: generated-check
	$(PYTHON) -m unittest tests.ppu_pooling.test_pool_fixture_set_contract -v
ppu-int-k2s2-test: generated-check
	$(PYTHON) tools/ppu/run_pool_int_k2s2.py --simulator verilator
ppu-int-k2s2-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_int_k2s2.py --simulator iverilog
ppu-int-k2s2-contract-test: generated-check
	$(PYTHON) -m unittest tests.ppu_pooling.test_pool_int_k2s2_contract -v
ppu-int-avg-test: generated-check
	$(PYTHON) tools/ppu/run_pool_int_avg.py --simulator verilator
ppu-int-avg-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_int_avg.py --simulator iverilog
ppu-pad-tail-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad_tail.py --simulator verilator
ppu-pad-tail-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad_tail.py --simulator iverilog
ppu-pad-avg-contract-test: generated-check
	$(PYTHON) -m unittest tests.ppu_pooling.test_pool_pad_and_avg_contract -v
ppu-i8-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_i8_k2s2_dma.py --simulator verilator
ppu-i8-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_i8_k2s2_dma.py --simulator iverilog
ppu-i8-dma-contract-test: generated-check
	$(PYTHON) -m unittest tests.ppu_pooling.test_pool_board_image_contract -v
ppu-board-test: generated-check
	$(PYTHON) tools/ppu/run_ppu_board.py --simulator verilator
ppu-board-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_ppu_board.py --simulator iverilog
ppu-board-contract-test: generated-check
	$(PYTHON) -m unittest tests.ppu_pooling.test_pool_board_image_contract -v
ppu-board-lint: generated-check
	@command -v verilator >/dev/null || { echo 'UNAVAILABLE: Verilator is required for RTL lint.' >&2; exit 2; }
	verilator --lint-only -Wall -Wno-fatal --top-module tb_ypcb_ppu_i8 \
	    rtl/ppu/rk_ppu_pool_self_test.sv rtl/ppu/rk_ppu_pool_demo_rom.sv \
	    rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv rtl/ppu/rk_ppu_pool_i8_k2s2_profile.sv \
	    rtl/ppu/rk_ppu_pool_int_k2s2.sv rtl/rk_bram.sv rtl/rk_startup_reset.sv \
	    fpga/ypcb_ppu_i8_top.sv tests/tb_ypcb_ppu_i8.sv
ppu-image-render: generated-check
	$(PYTHON) tools/ppu/vivado_ppu.py render
# Full synthesis/place/route of the pooling image. Opt-in: requires the board
# confirmation in the environment and performs no programming.
ppu-image-vivado: generated-check
	@command -v vivado >/dev/null || { echo 'UNAVAILABLE: full Vivado is required.' >&2; exit 2; }
	@test -n "$(RK_CONFIRM_BOARD)" || { echo 'UNAVAILABLE: set RK_CONFIRM_BOARD=YPCB_00338_1P1.' >&2; exit 2; }
	$(PYTHON) tools/ppu/vivado_ppu.py run
ppu-max-test: generated-check
	$(PYTHON) tools/ppu/run_pool_max.py --simulator verilator
ppu-max-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_max.py --simulator iverilog
ppu-max-pad1-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1.py --simulator verilator
ppu-max-pad1-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1.py --simulator iverilog
ppu-avg-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg.py --simulator verilator
ppu-avg-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg.py --simulator iverilog
ppu-avg-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_avg_contract.py' -v
ppu-min-test: generated-check
	$(PYTHON) tools/ppu/run_pool_min.py --simulator verilator
ppu-min-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_min.py --simulator iverilog
ppu-min-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_min_contract.py' -v
ppu-index-test: generated-check
	$(PYTHON) tools/ppu/run_pool_index.py --simulator verilator
ppu-index-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_index.py --simulator iverilog
ppu-index-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_index_contract.py' -v
ppu-c3-tail-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c3_tail.py --simulator verilator
ppu-c3-tail-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c3_tail.py --simulator iverilog
ppu-c3-tail-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_c3_tail_contract.py' -v
ppu-c3-raw-profile-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c3_raw_profile.py --simulator verilator
ppu-c3-raw-profile-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c3_raw_profile.py --simulator iverilog
ppu-c3-raw-profile-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_c3_raw_profile_contract.py' -v
ppu-c8-raw-profile-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c8_raw_profile.py --simulator verilator
ppu-c8-raw-profile-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c8_raw_profile.py --simulator iverilog
ppu-c8-raw-profile-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_c8_raw_profile_contract.py' -v
ppu-pad1-raw-profile-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1_raw_profile.py --simulator verilator
ppu-pad1-raw-profile-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1_raw_profile.py --simulator iverilog
ppu-pad1-raw-profile-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_pad1_raw_profile_contract.py' -v
ppu-min-raw-profile-test: generated-check
	$(PYTHON) tools/ppu/run_pool_min_raw_profile.py --simulator verilator
ppu-min-raw-profile-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_min_raw_profile.py --simulator iverilog
ppu-min-raw-profile-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_min_raw_profile_contract.py' -v
ppu-avg-raw-profile-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg_raw_profile.py --simulator verilator
ppu-avg-raw-profile-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg_raw_profile.py --simulator iverilog
ppu-avg-raw-profile-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_avg_raw_profile_contract.py' -v
ppu-index-raw-profile-test: generated-check
	$(PYTHON) tools/ppu/run_pool_index_raw_profile.py --simulator verilator
ppu-index-raw-profile-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_index_raw_profile.py --simulator iverilog
ppu-index-raw-profile-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_index_raw_profile_contract.py' -v
ppu-c3-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c3_raw_dma.py --simulator verilator
ppu-c3-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c3_raw_dma.py --simulator iverilog
ppu-c3-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_c3_raw_dma_contract.py' -v
ppu-c8-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c8_raw_dma.py --simulator verilator
ppu-c8-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_c8_raw_dma.py --simulator iverilog
ppu-c8-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_c8_raw_dma_contract.py' -v
ppu-pad1-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1_raw_dma.py --simulator verilator
ppu-pad1-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_pad1_raw_dma.py --simulator iverilog
ppu-pad1-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_pad1_raw_dma_contract.py' -v
ppu-min-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_min_raw_dma.py --simulator verilator
ppu-min-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_min_raw_dma.py --simulator iverilog
ppu-min-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_min_raw_dma_contract.py' -v
ppu-avg-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg_raw_dma.py --simulator verilator
ppu-avg-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg_raw_dma.py --simulator iverilog
ppu-avg-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_avg_raw_dma_contract.py' -v
ppu-index-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_index_raw_dma.py --simulator verilator
ppu-index-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_index_raw_dma.py --simulator iverilog
ppu-index-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_index_raw_dma_contract.py' -v
ppu-global-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_global_raw_dma.py --simulator verilator
ppu-global-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_global_raw_dma.py --simulator iverilog
ppu-global-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_global_raw_dma_contract.py' -v
ppu-avg-global3x5-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg_global3x5.py --simulator verilator
ppu-avg-global3x5-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_avg_global3x5.py --simulator iverilog
ppu-avg-global3x5-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_global_avg_raw_profile_contract.py' -v
ppu-global-avg-raw-profile-test: generated-check
	$(PYTHON) tools/ppu/run_pool_global_avg_raw_profile.py --simulator verilator
ppu-global-avg-raw-profile-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_global_avg_raw_profile.py --simulator iverilog
ppu-global-avg-raw-profile-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_global_avg_raw_profile_contract.py' -v
ppu-global-avg-raw-dma-test: generated-check
	$(PYTHON) tools/ppu/run_pool_global_avg_raw_dma.py --simulator verilator
ppu-global-avg-raw-dma-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_pool_global_avg_raw_dma.py --simulator iverilog
ppu-global-avg-raw-dma-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_global_avg_raw_dma_contract.py' -v
ppu-c3-job-control-test: generated-check
	$(PYTHON) tools/ppu/run_c3_job_control.py --simulator verilator
ppu-c3-job-control-four-state-test: generated-check
	$(PYTHON) tools/ppu/run_c3_job_control.py --simulator iverilog
ppu-c3-job-control-contract-test: generated-check
	$(PYTHON) -m unittest discover -s tests/ppu_pooling -p 'test_pool_c3_job_control_contract.py' -v
ppu-max-lint: generated-check
	@command -v verilator >/dev/null || { echo 'UNAVAILABLE: Verilator is required for RTL lint.' >&2; exit 2; }
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s1_c8 $(PPU_MAX_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2 $(PPU_MAX_PAD1_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_avg2x2s1_fp16_capture $(PPU_AVG_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_min2x2s1_fp16_capture $(PPU_MIN_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s2_index_c8_h2w2 $(PPU_INDEX_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max16x16s16_c8 $(PPU_GLOBAL_LEAF_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s2_c3_tail_h2w2 $(PPU_C3_TAIL_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_c3_raw_profile $(PPU_C3_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_c8_raw_profile $(PPU_C8_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_pad1_raw_profile $(PPU_PAD1_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_min_raw_profile $(PPU_MIN_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_avg_raw_profile $(PPU_AVG_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_raw_dma $(PPU_RAW_DMA_RTL)

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
	verilator --lint-only -Wall --top-module rk_ppu_pool_avg2x2s1_fp16_capture $(PPU_AVG_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_min2x2s1_fp16_capture $(PPU_MIN_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s2_index_c8_h2w2 $(PPU_INDEX_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max16x16s16_c8 $(PPU_GLOBAL_LEAF_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s2_c3_tail_h2w2 $(PPU_C3_TAIL_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_c3_raw_profile $(PPU_C3_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_c8_raw_profile $(PPU_C8_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_pad1_raw_profile $(PPU_PAD1_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_min_raw_profile $(PPU_MIN_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_avg_raw_profile $(PPU_AVG_PROFILE_RTL)
	verilator --lint-only -Wall --top-module rk_ppu_pool_raw_dma $(PPU_RAW_DMA_RTL)

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
