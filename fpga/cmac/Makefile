# Consolidated NVDLA-derived CMAC build; invoke from any working directory.
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
PYTHON ?= python3
TOOL ?= verilator
.DEFAULT_GOAL := cmac-test
.PHONY: cmac-dsp-prefix-control-test cmac-dsp-prefix-test
cmac-dsp-prefix-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_control.py -v
cmac-dsp-prefix-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_dsp_prefix_carry.py
.PHONY: cmac-dsp-prefix-mapped-control-test cmac-dsp-prefix-mapped-test
cmac-dsp-prefix-mapped-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_mapped_prefix_dsp_control.py -v
cmac-dsp-prefix-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_mapped_prefix_dsp.py --area-report "$(AREA_REPORT)"
.PHONY: array-dsp-prefix-control-test array-dsp-prefix-prepare array-dsp-prefix-native-test
array-dsp-prefix-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_array_control.py -v
array-dsp-prefix-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_dsp_prefix_array.py
array-dsp-prefix-native-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_dsp_prefix_array_native.py --lane-report "$(LANE_REPORT)" --prepared-report "$(PREPARED_REPORT)"
.PHONY: array-dsp-prefix-area-control-test array-dsp-prefix-area
array-dsp-prefix-area-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_array_area_control.py -v
array-dsp-prefix-area:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_dsp_prefix_array.py --lane-report "$(LANE_REPORT)"
.PHONY: array-dsp-prefix-board-preparation-control-test array-dsp-prefix-board-prepare
array-dsp-prefix-board-preparation-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_board_preparation_control.py -v
array-dsp-prefix-board-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_dsp_prefix_board.py --lane-report "$(LANE_REPORT)"
.PHONY: array-dsp-prefix-board-replay-control-test array-dsp-prefix-board-replay
array-dsp-prefix-board-replay-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_board_replay_control.py -v
array-dsp-prefix-board-replay:
	cd $(ROOT) && $(PYTHON) tools/cmac/replay_dsp_prefix_board.py --native-report "$(NATIVE_REPORT)" --prepared-report "$(PREPARED_REPORT)" --composed-report "$(COMPOSED_REPORT)"
.PHONY: array-dsp-prefix-board-area-control-test array-dsp-prefix-board-area array-dsp-prefix-board-mapping-preparation-control-test array-dsp-prefix-board-mapping-prepare
array-dsp-prefix-board-area-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_board_area_control.py -v
array-dsp-prefix-board-area:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_dsp_prefix_board.py --area-report "$(AREA_REPORT)" --board-report "$(BOARD_REPORT)"
array-dsp-prefix-board-mapping-preparation-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_board_mapping_preparation_control.py -v
array-dsp-prefix-board-mapping-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_dsp_prefix_board_mapping.py --area-report "$(AREA_REPORT)" --native-report "$(NATIVE_REPORT)" --prepared-report "$(PREPARED_REPORT)"
.PHONY: array-dsp-prefix-frontend-library-export-control-test
array-dsp-prefix-frontend-library-export-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_frontend_library_export_control.py -v
.PHONY: array-dsp-prefix-mapped-control-test array-dsp-prefix-mapped-test array-dsp-prefix-all-control-test
array-dsp-prefix-mapped-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_prefix_mapped_array_control.py -v
array-dsp-prefix-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_dsp_prefix_mapped_array.py --area-report "$(AREA_REPORT)" --native-report "$(NATIVE_REPORT)"
array-dsp-prefix-all-control-test: cmac-dsp-prefix-control-test cmac-dsp-prefix-mapped-control-test array-dsp-prefix-control-test array-dsp-prefix-area-control-test array-dsp-prefix-board-preparation-control-test array-dsp-prefix-board-replay-control-test array-dsp-prefix-mapped-control-test array-dsp-prefix-board-area-control-test array-dsp-prefix-board-mapping-preparation-control-test array-dsp-prefix-frontend-library-export-control-test
.PHONY: array-dsp-board-replay-control-test array-dsp-board-replay
array-dsp-board-replay-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_board_replay_control.py -v
array-dsp-board-replay:
	cd $(ROOT) && $(PYTHON) tools/cmac/replay_dsp_board.py --native-report "$(NATIVE_REPORT)" --prepared-report "$(PREPARED_REPORT)" --composed-report "$(COMPOSED_REPORT)"
