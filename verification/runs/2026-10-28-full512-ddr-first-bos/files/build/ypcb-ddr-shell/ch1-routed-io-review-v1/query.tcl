# Read-only routed checkpoint scalar top-level I/O audit. No DCP/constraint writes.
set dcp [file normalize [lindex $argv 0]]
set facts [file normalize [lindex $argv 1]]
set props [file normalize [lindex $argv 2]]
set ioreport [file normalize [lindex $argv 3]]
set f [open $facts w]
proc emit {f fields} {
  set out {}
  foreach value $fields {set value [string map [list "\t" {\\t} "\n" {\\n} "\r" {\\r}] $value]; lappend out $value}
  puts $f [join $out "\t"]; flush $f
}
proc prop {obj key} {
  if {[catch {get_property $key $obj} value]} {return "<UNAVAILABLE:$key>"}
  return $value
}
set_param general.maxThreads 1
open_checkpoint $dcp
set design [current_design]
emit $f [list DESIGN [get_property NAME $design] [get_property PART $design] CONFIG_VOLTAGE [prop $design CONFIG_VOLTAGE] CFGBVS [prop $design CFGBVS]]
report_property -all -file $props $design
set ports [lsort -dictionary [get_ports -quiet]]
emit $f [list PORT_COUNT [llength $ports]]
set first 0
set index 0
foreach port $ports {
  set name [get_property NAME $port]
  set package_pin [prop $port PACKAGE_PIN]
  set bank [prop $port BANK]
  set pkgobjs {}
  if {$package_pin ne "" && ![string match {<UNAVAILABLE:*} $package_pin]} {set pkgobjs [get_package_pins -quiet [list $package_pin]]}
  if {$bank eq "" && [llength $pkgobjs]==1} {set bank [prop [lindex $pkgobjs 0] BANK]}
  emit $f [list PORT $index $name [prop $port DIRECTION] $package_pin $bank [prop $port IOSTANDARD] \
      [prop $port SLEW] [prop $port DRIVE] [prop $port PULLTYPE] [prop $port DIFF_TERM] [prop $port IN_TERM]]
  report_property -all -append -file $props $port
  if {[llength $pkgobjs]==1} {
    set pkg [lindex $pkgobjs 0]
    emit $f [list PACKAGE_PIN $name $package_pin [prop $pkg BANK] [prop $pkg PIN_FUNC] [prop $pkg IS_BONDED]]
  } else {
    emit $f [list PACKAGE_PIN_OBJECTS $name $package_pin [llength $pkgobjs]]
  }
  incr index
}
set clocks [lsort -dictionary [get_clocks -quiet]]
emit $f [list CLOCK_COUNT [llength $clocks]]
foreach clock $clocks {
  set master "<NOT_LISTED>"
  set supported_props [list_property $clock]
  if {[lsearch -exact $supported_props MASTER_CLOCK]>=0} {set master [prop $clock MASTER_CLOCK]}
  emit $f [list CLOCK [prop $clock NAME] [prop $clock PERIOD] [prop $clock WAVEFORM] \
      [prop $clock IS_GENERATED] [prop $clock SOURCE_PINS] $master]
}
# Record logical reset-owner UI domains against the corresponding physical MIG UI pin.
set endpoint platform/endpoint
foreach domain {0 1} {
  set local_name [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint $domain]
  set local_cell [lindex [get_cells -quiet [list $local_name]] 0]
  if {[llength [get_cells -quiet [list $local_name]]]!=1} {error "Expected exact UI reset owner register $local_name"}
  set reg_pin [lindex [get_pins -quiet [list $local_name/C]] 0]
  set reg_clock [lindex [get_clocks -quiet -of_objects $reg_pin] 0]
  if {[llength [get_clocks -quiet -of_objects $reg_pin]]!=1} {error "Expected one register clock on $local_name/C"}
  set mig_pin_name [expr {$domain==0 ? "platform/mig/c1_ui_clk" : "platform/mig/c0_ui_clk"}]
  set mig_pin [lindex [get_pins -quiet [list $mig_pin_name]] 0]
  if {[llength [get_pins -quiet [list $mig_pin_name]]]!=1} {error "Expected exact physical MIG UI pin $mig_pin_name"}
  set mig_clock [lindex [get_clocks -quiet -of_objects $mig_pin] 0]
  if {[llength [get_clocks -quiet -of_objects $mig_pin]]!=1} {error "Expected one clock on physical MIG UI pin $mig_pin_name"}
  set logical_name [expr {$domain==0 ? "UI0" : "UI1"}]
  set same_clock [expr {$reg_clock eq $mig_clock}]
  emit $f [list UI_CLOCK_BINDING $logical_name $local_name/C [prop $reg_clock NAME] [prop $reg_clock PERIOD] $mig_pin_name [prop $mig_clock NAME] [prop $mig_clock PERIOD] $same_clock]
}
report_io -file $ioreport
close $f
close_design
puts "COMPLETED_READONLY_ROUTED_IO_AUDIT"
exit 0
