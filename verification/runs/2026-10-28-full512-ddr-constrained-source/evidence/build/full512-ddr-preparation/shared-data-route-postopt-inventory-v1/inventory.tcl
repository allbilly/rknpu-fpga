set dcp /home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/synthesis/post_opt.dcp
set output [open [file join [pwd] inventory-facts.txt] w]
proc emit {channel key value} {puts $channel "$key\t$value";flush $channel}
proc prop {object key} {if {[catch {get_property $key $object} value]} {return "<UNAVAILABLE:$key>"};return $value}
set constrained_source /home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source
set constraint_helpers [file join $constrained_source constraint-helpers]
set board_reset_helper [file join $constraint_helpers board_reset.tcl]
set memory_helper [file join $constraint_helpers memory_crossing.tcl]
set job_helper [file join $constraint_helpers job_cdc.tcl]
set status_helper [file join $constraint_helpers status_cdc.tcl]
set permit_helper [file join $constraint_helpers permit_cdc.tcl]
source $status_helper
source $job_helper
source $permit_helper
source $memory_helper
source $board_reset_helper
open_checkpoint $dcp
set design [current_design]
foreach key {NAME TOP PART CONFIG_VOLTAGE CFGBVS} {emit $output "DESIGN_$key" [prop $design $key]}
rk_status_require [expr {[prop $design TOP] eq "ypcb_ddr_dual_top" && [prop $design PART] eq "xc7k480tffg1156-2"}] "Unexpected post-opt full512 design identity"
rk_status_require [expr {[prop $design CONFIG_VOLTAGE]==1.8 && [prop $design CFGBVS] eq "GND"}] "Unexpected post-opt configuration properties"