.PHONY: array-dsp-board-area-control-test array-dsp-board-area
array-dsp-board-area-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_board_area_control.py -v
array-dsp-board-area:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_dsp_board.py --area-report "$(AREA_REPORT)" --board-report "$(BOARD_REPORT)"
.PHONY: array-dsp-mapped-control-test array-dsp-mapped-test
array-dsp-mapped-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_dsp_mapped_array_control.py -v
array-dsp-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_dsp_mapped_array.py --area-report "$(AREA_REPORT)" --native-report "$(NATIVE_REPORT)"
.PHONY: array-dsp-build-control-test array-dsp-vivado-prepare array-dsp-vivado
array-dsp-build-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_vivado_dsp_array_control.py -v
array-dsp-vivado-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_dsp_array.py prepare
array-dsp-vivado:
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_dsp_array.py run --area-report "$(AREA_REPORT)" --native-report "$(NATIVE_REPORT)" --board-report "$(BOARD_REPORT)" --mapped-report "$(MAPPED_REPORT)"
ATOMIC_C ?= 32
ATOMIC_K ?= 16
.PHONY: cmac-vectors cmac-test cmac-stream-test cmac-nvdla-model cmac-nvdla-rtl cmac-map cmac-mapped-test
cmac-vectors:
	cd $(ROOT) && { test -f build/rknpu-cmac-array/c$(ATOMIC_C)k$(ATOMIC_K)/vectors_report.json || $(PYTHON) tools/cmac/gen_array_vectors.py --channels $(ATOMIC_C) --kernels $(ATOMIC_K); }
cmac-test: cmac-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array.py --tool $(TOOL) --channels $(ATOMIC_C) --kernels $(ATOMIC_K)
cmac-stream-test: cmac-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_stream.py --tool $(TOOL) --channels $(ATOMIC_C) --kernels $(ATOMIC_K)
cmac-nvdla-model: cmac-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/check_nvdla_mac_cell.py --channels $(ATOMIC_C) --kernels $(ATOMIC_K)
cmac-nvdla-rtl: cmac-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_nvdla_rtl.py --channels $(ATOMIC_C) --kernels $(ATOMIC_K)
cmac-map:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_array.py --channels $(ATOMIC_C) --kernels $(ATOMIC_K)
.PHONY: cmac-map-unshared cmac-o0-test
cmac-map-unshared:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_array_unshared.py --channels $(ATOMIC_C) --kernels $(ATOMIC_K)
cmac-o0-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_o0.py --generated-report "$(GENERATED_REPORT)"
.PHONY: cmac-hier-test cmac-hier-replay
cmac-hier-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_hier_array.py --flat-report "$(FLAT_REPORT)"
cmac-hier-replay:
	cd $(ROOT) && $(PYTHON) tools/cmac/replay_hier_array.py --compiled-report "$(COMPILED_REPORT)"
.PHONY: hierarchy-probe cmac-hier-explicit-test
hierarchy-probe:
	cd $(ROOT) && $(PYTHON) tools/cmac/probe_hierarchy.py
cmac-hier-explicit-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_hier_array_explicit.py --flat-report "$(FLAT_REPORT)" --probe-report "$(PROBE_REPORT)"
.PHONY: cmac-hier-o2-test
cmac-hier-o2-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/rebuild_hier_array.py --source-report "$(SOURCE_REPORT)"
cmac-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_mapped_array.py --mapping-report "$(MAPPING_REPORT)" --native-report "$(NATIVE_REPORT)" --suite $(or $(SUITE),smoke)
.PHONY: cacc-array-vectors cacc-array-test cmac-cacc-test
cacc-array-vectors:
	cd $(ROOT) && { test -f build/rknpu-cmac-array/c32k16/vectors_report.json || $(PYTHON) tools/cmac/gen_array_vectors.py --channels 32 --kernels 16; }
	cd $(ROOT) && { test -f build/rknpu-cacc-array/c32k16/vectors_report.json || $(PYTHON) tools/cmac/gen_cacc_array_vectors.py; }
