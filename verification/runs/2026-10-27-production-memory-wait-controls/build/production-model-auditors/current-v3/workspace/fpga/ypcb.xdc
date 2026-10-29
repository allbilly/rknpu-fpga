# Board facts from TiferKing/ypcb_00338_1p1_hack constraints/ypcb003381p1.xdc
# and ypcb003381p1/1.0/board.xml, inspected 2026-09-20.
# Confirm board revision, oscillator and I/O supply before building/programming.
# These are ONLY the clock/reset/LED pins; this design does not use PCIe or DDR.
set_property PACKAGE_PIN AA28 [get_ports SYS_CLK]
set_property PACKAGE_PIN R28 [get_ports SYS_RSTN]
set_property PACKAGE_PIN P30 [get_ports {led_3bits_tri_o[0]}]
set_property PACKAGE_PIN M30 [get_ports {led_3bits_tri_o[1]}]
set_property PACKAGE_PIN N30 [get_ports {led_3bits_tri_o[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {SYS_CLK SYS_RSTN led_3bits_tri_o[*]}]
create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]
# External asynchronous reset only feeds the dedicated reset synchronizer.
set_false_path -from [get_ports SYS_RSTN]
# LEDs have no external synchronous timing requirement. Internal logic is timed.
set_false_path -to [get_ports {led_3bits_tri_o[*]}]
