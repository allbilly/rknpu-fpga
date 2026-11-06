# Root-reviewed preparation draft. This Tcl is hard-gated before project creation.
if {![info exists ::env(RK_SHARED_DATA_CONSTRAINED_ROOT_REVIEW)] || $::env(RK_SHARED_DATA_CONSTRAINED_ROOT_REVIEW) ne "APPROVED"} {error "Root review required before fresh source synthesis"}
set_param general.maxThreads 4
set expected_kernels 8
set expected_product_dsps 256
# K16 used 4 non-product DSPs (three rk_cmac_profile constants and one EW
# rk_fp16_alu multiply). The K8 front's original-OC16 atom arithmetic may
# retain up to three address DSPs that K16 constant-folds away. They are not
# numerical product DSPs and may disappear in post-opt constant propagation.
set expected_fixed_aux_dsps 4
set expected_front_aux_dsps_max 3
set pkg [file normalize [file dirname [info script]]]
set src [file join $pkg source]
set out [pwd]
proc ch1_require {condition message} {if {!$condition} {error $message}}
proc ch1_one {objects message} {ch1_require [expr {[llength $objects]==1}] "Expected exactly one $message"; return [lindex $objects 0]}
proc ch1_emit {f row} {puts $f [join $row "\t"]; flush $f}
puts "SHARED_DATA_CONSTRAINED_NATIVE_TOOL [version -short]"
create_project -in_memory -part xc7k480tffg1156-2
set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]
set srcs [list \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/000/mig_7series_v4_2_axi_ctrl_addr_decode.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/001/mig_7series_v4_2_axi_ctrl_read.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/002/mig_7series_v4_2_axi_ctrl_reg_bank.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/003/mig_7series_v4_2_axi_ctrl_reg.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/004/mig_7series_v4_2_axi_ctrl_top.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/005/mig_7series_v4_2_axi_ctrl_write.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/006/mig_7series_v4_2_axi_mc.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/007/mig_7series_v4_2_axi_mc_ar_channel.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/008/mig_7series_v4_2_axi_mc_aw_channel.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/009/mig_7series_v4_2_axi_mc_b_channel.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/010/mig_7series_v4_2_axi_mc_cmd_arbiter.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/011/mig_7series_v4_2_axi_mc_cmd_fsm.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/012/mig_7series_v4_2_axi_mc_wr_cmd_fsm.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/013/mig_7series_v4_2_axi_mc_cmd_translator.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/014/mig_7series_v4_2_axi_mc_incr_cmd.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/015/mig_7series_v4_2_axi_mc_r_channel.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/016/mig_7series_v4_2_axi_mc_simple_fifo.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/017/mig_7series_v4_2_axi_mc_fifo.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/018/mig_7series_v4_2_axi_mc_w_channel.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/019/mig_7series_v4_2_axi_mc_wrap_cmd.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/020/mig_7series_v4_2_ddr_a_upsizer.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/021/mig_7series_v4_2_ddr_axi_register_slice.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/022/mig_7series_v4_2_ddr_axi_upsizer.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/023/mig_7series_v4_2_ddr_axic_register_slice.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/024/mig_7series_v4_2_ddr_carry_and.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/025/mig_7series_v4_2_ddr_carry_latch_and.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/026/mig_7series_v4_2_ddr_carry_latch_or.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/027/mig_7series_v4_2_ddr_carry_or.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/028/mig_7series_v4_2_ddr_command_fifo.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/029/mig_7series_v4_2_ddr_comparator.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/030/mig_7series_v4_2_ddr_comparator_sel.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/031/mig_7series_v4_2_ddr_comparator_sel_static.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/032/mig_7series_v4_2_ddr_r_upsizer.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/033/mig_7series_v4_2_ddr_w_upsizer.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/034/mig_7series_v4_2_clk_ibuf.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/035/mig_7series_v4_2_infrastructure.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/036/mig_7series_v4_2_iodelay_ctrl.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/037/mig_7series_v4_2_tempmon.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/038/mig_7series_v4_2_arb_mux.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/039/mig_7series_v4_2_arb_row_col.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/040/mig_7series_v4_2_arb_select.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/041/mig_7series_v4_2_bank_cntrl.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/042/mig_7series_v4_2_bank_common.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/043/mig_7series_v4_2_bank_compare.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/044/mig_7series_v4_2_bank_mach.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/045/mig_7series_v4_2_bank_queue.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/046/mig_7series_v4_2_bank_state.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/047/mig_7series_v4_2_col_mach.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/048/mig_7series_v4_2_mc.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/049/mig_7series_v4_2_rank_cntrl.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/050/mig_7series_v4_2_rank_common.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/051/mig_7series_v4_2_rank_mach.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/052/mig_7series_v4_2_ecc_buf.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/053/mig_7series_v4_2_ecc_dec_fix.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/054/mig_7series_v4_2_ecc_gen.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/055/mig_7series_v4_2_ecc_merge_enc.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/056/mig_7series_v4_2_fi_xor.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/057/mig_7series_v4_2_mem_intfc.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/058/mig_7series_v4_2_memc_ui_top_axi.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/059/mig_7series_v4_2_ddr_byte_group_io.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/060/mig_7series_v4_2_ddr_byte_lane.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/061/mig_7series_v4_2_ddr_phy_tempmon.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/062/mig_7series_v4_2_ddr_calib_top.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/063/mig_7series_v4_2_ddr_skip_calib_tap.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/064/mig_7series_v4_2_ddr_if_post_fifo.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/065/mig_7series_v4_2_ddr_mc_phy.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/066/mig_7series_v4_2_ddr_mc_phy_wrapper.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/067/mig_7series_v4_2_ddr_of_pre_fifo.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/068/mig_7series_v4_2_ddr_phy_4lanes.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/069/mig_7series_v4_2_ddr_phy_ck_addr_cmd_delay.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/070/mig_7series_v4_2_ddr_phy_init.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/071/mig_7series_v4_2_ddr_phy_dqs_found_cal.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/072/mig_7series_v4_2_ddr_phy_dqs_found_cal_hr.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/073/mig_7series_v4_2_ddr_phy_oclkdelay_cal.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/074/mig_7series_v4_2_ddr_phy_prbs_rdlvl.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/075/mig_7series_v4_2_ddr_phy_rdlvl.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/076/mig_7series_v4_2_ddr_phy_top.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/077/mig_7series_v4_2_ddr_phy_wrcal.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/078/mig_7series_v4_2_ddr_phy_wrlvl.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/079/mig_7series_v4_2_ddr_phy_wrlvl_off_delay.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/080/mig_7series_v4_2_ddr_prbs_gen.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/081/mig_7series_v4_2_ddr_phy_ocd_lim.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/082/mig_7series_v4_2_poc_top.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/083/mig_7series_v4_2_ddr_phy_ocd_mux.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/084/mig_7series_v4_2_ddr_phy_ocd_data.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/085/mig_7series_v4_2_ddr_phy_ocd_samp.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/086/mig_7series_v4_2_ddr_phy_ocd_edge.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/087/mig_7series_v4_2_ddr_phy_ocd_cntlr.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/088/mig_7series_v4_2_ddr_phy_ocd_po_cntlr.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/089/mig_7series_v4_2_poc_pd.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/090/mig_7series_v4_2_poc_tap_base.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/091/mig_7series_v4_2_poc_meta.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/092/mig_7series_v4_2_poc_edge_store.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/093/mig_7series_v4_2_poc_cc.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/094/mig_7series_v4_2_ui_cmd.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/095/mig_7series_v4_2_ui_rd_data.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/096/mig_7series_v4_2_ui_top.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/097/mig_7series_v4_2_ui_wr_data.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/098/top_mig_7series_0_0.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/099/top_mig_7series_0_0_mig.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/100/mig_7series_v4_2_round_robin_arb.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/101/rk_fp16_alu.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/102/rk_ew_regs.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/103/rk_ew_engine.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/104/rk_ew_core.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/105/rk_ew_dma.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/106/rk_axi_mem.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/107/rk_job_control.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/108/rk_jtag_backend.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/109/rk_mig_reset_coordinator.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/110/rk_mig_ecc_monitor.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/111/rk_mig_write_fence.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/112/rk_ddr_memory_fabric_snapshot.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/113/rk_async_job_port.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/114/rk_async_mem_port.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/115/rk_ew_async_engine.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/116/rk_axi_mem_read_snapshot.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/117/platform.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/118/rk_startup_reset.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/119/otpu_jtag_mailbox.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/120/top.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/121/NV_DW02_tree.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/122/NV_DW_lsd.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/123/NV_NVDLA_CMAC_CORE_MAC_mul.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/124/NV_NVDLA_CACC_CALC_fp_48b.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/125/HLS_fp32_to_fp16.v} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/126/rk_cmac_profile.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/127/rk_cmac_fp16_rows.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/128/rk_cmac_fp16_discarded_carry.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/129/rk_cmac_fp16_lane_dsp_prefix.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/130/rk_cmac_fp16_cell_dsp_prefix.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/131/rk_cmac_fp16_array_dsp_prefix.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/132/rk_nvdla_cacc.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/133/rk_cacc_fp16_array.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/134/rk_cmac_cacc_fp16_array.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/135/rk_nvdla_fp32_to_fp16.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/136/rk_cmac_writer.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/137/rk_cmac_output_nvdla.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/138/rk_cmac_frame_output.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/139/rk_cmac_array_datapath.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/140/rk_cmac_array_front.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/141/rk_cmac_rw_arbiter.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/142/rk_cmac_array_core.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/143/rk_cmac_array_dma.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/144/rk_cmac_fp16_cell_dsp_prefix_pipe.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/145/rk_cmac_fp16_array_dsp_prefix_pipe.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/146/rk_cmac_success_rearm.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/147/rk_cmac_async_engine.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/148/rk_dual_async_dispatch.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/149/rk_dual_job_control.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/150/rk_jtag_dual_ddr_async.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/151/rk_cmac_fp16_shared_data.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/152/rk_ddr_capacity_owner.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/153/rk_ddr_capacity_regs.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/154/rk_ddr_diagnostic_mux.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/155/rk_ddr_capacity_service.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/156/rk_axil_diagnostic_router.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/157/rk_ddr_capacity_bist.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/158/rk_ddr_capacity_axi.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/159/rk_ddr_capacity_sweep.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/160/rk_ddr_capacity_pattern.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/161/rk_job_control_admission.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/162/rk_dual_job_control_admission.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/framework/00_rk_layout_job_control.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/framework/01_rk_layout_compute_dispatch.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/framework/02_rk_layout_dma.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/framework/03_rk_quiescent_compute_reset.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/framework/04_rk_compute_reset_regs.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/framework/05_rk_axil_compute_reset_router.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/sys_reset/rk_retained_jtag_mailbox.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/sys_reset/rk_whole_reset_control.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/sys_reset/rk_whole_reset_frame_gate.sv} \
    {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/hdl/sys_reset/rk_whole_reset_ui_bridge.sv}
]
read_verilog -sv {*}$srcs
read_xdc {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/mig-original.xdc}
read_xdc {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/board.xdc}
synth_design -top ypcb_ddr_dual_top -part xc7k480tffg1156-2 -flatten_hierarchy none
puts SHARED_DATA_CONSTRAINED_FRESH_SYNTHESIS_COMPLETED
set_property CONFIG_VOLTAGE 1.8 [current_design]
set_property CFGBVS GND [current_design]
ch1_require [expr {[get_property TOP [current_design]] eq "ypcb_ddr_dual_top" && [get_property PART [current_design]] eq "xc7k480tffg1156-2"}] "Wrong synthesized top or part"
ch1_require [expr {[get_property CONFIG_VOLTAGE [current_design]] == 1.8 && [get_property CFGBVS [current_design]] eq "GND"}] "Changed configuration voltage or CFGBVS"
ch1_require [expr {[llength [get_cells -quiet -hierarchical -filter {IS_BLACKBOX == 1}]]==0}] "Unresolved source black box"
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/status_cdc.tcl}
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/job_cdc.tcl}
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/permit_cdc.tcl}
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/compute_reset.tcl}
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/memory_crossing.tcl}
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/mailbox_ui.tcl}
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/mailbox_sys.tcl}
source {/home/fedora/.local/share/opencode/worktree/c66387/k8-full-top/build/k8-full-top-v1/source/constraint-helpers/board_reset.tcl}
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
set startup_cell [ch1_one [get_cells -quiet [list u_maintenance_mailbox/startup]] {mapped USER3 startup reset producer}]
set startup [get_property NAME $startup_cell]
set ui_startup_cell [ch1_one [get_cells -quiet [list u_mailbox/startup]] {mapped USER2 startup reset producer}]
set cfg_pin [rk_status_pin $endpoint/cfg_reset]
set cfg_segments [get_nets -quiet -segments -of_objects $cfg_pin]
ch1_require [expr {[llength $cfg_segments]>0}] "Missing endpoint cfg_reset segments"
set cfg_driver_pins [get_pins -quiet -leaf -of_objects $cfg_segments -filter {DIRECTION == OUT}]
set cfg_driver_pin [ch1_one $cfg_driver_pins {cfg_reset net driver pin}]
set inverter_cell [ch1_one [get_cells -quiet -of_objects $cfg_driver_pin] {mapped startup inverter cell}]
set inverter [get_property NAME $inverter_cell]
set ew_engine [ch1_one [get_cells -quiet [list $endpoint/engine/numerical/ew]] {EW async engine}]
set cmac_engine [ch1_one [get_cells -quiet [list $endpoint/engine/numerical/cmac]] {CMAC async engine}]
ch1_require [expr {[get_property REF_NAME $ew_engine] eq "rk_ew_async_engine" && [get_property REF_NAME $cmac_engine] eq "rk_cmac_async_engine"}] "Changed dual engine hierarchy/module identity"
set ew_job [format {%s/engine/numerical/ew/job_crossing/} $endpoint]
set cmac_job [format {%s/engine/numerical/cmac/job_crossing/} $endpoint]
set ew_memory [format {%s/engine/numerical/ew/memory_crossing} $endpoint]
set cmac_memory [format {%s/engine/numerical/cmac/memory_crossing} $endpoint]
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
rk_retained_ui_host_cdc_constrain $ui0_clock
rk_retained_sys_host_cdc_constrain $sys_clock
rk_status_cdc_constrain $endpoint $sys_clock $ui0_clock $ui1_clock
rk_job_cdc_constrain [string trimright $ew_job /] $ui0_clock $sys_clock ew_engine_e1_e8
rk_job_cdc_constrain [string trimright $cmac_job /] $ui0_clock $sys_clock $cmac_job_profile
rk_mem_cdc_constrain $ew_memory $sys_clock $ui0_clock
rk_mem_cdc_constrain $cmac_memory $sys_clock $ui0_clock
rk_cmac_permit_constrain $endpoint $ui0_clock $sys_clock
rk_compute_reset_constrain $endpoint $ui0_clock $sys_clock
rk_board_reset_constrain $endpoint $startup $inverter $sys_clock $ui0_clock $ui1_clock
set f [open [file join $out constrained_synthesis_facts.tsv] {WRONLY CREAT EXCL}]
ch1_emit $f [list DESIGN [get_property NAME [current_design]] TOP [get_property TOP [current_design]] PART [get_property PART [current_design]] CONFIG_VOLTAGE [get_property CONFIG_VOLTAGE [current_design]] CFGBVS [get_property CFGBVS [current_design]]]
ch1_emit $f [list CLOCK_BINDING SYS [get_property NAME $sys_clock] SYS_PERIOD [get_property PERIOD $sys_clock] UI0 [get_property NAME $ui0_clock] UI0_PERIOD [get_property PERIOD $ui0_clock] UI0_SOURCE_MIG_C1_PIN $mig_c1_pin UI1 [get_property NAME $ui1_clock] UI1_PERIOD [get_property PERIOD $ui1_clock] UI1_SOURCE_MIG_C0_PIN $mig_c0_pin MIG_CELL $mig_name ENDPOINT $endpoint STARTUP $startup INVERTER $inverter]
proc shared_census {out stage} {
    global expected_kernels expected_product_dsps expected_fixed_aux_dsps expected_front_aux_dsps_max
    set kernels [get_cells -quiet -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe || REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe}]
    ch1_require [expr {[llength $kernels]==$expected_kernels}] "$stage expected $expected_kernels actual K8 kernels"
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
    set front_aux [expr {$auxiliary-$expected_fixed_aux_dsps}]
    ch1_require [expr {$product_total==$expected_product_dsps && [dict size $owned]==$expected_product_dsps}] "$stage product DSP census mismatch"
    ch1_require [expr {$auxiliary>=$expected_fixed_aux_dsps && $front_aux<=$expected_front_aux_dsps_max}] "$stage auxiliary DSP census mismatch"
    ch1_require [expr {[llength $ports]==242}] "$stage scalar IO count changed"
    ch1_require [expr {[get_property CONFIG_VOLTAGE [current_design]]==1.8 && [get_property CFGBVS [current_design]] eq "GND"}] "$stage configuration voltage changed"
    ch1_emit $out [list CENSUS $stage TOP [get_property TOP [current_design]] PART [get_property PART [current_design]] KERNELS [llength $kernels] PRODUCT_DSPS $product_total TOTAL_DSPS [llength $dsps] AUXILIARY_DSPS $auxiliary FRONT_AUX_DSPS $front_aux SCALAR_PORTS [llength $ports] CONFIG_VOLTAGE [get_property CONFIG_VOLTAGE [current_design]] CFGBVS [get_property CFGBVS [current_design]]]
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
proc cap_check_total_luts {report_path limit} {
    set fd [open $report_path r]
    set found 0; set value -1
    while {[gets $fd line] >= 0} {
        if {[string match {| ypcb_ddr_dual_top *} $line]} {
            set fields [split $line |]
            ch1_require [expr {[llength $fields] > 3}] "Malformed post-opt utilization top row"
            set candidate [string trim [lindex $fields 3]]
            ch1_require [string is integer -strict $candidate] "Missing integer Total LUTs in top utilization row"
            ch1_require [expr {!$found}] "Duplicate top utilization row"
            set value $candidate; set found 1
        }
    }
    close $fd
    ch1_require $found "Missing top Total LUTs row in post-opt utilization report"
    ch1_require [expr {$value <= $limit}] "Post-opt Total LUT count exceeds xc7k480t limit"
    puts "CAPACITY_RESOURCE_GATE stage=post_opt total_luts=$value limit=$limit"
}
cap_check_total_luts [file join $out post_opt_utilization.rpt] 298600
report_io -file [file join $out post_opt_io.rpt]
report_clocks -file [file join $out post_opt_clocks.rpt]
report_drc -file [file join $out post_opt_default_drc.rpt]
report_cdc -details -file [file join $out post_opt_cdc.rpt]
write_checkpoint -force [file join $out post_opt_unaccepted.dcp]
rk_compute_reset_audit $endpoint $ui0_clock $sys_clock $out mapped
# The repair's lane enable must have no combinational request-READY input.
set layout [rk_status_cell $endpoint/engine/layout_engine]
ch1_require [expr {[get_property REF_NAME $layout] eq "rk_layout_dma"}] "Wrong mapped layout engine"
set ready_pin [rk_status_pin $layout/mem_req_ready]
set lane_cells {};set lane_stem $layout/lane_reg
set lane_ff_re [format {^%s/lane_reg\[[0-9]+\]$} $layout]
set lane_ff_types {FDCE FDRE FDSE FDPE}
foreach cell [get_cells -quiet -hier -filter {REF_NAME == FDCE || REF_NAME == FDRE || REF_NAME == FDSE || REF_NAME == FDPE}] {
  if {[regexp $lane_ff_re [get_property NAME $cell]]} {lappend lane_cells $cell}
}
set expected_lane_names {}
for {set i 0} {$i<32} {incr i} {lappend expected_lane_names [format {%s/lane_reg[%d]} $layout $i]}
ch1_require [expr {[llength $lane_cells]==32 && [lsort [lmap cell $lane_cells {get_property NAME $cell}]] eq [lsort $expected_lane_names]}] "Mapped lane FF identities/width changed"
foreach cell $lane_cells {ch1_require [expr {[get_property REF_NAME $cell] in $lane_ff_types}] "Lane counter source is not a flip-flop: $cell"}
set ready_endpoints [all_fanout -flat -endpoints_only -from $ready_pin]
ch1_require [expr {[llength $ready_endpoints]>0}] "Empty request-READY traversal cannot prove independence"
set ready_controls {}
foreach name {request_pending outstanding} {
  set control [rk_status_cell $layout/${name}_reg]
  rk_status_ff $control $ui0_clock
  set hits {}
  foreach pin [get_pins -quiet -of_objects $control -filter {DIRECTION == IN && REF_PIN_NAME != C}] {
    if {$pin in $ready_endpoints} {lappend hits $pin}
  }
  ch1_require [expr {[llength $hits]>0}] "READY traversal lacks known functional endpoint: $control"
  foreach pin $hits {lappend ready_controls $pin}
}
set lane_file [open [file join $out layout_lane_enable.tsv] w]
puts $lane_file "SOURCE\t$ready_pin"
puts $lane_file "READY_ENDPOINT_COUNT\t[llength $ready_endpoints]"
foreach pin $ready_controls {puts $lane_file "READY_POSITIVE_CONTROL\t$pin"}
set lane_nonclock_count 0
foreach cell $lane_cells {
  rk_status_ff $cell $ui0_clock
  set cell_nonclock 0
  foreach pin [get_pins -quiet -of_objects $cell -filter {DIRECTION == IN && REF_PIN_NAME != C}] {
    ch1_require [expr {$pin ni $ready_endpoints}] "Live request READY still reaches lane counter: $pin"
    puts $lane_file "LANE_NONCLOCK_PIN\t$cell\t$pin"
    incr cell_nonclock;incr lane_nonclock_count
  }
  ch1_require [expr {$cell_nonclock==3}] "Mapped lane FF nonclock input count changed: $cell"
  puts $lane_file "LANE_READY_INDEPENDENT\t$cell\t$ui0_clock"
}
ch1_require [expr {$lane_nonclock_count==96}] "Expected exactly 96 lane FF nonclock inputs"
puts $lane_file "LANE_NONCLOCK_INPUT_COUNT\t$lane_nonclock_count"
puts $lane_file "PASS_LANE_READY_INDEPENDENCE\t32"
close $lane_file

