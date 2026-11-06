# Build-local K8 image emission. Offline only: no board, reset, PCIe or flash.
if {![info exists ::env(RK_K8_IMAGE_APPROVED)] ||
    $::env(RK_K8_IMAGE_APPROVED) ne "APPROVED"} {
    error "K8 image emission requires explicit task-scoped approval"
}
if {![info exists ::env(RK_K8_IMAGE_TAG)]} {error "Missing K8 source tag"}
set tag $::env(RK_K8_IMAGE_TAG)
if {![regexp {^[0-9a-f]{8}$} $tag] || $tag eq "00000000"} {
    error "Malformed K8 source tag"
}
set_param general.maxThreads 4
proc one {objects message} {
    if {[llength $objects] != 1} {error "Expected exactly one $message"}
    return [lindex $objects 0]
}
proc require {condition message} {if {!$condition} {error $message}}

open_checkpoint post_route_final.dcp
set design [current_design]
require [expr {[get_property TOP $design] eq "ypcb_ddr_dual_top" &&
    [get_property PART $design] eq "xc7k480tffg1156-2"}] "Wrong K8 design/part"
require [expr {[get_property CONFIG_VOLTAGE $design] == 1.8 &&
    [get_property CFGBVS $design] eq "GND"}] "Changed configuration-bank settings"
require [expr {[llength [get_ports -quiet]] == 242}] "Changed 242-port interface"
require [expr {[llength [get_waivers]] == 0 &&
    [llength [get_cells -quiet -hierarchical -filter {IS_BLACKBOX == 1}]] == 0}] \
    "Waivers or unresolved black boxes are forbidden"
require [expr {[report_route_status -boolean_check ROUTED_FULLY] == 1 &&
    [report_route_status -boolean_check ERRORS_IN_ROUTES] == 0}] "Routing incomplete"
foreach cell {u_mailbox u_maintenance_mailbox gate maintenance bridge} {
    require [expr {[llength [get_cells -quiet $cell]] == 1}] "Missing required cell $cell"
}
require [expr {[llength [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}]] == 2}] \
    "Expected exactly two BSCAN chains"
require [expr {[llength [get_cells -quiet -hier -filter {REF_NAME =~ rk_ddr_capacity_bist*}]] == 0}] \
    "Capacity BIST must remain compiled out of this profile"
require [expr {[llength [get_cells -quiet -hier -filter {REF_NAME == rk_ddr_capacity_owner}]] == 1}] \
    "Missing capacity owner"
require [expr {[llength [get_cells -quiet -hier -filter {REF_NAME =~ rk_startup_reset*}]] == 2}] \
    "Changed startup-reset inventory"

# Preserve the accepted setup/hold gates on this exact routed checkpoint.
set setup_path [one [get_timing_paths -quiet -delay_type max -max_paths 1 -nworst 1] "worst setup path"]
set hold_path [one [get_timing_paths -quiet -delay_type min -max_paths 1 -nworst 1] "worst hold path"]
set setup_slack [get_property SLACK $setup_path]
set hold_slack [get_property SLACK $hold_path]
require [expr {$setup_slack >= 0.0}] "Routed setup timing failed"
require [expr {$hold_slack >= 0.0}] "Routed hold timing failed"

report_route_status -file emission/route_status.rpt
report_utilization -hierarchical -file emission/utilization.rpt
report_io -file emission/io.rpt
report_clocks -file emission/clocks.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file emission/timing.rpt
check_timing -verbose -file emission/check_timing.rpt
report_pulse_width -file emission/pulse_width.rpt
report_drc -ruledecks default -file emission/default_drc.rpt

# Exact observed K8 warning inventory; accepted rule names/severity are unchanged.
set expected [dict create DPIP-1 526 DPOP-1 263 DPOP-2 263 REQP-1709 2]
set counts [dict create DPIP-1 0 DPOP-1 0 DPOP-2 0 REQP-1709 0]
foreach violation [get_drc_violations] {
    set name [get_property NAME $violation]
    require [expr {[string toupper [get_property SEVERITY $violation]] eq "WARNING" &&
        [regexp {^(DPIP-1|DPOP-1|DPOP-2|REQP-1709)#[0-9]+$} $name -> rule]}] \
        "Blocking or unreviewed default DRC finding"
    dict incr counts $rule
}
require [expr {$counts eq $expected}] "Changed default DRC warning inventory"

set_property BITSTREAM.CONFIG.USR_ACCESS 0x$tag [current_design]
report_drc -ruledecks bitstream_checks -file emission/bitstream_drc.rpt
set bitcounts [dict create DPIP-1 0 DPOP-1 0 DPOP-2 0 REQP-1709 0]
foreach violation [get_drc_violations] {
    set name [get_property NAME $violation]
    require [expr {[string toupper [get_property SEVERITY $violation]] eq "WARNING" &&
        [regexp {^(DPIP-1|DPOP-1|DPOP-2|REQP-1709)#[0-9]+$} $name -> rule]}] \
        "Blocking or unreviewed bitstream-check DRC finding"
    dict incr bitcounts $rule
}
require [expr {$bitcounts eq $expected}] "Changed bitstream-check DRC warning inventory"

write_checkpoint -force emission/image.dcp
write_bitstream emission/k8-full-top.bit
puts PASS_K8_FULL_TOP_BITSTREAM_EMISSION_ONLY
