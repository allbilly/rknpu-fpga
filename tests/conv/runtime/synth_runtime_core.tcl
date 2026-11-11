# SPDX-License-Identifier: MIT
# Out-of-context synthesis area estimate for the runtime-decoded conv engine
# (EXPERIMENTAL prototype, task-13). No place/route, no bitstream, no hardware.
#
# Usage (through the host guard, from the repository root):
#   vivado -mode batch -notrace -source tests/conv/runtime/synth_runtime_core.tcl \
#          -tclargs build/runtime-conv-lab/area/ooc-<stamp>
#
# The runtime engine has no geometry parameters (geometry is runtime-decoded,
# operand stores sized for the corpus maxima), so one OOC synthesis of
# rk_conv_runtime_core is the whole area estimate.

set outdir [lindex $argv 0]
if {$outdir eq ""} {
    set outdir [file join build runtime-conv-lab area "ooc-unknown"]
}
file mkdir $outdir

set root [pwd]
set part "xc7k480tffg1156-2"
# Host-thermal policy: keep the synthesis thread count low.
set_param general.maxThreads 2

# Donor NVDLA arithmetic sources (pinned) and the repository CMAC/conv modules
# the runtime core instantiates. The production per-profile cores are NOT read:
# the estimate is the runtime engine alone.
set donor_files [list \
    [file join $root rtl/vendor/nvdla/NV_DW_lsd.v] \
    [file join $root rtl/vendor/nvdla/NV_DW02_tree.v] \
    [file join $root rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v] \
    [file join $root rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v] \
    [file join $root rtl/vendor/nvdla/HLS_fp32_to_fp16.v] \
]
set rtl_files [list \
    [file join $root rtl/cmac/rk_cmac_fp16_cell.sv] \
    [file join $root rtl/cmac/rk_cmac_fp16_array.sv] \
    [file join $root rtl/cmac/rk_nvdla_cacc.sv] \
    [file join $root rtl/cmac/rk_cacc_fp16_array.sv] \
    [file join $root rtl/cmac/rk_cmac_cacc_fp16_array.sv] \
    [file join $root rtl/cmac/rk_nvdla_fp32_to_fp16.sv] \
    [file join $root rtl/cmac/rk_cmac_writer.sv] \
    [file join $root rtl/cmac/rk_cmac_output_nvdla.sv] \
    [file join $root rtl/cmac/rk_cmac_frame_output.sv] \
    [file join $root rtl/cmac/rk_cmac_rw_arbiter.sv] \
    [file join $root rtl/cmac/rk_conv_output_atom.sv] \
    [file join $root rtl/cmac/rk_cmac_fp32_writer.sv] \
    [file join $root rtl/cmac/rk_frame_stage.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_conv_runtime_decode.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_conv_runtime_front.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_conv_runtime_fp32_output.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_conv_runtime_core.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_runtime_sdp_bram.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_runtime_frame_stage.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_runtime_fp16_cell.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_runtime_fp16_array.sv] \
    [file join $root rtl/cmac/experimental/runtime/rk_runtime_cacc_fp16_array.sv] \
]

# Vivado 2026.1 requires compile-unit mode on the source fileset before
# read_verilog accepts -define (older versions accepted it unconditionally).
if {[catch {set_property is_compile_unit_mode true [current_fileset]}]} {
    puts "WARNING: is_compile_unit_mode property unavailable; continuing"
}
# Synthesis elaboration drops the donor assertion instances (they live under
# `ifndef SYNTHESIS`), so the simulation-only compat checkers are not read and
# ASSERT_ON is not defined here. This also avoids the .vlib include path issue
# entirely: synthesis reads only synthesizable donor arithmetic sources.
# Proven in-tree OOC idiom (tools/ppu/ooc_pool_fit.py): an in-memory project,
# fileset properties for defines/include paths, then read_verilog and synthesis.
create_project -in_memory -part $part
set_property verilog_define {DESIGNWARE_NOEXIST SYNTHESIS} [current_fileset]
read_verilog -sv $rtl_files
read_verilog -sv $donor_files

synth_design -flatten_hierarchy rebuilt -part $part -top rk_conv_runtime_core \
    -name runtime_conv_core_ooc

report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization_hier.rpt]
report_utilization -hierarchical -hierarchical_depth 4 \
    -file [file join $outdir utilization_hier_depth4.rpt]
set fp [open [file join $outdir synth_summary.txt] w]
puts $fp "part=$part"
puts $fp "top=rk_conv_runtime_core"
puts $fp "mode=out_of_context (synthesis only; no opt/place/route, no bitstream)"
close $fp
write_checkpoint -force [file join $outdir runtime_conv_core_ooc.dcp]
puts "RUNTIME_OOC_SYNTH_DONE"