# Discover the actual endpoint and MIG wrapper by REF_NAME, then bind clocks
# from their real pins just like the fresh constrained-prep-v3 synthesis script.
set endpoint_cell [rk_status_one [get_cells -quiet -hierarchical -filter {REF_NAME == rk_jtag_dual_ddr_async}] {dual DDR asynchronous endpoint}]
set endpoint [prop $endpoint_cell NAME]
emit $output ENDPOINT "NAME=$endpoint REF_NAME=[prop $endpoint_cell REF_NAME]"
set reset_owner [rk_status_cell $endpoint/reset_owner]
emit $output RESET_OWNER "NAME=[prop $reset_owner NAME] REF_NAME=[prop $reset_owner REF_NAME]"
set sys_clock [rk_status_clock sys_clock 20.000]
set local0 [rk_status_cell [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint 0]]
set local1 [rk_status_cell [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint 1]]
set ui0_register_clock [rk_status_one [get_clocks -quiet -of_objects [get_pins $local0/C]] {mapped logical UI0 clock}]
set ui1_register_clock [rk_status_one [get_clocks -quiet -of_objects [get_pins $local1/C]] {mapped logical UI1 clock}]
set mig_cell [rk_status_one [get_cells -quiet -hierarchical -filter {REF_NAME == top_mig_7series_0_0}] {MIG dual-controller wrapper}]
set mig_name [prop $mig_cell NAME]
proc exact_cell_facts {channel label path} {
  set cells [get_cells -quiet [list $path]]
  emit $channel "EXACT_CELL_COUNT_$label" "PATH=$path COUNT=[llength $cells]"
  foreach cell $cells {
    set name [prop $cell NAME]
    emit $channel "EXACT_CELL_$label" "NAME=$name REF_NAME=[prop $cell REF_NAME] ORIG_REF_NAME=[prop $cell ORIG_REF_NAME] IS_PRIMITIVE=[prop $cell IS_PRIMITIVE] IS_BLACKBOX=[prop $cell IS_BLACKBOX] INIT=[prop $cell INIT] ASYNC_REG=[prop $cell ASYNC_REG]"
    set cpin [get_pins -quiet [list $name/C]]
    if {[llength $cpin]==1} {foreach clk [get_clocks -quiet -of_objects $cpin] {emit $channel "EXACT_CELL_CLOCK_$label" "CLOCK=[prop $clk NAME] PERIOD=[prop $clk PERIOD]"}}
    foreach pin_name {D Q CLR PRE} {
      set pins [get_pins -quiet [list $name/$pin_name]]
      foreach pin $pins {emit $channel "EXACT_CELL_PIN_$label" "PIN=[prop $pin NAME] REF_PIN_NAME=[prop $pin REF_PIN_NAME] DIRECTION=[prop $pin DIRECTION] NETS=[join [get_nets -quiet -segments -of_objects $pin] ,]"}
      if {$pin_name eq "D" && [llength $pins]==1} {emit $channel "EXACT_CELL_D_FANIN_$label" [join [all_fanin -flat -startpoints_only -to [lindex $pins 0]] ,]}
    }
  }
}
set mig_core_path "$mig_name/u_top_mig_7series_0_0_mig"
foreach {label path} [list \
  MIG_WRAPPER $mig_name \
  MIG_CORE $mig_core_path \
  C0_INFRA "$mig_core_path/c0_u_ddr3_infrastructure" \
  C1_INFRA "$mig_core_path/c1_u_ddr3_infrastructure" \
  C0_CONTROLLER "$mig_core_path/c0_u_memc_ui_top_axi" \
  C1_CONTROLLER "$mig_core_path/c1_u_memc_ui_top_axi" \
  C0_RESET_SOURCE "$mig_core_path/c0_u_ddr3_infrastructure/rstdiv0_sync_r1_reg" \
  C1_RESET_SOURCE "$mig_core_path/c1_u_ddr3_infrastructure/rstdiv0_sync_r1_reg"] {
  exact_cell_facts $output $label $path
}
set mig_c0_pin [rk_status_one [get_pins -quiet [list ${mig_name}/c0_ui_clk]] {actual MIG C0 UI output pin}]
set mig_c1_pin [rk_status_one [get_pins -quiet [list ${mig_name}/c1_ui_clk]] {actual MIG C1 UI output pin}]
set physical_c0_clock [rk_status_one [get_clocks -quiet -of_objects $mig_c0_pin] {clock on actual MIG C0 UI output}]
set physical_c1_clock [rk_status_one [get_clocks -quiet -of_objects $mig_c1_pin] {clock on actual MIG C1 UI output}]
set ui0_clock [rk_status_clock [prop $ui0_register_clock NAME] 7.500]
set ui1_clock [rk_status_clock [prop $ui1_register_clock NAME] 7.500]
foreach {label object} [list SYS $sys_clock LOGICAL_UI0 $ui0_clock LOGICAL_UI1 $ui1_clock MIG_C0 $physical_c0_clock MIG_C1 $physical_c1_clock] {
  emit $output "CLOCK_ROLE_$label" "NAME=[prop $object NAME] PERIOD=[prop $object PERIOD]"
}
emit $output LOGICAL_UI0_EQUALS_PHYSICAL_C1 [expr {$ui0_clock eq $physical_c1_clock}]
emit $output LOGICAL_UI1_EQUALS_PHYSICAL_C0 [expr {$ui1_clock eq $physical_c0_clock}]
emit $output MIG_WRAPPER "NAME=$mig_name REF_NAME=[prop $mig_cell REF_NAME]"

# Literal no-hier exact object checks, including bracketed register/pin names.
set direct_cells [list \
  [list endpoint $endpoint] \
  [list reset_owner "$endpoint/reset_owner"] \
  [list ew_engine "$endpoint/engine/ew"] \
  [list cmac_engine "$endpoint/engine/cmac"] \
  [list ew_job "$endpoint/engine/ew/job_crossing"] \
  [list cmac_job "$endpoint/engine/cmac/job_crossing"] \
  [list cmac_task0_ff [format {%s/engine/cmac/job_crossing/s_result_tasks_reg[%d]} $endpoint 0]] \
  [list cmac_code4_ff [format {%s/engine/cmac/job_crossing/s_result_code_reg[%d]} $endpoint 4]] \
  [list cmac_result_held40_ff [format {%s/engine/cmac/job_crossing/result_held_reg[%d]} $endpoint 40]]]
