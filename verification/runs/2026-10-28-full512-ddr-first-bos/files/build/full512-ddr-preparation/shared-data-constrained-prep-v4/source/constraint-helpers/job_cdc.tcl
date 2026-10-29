# Source-bound constraints/audit for the raw descriptor/result job crossing.
# No clock creation, severity changes or CDC waivers. Integration supplies
# real clocks/resets; this leaf audit cannot establish transaction-epoch CDC.
proc rk_job_require {condition message} {if {!$condition} {error $message}}
proc rk_job_finite {value} {
    return [expr {[string is double -strict $value] &&
        ![catch {expr {abs(double($value)) < Inf}} result] && $result}]
}
proc rk_job_one {objects label} {
    rk_job_require [expr {[llength $objects] == 1}] "Expected exactly one $label"
    return [lindex $objects 0]
}
proc rk_job_prefix {instance} {
    rk_job_require [regexp {^([A-Za-z_][A-Za-z0-9_$]*/)*([A-Za-z_][A-Za-z0-9_$]*)?$} $instance] "Unsupported crossing hierarchy"
    return [expr {$instance eq "" ? "" : "$instance/"}]
}
proc rk_job_cell {prefix name} {
    return [rk_job_one [get_cells -quiet [list ${prefix}${name}]] "crossing register $name"]
}
proc rk_job_clock {name period} {
    set clock [rk_job_one [get_clocks -quiet $name] "crossing clock $name"]
    set actual [get_property PERIOD $clock]
    rk_job_require [expr {[rk_job_finite $actual] && abs($actual-$period)<0.000001}] "Changed crossing clock period"
    return $clock
}
proc rk_job_vectors {prefix source target count} {
    set a {};set b {}
    for {set bit 0} {$bit<$count} {incr bit} {
        lappend a [rk_job_cell $prefix [format {%s_reg[%d]} $source $bit]]
        lappend b [rk_job_cell $prefix [format {%s_reg[%d]} $target $bit]]
    }
    return [list $a $b]
}
proc rk_job_profile {profile} {
    rk_job_require [expr {$profile in {full8 ew_e1_e8 ew_engine_e1_e8 cmac_terminal_full8}}] "Unsupported job result mapping profile"
}
proc rk_job_boundary_pin {block name} {
    set found {}
    foreach pin [get_pins -quiet -of_objects $block] {
        if {[get_property REF_PIN_NAME $pin] eq $name} {lappend found $pin}
    }
    return [rk_job_one $found "job boundary pin $name"]
}
proc rk_job_ground {object label {boundary upper}} {
    rk_job_require [expr {$boundary in {upper lower}}] "Invalid constant observer boundary"
    set options [list -quiet -segments -of_objects $object]
    if {$boundary eq "lower"} {lappend options -boundary_type lower}
    set net [rk_job_one [get_nets {*}$options] "$label constant net"]
    rk_job_require [expr {[get_property TYPE $net] eq "GROUND" &&
        [get_property DRIVER_COUNT $net]==1}] "$label is not a proved single-driver constant zero"
    return $net
}
proc rk_job_zero_error_codes {prefix {profile ew_e1_e8}} {
    # Explicit selected-EW profile only: raw E1..E8 and protocol E5 have zero
    # bits7:4. Verify actual input pins AND observable top output ports. An
    # absent register alone is never constant-field evidence.
    rk_job_require [expr {$prefix ne ""}] "Folded EW errors require an explicit job instance"
    set instance [string range $prefix 0 end-1]
    set block [rk_job_one [get_cells -quiet [list $instance]] "folded EW job hierarchy"]
    rk_job_require [expr {![get_property IS_PRIMITIVE $block]}] "Folded EW job must be hierarchical"
    rk_job_require [expr {$profile in {ew_e1_e8 ew_engine_e1_e8}}] "Invalid folded EW observer profile"
    if {$profile eq "ew_engine_e1_e8"} {
        # The joined platform does not export ui_result_code at its top. Its
        # actual EW engine boundary is the observable constant, never an
        # absent register or a different platform fault-code signal.
        rk_job_require [regexp {^(.+)/job_crossing$} $instance -> parent] "EW observer requires the engine job_crossing child"
        set engine [rk_job_one [get_cells -quiet [list $parent]] "EW engine observer hierarchy"]
        rk_job_require [expr {![get_property IS_PRIMITIVE $engine] &&
            [get_property REF_NAME $engine] eq "rk_ew_async_engine"}] "Unexpected EW observer module"
    }
    set facts {}
    for {set bit 4} {$bit<8} {incr bit} {
        set input [rk_job_boundary_pin $block [format {d_result_code[%d]} $bit]]
        set unused [rk_job_boundary_pin $block [format {s_result_code[%d]} $bit]]
        rk_job_require [expr {[get_property DIRECTION $input] eq "IN" &&
            [get_property DIRECTION $unused] eq "OUT"}] "Changed folded error boundary direction"
        if {$profile eq "ew_engine_e1_e8"} {
            set output [rk_job_boundary_pin $engine [format {ui_result_code[%d]} $bit]]
        } else {
            set found {}
            foreach port [get_ports -quiet] {
                if {[get_property NAME $port] eq [format {ui_result_code[%d]} $bit]} {lappend found $port}
            }
            set output [rk_job_one $found "observable EW error-code port"]
        }
        rk_job_require [expr {[get_property DIRECTION $output] eq "OUT"}] "Wrong observable error-code direction"
        set from [rk_job_ground $input "EW source error bit$bit"]
        # A hierarchical output's upper segment may be unused/absent. Query
        # its actual internal driver, never treat absence as a constant.
        set to [rk_job_ground $output "EW output error bit$bit" \
            [expr {$profile eq "ew_engine_e1_e8" ? "lower" : "upper"}]]
        rk_job_require [expr {[llength [get_nets -quiet -segments -of_objects $unused]]==0}] "Folded child error output unexpectedly connected"
        foreach name [list [format {result_held_reg[%d]} [expr {$bit+32}]] [format {s_result_code_reg[%d]} $bit]] {
            rk_job_require [expr {[llength [get_cells -quiet [list ${prefix}${name}]]]==0}] "Expected explicitly folded error register"
        }
        lappend facts [list ZERO_CODE $bit $input $from $output $to]
    }
    return $facts
}
proc rk_job_zero_terminal_tasks {prefix} {
    # Source contract: rk_cmac_success_rearm.completed_tasks is assigned only
    # 0/1; rk_cmac_async_engine forwards it or publishes zero on refused work.
    # The actual held mailbox has task bit0 and all eight error-code bits.
    # Every omitted task bit must be proved at input, child output and engine
    # observer, with both folded FFs absent. Absence is never the proof.
    rk_job_require [expr {$prefix ne ""}] "Terminal tasks require an explicit CMAC job instance"
    set instance [string range $prefix 0 end-1]
    rk_job_require [regexp {^(.+)/job_crossing$} $instance -> parent] "Terminal tasks require the CMAC job_crossing child"
    set engine [rk_job_one [get_cells -quiet [list $parent]] "CMAC terminal observer hierarchy"]
    rk_job_require [expr {![get_property IS_PRIMITIVE $engine] &&
        [get_property REF_NAME $engine] eq "rk_cmac_async_engine"}] "Unexpected CMAC terminal observer module"
    set block [rk_job_one [get_cells -quiet [list $instance]] "CMAC terminal job hierarchy"]
    rk_job_require [expr {![get_property IS_PRIMITIVE $block] &&
        [get_property REF_NAME $block] in {rk_async_job_port rk_async_job_port__1}}] "Unexpected CMAC terminal job module"
    set facts {}
    for {set bit 1} {$bit<32} {incr bit} {
        set input [rk_job_boundary_pin $block [format {d_result_tasks[%d]} $bit]]
        set child [rk_job_boundary_pin $block [format {s_result_tasks[%d]} $bit]]
        set output [rk_job_boundary_pin $engine [format {ui_result_tasks[%d]} $bit]]
        rk_job_require [expr {[get_property DIRECTION $input] eq "IN" &&
            [get_property DIRECTION $child] eq "OUT" &&
            [get_property DIRECTION $output] eq "OUT"}] "Changed CMAC terminal task boundary direction"
        set from [rk_job_ground $input "CMAC source task bit$bit"]
        set to [rk_job_ground $output "CMAC output task bit$bit" lower]
        set inside [rk_job_ground $child "CMAC child task bit$bit" lower]
        foreach name [list [format {result_held_reg[%d]} $bit] [format {s_result_tasks_reg[%d]} $bit]] {
            rk_job_require [expr {[llength [get_cells -quiet [list ${prefix}${name}]]]==0}] "Expected explicitly folded CMAC task register"
        }
        lappend facts [list ZERO_TASK $bit $input $from $output $to $child $inside]
    }
    return $facts
}
proc rk_job_constant_fields {prefix profile} {
    rk_job_profile $profile
    switch -- $profile {
        full8 {return {}}
        cmac_terminal_full8 {return [rk_job_zero_terminal_tasks $prefix]}
        default {return [rk_job_zero_error_codes $prefix $profile]}
    }
}
proc rk_job_payloads {prefix {profile full8}} {
    rk_job_profile $profile
    rk_job_constant_fields $prefix $profile
    lassign [rk_job_vectors $prefix descriptor_held descriptor_latched 64] descriptor_source descriptor_target
    set result_source {};set result_target {}
    for {set bit 0} {$bit<41} {incr bit} {
        if {$profile in {ew_e1_e8 ew_engine_e1_e8} && $bit>=36 && $bit<40} {continue}
        if {$profile eq "cmac_terminal_full8" && $bit>=1 && $bit<32} {continue}
        lappend result_source [rk_job_cell $prefix [format {result_held_reg[%d]} $bit]]
        if {$bit<32} {
            set target [format {s_result_tasks_reg[%d]} $bit]
        } elseif {$bit<40} {
            set target [format {s_result_code_reg[%d]} [expr {$bit-32}]]
        } else {
            set target s_result_error_reg
        }
        lappend result_target [rk_job_cell $prefix $target]
    }
    return [list [list descriptor $descriptor_source $descriptor_target 40.000] \
        [list result $result_source $result_target 15.000]]
}
proc rk_job_sync_cells {prefix name} {
    set cells {}
    for {set bit 0} {$bit<3} {incr bit} {
        lappend cells [rk_job_cell $prefix [format {%s_reg[%d]} $name $bit]]
    }
    set all [get_cells -quiet -hier -filter "NAME =~ ${prefix}${name}_reg*"]
    rk_job_require [expr {[lsort $all] eq [lsort $cells]}] "Changed synchronizer depth"
    return $cells
}
proc rk_job_cdc_constrain {instance source_clock destination_clock {profile full8}} {
    rk_job_profile $profile
    set prefix [rk_job_prefix $instance]
    set source [rk_job_clock $source_clock 7.500]
    set destination [rk_job_clock $destination_clock 20.000]
    rk_job_require [expr {$source ne $destination}] "Crossing clocks must be distinct"
    foreach payload [rk_job_payloads $prefix $profile] {
        lassign $payload label a b bound
        set_max_delay -datapath_only $bound -from $a -to $b
        # Each payload remains stable until the corresponding synchronized
        # witness returns; there is no synchronous hold relation across clocks.
        set_false_path -hold -from $a -to $b
        set_bus_skew $bound -from $a -to $b
    }
    foreach name {request_sync result_sync fault_sync} {
        set cells [rk_job_sync_cells $prefix $name]
        set_property ASYNC_REG TRUE $cells
        set_property DONT_TOUCH TRUE $cells
        # Only each chain's first asynchronous D pin is cut; later stages stay timed.
        set_false_path -to [get_pins [lindex $cells 0]/D]
    }
}
proc rk_job_register_clock {cell expected} {
    rk_job_require [expr {[get_property REF_NAME $cell] in {FDCE FDRE FDSE FDPE}}] "Crossing endpoint is not a flip-flop"
    set actual [rk_job_one [get_clocks -of_objects [get_pins $cell/C]] "mapped register clock"]
    rk_job_require [expr {$actual eq $expected}] "Wrong crossing register clock"
}
proc rk_job_report_skew {instance output} {
    rk_job_prefix $instance
    set options [list -warn_on_violation -file $output]
    if {$instance ne ""} {
        set block [rk_job_one [get_cells -quiet [list $instance]] "job crossing hierarchy"]
        rk_job_require [expr {![get_property IS_PRIMITIVE $block]}] "Job crossing scope must be hierarchical"
        lappend options -cells $block
    }
    report_bus_skew {*}$options
}
proc rk_job_cdc_audit {instance source_clock destination_clock output {profile full8}} {
    rk_job_profile $profile
    set prefix [rk_job_prefix $instance]
    set source [rk_job_clock $source_clock 7.500]
    set destination [rk_job_clock $destination_clock 20.000]
    rk_job_require [expr {$source ne $destination && [llength [get_waivers]]==0}] "Changed crossing clocks/waivers"
    set facts [open [file join $output async_job_cdc.tsv] w]
    if {$profile ne "full8"} {
        puts $facts "PROFILE\t$profile"
        foreach row [rk_job_constant_fields $prefix $profile] {puts $facts [join $row "\t"]}
    }
    foreach {name origin clock period} [list request_sync request_toggle $destination 20.000 \
            result_sync result_toggle $source 7.500 fault_sync d_protocol_fault $source 7.500] {
        set cells [rk_job_sync_cells $prefix $name]
        for {set bit 0} {$bit<3} {incr bit} {
            set cell [lindex $cells $bit]
            rk_job_register_clock $cell $clock
            rk_job_require [expr {[get_property ASYNC_REG $cell] && [get_property DONT_TOUCH $cell]}] "Unprotected synchronizer"
            set previous [expr {$bit==0 ? [rk_job_cell $prefix ${origin}_reg] : [lindex $cells [expr {$bit-1}]]}]
            if {$bit==0} {
                rk_job_register_clock $previous [expr {$name eq "request_sync" ? $source : $destination}]
            }
            set starts [lsort -unique [all_fanin -flat -startpoints_only -to [get_pins $cell/D]]]
            rk_job_require [expr {$starts eq [list [get_pins $previous/C]]}] "Unexpected synchronizer fanin"
            if {$bit>0} {
                set path [rk_job_one [get_timing_paths -quiet -from $previous -to $cell -delay_type max -max_paths 1] "later synchronizer timing path"]
                set slack [get_property SLACK $path];set required [get_property REQUIREMENT $path]
                rk_job_require [expr {[rk_job_finite $slack] && $slack>=0 && [rk_job_finite $required] && abs($required-$period)<0.000001}] "Later synchronizer is cut/failing"
            }
            puts $facts "SYNC\t$cell\t$clock\t$starts"
        }
    }
    foreach payload [rk_job_payloads $prefix $profile] {
        lassign $payload label a b bound
        set from_clock [expr {$label eq "descriptor" ? $source : $destination}]
        set to_clock [expr {$label eq "descriptor" ? $destination : $source}]
        set n [llength $a]
        for {set bit 0} {$bit<$n} {incr bit} {
            set from [lindex $a $bit];set to [lindex $b $bit]
            rk_job_register_clock $from $from_clock;rk_job_register_clock $to $to_clock
            set crosses {}
            foreach start [all_fanin -flat -startpoints_only -to [get_pins $to/D]] {
                set clock [get_clocks -quiet -of_objects $start]
                if {[llength $clock]==1 && [lindex $clock 0] eq $from_clock} {lappend crosses $start}
            }
            rk_job_require [expr {[lsort -unique $crosses] eq [list [get_pins $from/C]]}] "Wrong held-payload bit correspondence"
            set path [rk_job_one [get_timing_paths -quiet -from $from -to $to -delay_type max -max_paths 1] "active held-payload max-delay path"]
            set slack [get_property SLACK $path];set required [get_property REQUIREMENT $path]
            rk_job_require [expr {[rk_job_finite $slack] && $slack>=0 && [rk_job_finite $required] && abs($required-$bound)<0.000001}] "Payload path cut/loosened/failing"
        }
        puts $facts "PAYLOAD\t$label\t$n\t$bound"
        report_timing -from $a -to $b -max_paths $n -file [file join $output async_job_${label}_payload_timing.rpt]
    }
    close $facts
    report_cdc -details -file [file join $output async_job_cdc.rpt]
    report_exceptions -file [file join $output async_job_exceptions.rpt]
    rk_job_report_skew $instance [file join $output async_job_bus_skew.rpt]
    set channel [open [file join $output async_job_bus_skew.rpt] r]
    set text [read $channel];close $channel
    set slacks [regexp -all -inline -line {^Slack \((MET|VIOLATED)\)\s*:\s*([^\s]+)ns} $text]
    set limits [regexp -all -inline -line {^Requirement:\s*([^\s]+)ns\s*$} $text]
    set details [regexp -all -inline -line {^[ \t]+Requirement:\s*([^\s]+)ns\s*$} $text]
    rk_job_require [expr {[llength $slacks]==6 && [llength $limits]==4 && [llength $details]==4}] "Incomplete skew coverage"
    foreach {whole status slack} $slacks {
        rk_job_require [expr {$status eq "MET" && [rk_job_finite $slack] && $slack>=0}] "Crossing bus skew failed"
    }
    set observed {};set observed_details {}
    foreach {whole value} $limits {
        rk_job_require [rk_job_finite $value] "Invalid skew requirement"
        lappend observed [expr {double($value)}]
    }
    foreach {whole value} $details {
        rk_job_require [rk_job_finite $value] "Invalid skew detail requirement"
        lappend observed_details [expr {double($value)}]
    }
    rk_job_require [expr {[lsort -real $observed] eq {15.0 40.0} && [lsort -real $observed_details] eq {15.0 40.0}}] "Changed skew limits"
}
