# SPDX-License-Identifier: Apache-2.0
# Adapted from the frozen OpenTPU c0182800 USER2 constraints and routed audit.
# Native Vivado has1ps resolution. Floor the6MHz period to166.666ns,
# making the model faster/conservative, and use2*TCK=333.332ns for responses.
# Do not accept upward-rounded/slower periods or looser budgets.
# See reference.json and rtl/vendor/opentpu/LICENSE. No timing result is imported.

proc rk_host_finite {value} {
    return [expr {[string is double -strict $value] &&
        ![catch {expr {abs(double($value)) < Inf}} finite] && $finite}]
}
proc rk_host_one {objects description} {
    if {[llength $objects] != 1} { error "Expected exactly one $description." }
    return [lindex $objects 0]
}
proc rk_host_clock {name period} {
    set clock [rk_host_one [get_clocks -quiet $name] $name]
    set actual [get_property PERIOD $clock]
    if {![rk_host_finite $actual] || abs($actual-$period)>0.000001} {
        error "Wrong $name clock period ($actual)."
    }
    return $clock
}
proc rk_host_payload_cells {source target} {
    set a [get_cells -quiet -hier -filter "NAME =~ u_mailbox/${source}_reg*"]
    set b [get_cells -quiet -hier -filter "NAME =~ u_mailbox/${target}_reg*"]
    if {![llength $a] || ![llength $b]} { error "Missing held mailbox payload: $source/$target" }
    return [list $a $b]
}
proc rk_host_cdc_constrain {} {
    set bscan [rk_host_one [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}] USER2]
    if {[get_property JTAG_CHAIN $bscan] != 2} { error "Expected USER2 JTAG_CHAIN=2." }
    rk_host_clock sys_clk 20.000
    create_clock -name jtag_tck -period 166.666 [get_pins $bscan/TCK]
    rk_host_clock jtag_tck 166.666
    foreach {source target bound} {held req 40.000 response response_tck 333.332} {
        lassign [rk_host_payload_cells $source $target] a b
        set_max_delay -datapath_only $bound -from $a -to $b
        set_false_path -hold -from $a -to $b
        set_bus_skew $bound -from $a -to $b
    }
    foreach prefix {rq_sync rs_sync} {
        set cells [get_cells -quiet -hier -filter "NAME =~ u_mailbox/${prefix}_reg*"]
        set first [get_cells -quiet [list [format {u_mailbox/%s_reg[0]} $prefix]]]
        if {[llength $cells]!=3 || [llength $first]!=1} { error "Missing mailbox toggle synchronizer." }
        set_property ASYNC_REG TRUE $cells
        set_property DONT_TOUCH TRUE $cells
        # Only the asynchronous first-stage D pin is exempted. Later stages
        # and the held payloads retain their setup/max-delay constraints.
        set_false_path -to [get_pins $first/D]
    }
}
proc rk_host_cdc_audit {out} {
    set bscan [rk_host_one [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}] USER2]
    if {[get_property JTAG_CHAIN $bscan] != 2} { error "Changed USER2 primitive." }
    rk_host_clock sys_clk 20.000
    rk_host_clock jtag_tck 166.666
    set tck [rk_host_one [get_clocks -of_objects [get_pins $bscan/TCK]] {BSCAN TCK clock}]
    if {$tck ne [get_clocks jtag_tck]} { error "BSCAN TCK is not the constrained JTAG clock." }
    set facts [open [file join $out mailbox_cdc.tsv] w]
    foreach {prefix origin clock period} {rq_sync req_toggle sys_clk 20.000 rs_sync rsp_toggle jtag_tck 166.666} {
        for {set bit 0} {$bit<3} {incr bit} {
            set name [format {u_mailbox/%s_reg[%d]} $prefix $bit]
            set cell [rk_host_one [get_cells -quiet [list $name]] {mailbox synchronizer stage}]
            if {![get_property ASYNC_REG $cell] || ![get_property DONT_TOUCH $cell]} {
                error "Unprotected mailbox synchronizer stage: $name"
            }
            set actual [rk_host_one [get_clocks -of_objects [get_pins $cell/C]] {synchronizer clock}]
            if {$actual ne [get_clocks $clock]} { error "Wrong synchronizer clock: $name" }
            set prior [expr {$bit==0 ? "u_mailbox/${origin}_reg" :
                [format {u_mailbox/%s_reg[%d]} $prefix [expr {$bit-1}]]}]
            set previous [rk_host_one [get_cells -quiet [list $prior]] {synchronizer input register}]
            set starts [lsort [all_fanin -flat -startpoints_only -to [get_pins $cell/D]]]
            if {[llength $starts]!=1 || [lindex $starts 0] ne [lindex [get_pins $previous/C] 0]} {
                error "Unexpected synchronizer fanin: $name $starts"
            }
            if {$bit>0} {
                set path [rk_host_one [get_timing_paths -quiet -from $previous -to $cell -delay_type max -max_paths 1] {timed later synchronizer stage}]
                set slack [get_property SLACK $path]
                set required [get_property REQUIREMENT $path]
                if {![rk_host_finite $slack] || $slack<0 || ![rk_host_finite $required] || abs($required-$period)>0.000001} {
                    error "Later synchronizer stage is cut or fails timing: $name"
                }
            }
            puts $facts "SYNC\t$name\t$actual\t$starts"
        }
    }
    foreach {source target budget} {held req 40.000 response response_tck 333.332} {
        lassign [rk_host_payload_cells $source $target] a b
        set path [rk_host_one [get_timing_paths -quiet -from $a -to $b -delay_type max -max_paths 1] {active mailbox payload max-delay path}]
        set slack [get_property SLACK $path]
        set required [get_property REQUIREMENT $path]
        if {![rk_host_finite $slack] || $slack<0 || ![rk_host_finite $required] || abs($required-$budget)>0.000001} {
            error "Mailbox payload bound differs or fails: $source"
        }
        puts $facts "PAYLOAD\t$source\t$target\t[llength $a]\t[llength $b]\t$required\t$slack"
        report_timing -from $a -to $b -delay_type max -max_paths 32 -file [file join $out mailbox_${source}_timing.rpt]
    }
    close $facts
    report_cdc -details -file [file join $out mailbox_cdc.rpt]
    report_exceptions -file [file join $out mailbox_exceptions.rpt]
    report_bus_skew -warn_on_violation -file [file join $out mailbox_bus_skew.rpt]
    set channel [open [file join $out mailbox_bus_skew.rpt] r]
    set text [read $channel]; close $channel
    # This standalone design has exactly the two mailbox bus-skew constraints.
    # Use the documented native report form preserved in the donor evidence.
    set slacks [regexp -all -inline -line {^Slack \((MET|VIOLATED)\)\s*:\s*([^\s]+)ns} $text]
    set limits [regexp -all -inline -line {^\s*Requirement:\s*([^\s]+)ns\s*$} $text]
    if {[llength $slacks]!=6 || [llength $limits]!=4} { error "Incomplete mailbox bus-skew report." }
    foreach {whole status slack} $slacks {
        if {$status ne "MET" || ![rk_host_finite $slack] || $slack<0} { error "Mailbox bus skew failed." }
    }
    set bounds {}
    foreach {whole value} $limits {
        if {![rk_host_finite $value]} { error "Invalid bus-skew requirement." }
        lappend bounds $value
    }
    set bounds [lsort -real $bounds]
    if {abs([lindex $bounds 0]-40.0)>0.000001 || abs([lindex $bounds 1]-333.332)>0.000001} {
        error "Changed mailbox bus-skew budgets."
    }
}
