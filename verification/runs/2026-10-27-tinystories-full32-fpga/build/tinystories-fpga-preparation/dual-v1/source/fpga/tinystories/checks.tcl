# Source/routed checks for the new full512 dual endpoint. No constraints change.
proc rk_dual_require {condition message} {if {!$condition} {error $message}}
proc rk_dual_full512 {} {
    set kernels [get_cells -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe || REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe}]
    rk_dual_require [expr {[llength $kernels] == 16}] "Expected sixteen C32 kernels"
    set dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E1}]
    set owned {}
    foreach kernel $kernels {
        set prefix "[get_property NAME $kernel]/"
        set count 0
        foreach dsp $dsps {
            set name [get_property NAME $dsp]
            if {[string first $prefix $name] == 0} {
                rk_dual_require [expr {![dict exists $owned $name]}] "Duplicate DSP ownership"
                dict set owned $name 1
                incr count
            }
        }
        rk_dual_require [expr {$count == 32}] "Reduced C32 kernel"
    }
    rk_dual_require [expr {[dict size $owned] == 512}] "Reduced parallel product target"
    set memories [get_cells -hierarchical -filter {NAME =~ endpoint/memory/* && (REF_NAME == RAMB18E1 || REF_NAME == RAMB36E1)}]
    set data_bits 0
    foreach cell $memories {
        incr data_bits [expr {[get_property REF_NAME $cell] eq "RAMB36E1" ? 32768 : 16384}]
    }
    rk_dual_require [expr {$data_bits >= 8388608}] "Missing1MiB BRAM backing"
}

proc rk_dual_registered_reset {out stage} {
    set child [get_cells -quiet -hierarchical -filter {NAME =~ endpoint/cm_engine/child_release_reg*}]
    set global [get_cells -quiet -hierarchical -filter {NAME =~ startup/rst_n_reg*}]
    rk_dual_require [expr {[llength $child] > 0 && [llength $global] > 0}] "Missing registered reset sources"
    set allowed {}
    set child_clocks {}
    set facts [open [file join $out reset_${stage}.tsv] w]
    foreach cell [concat $child $global] {
        rk_dual_require [expr {[get_property REF_NAME $cell] in {FDRE FDSE}}] "Reset source is not a synchronous FF"
        set clock_pin [rk_host_one [get_pins $cell/C] {reset source clock pin}]
        set clock [rk_host_one [get_clocks -of_objects $clock_pin] {reset source clock}]
        rk_dual_require [expr {$clock eq [get_clocks sys_clk]}] "Reset FF crosses clock domains"
        lappend allowed $clock_pin
        if {[lsearch -exact $child $cell] >= 0} {lappend child_clocks $clock_pin}
        puts $facts "RESET_FF\t$cell\t[get_property REF_NAME $cell]\t[get_property INIT $cell]\t$clock"
    }
    set reset_pin [rk_host_one [get_pins -quiet endpoint/cm_engine/engine/rst_n] {owned CMAC reset sink}]
    set starts [lsort -unique [all_fanin -flat -startpoints_only -to $reset_pin]]
    rk_dual_require [expr {[llength $starts] > 0}] "Missing reset cone"
    set has_child 0
    foreach pin $starts {
        rk_dual_require [expr {[lsearch -exact $allowed $pin] >= 0}] "Unregistered/state-decoded reset source"
        if {[lsearch -exact $child_clocks $pin] >= 0} {set has_child 1}
    }
    rk_dual_require $has_child "Local registered reset FF does not drive the engine"
    puts $facts "RESET_CONE\t$reset_pin\t$starts"
    set startup [get_cells -hierarchical -filter {NAME =~ startup/* && REF_NAME == FDRE}]
    rk_dual_require [expr {[llength $startup] >= 65}] "Lost startup hold/release registers"
    foreach cell $startup {
        rk_dual_require [expr {[get_property INIT $cell] eq "1'b0"}] "Changed startup INIT"
        puts $facts "STARTUP_FF\t$cell\t[get_property INIT $cell]"
    }
    close $facts
}

proc rk_dual_pulse_gate {text} {
    set clock ""
    set observed {}
    foreach line [split $text \n] {
        if {[regexp {^Clock Name:\s+(\S+)\s*$} $line -> clock]} {
            rk_dual_require [expr {$clock in {sys_clk jtag_tck}}] "Unexpected pulse-width clock"
        } elseif {[regexp {^(Min Period|Low Pulse Width|High Pulse Width)\s+\S+\s+\S+\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+\S+\s+\S+\s*$} $line -> kind required actual slack]} {
            rk_dual_require [expr {$clock ne "" && ![dict exists $observed [list $clock $kind]]}] "Duplicate/unbound pulse check"
            rk_dual_require [expr {[rk_host_finite $required] && [rk_host_finite $actual] && [rk_host_finite $slack] &&
                                  $required > 0 && $actual > 0 && $slack >= 0}] "Invalid/failing pulse-width check"
            dict set observed [list $clock $kind] $slack
        }
    }
    foreach clock {sys_clk jtag_tck} {
        foreach kind {"Min Period" "Low Pulse Width" "High Pulse Width"} {
            rk_dual_require [dict exists $observed [list $clock $kind]] "Missing pulse-width check"
        }
    }
    rk_dual_require [expr {[dict size $observed] == 6}] "Wrong pulse-width inventory"
}
