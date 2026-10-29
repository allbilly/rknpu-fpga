# C32/K16 candidate template rendered by tools/cmac/vivado_array.py; unrun in Vivado.
# Tcl control-flow unit tests mock tool commands; they do not validate the design.
# No hardware connection, automatic FPGA programming, or flash writing occurs.
set root {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source}
set out {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/implementation}
if {![info exists ::env(RK_FULL512_STARTUP_SOURCE_SHA)] || $::env(RK_FULL512_STARTUP_SOURCE_SHA) ne "4c40ca1974fc62709de0be270dd34381dbfcf29dd16fb509bfae52d06817981b"} {
    error "Use tools/cmac/startup/prepare.py command after current parent and startup qualification."
}
cd $root
file mkdir $out
if {![info exists ::env(RK_CONFIRM_BOARD)] || $::env(RK_CONFIRM_BOARD) ne "YPCB_00338_1P1"} {
    error "Set RK_CONFIRM_BOARD=YPCB_00338_1P1 only after checking fpga/cmac/startup/ypcb_cmac_array_startup.xdc against your board."
}
# The startup package requires all reviewed electrical/polarity inputs.
foreach setting {RK_CONFIG_VOLTAGE RK_CFGBVS RK_LED_ACTIVE_LOW} {
    if {![info exists ::env($setting)]} {error "Missing reviewed startup setting $setting"}
}
set active_low 0
if {[info exists ::env(RK_LED_ACTIVE_LOW)]} { set active_low $::env(RK_LED_ACTIVE_LOW) }
if {$active_low ni {0 1}} { error "RK_LED_ACTIVE_LOW must be 0 or 1." }
set emit_bitstream 0
if {[info exists ::env(RK_EMIT_BITSTREAM)]} { set emit_bitstream $::env(RK_EMIT_BITSTREAM) }
if {$emit_bitstream ni {0 1}} { error "RK_EMIT_BITSTREAM must be 0 or 1." }
if {$emit_bitstream} { error "Bitstream emission is disabled in this candidate flow." }

# Validate requested settings before doing implementation work. These checks
# enforce a legal pair, not the unmeasured electrical facts of the user's PCB.
# AMD UG912 CFGBVS: GND selects 1.5/1.8 V; VCCO selects 2.5/3.3 V on 7-series.
set have_voltage [info exists ::env(RK_CONFIG_VOLTAGE)]
set have_cfgbvs [info exists ::env(RK_CFGBVS)]
if {$emit_bitstream || $have_voltage || $have_cfgbvs} {
    if {!$have_voltage || !$have_cfgbvs} {
        error "Supply both board-verified RK_CONFIG_VOLTAGE and RK_CFGBVS; see docs/FPGA.md."
    }
    if {$::env(RK_CONFIG_VOLTAGE) ni {1.5 1.8 2.5 3.3}} { error "Invalid RK_CONFIG_VOLTAGE." }
    if {$::env(RK_CFGBVS) ni {GND VCCO}} { error "RK_CFGBVS must be GND or VCCO." }
    if {($::env(RK_CONFIG_VOLTAGE) in {1.5 1.8} && $::env(RK_CFGBVS) ne "GND") ||
        ($::env(RK_CONFIG_VOLTAGE) in {2.5 3.3} && $::env(RK_CFGBVS) ne "VCCO")} {
        error "Incompatible RK_CONFIG_VOLTAGE/RK_CFGBVS pair; verify the actual board supplies and strap."
    }
}
# Exact part from the referenced public board.xml; check the actual device marking.
if {[llength [get_parts -quiet xc7k480tffg1156-2]] != 1} { error "XC7K480T FFG1156-2 support is unavailable." }
create_project -in_memory -part xc7k480tffg1156-2
set_property include_dirs [list {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/vendor/nvdla}] [current_fileset]
set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/vendor/nvdla/NV_DW02_tree.v}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/vendor/nvdla/compat/NV_DW_lsd.v}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/vendor/nvdla/HLS_fp32_to_fp16.v}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/rk_cmac_profile.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/experimental/rk_cmac_fp16_rows.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_nvdla_cacc.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cacc_fp16_array.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/generated/rk_cmac_cacc_fp16_array.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_nvdla_fp32_to_fp16.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_writer.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_output_nvdla.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_frame_output.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_array_datapath.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_array_front.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_rw_arbiter.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_array_core.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_array_dma.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_demo_memory.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_array_demo_rom.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/rk_cmac_array_bram_demo.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/fpga/cmac/startup/ypcb_cmac_array_startup_top.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/rk_startup_reset.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix_pipe.sv}
read_verilog -sv {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix_pipe.sv}
read_xdc {/home/fedora/rknpu-fpga/build/full512-pipeline-preparation/1793008000/source/fpga/cmac/startup/ypcb_cmac_array_startup.xdc}
synth_design -top ypcb_cmac_array_startup_top -part xc7k480tffg1156-2 -generic LED_ACTIVE_LOW=$active_low -flatten_hierarchy none
if {$have_voltage} {
    # Apply BEFORE reports/checkpoints/DRC, not only immediately before writing
    # a bitstream. The reports must describe the requested configuration.
    set_property CONFIG_VOLTAGE $::env(RK_CONFIG_VOLTAGE) [current_design]
    set_property CFGBVS $::env(RK_CFGBVS) [current_design]
}
set clocks [get_clocks -quiet sys_clk]
if {[llength $clocks] != 1} { error "Expected exactly one sys_clk constraint." }
set clock_period [get_property PERIOD [lindex $clocks 0]]
if {![string is double -strict $clock_period] || [catch {expr {double($clock_period) == 20.0}} expected_clock] || !$expected_clock} {
    error "Expected the unchanged 20.000 ns sys_clk constraint."
}
set brams [get_cells -hierarchical -filter {REF_NAME == RAMB18E1 || REF_NAME == RAMB36E1}]
if {[llength $brams] == 0} { error "No block RAM inferred for the BRAM self-test." }