cacc-array-test: cacc-array-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_cacc_array.py --tool $(TOOL)
cmac-cacc-test: cacc-array-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_cmac_cacc.py --kernels $(ATOMIC_K)
.PHONY: frame-output-vectors frame-output-test array-datapath-test
frame-output-vectors: cacc-array-vectors
	cd $(ROOT) && { test -f build/rknpu-frame-output/vectors_report.json || $(PYTHON) tools/cmac/gen_frame_output_vectors.py; }
frame-output-test: frame-output-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_frame_output.py --tool $(TOOL)
array-datapath-test: frame-output-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_datapath.py --suite $(or $(SUITE),full)
.PHONY: array-front-vectors array-front-test rw-arbiter-test
array-front-vectors:
	cd $(ROOT) && { test -f build/cmac_vectors/vectors_report.json || $(PYTHON) tools/gen_cmac_vectors.py; }
	cd $(ROOT) && { test -f build/rknpu-array-front/vectors_report.json || $(PYTHON) tools/cmac/gen_array_front_vectors.py; }
array-front-test: array-front-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_front.py --tool $(TOOL)
rw-arbiter-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_rw_arbiter.py --tool $(TOOL)
.PHONY: array-core-vectors array-core-test array-core-model
array-core-vectors: array-front-vectors frame-output-vectors
	cd $(ROOT) && { test -f build/rknpu-array-core-vectors/vectors_report.json || $(PYTHON) tools/cmac/gen_array_core_vectors.py; }
array-core-test: array-core-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_core.py --suite $(or $(SUITE),full)
array-core-model: array-core-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/check_array_core_model.py
.PHONY: array-core-replay
array-core-replay:
	cd $(ROOT) && $(PYTHON) tools/cmac/replay_array_core.py --compiled-report "$(COMPILED_REPORT)" --suite $(or $(SUITE),full)
.PHONY: array-dma-test array-dma-replay
array-dma-test: array-core-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_dma.py --suite $(or $(SUITE),smoke)
array-dma-replay:
	cd $(ROOT) && $(PYTHON) tools/cmac/replay_array_dma.py --compiled-report "$(COMPILED_REPORT)" --suite $(or $(SUITE),protocol)
.PHONY: array-axi-test
array-axi-test: array-core-vectors
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_axi.py --suite $(or $(SUITE),smoke)
.PHONY: array-axi-hier-test
.PHONY: cmac-map-hierarchical
cmac-map-hierarchical:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_array_hierarchical.py --native-report "$(NATIVE_REPORT)"
array-axi-hier-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_axi_hier.py --native-report "$(NATIVE_REPORT)" --cmac-report "$(CMAC_REPORT)" --donor-report "$(CACC_REPORT)" --donor-report "$(OUTPUT_REPORT)"
.PHONY: array-board-check array-board-test
array-board-check:
	cd $(ROOT) && $(PYTHON) tools/cmac/gen_array_board.py --check
