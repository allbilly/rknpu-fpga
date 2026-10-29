# Requires the source-bound status helpers to be sourced first. One registered
# UI health level crosses into SYS; no payload, reset or clock-group waiver.
proc rk_cmac_permit_inventory {endpoint ui sys} {
    rk_status_require [regexp {^[A-Za-z_][A-Za-z0-9_$/]*$} $endpoint] "Invalid dual endpoint hierarchy"
    set block [rk_status_cell $endpoint]
    rk_status_require [expr {[get_property REF_NAME $block] eq "rk_jtag_dual_ddr_async"}] "Wrong CMAC permit endpoint"
    set engine [rk_status_cell $endpoint/engine/cmac]
    rk_status_require [expr {[get_property REF_NAME $engine] eq "rk_cmac_async_engine"}] "Wrong CMAC permit engine"
    set ui [rk_status_clock $ui 7.500]
    set sys [rk_status_clock $sys 20.000]
    rk_status_require [expr {$ui ne $sys}] "CMAC permit clocks must be distinct"
    set source [rk_status_cell $endpoint/engine/cmac/permit_registered_reg]
    return [rk_status_chain $endpoint/engine/cmac permit_sync $source $ui $sys]
}
proc rk_cmac_permit_constrain {endpoint ui sys} {
    # Reject a wrong source, depth, clock or fanin before adding any exception.
    lassign [rk_cmac_permit_inventory $endpoint $ui $sys] label source from to cells
    set_property DONT_TOUCH TRUE $cells
    set_false_path -from [rk_status_pin $source/C] -to [rk_status_pin [lindex $cells 0]/D]
}
proc rk_cmac_permit_audit {endpoint ui sys output} {
    rk_status_require [expr {[llength [get_waivers]]==0}] "Unexpected CMAC permit waiver"
    lassign [rk_cmac_permit_inventory $endpoint $ui $sys] label source from to cells
    foreach cell $cells {
        rk_status_require [expr {[get_property DONT_TOUCH $cell]}] "Unprotected CMAC permit register"
    }
    rk_status_first_path_audit $source [lindex $cells 0]
    set f [open [file join $output cmac_permit_cdc.tsv] w]
    puts $f "CHAIN\t$source\t$from\t$to\t[join $cells ,]"
    for {set i 1} {$i<3} {incr i} {
        set previous [lindex $cells [expr {$i-1}]]
        set cell [lindex $cells $i]
        foreach {kind expected} {max 20.000 min 0.000} {
            set path [rk_status_one [get_timing_paths -quiet -from [rk_status_pin $previous/C] \
                -to [rk_status_pin $cell/D] -delay_type $kind -max_paths 1] "active CMAC permit $kind path"]
            set slack [get_property SLACK $path]
            set required [get_property REQUIREMENT $path]
            rk_status_require [expr {[string is double -strict $slack] &&
                ![catch {expr {abs(double($slack))<Inf}} finite] && $finite && $slack>=0 &&
                [string is double -strict $required] && abs($required-$expected)<0.000001 &&
                [get_property STARTPOINT_PIN $path] eq [rk_status_pin $previous/C] &&
                [get_property ENDPOINT_PIN $path] eq [rk_status_pin $cell/D]}] "CMAC permit later stage is cut, loosened or failing"
            puts $f "TIMED\t$previous\t$cell\t$kind\t$required\t$slack"
        }
    }
    close $f
}
