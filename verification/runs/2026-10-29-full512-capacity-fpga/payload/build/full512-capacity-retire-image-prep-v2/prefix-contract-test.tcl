source {/home/fedora/rknpu-fpga/build/full512-capacity-retire-vivado-prep-v1/source/constraint-helpers/job_cdc.tcl}
proc get_cells {args} {
    global expected
    set actual [lindex [lindex $args end] 0]
    if {$actual ne $expected} {error "PREFIX_MISMATCH:$actual"}
    error PREFIX_OK
}
foreach {instance profile} {platform/endpoint/engine/ew/job_crossing ew_engine_e1_e8 platform/endpoint/engine/cmac/job_crossing cmac_terminal_full8} {
    set expected [expr {$profile eq "cmac_terminal_full8" ? [file dirname $instance] : $instance}]
    catch {rk_job_constant_fields $instance $profile} old_result
    if {$old_result eq "PREFIX_OK"} {error "Old argument unexpectedly satisfied prefix contract"}
    catch {rk_job_constant_fields "${instance}/" $profile} new_result
    if {$new_result ne "PREFIX_OK"} {error "Corrected argument failed prefix contract: $new_result"}
    puts "PASS_CONSTANT_HELPER_PREFIX_CONTRACT $profile"
}
