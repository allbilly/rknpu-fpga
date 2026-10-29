set calls {}
proc set_param {args} {if {$args ne {general.maxThreads 2}} {error "unexpected set_param"}}
proc read_verilog {args} {if {[llength $args]!=2 || [lindex $args 0] ne "-sv" || [llength [lindex $args 1]]!=10} {error "source list shape"}; foreach p [lindex $args 1] {if {![file isfile $p]} {error "source missing"}};lappend ::calls read}
proc synth_design {args} {if {$args ne {-top rk_ddr_capacity_service -part xc7k480tffg1156-2 -mode out_of_context}} {error "wrong synthesis"};lappend ::calls synth}
proc report_utilization {args} {lappend ::calls utilization}
set script [lindex $argv 0]
set argv [list [lindex $argv 1]]
source $script
if {$calls ne {read synth utilization utilization}} {error "wrong command census"}
puts PASS_ROOT_TCL_STUB_ONLY
