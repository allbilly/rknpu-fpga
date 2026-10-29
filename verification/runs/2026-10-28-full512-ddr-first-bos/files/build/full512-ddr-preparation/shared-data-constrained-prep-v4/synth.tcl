# Root-reviewed preparation draft. This Tcl is hard-gated before project creation.
if {![info exists ::env(RK_SHARED_DATA_CONSTRAINED_ROOT_REVIEW)] || $::env(RK_SHARED_DATA_CONSTRAINED_ROOT_REVIEW) ne "APPROVED"} {error "Root review required before fresh source synthesis"}
set_param general.maxThreads 2
set pkg [file normalize [file dirname [info script]]]
set src [file join $pkg source]
set out [pwd]
proc ch1_require {condition message} {if {!$condition} {error $message}}
proc ch1_one {objects message} {ch1_require [expr {[llength $objects]==1}] "Expected exactly one $message"; return [lindex $objects 0]}
proc ch1_emit {f row} {puts $f [join $row "\t"]; flush $f}
puts "SHARED_DATA_CONSTRAINED_NATIVE_TOOL [version -short]"
create_project -in_memory -part xc7k480tffg1156-2
set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]
read_verilog -sv [list \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/000/mig_7series_v4_2_axi_ctrl_addr_decode.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/001/mig_7series_v4_2_axi_ctrl_read.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/002/mig_7series_v4_2_axi_ctrl_reg_bank.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/003/mig_7series_v4_2_axi_ctrl_reg.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/004/mig_7series_v4_2_axi_ctrl_top.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/005/mig_7series_v4_2_axi_ctrl_write.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/006/mig_7series_v4_2_axi_mc.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/007/mig_7series_v4_2_axi_mc_ar_channel.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/008/mig_7series_v4_2_axi_mc_aw_channel.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/009/mig_7series_v4_2_axi_mc_b_channel.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/010/mig_7series_v4_2_axi_mc_cmd_arbiter.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/011/mig_7series_v4_2_axi_mc_cmd_fsm.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/012/mig_7series_v4_2_axi_mc_wr_cmd_fsm.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/013/mig_7series_v4_2_axi_mc_cmd_translator.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/014/mig_7series_v4_2_axi_mc_incr_cmd.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/015/mig_7series_v4_2_axi_mc_r_channel.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/016/mig_7series_v4_2_axi_mc_simple_fifo.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/017/mig_7series_v4_2_axi_mc_fifo.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/018/mig_7series_v4_2_axi_mc_w_channel.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/019/mig_7series_v4_2_axi_mc_wrap_cmd.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/020/mig_7series_v4_2_ddr_a_upsizer.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/021/mig_7series_v4_2_ddr_axi_register_slice.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/022/mig_7series_v4_2_ddr_axi_upsizer.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/023/mig_7series_v4_2_ddr_axic_register_slice.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/024/mig_7series_v4_2_ddr_carry_and.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/025/mig_7series_v4_2_ddr_carry_latch_and.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/026/mig_7series_v4_2_ddr_carry_latch_or.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/027/mig_7series_v4_2_ddr_carry_or.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/028/mig_7series_v4_2_ddr_command_fifo.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/029/mig_7series_v4_2_ddr_comparator.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/030/mig_7series_v4_2_ddr_comparator_sel.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/031/mig_7series_v4_2_ddr_comparator_sel_static.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/032/mig_7series_v4_2_ddr_r_upsizer.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/033/mig_7series_v4_2_ddr_w_upsizer.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/034/mig_7series_v4_2_clk_ibuf.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/035/mig_7series_v4_2_infrastructure.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/036/mig_7series_v4_2_iodelay_ctrl.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/037/mig_7series_v4_2_tempmon.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/038/mig_7series_v4_2_arb_mux.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/039/mig_7series_v4_2_arb_row_col.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/040/mig_7series_v4_2_arb_select.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/041/mig_7series_v4_2_bank_cntrl.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/042/mig_7series_v4_2_bank_common.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/043/mig_7series_v4_2_bank_compare.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/044/mig_7series_v4_2_bank_mach.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/045/mig_7series_v4_2_bank_queue.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/046/mig_7series_v4_2_bank_state.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/047/mig_7series_v4_2_col_mach.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/048/mig_7series_v4_2_mc.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/049/mig_7series_v4_2_rank_cntrl.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/050/mig_7series_v4_2_rank_common.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/051/mig_7series_v4_2_rank_mach.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/052/mig_7series_v4_2_ecc_buf.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/053/mig_7series_v4_2_ecc_dec_fix.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/054/mig_7series_v4_2_ecc_gen.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/055/mig_7series_v4_2_ecc_merge_enc.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/056/mig_7series_v4_2_fi_xor.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/057/mig_7series_v4_2_mem_intfc.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/058/mig_7series_v4_2_memc_ui_top_axi.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/059/mig_7series_v4_2_ddr_byte_group_io.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/060/mig_7series_v4_2_ddr_byte_lane.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/061/mig_7series_v4_2_ddr_phy_tempmon.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/062/mig_7series_v4_2_ddr_calib_top.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/063/mig_7series_v4_2_ddr_skip_calib_tap.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/064/mig_7series_v4_2_ddr_if_post_fifo.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/065/mig_7series_v4_2_ddr_mc_phy.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/066/mig_7series_v4_2_ddr_mc_phy_wrapper.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/067/mig_7series_v4_2_ddr_of_pre_fifo.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/068/mig_7series_v4_2_ddr_phy_4lanes.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/069/mig_7series_v4_2_ddr_phy_ck_addr_cmd_delay.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/070/mig_7series_v4_2_ddr_phy_init.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/071/mig_7series_v4_2_ddr_phy_dqs_found_cal.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/072/mig_7series_v4_2_ddr_phy_dqs_found_cal_hr.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/073/mig_7series_v4_2_ddr_phy_oclkdelay_cal.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/074/mig_7series_v4_2_ddr_phy_prbs_rdlvl.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/075/mig_7series_v4_2_ddr_phy_rdlvl.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/076/mig_7series_v4_2_ddr_phy_top.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/077/mig_7series_v4_2_ddr_phy_wrcal.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/078/mig_7series_v4_2_ddr_phy_wrlvl.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/079/mig_7series_v4_2_ddr_phy_wrlvl_off_delay.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/080/mig_7series_v4_2_ddr_prbs_gen.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/081/mig_7series_v4_2_ddr_phy_ocd_lim.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/082/mig_7series_v4_2_poc_top.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/083/mig_7series_v4_2_ddr_phy_ocd_mux.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/084/mig_7series_v4_2_ddr_phy_ocd_data.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/085/mig_7series_v4_2_ddr_phy_ocd_samp.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/086/mig_7series_v4_2_ddr_phy_ocd_edge.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/087/mig_7series_v4_2_ddr_phy_ocd_cntlr.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/088/mig_7series_v4_2_ddr_phy_ocd_po_cntlr.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/089/mig_7series_v4_2_poc_pd.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/090/mig_7series_v4_2_poc_tap_base.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/091/mig_7series_v4_2_poc_meta.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/092/mig_7series_v4_2_poc_edge_store.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/093/mig_7series_v4_2_poc_cc.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/094/mig_7series_v4_2_ui_cmd.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/095/mig_7series_v4_2_ui_rd_data.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/096/mig_7series_v4_2_ui_top.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/097/mig_7series_v4_2_ui_wr_data.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/098/top_mig_7series_0_0.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/099/top_mig_7series_0_0_mig.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/100/mig_7series_v4_2_round_robin_arb.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/101/rk_fp16_alu.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/102/rk_ew_regs.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/103/rk_ew_engine.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/104/rk_ew_core.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/105/rk_ew_dma.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/106/rk_axi_mem.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/107/rk_job_control.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/108/rk_jtag_backend.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/109/rk_mig_reset_coordinator.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/110/rk_mig_ecc_monitor.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/111/rk_mig_write_fence.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/112/rk_ddr_memory_fabric_snapshot.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/113/rk_async_job_port.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/114/rk_async_mem_port.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/115/rk_ew_async_engine.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/116/rk_axi_mem_read_snapshot.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/117/platform.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/118/rk_startup_reset.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/119/otpu_jtag_mailbox.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/120/top.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/121/NV_DW02_tree.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/122/NV_DW_lsd.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/123/NV_NVDLA_CMAC_CORE_MAC_mul.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/124/NV_NVDLA_CACC_CALC_fp_48b.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/125/HLS_fp32_to_fp16.v} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/126/rk_cmac_profile.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/127/rk_cmac_fp16_rows.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/128/rk_cmac_fp16_discarded_carry.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/129/rk_cmac_fp16_lane_dsp_prefix.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/130/rk_cmac_fp16_cell_dsp_prefix.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/131/rk_cmac_fp16_array_dsp_prefix.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/132/rk_nvdla_cacc.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/133/rk_cacc_fp16_array.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/134/rk_cmac_cacc_fp16_array.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/135/rk_nvdla_fp32_to_fp16.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/136/rk_cmac_writer.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/137/rk_cmac_output_nvdla.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/138/rk_cmac_frame_output.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/139/rk_cmac_array_datapath.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/140/rk_cmac_array_front.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/141/rk_cmac_rw_arbiter.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/142/rk_cmac_array_core.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/143/rk_cmac_array_dma.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/144/rk_cmac_fp16_cell_dsp_prefix_pipe.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/145/rk_cmac_fp16_array_dsp_prefix_pipe.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/146/rk_cmac_success_rearm.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/147/rk_cmac_async_engine.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/148/rk_dual_async_dispatch.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/149/rk_dual_job_control.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/150/rk_jtag_dual_ddr_async.sv} \
    {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/151/rk_cmac_fp16_shared_data.sv}]
