# Separate raw-command EW BRAM profile, using the existing 50 MHz board clock.
# Board clock/LED pins match ypcb.xdc. No R28 input or reset exception exists.
# Configuration-bank voltage/CFGBVS and actual board facts still need review.
set_property PACKAGE_PIN AA28 [get_ports SYS_CLK]
set_property PACKAGE_PIN P30 [get_ports {led_3bits_tri_o[0]}]
set_property PACKAGE_PIN M30 [get_ports {led_3bits_tri_o[1]}]
set_property PACKAGE_PIN N30 [get_ports {led_3bits_tri_o[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {SYS_CLK led_3bits_tri_o[*]}]
create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]
# LEDs have no external synchronous interface; all internal logic stays timed.
set_false_path -to [get_ports {led_3bits_tri_o[*]}]