array-board-test: array-board-check
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_board.py --suite $(or $(SUITE),smoke)
.PHONY: array-board-hier-test
array-board-hier-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_array_board_hier.py --board-report "$(BOARD_REPORT)" --cmac-report "$(CMAC_REPORT)" --donor-report "$(CACC_REPORT)" --donor-report "$(OUTPUT_REPORT)"
.PHONY: array-build-control-test array-vivado-prepare array-vivado
array-build-control-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/check_array_build.py
array-vivado-prepare: array-board-check
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_array.py prepare
array-vivado: array-board-check
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_array.py run --board-report "$(BOARD_REPORT)"
.PHONY: cmac-fixed-rows-test cmac-fixed-test cmac-fixed-area array-bitstream-review array-bitstream
cmac-fixed-rows-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_fixed_fp16_rows.py --tool $(TOOL)
cmac-fixed-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_fixed_array.py --flat-report "$(FLAT_REPORT)" --rows-report "$(ROWS_REPORT)" --area-report "$(AREA_REPORT)" --probe-report "$(PROBE_REPORT)"
cmac-fixed-area:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_fixed_array.py --rows-area-report "$(AREA_REPORT)"
.PHONY: cmac-fixed-rows-mapped-test
cmac-fixed-rows-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_fixed_rows_mapped.py --area-report "$(AREA_REPORT)" --rows-report "$(ROWS_REPORT)"
.PHONY: cmac-fixed-rows-mapped-formal cmac-fixed-rows-formal-control-test
cmac-fixed-rows-mapped-formal:
	cd $(ROOT) && $(PYTHON) tools/cmac/prove_fixed_rows_mapped.py --area-report "$(AREA_REPORT)" --rows-report "$(ROWS_REPORT)"
cmac-fixed-rows-formal-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_mapped_rows_formal_control.py -v
.PHONY: cmac-fixed-mapped-test cmac-fixed-mapped-control-test
cmac-fixed-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_fixed_mapped_array.py --area-report "$(AREA_REPORT)" --fixed-report "$(FIXED_REPORT)"
cmac-fixed-mapped-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_fixed_mapped_array_control.py -v
.PHONY: array-fixed-area
array-fixed-area:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_fixed_board.py --area-report "$(AREA_REPORT)" --fixed-report "$(FIXED_REPORT)" --board-report "$(BOARD_REPORT)"
.PHONY: array-shared-cone-control-test array-shared-cone-analysis
array-shared-cone-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_shared_kernel_cones.py
array-shared-cone-analysis:
	cd $(ROOT) && $(PYTHON) tools/cmac/analyze_shared_kernel_cones.py --mapping-report "$(MAPPING_REPORT)"
.PHONY: array-shared-board-control-test array-shared-board-prepare
array-shared-board-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_shared_board_prepare.py
	cd $(ROOT) && $(PYTHON) tests/cmac/test_board_netlist_export.py
array-shared-board-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_shared_board.py --mapping-report "$(MAPPING_REPORT)"
.PHONY: array-lut-pair-control-test array-lut-pair-prepare
array-lut-pair-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_board_lut_pair.py
array-lut-pair-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/pair_board_luts.py --mapping-report "$(MAPPING_REPORT)"
.PHONY: cmac-paired-mapped-control-test cmac-paired-mapped-test
cmac-paired-mapped-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_paired_mapped_array_control.py
cmac-paired-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_paired_mapped_array.py --area-report "$(AREA_REPORT)" --fixed-report "$(FIXED_REPORT)" --paired-report "$(PAIRED_REPORT)"
.PHONY: array-lut-pair-unisim-control-test array-lut-pair-unisim-test array-mapped-bench-binding-control-test array-mapped-bench-binding
array-lut-pair-unisim-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_lut_pair_unisim_control.py
array-lut-pair-unisim-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_lut_pair_unisim.py --paired-report "$(PAIRED_REPORT)"
array-mapped-bench-binding-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_mapped_board_bench_binding.py
array-mapped-bench-binding:
	cd $(ROOT) && $(PYTHON) tools/cmac/bind_mapped_board_bench.py --mapping-report "$(MAPPING_REPORT)"