read_xdc {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/mig-original.xdc}
read_xdc {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/board.xdc}
synth_design -top ypcb_ddr_dual_top -part xc7k480tffg1156-2 -flatten_hierarchy none
puts SHARED_DATA_CONSTRAINED_FRESH_SYNTHESIS_COMPLETED
set_property CONFIG_VOLTAGE 1.8 [current_design]
set_property CFGBVS GND [current_design]
ch1_require [expr {[get_property TOP [current_design]] eq "ypcb_ddr_dual_top" && [get_property PART [current_design]] eq "xc7k480tffg1156-2"}] "Wrong synthesized top or part"
ch1_require [expr {[get_property CONFIG_VOLTAGE [current_design]] == 1.8 && [get_property CFGBVS [current_design]] eq "GND"}] "Changed configuration voltage or CFGBVS"
ch1_require [expr {[llength [get_cells -quiet -hierarchical -filter {IS_BLACKBOX == 1}]]==0}] "Unresolved source black box"
source {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/constraint-helpers/status_cdc.tcl}
source {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/constraint-helpers/job_cdc.tcl}
source {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/constraint-helpers/permit_cdc.tcl}
source {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/constraint-helpers/memory_crossing.tcl}
source {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/constraint-helpers/mailbox_ui.tcl}
source {/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/constraint-helpers/board_reset.tcl}
set endpoint_cells [get_cells -quiet -hierarchical -filter {REF_NAME == rk_jtag_dual_ddr_async}]
set endpoint_cell [ch1_one $endpoint_cells {dual DDR asynchronous endpoint}]
ch1_require [expr {[get_property REF_NAME $endpoint_cell] eq "rk_jtag_dual_ddr_async"}] "Wrong mapped endpoint module"
set endpoint [get_property NAME $endpoint_cell]
set owner [ch1_one [get_cells -quiet [list ${endpoint}/reset_owner]] {MIG reset owner}]
ch1_require [expr {[get_property REF_NAME $owner] eq "rk_mig_reset_coordinator"}] "Wrong mapped MIG reset owner"
set sys_clock [rk_status_clock sys_clock 20.000]
set local0 [rk_status_cell [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint 0]]
set local1 [rk_status_cell [format {%s/reset_owner/ui_domain[%d].local_rst_n_reg} $endpoint 1]]
set ui0_register_clock [ch1_one [get_clocks -quiet -of_objects [get_pins $local0/C]] {mapped logical UI0 clock}]
set ui1_register_clock [ch1_one [get_clocks -quiet -of_objects [get_pins $local1/C]] {mapped logical UI1 clock}]
set mig_cells [get_cells -quiet -hierarchical -filter {REF_NAME == top_mig_7series_0_0}]
set mig_cell [ch1_one $mig_cells {MIG dual-controller wrapper}]
set mig_name [get_property NAME $mig_cell]
set mig_c0_pin [ch1_one [get_pins -quiet [list ${mig_name}/c0_ui_clk]] {actual MIG C0 UI output pin}]
set mig_c1_pin [ch1_one [get_pins -quiet [list ${mig_name}/c1_ui_clk]] {actual MIG C1 UI output pin}]
set physical_c0_clock [ch1_one [get_clocks -quiet -of_objects $mig_c0_pin] {clock on actual MIG C0 UI output}]
set physical_c1_clock [ch1_one [get_clocks -quiet -of_objects $mig_c1_pin] {clock on actual MIG C1 UI output}]
ch1_require [expr {$ui0_register_clock eq $physical_c1_clock}] "Logical UI0 is not mapped to the actual physical C1 UI clock"
ch1_require [expr {$ui1_register_clock eq $physical_c0_clock}] "Logical UI1 is not mapped to the actual physical C0 UI clock"
set ui0_clock [rk_status_clock [get_property NAME $ui0_register_clock] 7.500]
set ui1_clock [rk_status_clock [get_property NAME $ui1_register_clock] 7.500]
set startup_cells [get_cells -quiet -hierarchical -filter {REF_NAME == rk_startup_reset}]
set startup_cell [ch1_one $startup_cells {mapped startup reset producer}]
set startup [get_property NAME $startup_cell]
set cfg_pin [rk_status_pin $endpoint/cfg_reset]
set cfg_segments [get_nets -quiet -segments -of_objects $cfg_pin]
ch1_require [expr {[llength $cfg_segments]>0}] "Missing endpoint cfg_reset segments"
set cfg_driver_pins [get_pins -quiet -leaf -of_objects $cfg_segments -filter {DIRECTION == OUT}]
set cfg_driver_pin [ch1_one $cfg_driver_pins {cfg_reset net driver pin}]
set inverter_cell [ch1_one [get_cells -quiet -of_objects $cfg_driver_pin] {mapped startup inverter cell}]
set inverter [get_property NAME $inverter_cell]
set ew_engine [ch1_one [get_cells -quiet [list $endpoint/engine/ew]] {EW async engine}]
set cmac_engine [ch1_one [get_cells -quiet [list $endpoint/engine/cmac]] {CMAC async engine}]
ch1_require [expr {[get_property REF_NAME $ew_engine] eq "rk_ew_async_engine" && [get_property REF_NAME $cmac_engine] eq "rk_cmac_async_engine"}] "Changed dual engine hierarchy/module identity"
set ew_job [format {%s/engine/ew/job_crossing/} $endpoint]
set cmac_job [format {%s/engine/cmac/job_crossing/} $endpoint]
set ew_memory [format {%s/engine/ew/memory_crossing} $endpoint]
set cmac_memory [format {%s/engine/cmac/memory_crossing} $endpoint]
set cmac_job_profile cmac_terminal_full8
set status_inventory [rk_status_inventory $endpoint $sys_clock $ui0_clock $ui1_clock]
ch1_require [expr {[llength $status_inventory]==9}] "Expected unchanged nine reset/status chains"
set permit_inventory [rk_cmac_permit_inventory $endpoint $ui0_clock $sys_clock]
set ew_payload [rk_job_payloads $ew_job ew_engine_e1_e8]
set cmac_payload [rk_job_payloads $cmac_job $cmac_job_profile]
ch1_require [expr {[llength [lindex $ew_payload 0 1]]==64 && [llength [lindex $ew_payload 1 1]]==37}] "EW job payload width changed"
ch1_require [expr {[llength [lindex $cmac_payload 0 1]]==64 && [llength [lindex $cmac_payload 1 1]]==10}] "CMAC terminal full8 payload must retain task bit0 plus all8 error bits"
set ew_memory_payload [rk_mem_payloads [rk_mem_prefix $ew_memory]]
set cmac_memory_payload [rk_mem_payloads [rk_mem_prefix $cmac_memory]]
set reset_inventory [rk_board_reset_inventory $endpoint $startup $inverter $sys_clock $ui0_clock $ui1_clock]
ch1_require [expr {[llength $reset_inventory]==4}] "Expected strict four-bank board reset inventory"
set constant_ew [rk_job_constant_fields $ew_job ew_engine_e1_e8]
set constant_cmac [rk_job_constant_fields $cmac_job $cmac_job_profile]
ch1_require [expr {[llength $constant_ew]==4 && [llength $constant_cmac]==31}] "Expected four EW ZERO_CODE and 31 CMAC ZERO_TASK rows"
rk_ddr_host_cdc_constrain $ui0_clock
rk_status_cdc_constrain $endpoint $sys_clock $ui0_clock $ui1_clock
rk_job_cdc_constrain [string trimright $ew_job /] $ui0_clock $sys_clock ew_engine_e1_e8
rk_job_cdc_constrain [string trimright $cmac_job /] $ui0_clock $sys_clock $cmac_job_profile
rk_mem_cdc_constrain $ew_memory $sys_clock $ui0_clock
rk_mem_cdc_constrain $cmac_memory $sys_clock $ui0_clock
rk_cmac_permit_constrain $endpoint $ui0_clock $sys_clock
rk_board_reset_constrain $endpoint $startup $inverter $sys_clock $ui0_clock $ui1_clock
set f [open [file join $out constrained_synthesis_facts.tsv] {WRONLY CREAT EXCL}]
ch1_emit $f [list DESIGN [get_property NAME [current_design]] TOP [get_property TOP [current_design]] PART [get_property PART [current_design]] CONFIG_VOLTAGE [get_property CONFIG_VOLTAGE [current_design]] CFGBVS [get_property CFGBVS [current_design]]]
ch1_emit $f [list CLOCK_BINDING SYS [get_property NAME $sys_clock] SYS_PERIOD [get_property PERIOD $sys_clock] UI0 [get_property NAME $ui0_clock] UI0_PERIOD [get_property PERIOD $ui0_clock] UI0_SOURCE_MIG_C1_PIN $mig_c1_pin UI1 [get_property NAME $ui1_clock] UI1_PERIOD [get_property PERIOD $ui1_clock] UI1_SOURCE_MIG_C0_PIN $mig_c0_pin MIG_CELL $mig_name ENDPOINT $endpoint STARTUP $startup INVERTER $inverter]
proc shared_census {out stage} {
    set kernels [get_cells -quiet -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe || REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe}]
    ch1_require [expr {[llength $kernels]==16}] "$stage expected 16 actual full512 kernels"
    set dsps [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E1}]
    set product_total 0; set owned [dict create]; set kcounts [dict create]
    foreach kernel $kernels {
        set prefix "[get_property NAME $kernel]/"; set count 0
        foreach dsp $dsps {set n [get_property NAME $dsp]; if {[string first $prefix $n]==0} {ch1_require [expr {![dict exists $owned $n]}] "Duplicate DSP ownership"; dict set owned $n 1; incr count}}
        ch1_require [expr {$count==32}] "$stage C32 kernel is missing product DSPs"
        incr product_total $count; dict set kcounts [get_property NAME $kernel] $count
    }
    set ports [get_ports -quiet]
    set auxiliary [expr {[llength $dsps]-[dict size $owned]}]
    ch1_require [expr {$product_total==512 && [dict size $owned]==512 && [llength $dsps]==516 && $auxiliary==4}] "$stage product/auxiliary DSP census mismatch"
    ch1_require [expr {[llength $ports]==242}] "$stage scalar IO count changed"
    ch1_require [expr {[get_property CONFIG_VOLTAGE [current_design]]==1.8 && [get_property CFGBVS [current_design]] eq "GND"}] "$stage configuration voltage changed"
    ch1_emit $out [list CENSUS $stage TOP [get_property TOP [current_design]] PART [get_property PART [current_design]] KERNELS [llength $kernels] PRODUCT_DSPS $product_total TOTAL_DSPS [llength $dsps] AUXILIARY_DSPS $auxiliary SCALAR_PORTS [llength $ports] CONFIG_VOLTAGE [get_property CONFIG_VOLTAGE [current_design]] CFGBVS [get_property CFGBVS [current_design]]]
    foreach k [lsort [dict keys $kcounts]] {ch1_emit $out [list KERNEL_DSP $stage $k [dict get $kcounts $k]]}
}
shared_census $f pre_opt
report_utilization -hierarchical -file [file join $out pre_opt_utilization.rpt]
report_io -file [file join $out pre_opt_io.rpt]
report_clocks -file [file join $out pre_opt_clocks.rpt]
report_drc -file [file join $out pre_opt_default_drc.rpt]
set row_count 0; set observations 0; set anchors [dict create]
foreach {profile rows expected_count kind first_bit net_indices} [list EW $constant_ew 4 ZERO_CODE 4 {3 5} CMAC $constant_cmac 31 ZERO_TASK 1 {3 5 7}] {
    ch1_require [expr {[llength $rows]==$expected_count}] "Changed $profile zero-proof row count"
    set row_index 0
    foreach row $rows {
        ch1_require [expr {[lindex $row 0] eq $kind && [lindex $row 1]==$first_bit+$row_index}] "Changed $profile zero-proof kind/bit order"
        set want_columns [expr {$profile eq "EW" ? 6 : 8}]
        ch1_require [expr {[llength $row]==$want_columns}] "Changed $profile zero-proof row width"
        ch1_emit $f [linsert $row 0 ZERO_ROW pre_opt $profile]
        foreach index $net_indices {
            set net [lindex $row $index]; set name [get_property NAME $net]
            ch1_require [expr {[get_property TYPE $net] eq "GROUND" && [get_property DRIVER_COUNT $net]==1}] "$profile boundary is not single-driver GROUND"
            ch1_emit $f [list ZERO_NET pre_opt $profile $row_index [lindex $row 1] $index $name [get_property TYPE $net] [get_property DRIVER_COUNT $net]]
            dict set anchors $name $net; incr observations
        }
        incr row_index; incr row_count
    }
}
ch1_require [expr {$row_count==35 && $observations==101 && [dict size $anchors]>0}] "Incomplete dual-engine pre-opt constant proof"
foreach name [lsort [dict keys $anchors]] {set net [dict get $anchors $name]; set_property KEEP TRUE $net; set_property DONT_TOUCH TRUE $net; ch1_emit $f [list ANCHOR_SET $name [get_property TYPE $net] [get_property DRIVER_COUNT $net] [get_property KEEP $net] [get_property DONT_TOUCH $net]]}
opt_design
set post_ew [rk_job_constant_fields $ew_job ew_engine_e1_e8]
set post_cmac [rk_job_constant_fields $cmac_job $cmac_job_profile]
ch1_require [expr {[llength $post_ew]==4 && [llength $post_cmac]==31}] "Changed post-opt dual constant proof row counts"
set post_anchors [dict create]; set post_rows 0; set post_observations 0
foreach {profile rows expected_count kind first_bit net_indices} [list EW $post_ew 4 ZERO_CODE 4 {3 5} CMAC $post_cmac 31 ZERO_TASK 1 {3 5 7}] {
    set row_index 0
    foreach row $rows {
        ch1_require [expr {[lindex $row 0] eq $kind && [lindex $row 1]==$first_bit+$row_index && [llength $row]==($profile eq "EW" ? 6 : 8)}] "Changed post-opt $profile proof row"
        ch1_emit $f [linsert $row 0 ZERO_ROW post_opt $profile]
        foreach index $net_indices {
            set net [lindex $row $index]; set name [get_property NAME $net]
            ch1_require [expr {[get_property TYPE $net] eq "GROUND" && [get_property DRIVER_COUNT $net]==1 && [get_property KEEP $net] && [get_property DONT_TOUCH $net]}] "Post-opt $profile boundary anchor lost or changed"
            ch1_emit $f [list ZERO_NET post_opt $profile $row_index [lindex $row 1] $index $name [get_property TYPE $net] [get_property DRIVER_COUNT $net] [get_property KEEP $net] [get_property DONT_TOUCH $net]]
            dict set post_anchors $name $net; incr post_observations
        }
        incr row_index; incr post_rows
    }
}
ch1_require [expr {$post_rows==35 && $post_observations==101 && [lsort [dict keys $post_anchors]] eq [lsort [dict keys $anchors]]}] "Post-opt proof or anchor set differs"
shared_census $f post_opt
report_utilization -hierarchical -file [file join $out post_opt_utilization.rpt]
report_io -file [file join $out post_opt_io.rpt]
report_clocks -file [file join $out post_opt_clocks.rpt]
report_drc -file [file join $out post_opt_default_drc.rpt]
report_cdc -details -file [file join $out post_opt_cdc.rpt]
write_checkpoint -force [file join $out post_opt.dcp]
close $f
puts READY_SHARED_DATA_CONSTRAINED_SYNTHESIS_ONLY_ROOT_REVIEW_REQUIRED
exit
