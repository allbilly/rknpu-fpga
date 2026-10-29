# Volatile SRAM only. Do not erase or write flash.
# Exact full512 CH1 image review and separate root approval are required.
set expected_target {localhost:3125/xilinx_tcf/Xilinx/80802026a77a01}
set bitstream {/home/fedora/rknpu-fpga/build/full512-capacity-retire-image-prep-v2/emission/full512-ddr-ch1-user2.bit}
set receipt {/home/fedora/rknpu-fpga/build/fpga-bringup/full512-capacity-retire-prep-v2/physical-test/load-2/program.tsv}
set expected_access {2c8f17dd}
set expected_bit_sha {de982cd7e6c41d13de8e1f047c92fd515ab590e6958339a1dd37135642bef2a4}
set expected_dna 004E544714C705C
set out [open $receipt {WRONLY CREAT EXCL}]
fconfigure $out -translation lf -buffering line
set manager_open 0
set connected 0
set target_open 0
set raw_mode 0
set programmed 0
proc host_idcode {} {
    run_state_hw_jtag RESET
    run_state_hw_jtag IDLE
    scan_ir_hw_jtag 6 -tdi 09
    set value [scan_dr_hw_jtag 32 -tdi 0]
    if {![regexp {^[0-9a-fA-F]{1,8}$} $value] || [expr "0x$value"] != 0x23751093} {
        error "Unexpected exact raw IDCODE"
    }
    scan_ir_hw_jtag 6 -tdi 3f
    run_state_hw_jtag IDLE
    return [format %08x [expr "0x$value"]]
}
proc verify_program_file {path expected} {
    if {![file isfile $path]} {error "Reviewed bitstream is missing"}
    set actual [lindex [exec sha256sum -- $path] 0]
    if {![string equal $actual $expected]} {error "Reviewed bitstream SHA256 mismatch"}
}
set failed [catch {
    verify_program_file $bitstream $expected_bit_sha
    puts $out "BITSTREAM_SHA256\t$expected_bit_sha"
    open_hw_manager
    set manager_open 1
    connect_hw_server -url localhost:3125
    set connected 1
    set targets [get_hw_targets]
    if {[llength $targets]!=1 || [lindex $targets 0] ne $expected_target} {error "Wrong audited cable"}
    current_hw_target [lindex $targets 0]
    set_property PARAM.FREQUENCY 3000000 [current_hw_target]
    open_hw_target
    set target_open 1
    if {[get_property PARAM.FREQUENCY [current_hw_target]] != 3000000} {error "Wrong TCK"}
    set devices [get_hw_devices]
    if {[llength $devices]!=1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {error "Wrong device family/count"}
    set dev [lindex $devices 0]
    refresh_hw_device $dev
    set dna [get_property REGISTER.EFUSE.DNA_PORT $dev]
    if {![string equal -nocase $dna $expected_dna]} {error "Wrong current target DNA"}
    puts $out "TARGET\t$expected_target"
    puts $out "DNA_PORT\t$dna"
    puts $out "TCK_HZ\t3000000"
    close_hw_target
    set target_open 0
    open_hw_target -jtag_mode 1
    set target_open 1
    set raw_mode 1
    puts $out "IDCODE_BEFORE\t[host_idcode]"
    close_hw_target
    set target_open 0
    set raw_mode 0
    open_hw_target
    set target_open 1
    set devices [get_hw_devices]
    if {[llength $devices]!=1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {error "Changed target before load"}
    set dev [lindex $devices 0]
    refresh_hw_device $dev
    if {![string equal -nocase [get_property REGISTER.EFUSE.DNA_PORT $dev] $expected_dna]} {error "Changed DNA before load"}
    verify_program_file $bitstream $expected_bit_sha
    # This is the first PROGRAM.FILE assignment and is reachable only after both
    # image review and root execution approval have been verified by the Python gate.
    set_property PROGRAM.FILE $bitstream $dev
    puts $out "PROGRAM_FILE\t$bitstream"
    flush $out
    program_hw_devices $dev
    set programmed 1
    puts $out "PROGRAM_RETURNED\t1"
    refresh_hw_device $dev
    set init [get_property REGISTER.IR.BIT4_INIT_COMPLETE $dev]
    set done [get_property REGISTER.IR.BIT5_DONE $dev]
    set access [get_property REGISTER.USR_ACCESS $dev]
    puts $out "INIT_COMPLETE\t$init"
    puts $out "DONE\t$done"
    puts $out "USR_ACCESS\t$access"
    if {$init ne "1" || $done ne "1"} {error "Configuration INIT/DONE failed"}
    if {![regexp {^[0-9a-fA-F]{1,8}$} $access] || [expr "0x$access"] != [expr "0x$expected_access"]} {error "Wrong source-derived USR_ACCESS tag"}
    close_hw_target
    set target_open 0
    open_hw_target -jtag_mode 1
    set target_open 1
    set raw_mode 1
    puts $out "IDCODE_AFTER\t[host_idcode]"
} problem]
if {$failed} {puts $out "ERROR_HEX\t[binary encode hex [encoding convertto utf-8 $problem]]"}
set cleanup_failed 0
if {$target_open && $raw_mode} {
    if {[catch {scan_ir_hw_jtag 6 -tdi 3f}]} {set cleanup_failed 1}
}
if {$target_open && [catch {close_hw_target}]} {set cleanup_failed 1}
if {$connected && [catch {disconnect_hw_server}]} {set cleanup_failed 1}
if {$manager_open && [catch {close_hw_manager}]} {set cleanup_failed 1}
puts $out "PROGRAMMED\t$programmed"
puts $out "CLEANUP\t[expr {!$cleanup_failed}]"
puts $out "PASS\t[expr {!$failed && !$cleanup_failed}]"
close $out
if {$failed || $cleanup_failed} {error "Volatile SRAM load failed; preserve receipts"}
puts "PASS_FULL512_DUAL_DDR_VOLATILE_SRAM_LOAD"
exit
