set_param general.maxThreads 2
open_checkpoint {/home/fedora/rknpu-fpga/build/original-ddr-real-synthesis/v2/actual_sources_synth.dcp}
source {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/frozen/reset_status_cdc.tcl}
set failed [catch {rk_status_inventory endpoint sys_clock clk_pll_i clk_pll_i_1} message]
if {!$failed || $message ne "Status chain contains restart logic, a bus or another source"} {error "Old-checkpoint structural negative mismatch: code=$failed message=$message"}
set nf [open {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/negative/old-v2-structural-negative.tsv} w];puts $nf "EXPECTED_REJECTION\t$message";close $nf
close_design
open_checkpoint {/home/fedora/rknpu-fpga/build/original-ddr-real-synthesis/reset-v3/actual_sources_synth.dcp}
source {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/frozen/async_job_cdc.tcl}
source {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/frozen/async_mem_cdc.tcl}
set failed [catch {rk_status_inventory endpoint clk_pll_i clk_pll_i clk_pll_i_1} message]
if {!$failed || $message ne "Changed status clock period"} {error "Negative clock-name control mismatch: code=$failed message=$message"}
set nf [open {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/negative/clock-name-negative.tsv} w];puts $nf "EXPECTED_REJECTION\t$message";close $nf
rk_status_cdc_constrain endpoint sys_clock clk_pll_i clk_pll_i_1
rk_job_cdc_constrain endpoint/engine/job_crossing clk_pll_i sys_clock ew_engine_e1_e8
rk_mem_cdc_constrain endpoint/engine/memory_crossing sys_clock clk_pll_i
rk_status_cdc_audit endpoint sys_clock clk_pll_i clk_pll_i_1 {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/status}
rk_job_cdc_audit endpoint/engine/job_crossing clk_pll_i sys_clock {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/job} ew_engine_e1_e8
rk_mem_cdc_audit endpoint/engine/memory_crossing sys_clock clk_pll_i {/home/fedora/rknpu-fpga/build/async-ew-clock-mapping/reset-v3-status-v6/memory}
puts PASS_RESET_JOB_MEMORY_CDC_AUDITS_WITH_OLD_DCP_AND_CLOCK_NEGATIVES
exit
