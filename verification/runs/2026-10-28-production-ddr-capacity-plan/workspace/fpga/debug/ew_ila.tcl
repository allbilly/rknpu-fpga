# SPDX-License-Identifier: MIT
# Optional EW startup debug insertion, using documented Vivado 2026.1 APIs.
# Call insert after synthesis, then the existing opt/place/route flow. Call
# audit after route. Neither procedure builds, programs, arms, or resets a card.
# UG908: Using XDC Commands to Insert Debug Cores; Changing the BSCAN User Scan
# Chain of the Debug Core Hub. UG835: create_debug_core, get_debug_ports,
# get_nets, get_clocks, report_debug_core, write_debug_probes.

proc rk_ew_debug_one {objects description} {
    if {[llength $objects] != 1} {error "Expected exactly one $description."}
    return [lindex $objects 0]
}
proc rk_ew_debug_literal {name} {
    if {![regexp {^[A-Za-z_][A-Za-z0-9_/]*(\[[0-9]+\])?(/[A-Za-z_][A-Za-z0-9_]*)?$} $name]} {
        error "Unsupported nonliteral debug object name: $name"
    }
    return $name
}
proc rk_ew_debug_net {name} {
    rk_ew_debug_literal $name
    set net [rk_ew_debug_one [get_nets -quiet -hierarchical -filter [format {NAME == "%s"} $name]] "net $name"]
    if {[get_property NAME $net] ne $name} {error "Debug net lookup changed name: $name"}
    return $net
}
proc rk_ew_debug_object {kind name} {
    rk_ew_debug_literal $name
    if {$kind eq "core"} {
        set object [rk_ew_debug_one [get_debug_cores -quiet [list $name]] "debug core $name"]
    } elseif {$kind eq "port"} {
        set object [rk_ew_debug_one [get_debug_ports -quiet [list $name]] "debug port $name"]
    } else {error "Unknown debug object kind."}
    if {[get_property NAME $object] ne $name} {error "Debug object lookup changed name: $name"}
    return $object
}
proc rk_ew_debug_expect {object property expected} {
    set actual [get_property $property $object]
    if {$actual ne $expected} {error "Changed debug $property: expected $expected, got $actual"}
}
proc rk_ew_debug_clock {plan} {
    set name [dict get $plan clock name]
    set port_name [dict get $plan clock port]
    set anchor_name [dict get $plan clock anchor_pin]
    foreach object [list $name $port_name $anchor_name] {rk_ew_debug_literal $object}
    set clock [rk_ew_debug_one [get_clocks -quiet [list $name]] "clock $name"]
    set port [rk_ew_debug_one [get_ports -quiet [list $port_name]] "clock port $port_name"]
    set anchor [rk_ew_debug_one [get_pins -quiet -hierarchical -filter [format {NAME == "%s"} $anchor_name]] "clock anchor $anchor_name"]
    if {[get_property NAME $clock] ne $name || [get_property NAME $port] ne $port_name ||
        [get_property NAME $anchor] ne $anchor_name} {error "Ambiguous debug clock objects."}
    set period [get_property PERIOD $clock]
    if {![string is double -strict $period] || [catch {expr {abs(double($period)) < Inf}} finite] ||
        !$finite || $period != [dict get $plan clock period_ns]} {error "Changed debug clock period."}
    foreach object [list $port $anchor] {
        set associated [rk_ew_debug_one [get_clocks -quiet -of_objects $object] {debug clock association}]
        if {[get_property NAME $associated] ne $name} {error "Debug clock anchor/port is on another clock."}
    }
    # Derive the buffered clock from an existing state-register clock pin.
    # The top input port's net can be the pre-IBUF wire and must not be used.
    set net [rk_ew_debug_one [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $anchor] {buffered debug clock net}]
    set associated [rk_ew_debug_one [get_clocks -quiet -of_objects $net] {buffered debug clock association}]
    if {[get_property NAME $associated] ne $name} {error "Debug clock net is on another clock."}
    return $net
}
proc rk_ew_debug_plan_check {plan} {
    set profile [dict get $plan profile]
    if {$profile eq "ew-startup-ila"} {
        set top ypcb_ew_startup_top; set anchor {demo/core/state_reg[0]/C}
    } elseif {$profile eq "host-jtag-ew-ila"} {
        set top ypcb_jtag_ew_top; set anchor {endpoint/engine/state_reg[0]/C}
    } else {error "Unsupported optional EW ILA profile."}
    if {[dict get $plan schema] ne "1" ||
        [dict get $plan top] ne $top || [dict get $plan part] ne "xc7k480tffg1156-2" ||
        [dict get $plan clock name] ne "sys_clk" || [dict get $plan clock port] ne "SYS_CLK" ||
        [dict get $plan clock period_ns] != 20.0 || [dict get $plan clock frequency_hz] != 50000000 ||
        [dict get $plan clock anchor_pin] ne $anchor ||
        [dict get $plan core name] ne "u_rk_ew_ila" || [dict get $plan core depth] ne "1024" ||
        [dict get $plan core input_pipe_stages] ne "0" || [dict get $plan core jtag_user_chain] ne "1" ||
        [llength [dict get $plan synthesis_options]] != 4 ||
        [join [dict get $plan synthesis_options] " "] ne "-flatten_hierarchy none -fsm_extraction off"} {
        error "Unsupported optional EW ILA profile."
    }
    if {[get_property NAME [current_design]] ne [dict get $plan top] ||
        [get_property PART [current_design]] ne [dict get $plan part]} {error "Wrong design for EW ILA."}
    set names {}; set bits {}; set total 0
    foreach probe [dict get $plan probes] {
        set name [dict get $probe name]; set width [dict get $probe width]; set nets [dict get $probe nets]
        if {![regexp {^[a-z][a-z0-9_]*$} $name] || ![string is integer -strict $width] ||
            $width<1 || $width>64 || [llength $nets]!=$width || $name in $names} {error "Invalid debug probe shape."}
        lappend names $name
        foreach net $nets {
            rk_ew_debug_literal $net
            if {$net in $bits} {error "Duplicated debug probe bit: $net"}
            lappend bits $net
        }
        incr total $width
    }
    if {[llength $names]!=14 || $total!=204} {error "Changed EW debug probe inventory."}
}
proc rk_ew_debug_bscan {plan inserted} {
    set host [expr {[dict get $plan profile] eq "host-jtag-ew-ila"}]
    set cells [get_cells -quiet -hierarchical -filter {REF_NAME == BSCANE2}]
    if {[llength $cells] != $host+$inserted} {error "Conflicting debug/mailbox BSCAN inventory."}
    set user1 0; set user2 0
    foreach cell $cells {
        set name [get_property NAME $cell]; set chain [get_property JTAG_CHAIN $cell]
        if {$host && $name eq "u_bscan" && $chain == 2} {
            incr user2
        } elseif {$inserted && $name ne "u_bscan" && $chain == 1} {
            incr user1
        } else {error "Unexpected BSCAN ownership or USER scan chain: $name ($chain)"}
    }
    if {$user1 != $inserted || $user2 != $host} {error "Missing required USER1/USER2 BSCAN owner."}
}
proc rk_ew_debug_properties {plan} {
    set name [dict get $plan core name]
    set core [rk_ew_debug_object core $name]
    set hub [rk_ew_debug_object core dbg_hub]
    rk_ew_debug_expect $core C_DATA_DEPTH [dict get $plan core depth]
    rk_ew_debug_expect $core C_INPUT_PIPE_STAGES [dict get $plan core input_pipe_stages]
    rk_ew_debug_expect $hub C_USER_SCAN_CHAIN [dict get $plan core jtag_user_chain]
    rk_ew_debug_expect $hub C_CLK_INPUT_FREQ_HZ [dict get $plan clock frequency_hz]
    set divider [get_property C_ENABLE_CLK_DIVIDER $hub]
    if {![string is boolean -strict $divider] || $divider} {error "Debug hub clock divider changed."}
    foreach port [list $name/clk dbg_hub/clk] {
        rk_ew_debug_expect [rk_ew_debug_object port $port] PORT_WIDTH 1
    }
    set expected [list $name/clk]; set index 0
    foreach probe [dict get $plan probes] {
        set port $name/probe$index
        rk_ew_debug_expect [rk_ew_debug_object port $port] PORT_WIDTH [dict get $probe width]
        lappend expected $port; incr index
    }
    set actual [get_property NAME [get_debug_ports -quiet "$name/*"]]
    if {[lsort $actual] ne [lsort $expected]} {error "Unexpected ILA debug port inventory."}
    set cores [get_property NAME [get_debug_cores -quiet]]
    if {[lsort $cores] ne [lsort [list $name dbg_hub]]} {error "Unexpected debug core inventory."}
}
proc rk_ew_debug_insert {out plan} {
    rk_ew_debug_plan_check $plan
    if {[llength [get_debug_cores -quiet]]} {error "Preexisting debug core conflicts with the optional USER1 ILA."}
    rk_ew_debug_bscan $plan 0
    set clock_net [rk_ew_debug_clock $plan]
    set groups {}
    foreach probe [dict get $plan probes] {
        set nets {}
        foreach name [dict get $probe nets] {lappend nets [rk_ew_debug_net $name]}
        lappend groups $nets
    }
    # All source lookups succeed before any design mutation. Each bit is looked
    # up individually so bus ordering does not depend on wildcard query order.
    foreach nets $groups {set_property MARK_DEBUG true $nets}
    set name [dict get $plan core name]
    create_debug_core $name ila
    set core [rk_ew_debug_object core $name]
    foreach {property value} {C_TRIGIN_EN false C_TRIGOUT_EN false C_ADV_TRIGGER false
        C_EN_STRG_QUAL false ALL_PROBE_SAME_MU true ALL_PROBE_SAME_MU_CNT 1} {
        set_property $property $value $core
    }
    set_property C_DATA_DEPTH [dict get $plan core depth] $core
    set_property C_INPUT_PIPE_STAGES [dict get $plan core input_pipe_stages] $core
    set_property port_width 1 [rk_ew_debug_object port $name/clk]
    connect_debug_port $name/clk [list $clock_net]
    set index 0
    foreach probe [dict get $plan probes] nets $groups {
        if {$index>0} {create_debug_port $name probe}
        set port [rk_ew_debug_object port $name/probe$index]
        set_property port_width [dict get $probe width] $port
        connect_debug_port $name/probe$index $nets
        incr index
    }
    # create_debug_core adds dbg_hub automatically; opt_design implements both.
    set hub [rk_ew_debug_object core dbg_hub]
    set_property C_USER_SCAN_CHAIN [dict get $plan core jtag_user_chain] $hub
    set_property C_CLK_INPUT_FREQ_HZ [dict get $plan clock frequency_hz] $hub
    set_property C_ENABLE_CLK_DIVIDER false $hub
    connect_debug_port dbg_hub/clk [list $clock_net]
    rk_ew_debug_properties $plan
    set ::rk_ew_debug_inserted [dict create plan $plan clock_net [get_property NAME $clock_net]]
    file mkdir $out
    set channel [open [file join $out ila_connections_requested.tsv] w]
    puts $channel "SCOPE\tRequested connection order; physical channel mapping and acquisition remain unverified"
    puts $channel "CLOCK\t[get_property NAME $clock_net]\t[dict get $plan clock name]"
    set index 0
    foreach probe [dict get $plan probes] {
        set bit 0
        foreach net [dict get $probe nets] {
            puts $channel "PROBE\t$index\t[dict get $probe name]\t$bit\t$net"
            incr bit
        }
        incr index
    }
    close $channel
}
proc rk_ew_debug_audit {out plan} {
    rk_ew_debug_plan_check $plan
    if {![info exists ::rk_ew_debug_inserted] || [dict get $::rk_ew_debug_inserted plan] ne $plan} {
        error "Missing or changed EW debug insertion record."
    }
    set clock_net [rk_ew_debug_clock $plan]
    if {[get_property NAME $clock_net] ne [dict get $::rk_ew_debug_inserted clock_net]} {error "Debug clock net changed after insertion."}
    rk_ew_debug_properties $plan
    foreach probe [dict get $plan probes] {
        foreach name [dict get $probe nets] {
            set marked [get_property MARK_DEBUG [rk_ew_debug_net $name]]
            if {![string is boolean -strict $marked] || !$marked} {error "Debug mark lost for $name"}
        }
    }
    rk_ew_debug_bscan $plan 1
    set report [file join $out ila_debug_core.rpt]
    set probes [file join $out ew_ila.ltx]
    report_debug_core -full_path -file $report
    write_debug_probes $probes
    foreach artifact [list $report $probes] {
        if {![file isfile $artifact] || [file size $artifact]==0} {error "Missing debug report/probe artifact: $artifact"}
    }
    set channel [open [file join $out ila_objects_audit.tsv] w]
    puts $channel "STATUS\tDEBUG_OBJECT_CHECKS_COMPLETE_PHYSICAL_PROBE_REVIEW_REQUIRED"
    puts $channel "CORE\t[dict get $plan core name]\t[dict get $plan core depth]\t[dict get $plan core input_pipe_stages]"
    puts $channel "CLOCK\t[get_property NAME $clock_net]\t[dict get $plan clock frequency_hz]"
    puts $channel "HUB_SCAN_CHAIN\t[dict get $plan core jtag_user_chain]"
    puts $channel "LIMIT\tNo per-channel debug-port to net object relationship is assumed; inspect the real debug report and LTX mapping"
    if {[dict get $plan profile] eq "ew-startup-ila"} {
        puts $channel "LIMIT\tNo startup-arm workflow is performed; postprogram arming can observe only latched autonomous state"
    } else {
        puts $channel "LIMIT\tArm-before-SUBMIT acquisition is not performed; preserve exclusive cable ownership and shared TCK at or below6MHz"
    }
    close $channel
}