.PHONY: array-observed-board-prepare-control-test array-observed-board-prepare
array-observed-board-prepare-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_observed_board_prepare_control.py
array-observed-board-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_observed_board.py --mapping-report "$(MAPPING_REPORT)"
.PHONY: array-observed-board-mapping-control-test array-observed-board-map
array-observed-board-mapping-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_observed_board_mapping_control.py
array-observed-board-map:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_observed_board.py --preparation-report "$(PREPARATION_REPORT)"
.PHONY: array-unisim-model-control-test array-unisim-model-control array-observed-mapped-control-test array-observed-mapped-test
array-unisim-model-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_unisim_board_models_control.py
array-unisim-model-control:
	cd $(ROOT) && $(PYTHON) tools/cmac/check_unisim_board_models.py
array-observed-mapped-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_observed_mapped_board_control.py
array-observed-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_observed_mapped_board.py --mapping-report "$(MAPPING_REPORT)"
.PHONY: array-fixed-board-test array-fixed-board-control-test
array-fixed-board-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_fixed_array_board.py --tool $(TOOL) --fixed-report "$(FIXED_REPORT)" --board-report "$(BOARD_REPORT)" --donor-report "$(CACC_REPORT)" --donor-report "$(OUTPUT_REPORT)"
array-fixed-board-control-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/check_fixed_board_control.py
.PHONY: array-fixed-vivado-prepare array-fixed-vivado array-fixed-build-control-test
array-fixed-build-control-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/check_fixed_array_build.py
array-fixed-vivado-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_fixed_array.py prepare
array-fixed-vivado:
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_fixed_array.py run --fixed-report "$(FIXED_REPORT)" --board-report "$(BOARD_REPORT)"
array-bitstream-review:
	cd $(ROOT) && $(PYTHON) tools/cmac/emit_array_bitstream.py review-template --implementation-report "$(IMPLEMENTATION_REPORT)"
array-bitstream:
	cd $(ROOT) && $(PYTHON) tools/cmac/emit_array_bitstream.py run --implementation-report "$(IMPLEMENTATION_REPORT)" --review "$(REVIEW)"
.PHONY: check test board-test core-test dma-test memory-test synth pnr
check:
	cd $(ROOT) && $(PYTHON) tools/cmac/run.py check
test: board-test core-test dma-test memory-test
board-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/run.py test --suite board --tool $(TOOL)
core-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/run.py test --suite core --tool $(TOOL)
dma-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/run.py test --suite dma --tool $(TOOL)
memory-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/run.py test --suite memory --tool $(TOOL)
synth:
	cd $(ROOT) && $(PYTHON) tools/cmac/run.py synth
pnr:
	cd $(ROOT) && $(PYTHON) tools/cmac/run.py pnr --synth-report "$(SYNTH_REPORT)"
.PHONY: array-lut-pair-sinks-control-test array-lut-pair-sinks-audit
array-lut-pair-sinks-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_lut_pair_sinks.py
array-lut-pair-sinks-audit:
	cd $(ROOT) && $(PYTHON) tools/cmac/audit_lut_pair_sinks.py --paired-report "$(PAIRED_REPORT)"

.PHONY: array-union-lut-control-test array-union-lut-analyze
array-union-lut-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_union_lut_pairs.py
array-union-lut-analyze:
	cd $(ROOT) && $(PYTHON) tools/cmac/analyze_union_lut_pairs.py --paired-report "$(PAIRED_REPORT)"

.PHONY: array-union-lut-proof-control-test array-union-lut-function-test
array-union-lut-proof-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_union_lut_functions_control.py
array-union-lut-function-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_union_lut_functions.py --analysis-report "$(UNION_ANALYSIS_REPORT)"

.PHONY: lane-dsp-control-test lane-dsp-experiment lane-dsp-area lane-dsp-formal lane-dsp-boolean-formal
lane-dsp-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_lane_dsp_control.py
	cd $(ROOT) && $(PYTHON) tests/cmac/test_lane_dsp_library.py
	cd $(ROOT) && $(PYTHON) tests/cmac/test_lane_dsp_boolean_control.py
lane-dsp-experiment:
	cd $(ROOT) && $(PYTHON) tools/cmac/check_lane_dsp.py
