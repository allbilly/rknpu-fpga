# Standalone Vivado build; full Vivado implementation remains unexecuted here.
# Tcl control-flow unit tests mock tool commands; they do not validate the design.
# No hardware connection, automatic FPGA programming, or flash writing occurs.
set root [file normalize [file join [file dirname [info script]] ..]]
set out [file join $root build vivado]
file mkdir $out
if {![info exists ::env(RK_CONFIRM_BOARD)] || $::env(RK_CONFIRM_BOARD) ne "YPCB_00338_1P1"} {
    error "Set RK_CONFIRM_BOARD=YPCB_00338_1P1 only after checking fpga/ypcb.xdc against your board."
}
set active_low 0
if {[info exists ::env(RK_LED_ACTIVE_LOW)]} { set active_low $::env(RK_LED_ACTIVE_LOW) }
if {$active_low ni {0 1}} { error "RK_LED_ACTIVE_LOW must be 0 or 1." }
set emit_bitstream 0
if {[info exists ::env(RK_EMIT_BITSTREAM)]} { set emit_bitstream $::env(RK_EMIT_BITSTREAM) }
if {$emit_bitstream ni {0 1}} { error "RK_EMIT_BITSTREAM must be 0 or 1." }

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
create_project -in_memory -part xc7k480tffg1156-2
set sources [list rk_fp16_alu.sv rk_ew_regs.sv rk_ew_engine.sv rk_ew_dma.sv rk_bram.sv rk_demo_memory.sv rk_dma_demo_rom.sv rk_ew_dma_demo.sv]
foreach source $sources { read_verilog -sv [file join $root rtl $source] }
read_verilog -sv [file join $root fpga ypcb_top.sv]
read_xdc [file join $root fpga ypcb.xdc]
synth_design -top ypcb_top -part xc7k480tffg1156-2 -generic LED_ACTIVE_LOW=$active_low
if {$have_voltage} {
    # Apply BEFORE reports/checkpoints/DRC, not only immediately before writing
    # a bitstream. The reports must describe the requested configuration.
    set_property CONFIG_VOLTAGE $::env(RK_CONFIG_VOLTAGE) [current_design]
    set_property CFGBVS $::env(RK_CFGBVS) [current_design]
}
set brams [get_cells -hierarchical -filter {REF_NAME == RAMB18E1 || REF_NAME == RAMB36E1}]
if {[llength $brams] == 0} { error "No block RAM inferred for the BRAM self-test." }
write_checkpoint -force [file join $out post_synth.dcp]
report_utilization -file [file join $out utilization_synth.rpt]
opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force [file join $out routed.dcp]
report_utilization -file [file join $out utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_drc -file [file join $out drc.rpt]
# Positive setup/hold slack says nothing about endpoints missing a clock or
# timing requirement. Query those internal checks separately; the board's
# intentional external reset/LED exceptions are not no-input/output-delay gates.
# UG835 documents -override_defaults and -return_string (incompatible with
# -file), so preserve each exact returned report ourselves before parsing it.
foreach check {no_clock unconstrained_internal_endpoints} {
    set detail [check_timing -override_defaults $check -no_header -return_string]
    set channel [open [file join $out check_timing_${check}.rpt] w]
    puts $channel $detail
    close $channel
    set heading [format {(?im)^\s*(?:[0-9]+\.\s*)?checking\s+%s(?:\s*\([0-9]+\))?\.?\s*$} $check]
    if {![regexp $heading $detail]} {
        error "Unrecognized $check timing report; no bitstream is emitted."
    }
    set summaries 0
    foreach line [split $detail \n] {
        if {[regexp {^\s*There are ([0-9]+) .+} $line -> count]} {
            incr summaries
            if {$count != 0} { error "Unresolved $check timing findings ($count); no bitstream is emitted." }
        } elseif {[regexp -nocase {there are} $line]} {
            error "Unrecognized $check timing count; no bitstream is emitted."
        }
    }
    if {$summaries == 0} { error "Missing $check timing count; no bitstream is emitted." }
}
# Do not confuse "bitstream emitted" with a timing-clean FPGA implementation.
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
puts "Routed checkpoint/reports produced. Review timing, DRC, BRAM inference and board constraints."
if {$emit_bitstream} {
    write_bitstream -force [file join $out rk_ew_demo.bit]
    puts "Bitstream written; NOT programmed. This is the EW self-test, not the complete NPU."
} else { puts "RK_EMIT_BITSTREAM not set: stopped at routed checkpoint, no .bit generated." }
