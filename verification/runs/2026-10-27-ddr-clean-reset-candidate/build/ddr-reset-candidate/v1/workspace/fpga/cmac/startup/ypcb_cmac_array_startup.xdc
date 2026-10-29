# Separate full C32/K16 startup profile using the existing 50 MHz board clock.
# Clock/LED pins match the EW startup profile; no external reset is consumed.
# Configuration-bank voltage/CFGBVS and actual board facts still need review.
set_property PACKAGE_PIN AA28 [get_ports SYS_CLK]
set_property PACKAGE_PIN P30 [get_ports {led_3bits_tri_o[0]}]
set_property PACKAGE_PIN M30 [get_ports {led_3bits_tri_o[1]}]
set_property PACKAGE_PIN N30 [get_ports {led_3bits_tri_o[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {SYS_CLK led_3bits_tri_o[*]}]
create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]
# LEDs have no external synchronous receiver; all internal logic stays timed.
set_false_path -to [get_ports {led_3bits_tri_o[*]}]