lane-dsp-area:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_lane_dsp_experiment.py
lane-dsp-formal:
	cd $(ROOT) && $(PYTHON) tools/cmac/prove_lane_dsp.py
lane-dsp-boolean-formal:
	cd $(ROOT) && $(PYTHON) tools/cmac/prove_lane_dsp_boolean.py

.PHONY: lane-dsp-mapped-control-test lane-dsp-mapped-test array-dsp-control-test array-dsp-native-test array-dsp-area
lane-dsp-mapped-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_mapped_lane_dsp_control.py
lane-dsp-mapped-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_mapped_lane_dsp.py --area-report "$(LANE_AREA_REPORT)"
array-dsp-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_array_contract.py
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_array_native_control.py
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_array_area_control.py
array-dsp-native-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_dsp_array_native.py --lane-report "$(LANE_REPORT)"
array-dsp-area:
	cd $(ROOT) && $(PYTHON) tools/cmac/map_dsp_array.py --lane-area-report "$(LANE_AREA_REPORT)"

.PHONY: lane-dsp-component-control-test lane-dsp-component-proofs
lane-dsp-component-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_component_proof_control.py
lane-dsp-component-proofs:
	cd $(ROOT) && $(PYTHON) tools/cmac/prove_lane_dsp_components.py

.PHONY: lane-dsp-replay-control-test lane-dsp-replay lane-dsp-tree-range-control-test lane-dsp-tree-range-proofs lane-dsp-donor-range-control-test lane-dsp-donor-ranges
lane-dsp-replay-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_mapped_dsp_replay_control.py
lane-dsp-replay:
	cd $(ROOT) && $(PYTHON) tools/cmac/replay_mapped_lane_dsp.py --timed-out-report "$(TIMED_OUT_REPORT)"
lane-dsp-tree-range-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_tree_range_control.py
lane-dsp-tree-range-proofs:
	cd $(ROOT) && $(PYTHON) tools/cmac/prove_lane_dsp_tree_ranges.py
lane-dsp-donor-range-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_donor_range_control.py
lane-dsp-donor-ranges:
	cd $(ROOT) && $(PYTHON) tools/cmac/audit_lane_dsp_ranges.py --tree-report "$(TREE_REPORT)"

.PHONY: array-dsp-board-preparation-control-test array-dsp-board-prepare
array-dsp-board-preparation-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_board_preparation_control.py
array-dsp-board-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_dsp_board.py

.PHONY: lane-dsp-product-control-test lane-dsp-product-certificate lane-dsp-composed-control-test lane-dsp-composed-certificate array-dsp-stage-probe
lane-dsp-product-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_product_certificate_control.py
lane-dsp-product-certificate:
	cd $(ROOT) && $(PYTHON) tools/cmac/audit_lane_dsp_product.py --range-report "$(RANGE_REPORT)" --component-report "$(COMPONENT_REPORT)"
lane-dsp-composed-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_composed_certificate_control.py
lane-dsp-composed-certificate:
	cd $(ROOT) && $(PYTHON) tools/cmac/prove_lane_dsp_composed.py --product-report "$(PRODUCT_REPORT)"
array-dsp-stage-probe:
	cd $(ROOT) && $(PYTHON) tools/cmac/probe_dsp_stage_execution.py

.PHONY: array-shared-union-lut-control-test array-shared-union-lut-analyze
array-shared-union-lut-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_shared_union_lut_control.py
array-shared-union-lut-analyze:
	cd $(ROOT) && $(PYTHON) tools/cmac/analyze_shared_union_lut_pairs.py --paired-report "$(PAIRED_REPORT)"

.PHONY: array-shared-union-board-control-test array-shared-union-board-prepare
array-shared-union-board-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_shared_union_board_control.py
array-shared-union-board-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_shared_union_board.py --analysis-report "$(UNION_ANALYSIS_REPORT)"

.PHONY: array-shared-union-function-fixture array-shared-union-function-test
array-shared-union-function-fixture:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_shared_union_board_functions.py --fixture
array-shared-union-function-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_shared_union_board_functions.py --analysis-report "$(UNION_ANALYSIS_REPORT)"