# Read-only V2 factored control observations use actual active interface pins,
# not removed/trimmed pre-factor readiness aliases.
proc ch1_observe_factor_output {file label relative} {
    set pin [ch1_one [get_pins -quiet [list $relative]] "active factor output $label"]
    ch1_require [expr {[get_property DIRECTION $pin] eq "OUT"}] "Wrong factor output direction: $label"
    set nets [get_nets -quiet -segments -of_objects $pin]
    ch1_require [expr {[llength $nets]>0}] "Factor output has no mapped net: $label"
    set fanout [all_fanout -flat -endpoints_only -from $pin]
    ch1_require [expr {[llength $fanout]>0}] "Factor output is trimmed or inactive: $label"
    ch1_emit $file [list FACTOR_ACTIVE_OUTPUT $label $pin [join $nets ,] [llength $fanout]]
    foreach endpoint_pin $fanout {ch1_emit $file [list FACTOR_ACTIVE_FANOUT $label $endpoint_pin]}
}
proc ch1_observe_factor_consumer {file label relative} {
    set pin [ch1_one [get_pins -quiet [list $relative]] "active factor consumer $label"]
    ch1_require [expr {[get_property DIRECTION $pin] eq "IN"}] "Wrong factor consumer direction: $label"
    set nets [get_nets -quiet -segments -of_objects $pin]
    ch1_require [expr {[llength $nets]>0}] "Factor consumer has no mapped net: $label"
    set sources [all_fanin -flat -startpoints_only -to $pin]
    ch1_require [expr {[llength $sources]>0}] "Factor consumer has no active source cone: $label"
    ch1_emit $file [list FACTOR_ACTIVE_CONSUMER $label $pin [join $nets ,] [llength $sources]]
    foreach source_pin $sources {ch1_emit $file [list FACTOR_CONSUMER_STARTPOINT $label $source_pin]}
}
set factor_file [open [file join $out factored_cone_observations.tsv] {WRONLY CREAT EXCL}]
puts $factor_file "SCOPE\tV2_ACTIVE_FACTORED_INTERFACE_CONES"
foreach {label relative} [list \
    start_slot $endpoint/engine/ui_start_slot_ready \
    ew_start_slot $endpoint/engine/ui_ew_start_slot_ready \
    cmac_start_slot $endpoint/engine/ui_cmac_start_slot_ready \
    layout_start_slot $endpoint/engine/ui_layout_start_slot_ready \
    idle_quiet $endpoint/engine/ui_idle_quiet \
    idle_restart_ready $endpoint/engine/ui_idle_restart_ready \
    fault_cause_pending $endpoint/memory/fault_cause_pending] {
    ch1_observe_factor_output $factor_file $label $relative
}
foreach {label relative} [list \
    ew_control_ready $endpoint/control/core_ew_start_ready \
    cmac_control_ready $endpoint/control/core_cmac_start_ready \
    layout_control_ready $endpoint/control/core_layout_start_ready \
    reset_quiet_consumer $endpoint/compute_reset/ui_quiet \
    reset_restart_consumer $endpoint/compute_reset/ui_restart_ready] {
    ch1_observe_factor_consumer $factor_file $label $relative
}
close $factor_file

