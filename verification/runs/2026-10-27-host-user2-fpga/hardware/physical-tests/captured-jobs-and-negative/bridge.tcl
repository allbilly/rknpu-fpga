# SPDX-License-Identifier: Apache-2.0
# Numeric RPC pattern adapted from OpenTPU's native Vivado JTAG runner.
# Root owns a fresh audited source image, global cable lease and hw_server.
# This bridge never programs/erases flash or the FPGA, or resets fabric state.
set expected_target [encoding convertfrom utf-8 [binary format H* {6c6f63616c686f73743a333132352f78696c696e785f7463662f58696c696e782f3830383032303236613737613031}]]
set server_url [encoding convertfrom utf-8 [binary format H* {6c6f63616c686f73743a33313235}]]
set expected_access [encoding convertfrom utf-8 [binary format H* {3361306566373566}]]
set ready_path [encoding convertfrom utf-8 [binary format H* {2f686f6d652f6665646f72612f726b6e70752d667067612f6275696c642f667067612d6272696e6775702f686f73742d75736572322d336d687a2d3230323631303236543137323932315a2f706879736963616c2d74657374732f63617074757265642d6a6f62732d616e642d6e656761746976652f72656164792e747874}]]
set rpc_port 3741
set manager 0
set connected 0
set target_open 0
set raw 0
set selected 0
set owner ""
set listener ""
set done 0
proc native_hex {value bits} {
    if {![regexp {^[0-9a-fA-F]+$} $value] || [string length $value]>160} {error "Nonbinary native scan"}
    set number [expr "0x$value"]
    if {$number >= (1<<$bits)} {error "Native scan overflow"}
    set value [string tolower [string trimleft $value 0]]
    if {$value eq ""} {set value 0}
    return $value
}
proc native_drop {channel} {
    global owner selected
    catch {scan_ir_hw_jtag 6 -tdi 3f}
    set selected 63
    catch {close $channel}
    if {$owner eq $channel} {set owner ""}
}
proc native_request {channel} {
    global selected done
    if {[eof $channel]} {native_drop $channel;return}
    if {[gets $channel line]<0} {return}
    if {[string length $line]>1024} {native_drop $channel;return}
    set failed [catch {
        set fields [split $line]
        set result 0
        switch -- [lindex $fields 0] {
            RESET {
                if {[llength $fields]!=1} {error "Malformed TAP reset"}
                run_state_hw_jtag RESET
                run_state_hw_jtag IDLE
                set selected 0
            }
            SCAN {
                if {[llength $fields]!=4} {error "Malformed scan"}
                lassign $fields unused kind bits value
                if {![string is integer -strict $bits] || $bits ni {6 32 640} ||
                    ![regexp {^[0-9a-fA-F]{1,160}$} $value] || [expr "0x$value"] >= (1<<$bits)} {error "Invalid scan fields"}
                if {$kind eq "IR" && $bits==6 && [expr "0x$value"] in {3 9 63}} {
                    set result [native_hex [scan_ir_hw_jtag 6 -tdi $value] 6]
                    set selected [expr "0x$value"]
                } elseif {$kind eq "DR" && (($selected==9 && $bits==32) || ($selected==3 && $bits==640))} {
                    set result [native_hex [scan_dr_hw_jtag $bits -tdi $value] $bits]
                } else {error "Instruction or DR width outside audited interface"}
            }
            QUIT {
                if {[llength $fields]!=1} {error "Malformed bridge exit"}
                after 0 {set ::done 1}
            }
            default {error "Unknown numeric command"}
        }
    } problem]
    if {$failed} {puts $channel "ERR"} else {puts $channel "OK $result"}
    flush $channel
    if {$failed} {native_drop $channel}
}
proc native_accept {channel address port} {
    global owner
    fconfigure $channel -blocking 0 -buffering line -translation lf
    if {$owner ne ""} {puts $channel BUSY;flush $channel;close $channel;return}
    set owner $channel
    puts $channel "READY 3000000"
    flush $channel
    fileevent $channel readable [list native_request $channel]
}
set failed [catch {
    open_hw_manager
    set manager 1
    connect_hw_server -url $server_url
    set connected 1
    set targets [get_hw_targets]
    if {[llength $targets]!=1 || [lindex $targets 0] ne $expected_target} {error "Wrong exact audited cable"}
    current_hw_target [lindex $targets 0]
    set_property PARAM.FREQUENCY 3000000 [current_hw_target]
    open_hw_target
    set target_open 1
    if {[get_property PARAM.FREQUENCY [current_hw_target]]!=3000000} {error "Wrong reported native TCK"}
    set devices [get_hw_devices]
    if {[llength $devices]!=1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {error "Wrong target count/family"}
    set device [lindex $devices 0]
    refresh_hw_device $device
    if {![string equal -nocase [get_property REGISTER.EFUSE.DNA_PORT $device] 004E544714C705C]} {error "Wrong current target DNA"}
    if {[get_property REGISTER.IR.BIT4_INIT_COMPLETE $device] ne "1" || [get_property REGISTER.IR.BIT5_DONE $device] ne "1"} {error "Target not configured"}
    set access [get_property REGISTER.USR_ACCESS $device]
    if {![regexp {^[0-9a-fA-F]{1,8}$} $access] || [expr "0x$access"] != [expr "0x$expected_access"]} {error "Wrong loaded source image"}
    close_hw_target
    set target_open 0
    open_hw_target -jtag_mode 1
    set target_open 1
    set raw 1
    run_state_hw_jtag RESET
    run_state_hw_jtag IDLE
    scan_ir_hw_jtag 6 -tdi 09
    set ident [native_hex [scan_dr_hw_jtag 32 -tdi 0] 32]
    if {$ident ne "23751093"} {error "Wrong raw TAP identity"}
    scan_ir_hw_jtag 6 -tdi 03
    set selected 3
    set reply [expr "0x[native_hex [scan_dr_hw_jtag 640 -tdi 0] 640]"]
    if {(($reply>>536)&0xffffffff)!=0x4f54504a || ($reply>>568)!=0} {error "Wrong USER2 mailbox"}
    set listener [socket -server native_accept -myaddr 127.0.0.1 $rpc_port]
    set f [open $ready_path {WRONLY CREAT EXCL}];puts $f "PASS_AUDITED_NATIVE_USER2_BRIDGE_READY";close $f
    vwait done
} problem]
set cleanup_failed 0
if {$owner ne ""} {native_drop $owner}
if {$listener ne "" && [catch {close $listener}]} {set cleanup_failed 1}
if {$raw && $target_open && [catch {scan_ir_hw_jtag 6 -tdi 3f}]} {set cleanup_failed 1}
if {$target_open && [catch {close_hw_target}]} {set cleanup_failed 1}
if {$connected && [catch {disconnect_hw_server}]} {set cleanup_failed 1}
if {$manager && [catch {close_hw_manager}]} {set cleanup_failed 1}
if {$failed || $cleanup_failed} {error "Native bridge failed: $problem; cleanup=$cleanup_failed"}
puts "PASS_NATIVE_USER2_BRIDGE_CLEAN_EXIT"
exit
