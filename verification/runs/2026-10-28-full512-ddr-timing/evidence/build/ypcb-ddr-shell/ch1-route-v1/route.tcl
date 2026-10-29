# Fresh implementation of the frozen real-source EW/DDR board checkpoint.
# No new timing exceptions, electrical changes, image emission or hardware.
set_param general.maxThreads 2
proc require {condition message} {if {!$condition} {error $message}}
proc finite {value} {
    return [expr {[string is double -strict $value] &&
        ![catch {expr {abs(double($value)) < Inf}} result] && $result}]
}
puts "DDR_ROUTE_TOOL [version -short]"
open_checkpoint /home/fedora/rknpu-fpga/build/ypcb-ddr-shell/ch1-physical-synth-v2/post_opt_anchored.dcp
require [expr {[get_property TOP [current_design]] eq "ypcb_ddr_ew_top" &&
    [get_property PART [current_design]] eq "xc7k480tffg1156-2"}] "Wrong DDR board checkpoint"
require [expr {[get_property CONFIG_VOLTAGE [current_design]]==1.8 &&
    [get_property CFGBVS [current_design]] eq "GND"}] "Changed configuration-bank settings"
require [expr {[llength [get_waivers]]==0 &&
    [llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]==0}] "Waiver or unresolved source"
source reset_status_cdc.tcl
source reset_bridge_board_cdc.tcl
source async_job_cdc.tcl
source async_mem_cdc.tcl
source mailbox_ui_cdc.tcl
set endpoint platform/endpoint
set sys [rk_status_clock sys_clock 20.000]
set ui0reg [rk_status_cell {platform/endpoint/reset_owner/ui_domain[0].local_rst_n_reg}]
set ui1reg [rk_status_cell {platform/endpoint/reset_owner/ui_domain[1].local_rst_n_reg}]
set ui0 [rk_status_one [get_clocks -quiet -of_objects [rk_status_pin $ui0reg/C]] {active CH1 UI clock}]
set ui1 [rk_status_one [get_clocks -quiet -of_objects [rk_status_pin $ui1reg/C]] {inactive CH0 UI clock}]
set physical1 [rk_status_one [get_clocks -quiet -of_objects [get_pins -quiet [list platform/mig/c1_ui_clk]]] {physical CH1 UI clock}]
set physical0 [rk_status_one [get_clocks -quiet -of_objects [get_pins -quiet [list platform/mig/c0_ui_clk]]] {physical CH0 UI clock}]
require [expr {$ui0 eq $physical1 && $ui1 eq $physical0 && $ui0 ne $ui1}] "Wrong physical/logical DDR channel clocks"
rk_status_clock [get_property NAME $ui0] 7.500
rk_status_clock [get_property NAME $ui1] 7.500
puts "CH1_ROUTE_CLOCK_BINDING UI0=$ui0 UI1=$ui1"
rk_board_reset_inventory $endpoint startup platform_i_1 $sys $ui0 $ui1
# Imported checkpoint already passed opt_design with one kept ground net.
set proof [rk_job_zero_error_codes $endpoint/engine/job_crossing/ ew_engine_e1_e8]
require [expr {[llength $proof]==4}] "Incomplete kept constant proof"
set anchors {}
foreach row $proof {
    foreach index {3 5} {
        set net [lindex $row $index]
        require [expr {[get_property KEEP $net] && [get_property DONT_TOUCH $net]}] "Lost constant observation anchor"
        lappend anchors $net
    }
}
require [expr {[llength [lsort -unique $anchors]]==1}] "Changed constant observation net set"
puts PRESERVED_ONE_PROVED_CONSTANT_NET_BEFORE_PLACEMENT
write_checkpoint post_opt.dcp
place_design -directive Explore
phys_opt_design -directive Explore
write_checkpoint post_place.dcp
route_design -directive Explore
# Preserve the actual route even if subsequent acceptance fails.
write_checkpoint post_route.dcp
report_route_status -file route_status.rpt
report_utilization -hierarchical -file utilization.rpt
report_io -file io.rpt
report_clocks -file clocks.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing.rpt
report_pulse_width -file pulse_width.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
report_cdc -details -file cdc.rpt
require [expr {[report_route_status -boolean_check ROUTED_FULLY]==1 &&
    [report_route_status -boolean_check ERRORS_IN_ROUTES]==0}] "DDR routing incomplete or erroneous"
require [expr {[llength [get_waivers]]==0}] "Route introduced a waiver"
foreach violation [get_drc_violations] {
    set severity [string toupper [get_property SEVERITY $violation]]
    require [expr {$severity in {WARNING ADVISORY INFO}}] "Blocking DDR DRC finding: $violation ($severity)"
}
file mkdir bridge status job memory mailbox
rk_board_reset_audit $endpoint startup platform_i_1 $sys $ui0 $ui1 bridge
rk_status_cdc_audit $endpoint $sys $ui0 $ui1 status
rk_job_cdc_audit $endpoint/engine/job_crossing $ui0 $sys job ew_engine_e1_e8
rk_mem_cdc_audit $endpoint/engine/memory_crossing $sys $ui0 memory
rk_ddr_host_cdc_audit mailbox $ui0
foreach type {max min} {
    set paths [get_timing_paths -delay_type $type -max_paths 1]
    require [expr {[llength $paths]==1}] "Missing routed DDR timing path"
    set slack [get_property SLACK [lindex $paths 0]]
    require [expr {[finite $slack] && $slack>=0}] "DDR routed $type timing fails"
}
foreach check {no_clock unconstrained_internal_endpoints} {
    set detail [check_timing -override_defaults $check -no_header -return_string]
    set f [open check_timing_${check}.rpt w];puts $f $detail;close $f
    set heading [format {(?im)^\s*(?:[0-9]+\.\s*)?checking\s+%s(?:\s*\([0-9]+\))?\.?\s*$} $check]
    require [regexp $heading $detail] "Unrecognized DDR $check report"
    set found 0
    foreach line [split $detail \n] {
        if {[regexp {^\s*There are ([0-9]+) .+} $line -> count]} {
            incr found
            require [expr {$count==0}] "Unresolved DDR $check findings"
        } elseif {[regexp -nocase {there are} $line]} {error "Unrecognized DDR timing count"}
    }
    require [expr {$found>0}] "Missing DDR internal timing coverage"
}
set pulse [report_pulse_width -return_string]
foreach kind {"Min Period" "Low Pulse Width" "High Pulse Width"} {
    require [regexp -line "^${kind}\\s+\\S+\\s+\\S+\\s+\\S+\\s+(\\S+)\\s+(\\S+)\\s+(\\S+)\\s+\\S+\\s+\\S+\\s*$" $pulse -> required actual slack] "Missing DDR pulse-width check"
    require [expr {[finite $required] && [finite $actual] && [finite $slack] &&
        $required>0 && $actual>0 && $slack>=0}] "Invalid or failing DDR pulse-width check"
}
puts PASS_CH1_ROUTED_CHECKPOINT_ONLY_REQUIRES_CDC_IO_IMAGE_AND_PHYSICAL_REVIEW
exit
