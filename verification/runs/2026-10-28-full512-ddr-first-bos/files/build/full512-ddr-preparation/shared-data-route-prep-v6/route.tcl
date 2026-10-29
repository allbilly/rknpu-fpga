# Full512 dual-engine DDR route candidate. Read-only source binding and strict
# audit helpers precede implementation. No timing exceptions are added here;
# exceptions already present in the admitted post-opt DCP are audited after route.
set_param general.maxThreads 2
proc route_require {condition message} {if {!$condition} {error $message}}
proc route_one {objects message} {route_require [expr {[llength $objects]==1}] "Expected exactly one $message"; return [lindex $objects 0]}
proc route_emit {channel row} {puts $channel [join $row "\t"]; flush $channel}
proc route_finite {value} {return [expr {[string is double -strict $value] && ![catch {expr {abs(double($value)) < Inf}} ok] && $ok}]}
puts "SHARED_DATA_ROUTE_TOOL [version -short]"
route_require [info exists ::env(RK_SHARED_ROUTE_POST_OPT_DCP)] "Unbound post-opt DCP path"
set dcp [file normalize $::env(RK_SHARED_ROUTE_POST_OPT_DCP)]
route_require [file exists $dcp] "Bound post-opt DCP is missing"
route_require [string match /* $dcp] "Post-opt DCP path must be absolute"
open_checkpoint $dcp
set design [current_design]
route_require [expr {[get_property TOP $design] eq "ypcb_ddr_dual_top" && [get_property PART $design] eq "xc7k480tffg1156-2"}] "Wrong full512 design or part"
route_require [expr {[get_property CONFIG_VOLTAGE $design] == 1.8 && [get_property CFGBVS $design] eq "GND"}] "Changed configuration-bank properties"
route_require [expr {[llength [get_waivers]] == 0 && [llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]] == 0}] "Unexpected waiver or unresolved black box"
set package [file dirname [file normalize [info script]]]
foreach helper {status_cdc.tcl job_cdc.tcl permit_cdc.tcl memory_crossing.tcl mailbox_ui.tcl board_reset.tcl} {
  source [file join $package helpers $helper]
}
set endpoint_cell [route_one [get_cells -quiet -hierarchical -filter {REF_NAME == rk_jtag_dual_ddr_async}] {dual DDR asynchronous endpoint}]
set endpoint [get_property NAME $endpoint_cell]
route_require [expr {[get_property REF_NAME $endpoint_cell] eq "rk_jtag_dual_ddr_async"}] "Wrong endpoint module"
set owner [route_one [get_cells -quiet [list $endpoint/reset_owner]] {MIG reset owner}]
route_require [expr {[get_property REF_NAME $owner] eq "rk_mig_reset_coordinator"}] "Wrong reset owner module"
set sys [rk_status_clock sys_clock 20.000]
set local0 [rk_status_cell [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint 0]]
set local1 [rk_status_cell [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint 1]]
set ui0reg [route_one [get_clocks -quiet -of_objects [rk_status_pin $local0/C]] {logical UI0 register clock}]
set ui1reg [route_one [get_clocks -quiet -of_objects [rk_status_pin $local1/C]] {logical UI1 register clock}]
set mig [route_one [get_cells -quiet -hierarchical -filter {REF_NAME == top_mig_7series_0_0}] {MIG dual-controller wrapper}]
set mig_name [get_property NAME $mig]
set c0_pin [route_one [get_pins -quiet [list ${mig_name}/c0_ui_clk]] {MIG C0 UI output pin}]
set c1_pin [route_one [get_pins -quiet [list ${mig_name}/c1_ui_clk]] {MIG C1 UI output pin}]
set physical0 [route_one [get_clocks -quiet -of_objects $c0_pin] {MIG C0 UI clock}]
set physical1 [route_one [get_clocks -quiet -of_objects $c1_pin] {MIG C1 UI clock}]
route_require [expr {$ui0reg eq $physical1 && $ui1reg eq $physical0 && $ui0reg ne $ui1reg}] "Logical/physical MIG UI clock mapping changed"
set ui0 [rk_status_clock [get_property NAME $ui0reg] 7.500]
set ui1 [rk_status_clock [get_property NAME $ui1reg] 7.500]
set startup [route_one [get_cells -quiet -hierarchical -filter {REF_NAME == rk_startup_reset}] {mapped startup reset producer}]
set startup_name [get_property NAME $startup]
set cfg_pin [rk_status_pin $endpoint/cfg_reset]
set cfg_segments [get_nets -quiet -segments -of_objects $cfg_pin]
route_require [expr {[llength $cfg_segments] > 0}] "Missing endpoint cfg_reset segments"
set cfg_drivers [get_pins -quiet -leaf -of_objects $cfg_segments -filter {DIRECTION == OUT}]
set cfg_driver [route_one $cfg_drivers {cfg_reset leaf driver}]
set inverter [route_one [get_cells -quiet -of_objects $cfg_driver] {mapped startup inverter}]
set inverter_name [get_property NAME $inverter]
route_require [expr {[get_property REF_NAME $inverter] eq "LUT1"}] "Unexpected cfg_reset driver primitive"
puts "ROUTE_CLOCKS SYS=[get_property NAME $sys] UI0=[get_property NAME $ui0] UI1=[get_property NAME $ui1] MIG=$mig_name C0=$c0_pin C1=$c1_pin STARTUP=$startup_name CFG_DRIVER=[get_property NAME $cfg_driver] INVERTER=$inverter_name"

# Immutable mapped census and proof at the imported post-opt boundary.
proc route_census {out stage} {
  set kernels [get_cells -quiet -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe || REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe}]
  route_require [expr {[llength $kernels] == 16}] "$stage requires 16 C32 product kernels"
  set dsps [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E1}]
  set owned [dict create]; set total 0
  foreach kernel $kernels {
    set prefix "[get_property NAME $kernel]/"; set count 0
    foreach dsp $dsps {
      set name [get_property NAME $dsp]
      if {[string first $prefix $name] == 0} {route_require [expr {![dict exists $owned $name]}] "Duplicate DSP ownership"; dict set owned $name 1; incr count}
    }
    route_require [expr {$count == 32}] "$stage kernel is not C32"
    incr total $count
  }
  route_require [expr {$total == 512 && [dict size $owned] == 512 && [llength $dsps] == 516 && [llength [get_ports -quiet]] == 242}] "$stage product/auxiliary/IO census changed"
  route_require [expr {[get_property CONFIG_VOLTAGE [current_design]] == 1.8 && [get_property CFGBVS [current_design]] eq "GND"}] "$stage configuration properties changed"
  route_emit $out [list CENSUS $stage [get_property TOP [current_design]] [get_property PART [current_design]] 16 512 516 242]
}
proc route_mig_census {out stage mig_name c0_pin c1_pin} {
  set wrapper [route_one [get_cells -quiet [list $mig_name]] "$stage actual dual-channel MIG wrapper"]
  set child_name "$mig_name/u_top_mig_7series_0_0_mig"
  set child [route_one [get_cells -quiet [list $child_name]] "$stage generated MIG core"]
  set c0_infra [route_one [get_cells -quiet [list $child_name/c0_u_ddr3_infrastructure]] "$stage MIG C0 infrastructure"]
  set c1_infra [route_one [get_cells -quiet [list $child_name/c1_u_ddr3_infrastructure]] "$stage MIG C1 infrastructure"]
  set c0_controller [route_one [get_cells -quiet [list $child_name/c0_u_memc_ui_top_axi]] "$stage MIG C0 controller"]
  set c1_controller [route_one [get_cells -quiet [list $child_name/c1_u_memc_ui_top_axi]] "$stage MIG C1 controller"]
  route_require [expr {![get_property IS_BLACKBOX $wrapper] && ![get_property IS_BLACKBOX $child] &&
      ![get_property IS_PRIMITIVE $wrapper] && ![get_property IS_PRIMITIVE $child]}] "$stage MIG wrapper/core became primitive or black box"
  route_require [expr {[get_property ORIG_REF_NAME $wrapper] eq "top_mig_7series_0_0" &&
      [get_property ORIG_REF_NAME $child] eq "top_mig_7series_0_0_mig"}] "$stage MIG wrapper/core identity changed"
  foreach cell [list $c0_infra $c1_infra $c0_controller $c1_controller] {
    route_require [expr {![get_property IS_BLACKBOX $cell] && ![get_property IS_PRIMITIVE $cell]}] "$stage MIG channel hierarchy became primitive or black box"
  }
  foreach cell [list $c0_infra $c1_infra] {
    route_require [expr {[get_property ORIG_REF_NAME $cell] eq "mig_7series_v4_2_infrastructure"}] "$stage MIG infrastructure origin changed"
  }
  foreach cell [list $c0_controller $c1_controller] {
    route_require [expr {[get_property ORIG_REF_NAME $cell] eq "mig_7series_v4_2_memc_ui_top_axi"}] "$stage MIG controller origin changed"
  }
  route_require [expr {[llength [get_pins -quiet [list $c0_pin]]]==1 && [llength [get_pins -quiet [list $c1_pin]]]==1}] "$stage MIG UI clock pins missing"
  route_emit $out [list MIG_CHANNELS $stage [get_property NAME $wrapper] [get_property REF_NAME $wrapper] [get_property ORIG_REF_NAME $wrapper] [get_property NAME $child] [get_property REF_NAME $child] [get_property ORIG_REF_NAME $child] [get_property NAME $c0_infra] [get_property REF_NAME $c0_infra] [get_property ORIG_REF_NAME $c0_infra] [get_property NAME $c1_infra] [get_property REF_NAME $c1_infra] [get_property ORIG_REF_NAME $c1_infra] [get_property NAME $c0_controller] [get_property REF_NAME $c0_controller] [get_property ORIG_REF_NAME $c0_controller] [get_property NAME $c1_controller] [get_property REF_NAME $c1_controller] [get_property ORIG_REF_NAME $c1_controller] $c0_pin $c1_pin]
}
set ew_job [format {%s/engine/ew/job_crossing/} $endpoint]
set cmac_job [format {%s/engine/cmac/job_crossing/} $endpoint]
set ew_mem [format {%s/engine/ew/memory_crossing} $endpoint]
set cmac_mem [format {%s/engine/cmac/memory_crossing} $endpoint]
set ew_profile ew_engine_e1_e8
set cmac_profile cmac_terminal_full8
set status_inventory [rk_status_inventory $endpoint $sys $ui0 $ui1]
route_require [expr {[llength $status_inventory] == 9}] "Expected exactly nine status chains"
set permit_inventory [rk_cmac_permit_inventory $endpoint $ui0 $sys]
set ew_payload [rk_job_payloads $ew_job $ew_profile]
set cmac_payload [rk_job_payloads $cmac_job $cmac_profile]
route_require [expr {[llength [lindex $ew_payload 0 1]] == 64 && [llength [lindex $ew_payload 1 1]] == 37}] "EW held payload inventory changed"
route_require [expr {[llength [lindex $cmac_payload 0 1]] == 64 && [llength [lindex $cmac_payload 1 1]] == 10}] "CMAC terminal held payload inventory changed"
set ew_mem_payload [rk_mem_payloads [rk_mem_prefix $ew_mem]]
set cmac_mem_payload [rk_mem_payloads [rk_mem_prefix $cmac_mem]]
set reset_inventory [rk_board_reset_inventory $endpoint $startup_name $inverter_name $sys $ui0 $ui1]
route_require [expr {[llength $reset_inventory] == 4}] "Expected strict four-bank board reset inventory"
set ew_constants [rk_job_constant_fields $ew_job $ew_profile]
set cmac_constants [rk_job_constant_fields $cmac_job $cmac_profile]
route_require [expr {[llength $ew_constants] == 4 && [llength $cmac_constants] == 31}] "Expected 4 EW ZERO_CODE and 31 CMAC ZERO_TASK rows"
set constant_rows 0; set constant_observations 0; set anchor_nets [dict create]
foreach {profile rows expected kind first indexes} [list EW $ew_constants 4 ZERO_CODE 4 {3 5} CMAC $cmac_constants 31 ZERO_TASK 1 {3 5 7}] {
  route_require [expr {[llength $rows] == $expected}] "$profile constant proof row count changed"
  set row_index 0
  foreach row $rows {
    route_require [expr {[lindex $row 0] eq $kind && [lindex $row 1] == $first+$row_index}] "$profile constant proof ordering changed"
    foreach index $indexes {
      set net [lindex $row $index]; set name [get_property NAME $net]
      route_require [expr {[get_property TYPE $net] eq "GROUND" && [get_property DRIVER_COUNT $net] == 1 && [get_property KEEP $net] && [get_property DONT_TOUCH $net]}] "$profile constant anchor changed/lost"
      dict set anchor_nets $name 1; incr constant_observations
    }
    incr row_index; incr constant_rows
  }
}
route_require [expr {$constant_rows == 35 && $constant_observations == 101 && [dict size $anchor_nets] > 0}] "Post-opt constant row/observation census changed"
route_require [info exists ::env(RK_SHARED_ROUTE_EXPECTED_ANCHOR_FILE)] "Unbound synthesis anchor-set audit"
set anchor_channel [open $::env(RK_SHARED_ROUTE_EXPECTED_ANCHOR_FILE) r]
set expected_anchor_names [split [string trim [read $anchor_channel]] "\n"]
close $anchor_channel
route_require [expr {[llength $expected_anchor_names] > 0 && [lsort -unique $expected_anchor_names] eq [lsort [dict keys $anchor_nets]]}] "Post-opt anchor set differs from source-bound synthesis audit"
set facts [open route_import_facts.tsv {WRONLY CREAT EXCL}]
route_emit $facts [list IMPORTED_DCP $dcp [get_property TOP [current_design]] [get_property PART [current_design]]]
route_emit $facts [list CLOCKS [get_property NAME $sys] [get_property NAME $ui0] [get_property NAME $ui1] $mig_name $c0_pin $c1_pin]
route_emit $facts [list CONSTANT_PROOF $constant_rows $constant_observations [dict size $anchor_nets]]
route_emit $facts [list PAYLOADS EW 64 37 CMAC 64 10 EW_MEMORY [llength $ew_mem_payload] CMAC_MEMORY [llength $cmac_mem_payload] STATUS 9 PERMIT [llength $permit_inventory] BOARD_RESET 4]
route_mig_census $facts imported_post_opt $mig_name $c0_pin $c1_pin
close $facts
set census_file [open route_census.tsv {WRONLY CREAT EXCL}]
route_census $census_file imported_post_opt
close $census_file

# Physical implementation is separately bound to root review. The helper
# exceptions are already present in the imported DCP and are not reapplied.
route_require [info exists ::env(RK_SHARED_ROUTE_ROOT_APPROVED)] "Root route approval binding is missing"
route_require [expr {$::env(RK_SHARED_ROUTE_ROOT_APPROVED) eq "APPROVED"}] "Root route approval binding is not approved"
write_checkpoint -force route_input_post_opt.dcp
place_design -directive Explore
phys_opt_design -directive Explore
write_checkpoint -force post_place.dcp
route_design -directive Explore
write_checkpoint -force post_route.dcp
report_route_status -file route_status.rpt
report_utilization -hierarchical -file utilization.rpt
report_io -file io.rpt
report_clocks -file clocks.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing.rpt
report_pulse_width -file pulse_width.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
report_cdc -details -file cdc.rpt
route_require [expr {[report_route_status -boolean_check ROUTED_FULLY] == 1 && [report_route_status -boolean_check ERRORS_IN_ROUTES] == 0}] "Full512 routing incomplete or erroneous"
set census_file [open route_census.tsv {WRONLY APPEND}]
route_census $census_file post_route
route_mig_census $census_file post_route $mig_name $c0_pin $c1_pin
close $census_file
# Re-extract all35 constant rows/101 boundary nets after physical optimization
# and routing; compare the complete actual anchor set with both source audit
# and the imported-checkpoint result captured above.
set post_ew_constants [rk_job_constant_fields $ew_job $ew_profile]
set post_cmac_constants [rk_job_constant_fields $cmac_job $cmac_profile]
route_require [expr {[llength $post_ew_constants]==4 && [llength $post_cmac_constants]==31}] "Post-route constant row count changed"
set post_anchor_nets [dict create]; set post_rows 0; set post_observations 0
foreach {profile rows expected kind first indexes} [list EW $post_ew_constants 4 ZERO_CODE 4 {3 5} CMAC $post_cmac_constants 31 ZERO_TASK 1 {3 5 7}] {
  route_require [expr {[llength $rows]==$expected}] "$profile post-route constant row count changed"
  set bit_index 0
  foreach row $rows {
    route_require [expr {[lindex $row 0] eq $kind && [lindex $row 1]==$first+$bit_index}] "$profile post-route constant row ordering changed"
    foreach index $indexes {
      set net [lindex $row $index]; set name [get_property NAME $net]
      route_require [expr {[get_property TYPE $net] eq "GROUND" && [get_property DRIVER_COUNT $net]==1 && [get_property KEEP $net] && [get_property DONT_TOUCH $net]}] "$profile post-route GROUND anchor lost or changed"
      dict set post_anchor_nets $name 1; incr post_observations
    }
    incr bit_index; incr post_rows
  }
}
route_require [expr {$post_rows==35 && $post_observations==101 && [lsort [dict keys $post_anchor_nets]] eq [lsort [dict keys $anchor_nets]] && [lsort [dict keys $post_anchor_nets]] eq [lsort $expected_anchor_names]}] "Post-route constant anchor set differs from source/pre-route proof"
set proof_file [open route_import_facts.tsv {WRONLY APPEND}]
route_emit $proof_file [list CONSTANT_PROOF post_route $post_rows $post_observations [dict size $post_anchor_nets]]
close $proof_file
route_require [expr {[llength [get_waivers]] == 0}] "Route introduced a waiver"
foreach violation [get_drc_violations] {
  set severity [string toupper [get_property SEVERITY $violation]]
  route_require [expr {$severity in {WARNING ADVISORY INFO}}] "Blocking full512 DRC finding: $violation ($severity)"
}
file mkdir bridge status permit ew_job cmac_job ew_memory cmac_memory mailbox
rk_board_reset_audit $endpoint $startup_name $inverter_name $sys $ui0 $ui1 bridge
rk_status_cdc_audit $endpoint $sys $ui0 $ui1 status
rk_cmac_permit_audit $endpoint $ui0 $sys permit
rk_job_cdc_audit [string trimright $ew_job /] $ui0 $sys ew_job $ew_profile
rk_job_cdc_audit [string trimright $cmac_job /] $ui0 $sys cmac_job $cmac_profile
rk_mem_cdc_audit $ew_mem $sys $ui0 ew_memory
rk_mem_cdc_audit $cmac_mem $sys $ui0 cmac_memory
rk_ddr_host_cdc_audit mailbox $ui0
foreach kind {max min} {
  set paths [get_timing_paths -quiet -delay_type $kind -max_paths 1]
  set path [route_one $paths "routed global $kind timing path"]
  set slack [get_property SLACK $path]
  route_require [expr {[route_finite $slack] && $slack >= 0}] "Routed global $kind timing fails"
}
foreach check {no_clock unconstrained_internal_endpoints} {
  set detail [check_timing -override_defaults $check -no_header -return_string]
  set file [open check_timing_${check}.rpt w]; puts $file $detail; close $file
  set heading [format {(?im)^\s*(?:[0-9]+\.\s*)?checking\s+%s(?:\s*\([0-9]+\))?\.?\s*$} $check]
  route_require [regexp $heading $detail] "Unrecognized $check report"
  set found 0
  foreach line [split $detail \n] {
    if {[regexp {^\s*There are ([0-9]+) .+} $line -> count]} {incr found; route_require [expr {$count == 0}] "Unresolved route $check findings"} elseif {[regexp -nocase {there are} $line]} {error "Unrecognized route timing count"}
  }
  route_require [expr {$found > 0}] "Missing route internal timing coverage"
}
set pulse [report_pulse_width -return_string]
foreach kind {"Min Period" "Low Pulse Width" "High Pulse Width"} {
  route_require [regexp -line "^${kind}\\s+\\S+\\s+\\S+\\s+\\S+\\s+(\\S+)\\s+(\\S+)\\s+(\\S+)\\s+\\S+\\s+\\S+\\s*$" $pulse -> required actual slack] "Missing routed $kind pulse-width check"
  route_require [expr {[route_finite $required] && [route_finite $actual] && [route_finite $slack] && $required > 0 && $actual > 0 && $slack >= 0}] "Invalid or failing routed $kind pulse-width check"
}
puts PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW
exit