foreach pair $direct_cells {
  lassign $pair label path
  set cells [get_cells -quiet [list $path]]
  emit $output "LITERAL_CELL_COUNT_$label" [llength $cells]
  foreach cell $cells {emit $output "LITERAL_CELL_$label" "NAME=[prop $cell NAME] REF_NAME=[prop $cell REF_NAME] ORIG_REF_NAME=[prop $cell ORIG_REF_NAME] ASYNC_REG=[prop $cell ASYNC_REG] INIT=[prop $cell INIT]"}
}
set direct_pins [list \
  [list endpoint_cfg_reset "$endpoint/cfg_reset"] \
  [list mig_c0_ui "${mig_name}/c0_ui_clk"] \
  [list mig_c1_ui "${mig_name}/c1_ui_clk"] \
  [list logical_ui0 "$endpoint/c0_ui_clk"] \
  [list logical_ui1 "$endpoint/c1_ui_clk"] \
  [list task_input [format {%s/engine/cmac/job_crossing/d_result_tasks[%d]} $endpoint 1]] \
  [list task_child [format {%s/engine/cmac/job_crossing/s_result_tasks[%d]} $endpoint 1]] \
  [list task_output [format {%s/engine/cmac/ui_result_tasks[%d]} $endpoint 1]] \
  [list result_error_input [format {%s/engine/cmac/job_crossing/d_result_code[%d]} $endpoint 4]] \
  [list result_error_child [format {%s/engine/cmac/job_crossing/s_result_code[%d]} $endpoint 4]] \
  [list result_error_output [format {%s/engine/cmac/ui_result_code[%d]} $endpoint 4]]]
foreach pair $direct_pins {
  lassign $pair label path
  set pins [get_pins -quiet [list $path]]
  emit $output "LITERAL_PIN_COUNT_$label" [llength $pins]
  foreach pin $pins {
    emit $output "LITERAL_PIN_$label" "NAME=[prop $pin NAME] DIRECTION=[prop $pin DIRECTION] REF_PIN_NAME=[prop $pin REF_PIN_NAME] NET=[join [get_nets -quiet -segments -of_objects $pin] ,]"
    foreach clk [get_clocks -quiet -of_objects $pin] {emit $output "LITERAL_PIN_CLOCK_$label" "NAME=[prop $clk NAME] PERIOD=[prop $clk PERIOD]"}
  }
}

# Profile-aware job payloads and terminal constant observations.
set ew_job [rk_job_prefix $endpoint/engine/ew/job_crossing]
set ew_payload [rk_job_payloads $ew_job ew_engine_e1_e8]
set ew_zero [rk_job_constant_fields $ew_job ew_engine_e1_e8]
emit $output EW_PROFILE ew_engine_e1_e8
foreach payload $ew_payload {lassign $payload label from to bound;emit $output "EW_PAYLOAD_$label" "FROM=[llength $from] TO=[llength $to] BOUND_NS=$bound"}
emit $output EW_ZERO_CODE_COUNT [llength $ew_zero]
foreach fact $ew_zero {emit $output EW_ZERO_CODE_FACT [join $fact "\t"]}
set cmac_job [rk_job_prefix $endpoint/engine/cmac/job_crossing]
set cmac_payload [rk_job_payloads $cmac_job cmac_terminal_full8]
set cmac_zero [rk_job_constant_fields $cmac_job cmac_terminal_full8]
emit $output CMAC_PROFILE cmac_terminal_full8
foreach payload $cmac_payload {lassign $payload label from to bound;emit $output "CMAC_PAYLOAD_$label" "FROM=[llength $from] TO=[llength $to] BOUND_NS=$bound"}
emit $output CMAC_ZERO_TASK_COUNT [llength $cmac_zero]
foreach fact $cmac_zero {emit $output CMAC_ZERO_TASK_FACT [join $fact "\t"]}
emit $output TOTAL_CONSTANT_ROWS [expr {[llength $ew_zero]+[llength $cmac_zero]}]
emit $output TOTAL_CONSTANT_NET_OBSERVATIONS [expr {2*[llength $ew_zero]+3*[llength $cmac_zero]}]

