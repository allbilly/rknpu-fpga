# Physical boot-only board profile. Source reset_status_cdc.tcl first.
# Bind the actual registered SYS startup producer before excluding its async
# assertion into UI reset banks. All local data and local reset paths stay timed.
# This helper does not qualify vendor resets, PHY training or global timing.
proc rk_board_reset_constant {pin type} {
    set net [rk_status_one [get_nets -quiet -of_objects $pin] "constant startup net"]
    rk_status_require [expr {[get_property TYPE $net] eq $type &&
        [get_property DRIVER_COUNT $net]==1 &&
        [llength [all_fanin -flat -startpoints_only -to $pin]]==0}] "Changed startup constant"
}
proc rk_board_reset_same_net {left right} {
    set a [lsort -unique [get_nets -quiet -segments -of_objects $left]]
    set b [lsort -unique [get_nets -quiet -segments -of_objects $right]]
    rk_status_require [expr {[llength $a]>0 && $a eq $b}] "Changed startup inverter connectivity"
}
proc rk_board_reset_producer {endpoint startup inverter sys} {
    rk_status_require [expr {[llength [get_ports -quiet cfg_reset]]==0}] "Physical profile cannot use OOC cfg_reset"
    set block [rk_status_cell $startup]
    rk_status_require [expr {[get_property REF_NAME $block] eq "rk_startup_reset"}] "Wrong startup producer module"
    set chain {}
    for {set i 0} {$i<64} {incr i} {
        lappend chain [rk_status_cell [format {%s/release_pipe_reg[%d]} $startup $i]]
    }
    lappend chain [rk_status_cell $startup/rst_n_reg]
    # Vivado 2026.1 maps one local GND and VCC primitive alongside the 65
    # FDREs. Admit these exact observed constants, never extra logic/registers.
    # See cfg-producer-query-v1/facts.tsv, bound to checkpoint 739ef00239e5.
    set constants {}
    foreach kind {GND VCC} {
        set cell [rk_status_cell $startup/$kind]
        rk_status_require [expr {[get_property REF_NAME $cell] eq $kind}] "Changed mapped startup constant primitive"
        lappend constants $cell
    }
    set actual [get_cells -quiet -hier -filter "NAME =~ $startup/* && IS_PRIMITIVE == 1"]
    rk_status_require [expr {[lsort $actual] eq [lsort [concat $chain $constants]]}] "Changed boot startup chain"
    set previous {}
    foreach cell $chain {
        rk_status_ff $cell $sys
        rk_status_require [expr {[get_property REF_NAME $cell] eq "FDRE" &&
            [get_property INIT $cell] eq "1'b0"}] "Unreviewed startup register"
        rk_board_reset_constant [rk_status_pin $cell/CE] POWER
        rk_board_reset_constant [rk_status_pin $cell/R] GROUND
        set data [rk_status_pin $cell/D]
        if {$previous eq ""} {
            rk_board_reset_constant $data POWER
        } else {
            rk_status_require [expr {[all_fanin -flat -startpoints_only -to $data] eq
                [rk_status_pin $previous/C]}] "Startup release contains another source"
        }
        set previous $cell
    }
    set origin [rk_status_pin $previous/C]
    set inv [rk_status_cell $inverter]
    rk_status_require [expr {[get_property REF_NAME $inv] eq "LUT1" &&
        [get_property INIT $inv] eq "2'h1"}] "Configuration reset must invert registered startup"
    rk_board_reset_same_net [rk_status_pin $previous/Q] [rk_status_pin $inv/I0]
    rk_board_reset_same_net [rk_status_pin $inv/O] [rk_status_pin $endpoint/cfg_reset]
    set cfg_starts [all_fanin -flat -startpoints_only -to [rk_status_pin $endpoint/cfg_reset]]
    rk_status_require [expr {$cfg_starts eq $origin}] "Unregistered physical configuration reset"
    return [list $origin $chain]
}
proc rk_board_reset_inventory {endpoint startup inverter sys ui0 ui1} {
    set owner [rk_status_cell $endpoint/reset_owner]
    rk_status_require [expr {[get_property REF_NAME $owner] eq "rk_mig_reset_coordinator"}] "Wrong board reset owner"
    set sys [rk_status_clock $sys 20.000]
    set ui0 [rk_status_clock $ui0 7.500]
    set ui1 [rk_status_clock $ui1 7.500]
    rk_status_require [expr {$sys ne $ui0 && $sys ne $ui1 && $ui0 ne $ui1}] "Board reset clocks must remain distinct"
    lassign [rk_board_reset_producer $endpoint $startup $inverter $sys] cfg chain
    set result {}
    for {set domain 0} {$domain<2} {incr domain} {
        set ui [expr {$domain==0 ? $ui0 : $ui1}]
        set local [rk_status_cell [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint $domain]]
        foreach kind {epoch permit} {
            if {$kind eq "epoch"} {
                set source [rk_status_cell $endpoint/reset_owner/mig_sys_rst_n_reg]
                set cells [list [rk_status_cell [format {%s/reset_owner/ui_domain[%d].reset_pipe_reg[0]} $endpoint $domain]] \
                    [rk_status_cell [format {%s/reset_owner/ui_domain[%d].reset_pipe_reg[1]} $endpoint $domain]] $local]
                set sources [list [rk_status_pin $source/C] $cfg]
                set expected [lsort $sources]
            } else {
                set source [rk_status_cell $endpoint/reset_owner/release_permit_reg]
                set cells {}
                for {set i 0} {$i<3} {incr i} {
                    lappend cells [rk_status_cell [format {%s/reset_owner/ui_domain[%d].permit_sync_reg[%d]} $endpoint $domain $i]]
                }
                set sources [list [rk_status_pin $source/C]]
                set expected [lsort [concat $sources [list [rk_status_pin $local/C]]]]
            }
            rk_status_ff $source $sys
            set previous {}
            set common {}
            foreach cell $cells {
                rk_status_ff $cell $ui
                rk_status_require [expr {[get_property REF_NAME $cell] eq "FDCE" &&
                    [get_property INIT $cell] eq "1'b0" && [get_property ASYNC_REG $cell]}] "Unreviewed board reset-release register"
                set clr [rk_status_pin $cell/CLR]
                set net [rk_status_one [get_nets -quiet -of_objects $clr] "shared board reset CLR net"]
                if {$common eq ""} {set common $net}
                rk_status_require [expr {$common eq $net}] "Board reset bank does not share one CLR"
                set starts [lsort -unique [all_fanin -flat -startpoints_only -to $clr]]
                rk_status_require [expr {$starts eq $expected}] "Unexpected physical reset source in release bank"
                set data [rk_status_pin $cell/D]
                if {$previous eq ""} {
                    rk_board_reset_constant $data POWER
                } else {
                    rk_status_require [expr {[all_fanin -flat -startpoints_only -to $data] eq
                        [rk_status_pin $previous/C]}] "Board reset release contains another data source"
                }
                set previous $cell
            }
            lappend result [list $domain $kind $sources $local $ui $cells $common]
        }
    }
    rk_status_require [expr {[llength $result]==4}] "Incomplete physical reset-release inventory"
    return $result
}
proc rk_board_reset_constrain {endpoint startup inverter sys ui0 ui1} {
    # Complete structural admission precedes every constraint mutation.
    set inventory [rk_board_reset_inventory $endpoint $startup $inverter $sys $ui0 $ui1]
    foreach bank $inventory {
        lassign $bank domain kind sources local ui cells net
        set_property DONT_TOUCH TRUE $cells
        foreach source $sources {
            foreach cell $cells {
                set_false_path -from $source -to [rk_status_pin $cell/CLR]
            }
        }
    }
}
proc rk_board_reset_timed {source target period file label} {
    foreach type {max min} {
        set p [rk_status_one [get_timing_paths -quiet -from [rk_status_pin $source/C] -to $target -delay_type $type -max_paths 1] "active board reset-bank path"]
        set required [get_property REQUIREMENT $p]
        set slack [get_property SLACK $p]
        set expected [expr {$type eq "max" ? $period : 0.000}]
        puts $file "OBSERVED_$label\t$type\t$source\t$target\t$required\t$slack\t[get_property EXCEPTION $p]"
        flush $file
        rk_status_require [expr {[get_property EXCEPTION $p] eq "" &&
            [string is double -strict $slack] && abs($slack)<Inf && $slack>=0 &&
            [string is double -strict $required] && abs($required-$expected)<0.000001 &&
            [get_property STARTPOINT_PIN $p] eq [rk_status_pin $source/C] &&
            [get_property ENDPOINT_PIN $p] eq $target}] "Local board reset path is cut, changed or failing"
        puts $file "$label\t$type\t$source\t$target\t$required\t$slack"
    }
}
proc rk_board_reset_audit {endpoint startup inverter sys ui0 ui1 output} {
    rk_status_require [expr {[llength [get_waivers]]==0}] "Unexpected physical reset waiver"
    set inventory [rk_board_reset_inventory $endpoint $startup $inverter $sys $ui0 $ui1]
    set f [open [file join $output reset_bridge_board.tsv] w]
    foreach bank $inventory {
        lassign $bank domain kind sources local ui cells net
        set period [get_property PERIOD [get_clocks -quiet [list $ui]]]
        set previous {}
        foreach cell $cells {
            rk_status_require [expr {[get_property DONT_TOUCH $cell]}] "Unprotected board reset release bank"
            set target [rk_status_pin $cell/CLR]
            foreach source $sources {
                foreach type {max min} {
                    set p [rk_status_one [get_timing_paths -quiet -from $source -to $target -delay_type $type -max_paths 1] "physical async reset path object"]
                    rk_status_require [expr {[get_property EXCEPTION $p] eq "False Path" &&
                        [get_property SLACK $p] eq "" && [get_property REQUIREMENT $p] eq "" &&
                        [get_property REQUIRED_TIME $p] eq "" &&
                        [get_property STARTPOINT_PIN $p] eq $source &&
                        [get_property ENDPOINT_PIN $p] eq $target}] "Physical reset exception has wrong scope"
                    puts $f "ASYNC_CLR\t$domain\t$kind\t$type\t$source\t$cell"
                }
            }
            if {$previous ne ""} {
                rk_board_reset_timed $previous [rk_status_pin $cell/D] $period $f DATA
            }
            if {$kind eq "permit"} {
                rk_board_reset_timed $local $target $period $f LOCAL_CLR
            }
            set previous $cell
        }
        puts $f "BANK\t$domain\t$kind\t$net\t3"
    }
    close $f
    report_exceptions -file [file join $output reset_bridge_board_exceptions.rpt]
    puts PASS_PHYSICAL_PROJECT_RESET_BANKS_ONLY_VENDOR_PHY_AND_GLOBAL_TIMING_OPEN
}