.PHONY: array-cofactor-lut-control-test array-cofactor-lut-analyze array-cofactor-function-fixture array-cofactor-function-test
array-cofactor-lut-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_cofactor_lut_pair_control.py
	cd $(ROOT) && $(PYTHON) tests/cmac/test_cofactor_lut_functions_control.py
array-cofactor-lut-analyze:
	cd $(ROOT) && $(PYTHON) tools/cmac/analyze_cofactor_lut_pairs.py --analysis-report "$(UNION_ANALYSIS_REPORT)"
array-cofactor-function-fixture:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_cofactor_lut_functions.py --fixture
array-cofactor-function-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_cofactor_lut_functions.py --analysis-report "$(COFACTOR_ANALYSIS_REPORT)"

.PHONY: array-augmented-union-control-test array-augmented-union-analyze
array-augmented-union-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_augmented_union_pairs.py
array-augmented-union-analyze:
	cd $(ROOT) && $(PYTHON) tools/cmac/analyze_augmented_union_pairs.py --analysis-report "$(UNION_ANALYSIS_REPORT)"

.PHONY: array-dsp-prefix-vivado-control-test array-dsp-prefix-vivado-prepare array-dsp-prefix-vivado
array-dsp-prefix-vivado-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_vivado_dsp_prefix_array_control.py
array-dsp-prefix-vivado-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_dsp_prefix_array.py prepare
array-dsp-prefix-vivado:
	cd $(ROOT) && $(PYTHON) tools/cmac/vivado_dsp_prefix_array.py run --area-report "$(AREA_REPORT)" --native-report "$(NATIVE_REPORT)" --board-report "$(BOARD_REPORT)" --mapped-report "$(MAPPED_REPORT)"

.PHONY: array-dsp-prefix-primitive-model-control-test array-dsp-prefix-primitive-model-test
array-dsp-prefix-primitive-model-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_primitive_models_control.py
array-dsp-prefix-primitive-model-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_dsp_prefix_primitive_models.py --mapped-report "$(MAPPED_REPORT)" --simulator "$(TOOL)"

.PHONY: array-dsp-prefix-emitter-control-test array-dsp-prefix-bitstream-review-template array-dsp-prefix-bitstream
array-dsp-prefix-emitter-control-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/check_dsp_prefix_emitter.py
array-dsp-prefix-bitstream-review-template:
	cd $(ROOT) && $(PYTHON) tools/cmac/emit_dsp_prefix_bitstream.py review-template --implementation-report "$(IMPLEMENTATION_REPORT)"
array-dsp-prefix-bitstream:
	cd $(ROOT) && $(PYTHON) tools/cmac/emit_dsp_prefix_bitstream.py run --implementation-report "$(IMPLEMENTATION_REPORT)" --review "$(REVIEW)"

.PHONY: array-dsp-prefix-preparation-control-test
array-dsp-prefix-preparation-control-test: array-dsp-prefix-all-control-test array-dsp-prefix-vivado-control-test array-dsp-prefix-primitive-model-control-test array-dsp-prefix-emitter-control-test

.PHONY: array-dsp-prefix-pin-cone-control-test array-dsp-prefix-pin-cone-test array-dsp-prefix-compile-inventory-control-test array-dsp-prefix-compile-inventory-test array-dsp-prefix-diagnostic-preparation-control-test
array-dsp-prefix-pin-cone-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_pin_cone_control.py
array-dsp-prefix-pin-cone-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/audit_dsp_prefix_pin_cone.py --mapped-report "$(MAPPED_REPORT)"
array-dsp-prefix-compile-inventory-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_compile_inventory_control.py
array-dsp-prefix-compile-inventory-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/audit_dsp_prefix_compile_inventory.py --mapped-report "$(MAPPED_REPORT)" --cone-report "$(CONE_REPORT)"
array-dsp-prefix-diagnostic-preparation-control-test: array-dsp-prefix-primitive-model-control-test array-dsp-prefix-pin-cone-control-test array-dsp-prefix-compile-inventory-control-test

