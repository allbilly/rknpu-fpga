# Source-bound constraints/audit for the default three-stage halfword crossing.
# No clock creation, severity changes or CDC waivers. Integration supplies and
# audits real clocks/resets; these procedures cannot establish epoch coverage.
proc rk_mem_require {condition message} {if {!$condition} {error $message}}
proc rk_mem_finite {value} {
    return [expr {[string is double -strict $value] &&
        ![catch {expr {abs(double($value)) < Inf}} result] && $result}]
}
proc rk_mem_one {objects label} {
    rk_mem_require [expr {[llength $objects] == 1}] "Expected exactly one $label"
    return [lindex $objects 0]
}
proc rk_mem_prefix {instance} {
    rk_mem_require [regexp {^([A-Za-z_][A-Za-z0-9_$]*/)*([A-Za-z_][A-Za-z0-9_$]*)?$} $instance] "Unsupported crossing hierarchy"
    return [expr {$instance eq "" ? "" : "$instance/"}]
}
proc rk_mem_cell {prefix name} {
    return [rk_mem_one [get_cells -quiet [list ${prefix}${name}]] "crossing register $name"]
}
proc rk_mem_clock {name period} {
    set clock [rk_mem_one [get_clocks -quiet $name] "crossing clock $name"]
    set actual [get_property PERIOD $clock]
    rk_mem_require [expr {[rk_mem_finite $actual] && abs($actual-$period)<0.000001}] "Changed crossing clock period"
    return $clock
}
proc rk_mem_vectors {prefix source target count} {
    set a {};set b {}
    for {set bit 0} {$bit<$count} {incr bit} {
        lappend a [rk_mem_cell $prefix [format {%s_reg[%d]} $source $bit]]
        lappend b [rk_mem_cell $prefix [format {%s_reg[%d]} $target $bit]]
    }
    return [list $a $b]
}
proc rk_mem_payloads {prefix} {
    lassign [rk_mem_vectors $prefix request_held request_latched 49] request_source request_target
    set response_source {};set response_target {}
    for {set bit 0} {$bit<17} {incr bit} {
        lappend response_source [rk_mem_cell $prefix [format {response_held_reg[%d]} $bit]]
        lappend response_target [rk_mem_cell $prefix [expr {$bit==16 ? "s_mem_rsp_error_reg" : [format {s_mem_rsp_rdata_reg[%d]} $bit]}]]
    }
    return [list [list request $request_source $request_target 15.000] [list response $response_source $response_target 40.000]]
}
proc rk_mem_sync_cells {prefix name} {
    set cells {}
    for {set bit 0} {$bit<3} {incr bit} {
        lappend cells [rk_mem_cell $prefix [format {%s_reg[%d]} $name $bit]]
    }
    set all [get_cells -quiet -hier -filter "NAME =~ ${prefix}${name}_reg*"]
    rk_mem_require [expr {[lsort $all] eq [lsort $cells]}] "Changed synchronizer depth"
    return $cells
}
proc rk_mem_cdc_constrain {instance source_clock destination_clock} {
    set prefix [rk_mem_prefix $instance]
    set source [rk_mem_clock $source_clock 20.000]
    set destination [rk_mem_clock $destination_clock 7.500]
    rk_mem_require [expr {$source ne $destination}] "Crossing clocks must be distinct"
    foreach payload [rk_mem_payloads $prefix] {
        lassign $payload label a b bound
        set_max_delay -datapath_only $bound -from $a -to $b
        # The transfer is asynchronous and held until its synchronized witness;
        # no synchronous hold relationship exists between these source clocks.
        set_false_path -hold -from $a -to $b
        set_bus_skew $bound -from $a -to $b
    }
    foreach name {request_sync response_sync fault_sync} {
        set cells [rk_mem_sync_cells $prefix $name]
        set_property ASYNC_REG TRUE $cells
        set_property DONT_TOUCH TRUE $cells
        # Only the first asynchronous D pin is cut. Later stages stay timed.
        set_false_path -to [get_pins [lindex $cells 0]/D]
    }
}
proc rk_mem_register_clock {cell expected} {
    rk_mem_require [expr {[get_property REF_NAME $cell] in {FDCE FDRE FDSE FDPE}}] "Crossing endpoint is not a flip-flop"
    set actual [rk_mem_one [get_clocks -of_objects [get_pins $cell/C]] "mapped register clock"]
    rk_mem_require [expr {$actual eq $expected}] "Wrong crossing register clock"
}
proc rk_mem_report_skew {instance output} {
    rk_mem_prefix $instance
    set options [list -warn_on_violation -file $output]
    if {$instance ne ""} {
        set block [rk_mem_one [get_cells -quiet [list $instance]] "memory crossing hierarchy"]
        rk_mem_require [expr {![get_property IS_PRIMITIVE $block]}] "Memory crossing scope must be hierarchical"
        lappend options -cells $block
    }
    report_bus_skew {*}$options
}
proc rk_mem_cdc_audit {instance source_clock destination_clock output} {
    set prefix [rk_mem_prefix $instance]
    set source [rk_mem_clock $source_clock 20.000]
    set destination [rk_mem_clock $destination_clock 7.500]
    rk_mem_require [expr {$source ne $destination && [llength [get_waivers]]==0}] "Changed crossing clocks/waivers"
    set facts [open [file join $output async_memory_cdc.tsv] w]
    foreach {name origin clock period} [list request_sync request_toggle $destination 7.500 response_sync response_toggle $source 20.000 fault_sync d_protocol_fault $source 20.000] {
        set cells [rk_mem_sync_cells $prefix $name]
        for {set bit 0} {$bit<3} {incr bit} {
            set cell [lindex $cells $bit]
            rk_mem_register_clock $cell $clock
            rk_mem_require [expr {[get_property ASYNC_REG $cell] && [get_property DONT_TOUCH $cell]}] "Unprotected synchronizer"
            set previous [expr {$bit==0 ? [rk_mem_cell $prefix ${origin}_reg] : [lindex $cells [expr {$bit-1}]]}]
            if {$bit==0} {
                rk_mem_register_clock $previous [expr {$name eq "request_sync" ? $source : $destination}]
            }
            set starts [lsort -unique [all_fanin -flat -startpoints_only -to [get_pins $cell/D]]]
            rk_mem_require [expr {$starts eq [list [get_pins $previous/C]]}] "Unexpected synchronizer fanin"
            if {$bit>0} {
                set path [rk_mem_one [get_timing_paths -quiet -from $previous -to $cell -delay_type max -max_paths 1] "later synchronizer timing path"]
                set slack [get_property SLACK $path];set required [get_property REQUIREMENT $path]
                rk_mem_require [expr {[rk_mem_finite $slack] && $slack>=0 && [rk_mem_finite $required] && abs($required-$period)<0.000001}] "Later synchronizer is cut/failing"
            }
            puts $facts "SYNC\t$cell\t$clock\t$starts"
        }
    }
    foreach payload [rk_mem_payloads $prefix] {
        lassign $payload label a b bound
        set from_clock [expr {$label eq "request" ? $source : $destination}]
        set to_clock [expr {$label eq "request" ? $destination : $source}]
        set n [llength $a]
        for {set bit 0} {$bit<$n} {incr bit} {
            set from [lindex $a $bit];set to [lindex $b $bit]
            rk_mem_register_clock $from $from_clock;rk_mem_register_clock $to $to_clock
            set crosses {}
            foreach start [all_fanin -flat -startpoints_only -to [get_pins $to/D]] {
                set clock [get_clocks -quiet -of_objects $start]
                if {[llength $clock]==1 && [lindex $clock 0] eq $from_clock} {lappend crosses $start}
            }
            rk_mem_require [expr {[lsort -unique $crosses] eq [list [get_pins $from/C]]}] "Wrong held-payload bit correspondence"
            set path [rk_mem_one [get_timing_paths -quiet -from $from -to $to -delay_type max -max_paths 1] "active held-payload max-delay path"]
            set slack [get_property SLACK $path];set required [get_property REQUIREMENT $path]
            rk_mem_require [expr {[rk_mem_finite $slack] && $slack>=0 && [rk_mem_finite $required] && abs($required-$bound)<0.000001}] "Payload path cut/loosened/failing"
        }
        puts $facts "PAYLOAD\t$label\t$n\t$bound"
        report_timing -from $a -to $b -max_paths $n -file [file join $output ${label}_payload_timing.rpt]
    }
    close $facts
    report_cdc -details -file [file join $output async_memory_cdc.rpt]
    report_exceptions -file [file join $output async_memory_exceptions.rpt]
    rk_mem_report_skew $instance [file join $output async_memory_bus_skew.rpt]
    set channel [open [file join $output async_memory_bus_skew.rpt] r]
    set text [read $channel];close $channel
    set slacks [regexp -all -inline -line {^Slack \((MET|VIOLATED)\)\s*:\s*([^\s]+)ns} $text]
    set limits [regexp -all -inline -line {^Requirement:\s*([^\s]+)ns\s*$} $text]
    set details [regexp -all -inline -line {^[ \t]+Requirement:\s*([^\s]+)ns\s*$} $text]
    rk_mem_require [expr {[llength $slacks]==6 && [llength $limits]==4 && [llength $details]==4}] "Incomplete skew coverage"
    foreach {whole status slack} $slacks {
        rk_mem_require [expr {$status eq "MET" && [rk_mem_finite $slack] && $slack>=0}] "Crossing bus skew failed"
    }
    set observed {};set observed_details {}
    foreach {whole value} $limits {
        rk_mem_require [rk_mem_finite $value] "Invalid skew requirement"
        lappend observed [expr {double($value)}]
    }
    foreach {whole value} $details {
        rk_mem_require [rk_mem_finite $value] "Invalid skew detail requirement"
        lappend observed_details [expr {double($value)}]
    }
    rk_mem_require [expr {[lsort -real $observed] eq {15.0 40.0} && [lsort -real $observed_details] eq {15.0 40.0}}] "Changed skew limits"
}
