# Read-only I/O snapshot for the exact future full512 post-route checkpoint.
# This Tcl creates facts and reports only; it has no constraint or image calls.
if {![info exists ::env(RK_FULL512_ROUTE_DCP)] || ![info exists ::env(RK_FULL512_ROUTE_DCP_SHA256)]} {
    error "Missing bound full512 routed-DCP path/hash"
}
set dcp [file normalize $::env(RK_FULL512_ROUTE_DCP)]
set want_sha $::env(RK_FULL512_ROUTE_DCP_SHA256)
if {![string match /* $dcp] || ![file isfile $dcp]} {error "Bound routed checkpoint missing or not absolute"}
set raw [exec sha256sum -z -- $dcp]
if {![regexp {^([0-9a-f]{64})[ \t]} $raw -> actual_sha] || $actual_sha ne $want_sha} {
    error "Routed checkpoint SHA256 mismatch"
}
set tsv [open full512-io-facts.tsv {WRONLY CREAT EXCL}]
set port_tcl [open full512-ports.tcl {WRONLY CREAT EXCL}]
set prop_file [file normalize full512-properties.txt]
proc io_emit {channel fields} {
    set encoded {}
    foreach value $fields {
        set value [string map [list "\\" "\\\\" "\t" "\\t" "\n" "\\n" "\r" "\\r"] $value]
        lappend encoded $value
    }
    puts $channel [join $encoded "\t"]
    flush $channel
}
proc io_prop {port property} {
    if {[catch {get_property $property $port} value]} {error "Missing actual port property $property for [get_property NAME $port]"}
    if {[string match {<UNAVAILABLE:*} $value]} {error "Unavailable actual port property $property for [get_property NAME $port]"}
    return $value
}
set_param general.maxThreads 1
open_checkpoint $dcp
set design [current_design]
if {[get_property TOP $design] ne "ypcb_ddr_dual_top" || [get_property PART $design] ne "xc7k480tffg1156-2"} {
    error "Wrong full512 design identity in routed DCP"
}
if {[get_property CONFIG_VOLTAGE $design] != 1.8 || [get_property CFGBVS $design] ne "GND"} {
    error "Unexpected full512 configuration properties"
}
if {[llength [get_waivers]] != 0 || [llength [get_cells -quiet -hierarchical -filter {IS_BLACKBOX == 1}]] != 0} {
    error "Waiver or unresolved black box present in routed DCP"
}
if {[report_route_status -boolean_check ROUTED_FULLY] != 1 || [report_route_status -boolean_check ERRORS_IN_ROUTES] != 0} {
    error "Full512 route not fully completed or has routing errors"
}
set ports [lsort -dictionary [get_ports -quiet]]
if {[llength $ports] != 242} {error "Expected exactly242 scalar DDR/JTAG/endpoint ports"}
set expected_properties {PACKAGE_PIN IOSTANDARD SLEW DRIVE PULLTYPE DIFF_TERM IN_TERM DIRECTION}
report_property -all -file $prop_file $design
puts $port_tcl {set full512_ports [dict create]}
io_emit $tsv [list DESIGN [get_property NAME $design] [get_property TOP $design] [get_property PART $design] [get_property CONFIG_VOLTAGE $design] [get_property CFGBVS $design]]
io_emit $tsv [list DCP $dcp $actual_sha]
io_emit $tsv [list PORT_COUNT [llength $ports]]
set index 0
foreach port $ports {
    set name [get_property NAME $port]
    set values {}
    report_property -all -append -file $prop_file $port
    foreach key $expected_properties {
        set value [io_prop $port $key]
        lappend values $key $value
        io_emit $tsv [list PORT $index $name $key $value]
    }
    puts $port_tcl [list dict set full512_ports $name $values]
    incr index
}
io_emit $tsv [list SNAPSHOT_COMPLETE $index]
report_io -file full512-route-report-io.rpt
report_clocks -file full512-route-clocks.rpt
close $tsv
close $port_tcl
close_design
puts PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT
exit
