# Clean level/status crossings only. No clock groups, reset-pin cuts, waivers
# or physical acceptance. Apply only to the source-bound three-stage profile.
proc rk_status_require {ok message} {if {!$ok} {error $message}}
proc rk_status_one {objects label} {
    rk_status_require [expr {[llength $objects]==1}] "Expected one $label"
    return [lindex $objects 0]
}
proc rk_status_cell {name} {return [rk_status_one [get_cells -quiet [list $name]] "status cell $name"]}
proc rk_status_pin {name} {return [rk_status_one [get_pins -quiet [list $name]] "status pin $name"]}
proc rk_status_clock {name period} {
    set clock [rk_status_one [get_clocks -quiet [list $name]] "status clock $name"]
    rk_status_require [expr {abs([get_property PERIOD $clock]-$period)<0.000001}] "Changed status clock period"
    return $clock
}
proc rk_status_ff {cell clock} {
    rk_status_require [expr {[get_property REF_NAME $cell] in {FDCE FDRE FDSE FDPE}}] "Status endpoint is not a flip-flop"
    rk_status_require [expr {[get_clocks -quiet -of_objects [rk_status_pin $cell/C]] eq $clock}] "Wrong status register clock"
}
proc rk_status_boundary_origin {endpoint pin clock} {
    set starts [all_fanin -flat -startpoints_only -to [rk_status_pin $endpoint/$pin]]
    set start [rk_status_one $starts "registered MIG UI status origin"]
    set cell [rk_status_one [get_cells -quiet -of_objects $start] "MIG status source register"]
    rk_status_ff $cell $clock
    rk_status_require [expr {$start eq [rk_status_pin $cell/C]}] "Unexpected MIG status startpoint"
    return $cell
}
proc rk_status_chain {endpoint relative source from_clock to_clock} {
    set cells {}
    for {set i 0} {$i<3} {incr i} {lappend cells [rk_status_cell [format {%s/%s_reg[%d]} $endpoint $relative $i]]}
    # Literal comparison avoids treating generated hierarchy's [0]/[1] as
    # wildcard character classes in a Vivado NAME filter.
    set all {};set stem $endpoint/${relative}_reg
    foreach candidate [get_cells -quiet -hier -filter "NAME =~ $endpoint/*"] {
        if {[string first $stem [get_property NAME $candidate]]==0} {lappend all $candidate}
    }
    rk_status_require [expr {[lsort $all] eq [lsort $cells]}] "Changed status synchronizer depth"
    rk_status_ff $source $from_clock
    set previous $source
    foreach cell $cells {
        rk_status_ff $cell $to_clock
        rk_status_require [expr {[get_property ASYNC_REG $cell]}] "Missing source ASYNC_REG property"
        set starts [lsort -unique [all_fanin -flat -startpoints_only -to [rk_status_pin $cell/D]]]
        rk_status_require [expr {$starts eq [list [rk_status_pin $previous/C]]}] "Status chain contains restart logic, a bus or another source"
        set previous $cell
    }
    return [list $relative $source $from_clock $to_clock $cells]
}
proc rk_status_inventory {endpoint sys ui0 ui1} {
    rk_status_require [regexp {^[A-Za-z_][A-Za-z0-9_$/]*$} $endpoint] "Invalid status hierarchy"
    set block [rk_status_cell $endpoint]
    rk_status_require [expr {[get_property REF_NAME $block] eq "rk_jtag_ew_ddr_async"}] "Wrong status endpoint module"
    set owner [rk_status_cell $endpoint/reset_owner]
    rk_status_require [expr {[get_property REF_NAME $owner] eq "rk_mig_reset_coordinator"}] "Wrong reset owner module"
    set sys [rk_status_clock $sys 20.000]
    set ui0 [rk_status_clock $ui0 7.500];set ui1 [rk_status_clock $ui1 7.500]
    rk_status_require [expr {$sys ne $ui0 && $sys ne $ui1 && $ui0 ne $ui1}] "Status clocks must remain distinct"
    set result {}
    for {set domain 0} {$domain<2} {incr domain} {
        set ui [expr {$domain==0 ? $ui0 : $ui1}]
        set origin [rk_status_boundary_origin $endpoint c${domain}_ui_clk_sync_rst $ui]
        lappend result [rk_status_chain $endpoint reset_owner/reset${domain}_sync $origin $ui $sys]
        foreach {name origin_name} {fresh fresh release clients_rst_n} {
            set source [rk_status_cell [format {%s/reset_owner/ui_domain[%d].%s_reg} $endpoint $domain $origin_name]]
            lappend result [rk_status_chain $endpoint reset_owner/${name}${domain}_sync $source $ui $sys]
        }
        set source [rk_status_cell [format {%s/reset_owner/assertion_seen_reg[%d]} $endpoint $domain]]
        lappend result [rk_status_chain $endpoint [format {reset_owner/ui_domain[%d].assertion_sync} $domain] $source $sys $ui]
    }
    set source [rk_status_cell $endpoint/sequence_complete_registered_reg]
    lappend result [rk_status_chain $endpoint sequence_sync $source $sys $ui0]
    rk_status_require [expr {[llength $result]==9}] "Incomplete reset status inventory"
    return $result
}
proc rk_status_cdc_constrain {endpoint sys ui0 ui1} {
    # Inventory and correspondence must pass BEFORE setting any exception.
    set inventory [rk_status_inventory $endpoint $sys $ui0 $ui1]
    foreach item $inventory {
        lassign $item label source from_clock to_clock cells
        set_property DONT_TOUCH TRUE $cells
        # Only the actual asynchronous level's first D input is excluded.
        # CLR/R/PRE and every subsequent data stage remain fully timed.
        set_false_path -from [rk_status_pin $source/C] -to [rk_status_pin [lindex $cells 0]/D]
    }
}
proc rk_status_first_path_audit {source first} {
    # Directed get_timing_paths queries can return an excepted path object.
    # Vivado2026.1 labels the object False Path and leaves all three timing
    # properties empty (report_timing renders that as inf). Require this
    # native-observed schema and the exact endpoints, never a numeric path.
    set p [rk_status_one [get_timing_paths -quiet -from [rk_status_pin $source/C] -to [rk_status_pin $first/D] -max_paths 1] "first status timing object"]
    rk_status_require [expr {[get_property EXCEPTION $p] eq "False Path" &&
        [get_property SLACK $p] eq "" && [get_property REQUIREMENT $p] eq "" &&
        [get_property REQUIRED_TIME $p] eq "" &&
        [get_property STARTPOINT_PIN $p] eq [rk_status_pin $source/C] &&
        [get_property ENDPOINT_PIN $p] eq [rk_status_pin $first/D]}] "First status path is not an explicit untimed false path"
}
proc rk_status_cdc_audit {endpoint sys ui0 ui1 output} {
    rk_status_require [expr {[llength [get_waivers]]==0}] "Unexpected CDC waiver"
    set inventory [rk_status_inventory $endpoint $sys $ui0 $ui1]
    set f [open [file join $output reset_status_cdc.tsv] w]
    foreach item $inventory {
        lassign $item label source from_clock to_clock cells
        foreach cell $cells {rk_status_require [expr {[get_property DONT_TOUCH $cell]}] "Unprotected status synchronizer"}
        set first [lindex $cells 0]
        rk_status_first_path_audit $source $first
        # Resolve the clock name back to a clock object. A serialized name
        # can also name a MIG net and is not a typed get_property argument.
        set period [get_property PERIOD [get_clocks -quiet [list $to_clock]]]
        for {set i 1} {$i<3} {incr i} {
            set previous [lindex $cells [expr {$i-1}]];set cell [lindex $cells $i]
            set p [rk_status_one [get_timing_paths -quiet -from [rk_status_pin $previous/C] -to [rk_status_pin $cell/D] -delay_type max -max_paths 1] "timed later status stage"]
            set slack [get_property SLACK $p];set required [get_property REQUIREMENT $p]
            rk_status_require [expr {[string is double -strict $slack] && abs($slack)<Inf && $slack>=0 &&
                [string is double -strict $required] && abs($required-$period)<0.000001}] "Later status stage is cut, loosened or setup-failing"
            puts $f "TIMED\t$label\t$i\t$required\t$slack"
        }
        puts $f "CHAIN\t$label\t$source\t$from_clock\t$to_clock\t3"
    }
    close $f
    report_exceptions -file [file join $output reset_status_exceptions.rpt]
    report_cdc -details -file [file join $output reset_status_cdc.rpt]
    report_timing_summary -file [file join $output unplaced_platform_timing.rpt]
    puts PASS_NINE_CLEAN_STATUS_CHAINS_ONLY_RESET_PINS_AND_PLATFORM_SIGNOFF_OPEN
}
