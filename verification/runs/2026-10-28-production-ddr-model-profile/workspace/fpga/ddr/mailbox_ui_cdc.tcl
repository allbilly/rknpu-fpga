# SPDX-License-Identifier: Apache-2.0
# UI-clock adaptation of fpga/host/mailbox_cdc.tcl; original helper unchanged.
# The DDR mailbox uses actual C0 UI7.500ns, not SYS20ns. Its request budget
# is two UI cycles,15ns; the conservative6MHz TCK166.666ns and response
# budget333.332ns are retained. Actual bring-up TCK remains3MHz.
# Scope skew reports to u_mailbox because job/memory crossings coexist.
# No timing evidence is imported and no clock groups/reset cuts/waivers added.

proc rk_ddr_host_finite {value} {
    return [expr {[string is double -strict $value] &&
        ![catch {expr {abs(double($value)) < Inf}} finite] && $finite}]
}
proc rk_ddr_host_one {objects description} {
    if {[llength $objects] != 1} { error "Expected exactly one $description." }
    return [lindex $objects 0]
}
proc rk_ddr_host_clock {name period} {
    set clock [rk_ddr_host_one [get_clocks -quiet $name] $name]
    set actual [get_property PERIOD [get_clocks -quiet [list $name]]]
    if {![rk_ddr_host_finite $actual] || abs($actual-$period)>0.000001} {
        error "Wrong $name clock period ($actual)."
    }
    return $clock
}
proc rk_ddr_host_payload_cells {source target} {
    set a [get_cells -quiet -hier -filter "NAME =~ u_mailbox/${source}_reg*"]
    set b [get_cells -quiet -hier -filter "NAME =~ u_mailbox/${target}_reg*"]
    if {![llength $a] || ![llength $b]} { error "Missing held mailbox payload: $source/$target" }
    return [list $a $b]
}
proc rk_ddr_host_cdc_constrain {ui_clock} {
    set bscan [rk_ddr_host_one [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}] USER2]
    if {[get_property JTAG_CHAIN $bscan] != 2} { error "Expected USER2 JTAG_CHAIN=2." }
    rk_ddr_host_clock $ui_clock 7.500
    set first [rk_ddr_host_one [get_cells -quiet [list {u_mailbox/rq_sync_reg[0]}]] {first UI mailbox stage}]
    if {[get_clocks -of_objects [get_pins $first/C]] ne [get_clocks $ui_clock]} {error "Mailbox is not in selected C0 UI domain."}
    if {[llength [get_clocks -quiet jtag_tck]]!=0} {error "Fresh JTAG clock constraint required."}
    create_clock -name jtag_tck -period 166.666 [get_pins $bscan/TCK]
    rk_ddr_host_clock jtag_tck 166.666
    foreach {source target bound} {held req 15.000 response response_tck 333.332} {
        lassign [rk_ddr_host_payload_cells $source $target] a b
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
proc rk_ddr_host_report_skew {out} {
    set block [rk_ddr_host_one [get_cells -quiet u_mailbox] {UI mailbox hierarchy}]
    if {[get_property IS_PRIMITIVE $block]} {error "Expected hierarchical UI mailbox."}
    report_bus_skew -cells $block -warn_on_violation -file [file join $out mailbox_bus_skew.rpt]
}
proc rk_ddr_host_cdc_audit {out ui_clock} {
    set bscan [rk_ddr_host_one [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}] USER2]
    if {[get_property JTAG_CHAIN $bscan] != 2} { error "Changed USER2 primitive." }
    rk_ddr_host_clock $ui_clock 7.500
    rk_ddr_host_clock jtag_tck 166.666
    set tck [rk_ddr_host_one [get_clocks -of_objects [get_pins $bscan/TCK]] {BSCAN TCK clock}]
    if {$tck ne [get_clocks jtag_tck]} { error "BSCAN TCK is not the constrained JTAG clock." }
    set facts [open [file join $out mailbox_cdc.tsv] w]
    foreach {prefix origin clock period} [list rq_sync req_toggle $ui_clock 7.500 rs_sync rsp_toggle jtag_tck 166.666] {
        for {set bit 0} {$bit<3} {incr bit} {
            set name [format {u_mailbox/%s_reg[%d]} $prefix $bit]
            set cell [rk_ddr_host_one [get_cells -quiet [list $name]] {mailbox synchronizer stage}]
            if {![get_property ASYNC_REG $cell] || ![get_property DONT_TOUCH $cell]} {
                error "Unprotected mailbox synchronizer stage: $name"
            }
            set actual [rk_ddr_host_one [get_clocks -of_objects [get_pins $cell/C]] {synchronizer clock}]
            if {$actual ne [get_clocks $clock]} { error "Wrong synchronizer clock: $name" }
            set prior [expr {$bit==0 ? "u_mailbox/${origin}_reg" :
                [format {u_mailbox/%s_reg[%d]} $prefix [expr {$bit-1}]]}]
            set previous [rk_ddr_host_one [get_cells -quiet [list $prior]] {synchronizer input register}]
            set starts [lsort [all_fanin -flat -startpoints_only -to [get_pins $cell/D]]]
            if {[llength $starts]!=1 || [lindex $starts 0] ne [lindex [get_pins $previous/C] 0]} {
                error "Unexpected synchronizer fanin: $name $starts"
            }
            if {$bit>0} {
                set path [rk_ddr_host_one [get_timing_paths -quiet -from $previous -to $cell -delay_type max -max_paths 1] {timed later synchronizer stage}]
                set slack [get_property SLACK $path]
                set required [get_property REQUIREMENT $path]
                if {![rk_ddr_host_finite $slack] || $slack<0 || ![rk_ddr_host_finite $required] || abs($required-$period)>0.000001} {
                    error "Later synchronizer stage is cut or fails timing: $name"
                }
            }
            puts $facts "SYNC\t$name\t$actual\t$starts"
        }
    }
    foreach {source target budget} {held req 15.000 response response_tck 333.332} {
        lassign [rk_ddr_host_payload_cells $source $target] a b
        set path [rk_ddr_host_one [get_timing_paths -quiet -from $a -to $b -delay_type max -max_paths 1] {active mailbox payload max-delay path}]
        set slack [get_property SLACK $path]
        set required [get_property REQUIREMENT $path]
        if {![rk_ddr_host_finite $slack] || $slack<0 || ![rk_ddr_host_finite $required] || abs($required-$budget)>0.000001} {
            error "Mailbox payload bound differs or fails: $source"
        }
        puts $facts "PAYLOAD\t$source\t$target\t[llength $a]\t[llength $b]\t$required\t$slack"
        report_timing -from $a -to $b -delay_type max -max_paths 32 -file [file join $out mailbox_${source}_timing.rpt]
    }
    close $facts
    report_cdc -details -file [file join $out mailbox_cdc.rpt]
    report_exceptions -file [file join $out mailbox_exceptions.rpt]
    rk_ddr_host_report_skew $out
    set channel [open [file join $out mailbox_bus_skew.rpt] r]
    set text [read $channel]; close $channel
    # This hierarchical scope has exactly the two mailbox bus-skew constraints.
    # Use the documented native report form preserved in the donor evidence.
    set slacks [regexp -all -inline -line {^Slack \((MET|VIOLATED)\)\s*:\s*([^\s]+)ns} $text]
    # Native reports repeat each requirement: an unindented constraint header
    # and an indented path detail. Require both complete inventories and equal
    # values; do not mistake the second copy for another constraint.
    set limits [regexp -all -inline -line {^Requirement:\s*([^\s]+)ns\s*$} $text]
    set details [regexp -all -inline -line {^[ \t]+Requirement:\s*([^\s]+)ns\s*$} $text]
    if {[llength $slacks]!=6 || [llength $limits]!=4 || [llength $details]!=4} {
        error "Incomplete mailbox bus-skew report."
    }
    foreach {whole status slack} $slacks {
        if {$status ne "MET" || ![rk_ddr_host_finite $slack] || $slack<0} { error "Mailbox bus skew failed." }
    }
    set bounds {}
    foreach {whole value} $limits {
        if {![rk_ddr_host_finite $value]} { error "Invalid bus-skew requirement." }
        lappend bounds $value
    }
    set bounds [lsort -real $bounds]
    set detail_bounds {}
    foreach {whole value} $details {
        if {![rk_ddr_host_finite $value]} { error "Invalid detailed bus-skew requirement." }
        lappend detail_bounds $value
    }
    foreach expected $bounds detail [lsort -real $detail_bounds] {
        if {$expected != $detail} { error "Conflicting bus-skew requirements." }
    }
    if {abs([lindex $bounds 0]-15.0)>0.000001 || abs([lindex $bounds 1]-333.332)>0.000001} {
        error "Changed mailbox bus-skew budgets."
    }
}