# Preserve and count the actual CMAC hierarchy, independently of shell DSPs.
proc require_full_dsp_cmac {} {
    set kernels [get_cells -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe || REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe}]
    if {[llength $kernels] != 16} { error "Expected sixteen full C32 DSP kernels." }
    set all_dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E1}]
    set owned {}
    foreach kernel $kernels {
        set prefix "[get_property NAME $kernel]/"
        set count 0
        foreach dsp $all_dsps {
            set name [get_property NAME $dsp]
            if {[string first $prefix $name] == 0} {
                if {[dict exists $owned $name]} { error "DSP belongs to duplicate CMAC kernels." }
                dict set owned $name 1
                incr count
            }
        }
        if {$count != 32} { error "Expected 32 DSP48E1 products in every C32 kernel." }
    }
    if {[dict size $owned] != 512} { error "Expected 512 retained parallel CMAC DSP products." }
}
require_full_dsp_cmac

write_checkpoint -force [file join $out post_synth.dcp]
report_utilization -file [file join $out utilization_synth.rpt]
opt_design
place_design
phys_opt_design
route_design
require_full_dsp_cmac
write_checkpoint -force [file join $out routed.dcp]
report_utilization -file [file join $out utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_pulse_width -file [file join $out pulse_width.rpt]
report_drc -file [file join $out drc.rpt]
# Do not confuse "bitstream emitted" with a timing-clean FPGA implementation.
foreach check {no_clock unconstrained_internal_endpoints} {
    set detail [check_timing -override_defaults $check -no_header -return_string]
    set channel [open [file join $out check_timing_${check}.rpt] w]
    puts $channel $detail
    close $channel
    set heading [format {(?im)^\s*(?:[0-9]+\.\s*)?checking\s+%s(?:\s*\([0-9]+\))?\.?\s*$} $check]
    if {![regexp $heading $detail]} { error "Unrecognized $check timing report." }
    set summaries 0
    foreach line [split $detail \n] {
        if {[regexp {^\s*There are ([0-9]+) .+} $line -> count]} {
            incr summaries
            if {$count != 0} { error "Unresolved $check timing findings ($count)." }
        } elseif {[regexp -nocase {there are} $line]} {
            error "Unrecognized $check timing count."
        }
    }
    if {$summaries == 0} { error "Missing $check timing count." }
}
foreach delay_type {max min} {
    set paths [get_timing_paths -delay_type $delay_type -max_paths 1]
    if {[llength $paths] == 0} { error "No $delay_type timing paths found; inspect constraints." }
    foreach path $paths {
        set slack [get_property SLACK $path]
        # Empty, NaN, infinity and unavailable values must never pass signoff.
        if {![string is double -strict $slack] ||
            [catch {expr {abs(double($slack)) < Inf}} finite] || !$finite} {
            error "Invalid $delay_type slack ($slack); no bitstream is emitted."
        }
        if {$slack < 0} { error "Negative $delay_type slack ($slack ns): no bitstream is emitted." }
    }
}
foreach violation [get_drc_violations] {
    set severity [string toupper [get_property SEVERITY $violation]]
    # Do not demote/waive rules. Unknown or absent severity fails closed too.
    if {$severity ni {WARNING ADVISORY INFO}} {
        error "Blocking DRC violation $violation (severity $severity)."
    }
}
puts "C32/K16 routed checkpoint produced; no bitstream or programming. Review unconstrained paths, pulse width, reports and physical board facts before signoff."
