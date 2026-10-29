# Generated from the immutable 10-source manifest. Root review required before launch.
set_param general.maxThreads 2
set outdir [lindex $argv 0]
if {$outdir eq "" || ![file isdirectory $outdir]} { error "Fresh OOC output directory required" }
set srcs [list \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/00-rk_ddr_capacity_service.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/01-rk_ddr_capacity_owner.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/02-rk_ddr_capacity_regs.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/03-rk_ddr_diagnostic_mux.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/04-rk_ddr_capacity_bist.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/05-rk_ddr_capacity_axi.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/06-rk_ddr_capacity_sweep.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/07-rk_ddr_capacity_pattern.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/08-rk_mig_write_fence.sv} \
    {/home/fedora/rknpu-fpga/build/ddr-capacity-service-vivado-ooc-v2/source/09-rk_mig_ecc_monitor.sv}
]
read_verilog -sv {*}$srcs
synth_design -top rk_ddr_capacity_service -part xc7k480tffg1156-2 -mode out_of_context
report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization-hierarchical.rpt]
puts "PASS_DDR_CAPACITY_SERVICE_OOC_SYNTH_ONLY"
