# Capability initialization only. No server connection or target operation.
set receipt [open capabilities.tsv {WRONLY CREAT EXCL}]
puts $receipt "VERSION_SHORT\t[version -short]"
set full [open version.txt {WRONLY CREAT EXCL}]
puts $full [version]
close $full
open_hw_manager
foreach command {connect_hw_server disconnect_hw_server get_hw_targets open_hw_target close_hw_target get_hw_devices refresh_hw_device program_hw_devices scan_ir_hw_jtag scan_dr_hw_jtag run_state_hw_jtag} {
    if {[llength [info commands $command]] != 1} {error "Required native capability missing"}
    puts $receipt "COMMAND\t$command"
}
close_hw_manager
puts $receipt "SERVER_CONNECTED\t0"
puts $receipt "TARGET_OPENED\t0"
puts $receipt "HARDWARE_ACCESSED\t0"
puts $receipt "PASS\t1"
close $receipt
puts PASS_LAB_SOFTWARE_CAPABILITIES_ONLY
exit
