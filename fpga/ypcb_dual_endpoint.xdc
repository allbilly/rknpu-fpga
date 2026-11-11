# SPDX-License-Identifier: MIT
# Same audited 50 MHz clock and LED pins as the other board images.
# This image self-resets; it consumes no external reset input.
set_property PACKAGE_PIN AA28 [get_ports SYS_CLK]
set_property PACKAGE_PIN P30 [get_ports {led_3bits_tri_o[0]}]
set_property PACKAGE_PIN M30 [get_ports {led_3bits_tri_o[1]}]
set_property PACKAGE_PIN N30 [get_ports {led_3bits_tri_o[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {SYS_CLK led_3bits_tri_o[*]}]
create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]
# The AXI4-Lite slave is a top-level port here and has no board pins, so this
# profile cannot reach a bitstream (NSTD-1/UCIO-1). Use the pin-free successor,
# fpga/jtag_dual.xdc + ypcb_jtag_dual_top (see docs/JTAG_DUAL_IMAGE.md), for any
# image that is actually built.
set_false_path -to [get_ports {led_3bits_tri_o[*]}]
