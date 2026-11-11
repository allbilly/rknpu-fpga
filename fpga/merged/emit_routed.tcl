# Emission-only pass for the Image A merged image.
#
# WHY THIS EXISTS: `tools/merged/vivado_merged_image.py synth --execute` runs
# synthesis + implementation and stops at the routed checkpoint unless
# RK_EMIT_BITSTREAM=1. Re-running that whole flow just to emit would cost another
# ~2 hours. This script opens the ALREADY VERIFIED routed checkpoint and applies
# exactly the same reviewed emission gate family the build template carries
# (pins/standards/directions, clean routing, no waivers, board voltage pair,
# reviewed DRC deck, source-derived USR_ACCESS) before writing the bitstream.
# No constraint is relaxed and no gate is skipped; the datapath is untouched.
#
# Usage:
#   RK_EMIT_BITSTREAM=1 RK_CONFIRM_BOARD=YPCB_00338_1P1 \
#   RK_CONFIG_VOLTAGE=1.8 RK_CFGBVS=GND RK_LED_ACTIVE_LOW=0 \
#   RK_MERGED_SOURCE_SHA=<rendered sha> \
#   vivado -mode batch -source fpga/merged/emit_routed.tcl \
#          -tclargs <routed.dcp> <outdir> <source_tag>
#
# Never programs a device and never touches hardware.

if {![info exists ::env(RK_CONFIRM_BOARD)] || $::env(RK_CONFIRM_BOARD) ne "YPCB_00338_1P1"} {
    error "Set RK_CONFIRM_BOARD=YPCB_00338_1P1 only after checking the XDC against your board."
}
if {![info exists ::env(RK_EMIT_BITSTREAM)] || $::env(RK_EMIT_BITSTREAM) ne "1"} {
    error "This script only emits: set RK_EMIT_BITSTREAM=1 explicitly."
}
set emit_polarity 0
if {[info exists ::env(RK_LED_ACTIVE_LOW)]} {
    if {$::env(RK_LED_ACTIVE_LOW) ni {0 1}} { error "RK_LED_ACTIVE_LOW must be 0 or 1." }
    set emit_polarity $::env(RK_LED_ACTIVE_LOW)
} else {
    error "Set RK_LED_ACTIVE_LOW=0|1 after observing the board's LEDs; it is unverified in the donor sources."
}
if {![info exists ::env(RK_CONFIG_VOLTAGE)] || ![info exists ::env(RK_CFGBVS)]} {
    error "Supply both board-verified RK_CONFIG_VOLTAGE and RK_CFGBVS."
}
if {$::env(RK_CONFIG_VOLTAGE) ni {1.5 1.8 2.5 3.3}} { error "Invalid RK_CONFIG_VOLTAGE." }
if {$::env(RK_CFGBVS) ni {GND VCCO}} { error "RK_CFGBVS must be GND or VCCO." }
if {($::env(RK_CONFIG_VOLTAGE) in {1.5 1.8} && $::env(RK_CFGBVS) ne "GND") ||
    ($::env(RK_CONFIG_VOLTAGE) in {2.5 3.3} && $::env(RK_CFGBVS) ne "VCCO")} {
    error "Incompatible RK_CONFIG_VOLTAGE/RK_CFGBVS pair; verify the actual board supplies and strap."
}

if {[llength $argv] != 3} {
    error "usage: -tclargs <routed.dcp> <outdir> <source_tag>"
}
lassign $argv dcp out source_tag
if {![file exists $dcp]} { error "routed checkpoint not found: $dcp" }
if {!([regexp {^[0-9a-f]{8}$} $source_tag])} { error "Invalid source tag." }
if {[file exists $out] && [llength [glob -nocomplain -directory $out *]] != 0} {
    error "Emission requires a fresh output directory."
}
file mkdir $out

open_checkpoint $dcp
set_property CONFIG_VOLTAGE $::env(RK_CONFIG_VOLTAGE) [current_design]
set_property CFGBVS $::env(RK_CFGBVS) [current_design]

# ---- unchanged clock gate --------------------------------------------------
set clocks [get_clocks -quiet sys_clk]
if {[llength $clocks] != 1} { error "Expected exactly one sys_clk constraint." }
set clock_period [get_property PERIOD [lindex $clocks 0]]
if {![string is double -strict $clock_period] ||
    [catch {expr {double($clock_period) == 20.0}} expected_clock] || !$expected_clock} {
    error "Expected the unchanged 20.000 ns sys_clk constraint."
}

# ---- reviewed emission gates ----------------------------------------------
if {[llength [get_waivers]] != 0} { error "Waivers are forbidden for an emitted image." }
if {[report_route_status -boolean_check ROUTED_FULLY] != 1 ||
    [report_route_status -boolean_check ERRORS_IN_ROUTES] != 0} {
    error "Routing is not clean; no bitstream is emitted."
}
set expected_ports {SYS_CLK led_3bits_tri_o[0] led_3bits_tri_o[1] led_3bits_tri_o[2]}
if {[lsort [get_ports]] ne [lsort $expected_ports]} { error "Wrong physical ports for the pinned image." }
foreach {name pin direction} {SYS_CLK AA28 IN {led_3bits_tri_o[0]} P30 OUT {led_3bits_tri_o[1]} M30 OUT {led_3bits_tri_o[2]} N30 OUT} {
    set ports [get_ports -quiet [list $name]]
    if {[llength $ports] != 1} { error "Expected one exact physical port: $name" }
    set port [lindex $ports 0]
    if {[get_property PACKAGE_PIN $port] ne $pin ||
        [get_property DIRECTION $port] ne $direction ||
        [get_property IOSTANDARD $port] ne "LVCMOS18"} {
        error "Changed pin/standard/direction for $name."
    }
}
if {[get_property CONFIG_VOLTAGE [current_design]] != 1.8 ||
    [get_property CFGBVS [current_design]] ne "GND"} {
    error "Changed configuration-bank pair; emission requires the reviewed 1.8/GND values."
}
# Source identity metadata only; no datapath, placement or timing change.
set_property BITSTREAM.CONFIG.USR_ACCESS 0x$source_tag [current_design]
report_drc -ruledecks bitstream_checks -file [file join $out bitstream_drc.rpt]
foreach violation [get_drc_violations] {
    set severity [string toupper [get_property SEVERITY $violation]]
    if {$severity ni {WARNING ADVISORY INFO}} {
        error "Unreviewed bitstream DRC finding: $violation"
    }
}
write_bitstream -force [file join $out host-merged.bit]
puts "Merged image bitstream written; NOT programmed. Candidate image, review pending."