.PHONY: array-dsp-prefix-model-proof-control-test array-dsp-prefix-model-proof array-dsp-prefix-mapped-continuation-control-test array-dsp-prefix-mapped-continuation array-dsp-prefix-extended-diagnostic-control-test
array-dsp-prefix-model-proof-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_actual_model_proof_control.py
array-dsp-prefix-model-proof:
	cd $(ROOT) && $(PYTHON) tools/cmac/prove_dsp_prefix_actual_model.py --cone-report "$(CONE_REPORT)"
array-dsp-prefix-mapped-continuation-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_compile_admission_control.py
array-dsp-prefix-mapped-continuation:
	cd $(ROOT) && $(PYTHON) tools/cmac/continue_dsp_prefix_mapped_array.py --compile-report "$(MAPPED_REPORT)" --inventory-report "$(INVENTORY_REPORT)" --cone-report "$(CONE_REPORT)" --proof-report "$(MODEL_PROOF_REPORT)" --verilator-report "$(PRIMITIVE_VERILATOR_REPORT)" --iverilog-report "$(PRIMITIVE_IVERILOG_REPORT)" --archive-report "$(COMPILE_ARCHIVE_INDEX)"
array-dsp-prefix-extended-diagnostic-control-test: array-dsp-prefix-diagnostic-preparation-control-test array-dsp-prefix-model-proof-control-test array-dsp-prefix-mapped-continuation-control-test array-dsp-prefix-protected-library-control-test array-dsp-prefix-build-contract-control-test

.PHONY: array-dsp-prefix-build-contract-control-test
array-dsp-prefix-build-contract-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_build_contract_control.py

.PHONY: array-dsp-prefix-clean-replay-admission-control-test
array-dsp-prefix-clean-replay-admission-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_clean_replay_admission_control.py

.PHONY: array-dsp-prefix-accepted-checkpoint-prepare
array-dsp-prefix-accepted-checkpoint-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_dsp_prefix_checkpoint.py --area-report "$(AREA_REPORT)" --native-report "$(NATIVE_REPORT)" --board-report "$(BOARD_REPORT)" --mapped-report "$(MAPPED_REPORT)"

.PHONY: array-dsp-prefix-fdce-startup-test array-dsp-prefix-protected-library-control-test array-dsp-prefix-generated-top-replay
array-dsp-prefix-fdce-startup-test:
	cd $(ROOT) && $(PYTHON) tools/cmac/test_dsp_prefix_fdce_startup.py --compile-report "$(MAPPED_REPORT)" --simulator "$(TOOL)"
array-dsp-prefix-protected-library-control-test:
	cd $(ROOT) && $(PYTHON) tests/cmac/test_dsp_prefix_protected_library_control.py
array-dsp-prefix-generated-top-replay:
	cd $(ROOT) && $(PYTHON) tools/cmac/resume_dsp_prefix_generated_top.py --top-report "$(TOP_REPORT)" --fdce-verilator-report "$(FDCE_VERILATOR_REPORT)" --fdce-iverilog-report "$(FDCE_IVERILOG_REPORT)" --top-archive-report "$(TOP_ARCHIVE_INDEX)" --interface-archive-report "$(INTERFACE_ARCHIVE_INDEX)" --build-errors-archive-report "$(BUILD_ERRORS_ARCHIVE_INDEX)"
# Serialized raw-command numerical board: source preparation only.
.PHONY: serial-vivado-prepare serial-vivado-control-test
serial-vivado-prepare:
	cd $(ROOT) && $(PYTHON) tools/cmac/prepare_serial_board.py prepare
serial-vivado-control-test:
	cd $(ROOT) && $(PYTHON) -m unittest discover -s tests/cmac -p test_prepare_serial_board.py -v