# Reset/status, permit and memory payload inventories only; no constraints or audits.
set status_inventory [rk_status_inventory $endpoint $sys_clock $ui0_clock $ui1_clock]
emit $output STATUS_CHAIN_COUNT [llength $status_inventory]
foreach item $status_inventory {lassign $item label source from to cells;emit $output STATUS_CHAIN "LABEL=$label SOURCE=$source FROM=$from TO=$to CELLS=[join $cells ,]"}
set permit_inventory [rk_cmac_permit_inventory $endpoint $ui0_clock $sys_clock]
lassign $permit_inventory label source from to cells
emit $output CMAC_PERMIT_INVENTORY "SOURCE=$source FROM=$from TO=$to CELLS=[join $cells ,]"
foreach engine {ew cmac} {
  set payloads [rk_mem_payloads [rk_mem_prefix [format {%s/engine/%s/memory_crossing} $endpoint $engine]]]
  emit $output "${engine}_MEMORY_PAYLOAD_COUNT" [llength $payloads]
  foreach payload $payloads {lassign $payload label from to bound;emit $output "${engine}_MEMORY_PAYLOAD" "LABEL=$label FROM=[llength $from] TO=[llength $to] BOUND_NS=$bound"}
}
# Discover reset startup/cfg-reset facts only after job/status/permit/memory
# inventories have been emitted. Segment queries are collections: retain each
# actual net and enumerate leaf output pins before the strict board helper.
set startup_cell [rk_status_one [get_cells -quiet -hierarchical -filter {REF_NAME == rk_startup_reset}] {mapped startup reset producer}]
set startup [prop $startup_cell NAME]
set cfg_pin [rk_status_pin $endpoint/cfg_reset]
emit $output STARTUP_MODULE "NAME=$startup REF_NAME=[prop $startup_cell REF_NAME]"
set direct_cfg_nets [get_nets -quiet -of_objects $cfg_pin]
set cfg_segments [get_nets -quiet -segments -of_objects $cfg_pin]
emit $output CFG_RESET_PIN "NAME=[prop $cfg_pin NAME] DIRECTION=[prop $cfg_pin DIRECTION] DIRECT_NET_COUNT=[llength $direct_cfg_nets] SEGMENT_COUNT=[llength $cfg_segments]"
foreach net $direct_cfg_nets {emit $output CFG_RESET_DIRECT_NET "NAME=[prop $net NAME] TYPE=[prop $net TYPE] DRIVER_COUNT=[prop $net DRIVER_COUNT]"}
foreach net $cfg_segments {emit $output CFG_RESET_SEGMENT_NET "NAME=[prop $net NAME] TYPE=[prop $net TYPE] DRIVER_COUNT=[prop $net DRIVER_COUNT]"}
set cfg_leaf_drivers [get_pins -quiet -leaf -of_objects $cfg_segments -filter {DIRECTION == OUT}]
emit $output CFG_RESET_LEAF_DRIVER_COUNT [llength $cfg_leaf_drivers]
foreach pin $cfg_leaf_drivers {
  set cells [get_cells -quiet -of_objects $pin]
  emit $output CFG_RESET_LEAF_DRIVER "PIN=[prop $pin NAME] REF_PIN_NAME=[prop $pin REF_PIN_NAME] CELL_COUNT=[llength $cells]"
  foreach cell $cells {emit $output CFG_RESET_LEAF_DRIVER_CELL "NAME=[prop $cell NAME] REF_NAME=[prop $cell REF_NAME] ORIG_REF_NAME=[prop $cell ORIG_REF_NAME]"}
}
# The strict checks below still require one exact leaf driver and the proven
# startup inverter/source shape; this raw inventory does not accept net absence.
rk_status_require [expr {[llength $cfg_leaf_drivers] == 1}] "Expected one cfg_reset leaf driver pin"
set cfg_driver_pin [lindex $cfg_leaf_drivers 0]
set cfg_driver_cells [get_cells -quiet -of_objects $cfg_driver_pin]
rk_status_require [expr {[llength $cfg_driver_cells] == 1}] "Expected one cfg_reset driver cell"
set inverter_cell [lindex $cfg_driver_cells 0]
set inverter [prop $inverter_cell NAME]
emit $output CFG_RESET_DRIVER "ENDPOINT_PIN=[prop $cfg_pin NAME] DRIVER=[prop $cfg_driver_pin NAME] INVERTER=$inverter REF_NAME=[prop $inverter_cell REF_NAME]"
set reset_inventory [rk_board_reset_inventory $endpoint $startup $inverter $sys_clock $ui0_clock $ui1_clock]
emit $output BOARD_RESET_BANK_COUNT [llength $reset_inventory]
foreach bank $reset_inventory {lassign $bank domain kind sources local ui cells net;emit $output BOARD_RESET_BANK "DOMAIN=$domain KIND=$kind SOURCES=[join $sources ,] LOCAL=$local UI=$ui CELLS=[join $cells ,] CLR_NET=$net"}
close $output
puts PASS_READ_ONLY_DUAL_CDC_AND_RESET_INVENTORY
exit
