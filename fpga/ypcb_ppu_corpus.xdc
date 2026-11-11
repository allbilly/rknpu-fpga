# SPDX-License-Identifier: MIT
# Pin budget for the pin-free pooling-corpus image. Only the audited board
# pins appear:
# the 50 MHz oscillator and the three LEDs. The JTAG port is a dedicated
# configuration interface (BSCANE2), not package I/O, so it needs no LOC.
#
# The bare-AXI corpus top could not become a bitstream because its 32-bit AXI
# slave was a top-level port with no pins (NSTD-1 + UCIO-1). Wrapping it behind
# the USER2 mailbox removes that port entirely; there is no invented pin.
set_property PACKAGE_PIN AA28 [get_ports SYS_CLK]
set_property PACKAGE_PIN P30 [get_ports {led_3bits_tri_o[0]}]
set_property PACKAGE_PIN M30 [get_ports {led_3bits_tri_o[1]}]
set_property PACKAGE_PIN N30 [get_ports {led_3bits_tri_o[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {SYS_CLK led_3bits_tri_o[*]}]
create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]
# LEDs have no external synchronous receiver; all internal paths stay timed.
set_false_path -to [get_ports {led_3bits_tri_o[*]}]
# The mailbox CDC constraints (USER2 TCK clock, held/response payload bounds,
# synchronizer cells) are applied after synthesis by the rendered Tcl, exactly
# as the adopted six-page USER2 image does.