# Diagnostic-only synthesis timing path inventory. These estimates are not
# routed/setup/hold acceptance criteria and do not modify clocks or exceptions.
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out post_opt_timing_summary_diagnostic.rpt]
report_timing -delay_type max -max_paths 100 -nworst 10 -input_pins -nets -file [file join $out post_opt_setup_top100_diagnostic.rpt]
report_timing -delay_type min -max_paths 100 -nworst 10 -input_pins -nets -file [file join $out post_opt_hold_top100_diagnostic.rpt]
proc ch1_timing_family {pin_name} {
    set parts [split $pin_name /]
    if {[llength $parts]<2} {return $pin_name}
    set pin [lindex $parts end];set cell [lindex $parts end-1]
    regsub -all {\[[0-9]+\]} $cell {} stem
    return [join [concat [lrange $parts 0 end-2] [list $stem $pin]] /]
}
set v4_path [file join $pkg reference v4-negative-endpoint-groups.tsv]
set v4_fd [open $v4_path r]
set v4_header [gets $v4_fd]
ch1_require [expr {$v4_header eq "GROUP\tCOUNT\tWORST_SLACK\tSTART\tEND"}] "V4 timing-family reference schema changed"
set v4_families [dict create]
while {[gets $v4_fd line]>=0} {
    set row [split $line \t]
    ch1_require [expr {[llength $row]==5}] "Malformed V4 timing-family reference row"
    dict set v4_families [lindex $row 0] [lrange $row 1 4]
}
close $v4_fd
set new_families [dict create]
foreach kind {max min} {
    set paths [get_timing_paths -quiet -delay_type $kind -slack_lesser_than 0 -max_paths 3000 -nworst 1]
    foreach path $paths {
        set endpoint_pin [get_property ENDPOINT_PIN $path]
        set startpoint_pin [get_property STARTPOINT_PIN $path]
        set family [ch1_timing_family $endpoint_pin]
        set slack [get_property SLACK $path]
        set levels [get_property LOGIC_LEVELS $path]
        set delay [get_property DATAPATH_DELAY $path]
        set key "$kind\t$family"
        if {![dict exists $new_families $key]} {
            dict set new_families $key [list 1 $slack $startpoint_pin $endpoint_pin $levels $delay]
        } else {
            set row [dict get $new_families $key]
            lset row 0 [expr {[lindex $row 0]+1}]
            if {$slack<[lindex $row 1]} {lset row 1 $slack;lset row 2 $startpoint_pin;lset row 3 $endpoint_pin;lset row 4 $levels;lset row 5 $delay}
            dict set new_families $key $row
        }
    }
}
set timing_file [open [file join $out post_opt_timing_diagnostics.tsv] {WRONLY CREAT EXCL}]
puts $timing_file "SCOPE\tSYNTHESIS_ESTIMATE_ONLY_NOT_ROUTED_ACCEPTANCE"
puts $timing_file "V4_REFERENCE\tFAMILY\tCOUNT\tWORST_SLACK\tSTART\tEND"
foreach family [lsort [dict keys $v4_families]] {ch1_emit $timing_file [linsert [dict get $v4_families $family] 0 V4_REFERENCE $family]}
puts $timing_file "POST_OPT_NEGATIVE\tDELAY_TYPE\tFAMILY\tCOUNT\tWORST_SLACK\tSTART\tEND\tLOGIC_LEVELS\tDATAPATH_DELAY\tV4_COUNT\tV4_WORST_SLACK"
foreach key [lsort [dict keys $new_families]] {
    lassign [split $key \t] kind family
    set row [dict get $new_families $key]
    set v4_count 0;set v4_slack ""
    if {$kind eq "max" && [dict exists $v4_families $family]} {set v4 [dict get $v4_families $family];set v4_count [lindex $v4 0];set v4_slack [lindex $v4 1]}
    ch1_emit $timing_file [list POST_OPT_NEGATIVE $kind $family {*}$row $v4_count $v4_slack]
}
close $timing_file
write_checkpoint -force [file join $out post_opt.dcp]
close $f
puts READY_READINESS_FACTOR_SYNTHESIS_ONLY_ROOT_REVIEW_REQUIRED
exit
