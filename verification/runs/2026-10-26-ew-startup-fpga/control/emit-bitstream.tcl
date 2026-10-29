# Root executes only after the exact routed checkpoint's independent review.
set dcp {/home/fedora/rknpu-fpga/build/fpga-bringup/ew-startup-1792988881763089417/prepared/implementation/routed.dcp}
set out {/home/fedora/rknpu-fpga/build/fpga-bringup/ew-startup-1792988881763089417/bitstream}
if {[file exists $out]} {error "Fresh image output required"}
file mkdir $out
open_checkpoint $dcp
if {[get_property PART [current_design]] ne "xc7k480tffg1156-2"} {error "Wrong exact routed part"}
if {![report_route_status -boolean_check ROUTED_FULLY] || [report_route_status -boolean_check ERRORS_IN_ROUTES]} {error "Routed checkpoint not clean"}
if {[get_property CONFIG_VOLTAGE [current_design]] != 1.8 || [get_property CFGBVS [current_design]] ne "GND"} {error "Changed configuration-bank pair"}
set clocks [get_clocks -quiet]
if {[llength $clocks]!=1 || [get_property NAME [lindex $clocks 0]] ne "sys_clk" || [get_property PERIOD [lindex $clocks 0]] != 20.0} {error "Changed clock constraint"}
foreach type {max min} {
    set paths [get_timing_paths -delay_type $type -max_paths 1]
    if {[llength $paths]!=1} {error "Missing routed timing path"}
    set slack [get_property SLACK [lindex $paths 0]]
    if {![string is double -strict $slack] || [catch {expr {abs(double($slack)) < Inf}} finite] || !$finite || $slack < 0} {error "Negative/invalid routed slack"}
}
# This changes only the source tag, not the datapath, clock, placement or routing.
set_property BITSTREAM.CONFIG.USR_ACCESS 0xd1d0e3d0 [current_design]
report_drc -ruledeck bitstream_checks -file [file join $out pre_bitstream_drc.rpt]
foreach item [get_drc_violations] {
    set severity [string toupper [get_property SEVERITY $item]]
    if {$severity ni {WARNING ADVISORY INFO}} {error "Blocking bitstream DRC $item ($severity)"}
}
write_checkpoint [file join $out image.dcp]
write_bitstream [file join $out ew-startup.bit]
puts "PASS_SOURCE_REVIEWED_EW_BITSTREAM_EMISSION"
exit
