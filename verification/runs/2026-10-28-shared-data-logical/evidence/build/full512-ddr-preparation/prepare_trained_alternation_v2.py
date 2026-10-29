"""Prepare original trained TinyStories tile CMAC/EW/CMAC on real MC logic."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path('/home/fedora/rknpu-fpga')
PARENT=ROOT/'build/full512-ddr-preparation/joined-model-source-v1'
OUT=ROOT/'build/full512-ddr-preparation/trained-alternation-source-v2'
VECTORS=ROOT/'build/tinystories-joined-vectors/v2'
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()

def need(ok,message):
    if not ok:raise RuntimeError(message)


need(not OUT.exists(),'Fresh trained alternation preparation required')
parent=json.loads((PARENT/'preparation.json').read_text())
vectors=json.loads((VECTORS/'report.json').read_text())
need(vectors['status']=='STATIC_TRAINED_TILE_JOINED_TEST_VECTORS' and
     (vectors['lines'],vectors['ew_delta_lines'],vectors['repeat_delta_lines'],vectors['cmac_amount'],vectors['ew_amount'])==
     (1408,9,11,45,22),'Changed original trained raw-vector contract')
for name,digest in vectors['files'].items():need(sha(VECTORS/name)==digest,'Changed trained vector '+name)
need(sha(vectors['source_report_path'])==vectors['source_report_sha256'],'Changed final-writer projection source')
OUT.mkdir()
shutil.copytree(VECTORS,OUT/'vectors')
parent_bench=Path(parent['bench'])
prefix=parent_bench.read_text().split('  // All paths meet one completion point;')[0]
need(prefix.startswith('// SPDX-License-Identifier: MIT'),'Unexpected source bench')
# Retain only active trained-test helpers; the old negative-matrix driver is
# not executed here and has its own source/receipts.
import re
for task in ('check_memory','upload_images'):
    prefix,count=re.subn(r'  task automatic '+task+r';.*?  endtask\n','',prefix,flags=re.S)
    need(count==1,'Unexpected inherited task '+task)
prefix=prefix.replace('  wire [31:0] selected_identity=csr_base==32\'h100 ? 32\'h524b4344 : 32\'h524b4144;\n','')
prefix=prefix.replace('  logic [31:0] address,start_address,start_amount,tag;','  logic [31:0] address;')
prefix=prefix.replace('  integer upload_count,expected_tasks,jobs,negative_mode,original_negative;\n','')
prefix=prefix.replace('  integer fd,observed,polls,uploaded_nonzero,submissions,reset_recovery,recovered;','  integer fd,observed,polls;')
prefix=prefix.replace('  integer prior_dma_launches,prior_fabric_claims;\n','')
prefix=prefix.replace('  logic expect_error,stop_after_error;\n','')
prefix=prefix.replace('  string prefix,output_path;\n','')

body=r'''
  integer engine_writes,phase,prior_writes,prior_launches,prior_claims,prior_retire;
  integer actual_upload_lines;
  string directory,output_directory;
  always @(posedge c0_ui_clk)begin
    if(!c0_clients_rst_n)engine_writes<=0;
    else if(dut.engine_req_valid&&dut.engine_req_ready&&dut.engine_req_write)
      engine_writes<=engine_writes+1;
  end
  task automatic phase_log(input string state_name);
    $display("TRAINED_DDR phase=%0d stage=%s time=%0t uploaded_lines=%0d engine_writes=%0d phy_returns=%0d",
             phase,state_name,$time,actual_upload_lines,engine_writes,read_return_count);
    $fflush();
  endtask
  task automatic trained_upload(input string name,input integer count,input logic initialized_zero);
    logic [31:0] previous;
    ddr_image_open({directory,"/",name},count,fd);previous=0;
    for(integer line=0;line<count;line=line+1)begin
      ddr_image_read(fd,line,previous,address,upload_line);previous=address;
      // Initial zero lines are already written/fenced by the actual controller.
      // Every delta line is transferred, including explicit zero padding.
      if(!initialized_zero||upload_line!==0)begin
        command(4,address,upload_line,value);actual_upload_lines=actual_upload_lines+1;
      end
    end
    ddr_image_finish(fd);
  endtask
  task automatic trained_check(input string name,input string capture_name);
    logic [31:0] previous;
    ddr_image_open({directory,"/",name},1408,fd);previous=0;
    observed=$fopen({output_directory,"/",capture_name},"w");
    if(observed==0)$fatal(1,"Missing complete BO capture target");
    for(integer line=0;line<1408;line=line+1)begin
      ddr_image_read(fd,line,previous,address,expected_line);previous=address;
      command(3,address,0,value);
      $fdisplay(observed,"%08h %0128h",address,value);
      if(value!==expected_line)$fatal(1,"Trained full DDR BO mismatch at%h",address);
    end
    ddr_image_finish(fd);$fclose(observed);
  endtask
  task automatic stage_trained(input logic [31:0] amount,input logic [31:0] job_tag);
    register_command(2,32'h10,512'h100e0000,value);
    register_command(2,32'h14,{480'b0,amount},value);
    register_command(2,32'h18,{480'b0,job_tag},value);
  endtask
  task automatic await_trained(input logic [31:0] job_tag,input logic [31:0] tasks);
    polls=0;value=0;
    while(!value[2])begin
      register_command(1,8,0,value);polls=polls+1;
      if(polls>100000)$fatal(1,"Trained DDR result watchdog");
    end
    if(value[1]||value[3]||value[5]||value[6]||!irq||fault||!job_owned||!job_retired&&retired_count==prior_retire)
      $fatal(1,"Trained job did not retain a successful retired result");
    expect_reg(32'h1c,job_tag);expect_reg(32'h20,tasks);expect_reg(32'h24,0);
    if(engine_writes-prior_writes!=32||dma_launches-prior_launches!=1||
       fabric_claims-prior_claims!=1||retired_count-prior_retire!=1||pending_writes!=0)
      $fatal(1,"Trained job bypassed exact writes/launch/fence/ECC retirement");
  endtask
  task automatic ack_trained;
    register_command(2,32'h0c,512'd2,value);
    polls=0;
    while(job_owned||!memory_ready||dut.control_owned)begin
      @(negedge c0_ui_clk);polls=polls+1;
      if(polls>100)$fatal(1,"Trained ACK did not release both owners");
    end
    if(irq||fault)$fatal(1,"Trained ACK left result/fault active");
  endtask
  initial begin
    cfg_reset=1;reset_req_valid=0;c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;
    c0_trained=0;bringup0=0;bringup1=0;commands=0;sequence_id=0;
    read64_packets=0;read64_axi_reads=0;actual_upload_lines=0;phase=-1;csr_base=0;
    if(!$value$plusargs("DIRECTORY=%s",directory)||
       !$value$plusargs("OUTPUT_DIRECTORY=%s",output_directory))$fatal(1,"Missing static trained-vector paths");
    repeat(5)@(negedge sys_clk);cfg_reset=0;
    polls=0;while(!req_ready)begin
      @(negedge c0_ui_clk);polls=polls+1;
      if(polls>10000)$fatal(1,"Trained endpoint boot admission timeout");
    end
    expect_reg(0,32'h524b4144);expect_reg(4,32'h10000);
    csr_base=32'h100;expect_reg(0,32'h524b4344);expect_reg(4,32'h10000);
    command(3,BASE,0,value,2);await_initialization();
    if(!reset_req_ready)$fatal(1,"Joint epoch reset owner is not idle after initialization");
    phase_log("initialized");
    command(3,BASE,0,value);if(value!==0)$fatal(1,"First initialized DDR line differs");
    command(3,BASE+32'hfffc0,0,value);if(value!==0)$fatal(1,"Last initialized DDR line differs");
    command(4,BASE+32'hfffc0,0,value);
    trained_upload("initial.txt",1408,1'b1);
    if(actual_upload_lines!=265)$fatal(1,"Changed complete trained initial upload inventory");
    for(phase=0;phase<3;phase=phase+1)begin
      if(phase==1)begin csr_base=0;trained_upload("ew_delta.txt",9,1'b0);end
      else begin
        csr_base=32'h100;
        if(phase==2)trained_upload("repeat_delta.txt",11,1'b0);
      end
      phase_log("uploaded");
      stage_trained(phase==1 ? 32'd22 : 32'd45,32'habc00001+32'(phase));
      prior_writes=engine_writes;prior_launches=dma_launches;
      prior_claims=fabric_claims;prior_retire=retired_count;
      register_command(2,32'h0c,512'd1,value);phase_log("submitted");
      // The other bank cannot stage, submit or ACK while this owner is held.
      command(2,csr_base==0 ? 32'h110 : 32'h10,512'h100e0000,value,2);
      command(2,csr_base==0 ? 32'h10c : 32'h0c,512'd1,value,2);
      command(2,csr_base==0 ? 32'h10c : 32'h0c,512'd2,value,2);
      command(3,BASE+32'h10000,0,value,2);
      await_trained(32'habc00001+32'(phase),phase==1 ? 32'd2 : 32'd1);
      phase_log("retired");
      if(phase==0)trained_check("cmac_expected.txt","cmac-actual.txt");
      else if(phase==1)trained_check("ew_expected.txt","ew-actual.txt");
      else trained_check("repeat_expected.txt","repeat-actual.txt");
      phase_log("readback_before_ack");ack_trained();phase_log("acknowledged");
    end
    if(inj_seen||engine_writes!=96||dut.engine.cmac.engine.rearm_count!=2||
       actual_upload_lines!=285||dma_launches!=3||fabric_claims!=3||retired_count!=3||
       read64_packets!=4226||read64_axi_reads!=4226||read_return_count!=27614)
      $fatal(1,"Trained alternation traffic, ownership or numerical rearm inventory differs");
    $display("PASS trained_tile_dual_ddr cmac_jobs=2 ew_tasks=2 engine_writes=96 rearm=2 checked_bo_lines=4224 phy_user_returns=27614 read64_packets=4226 read64_axi_reads=4226 scope=actual_AXI_UI_MC_modeled_PHY");
    $finish;
  end
  initial begin repeat(100000000)@(posedge c0_ui_clk);$fatal(1,"Trained joined DDR cycle watchdog");end
endmodule
'''
bench=OUT/'tb_jtag_dual_ddr_async.sv';bench.write_text(prefix+body)
inputs=dict(parent['inputs'])|dict(parent['files'])
inputs.update({str(parent_bench):sha(parent_bench),str(PARENT/'preparation.json'):sha(PARENT/'preparation.json'),
               str(VECTORS/'report.json'):sha(VECTORS/'report.json'),str(Path(__file__)):sha(__file__)})
for name,digest in inputs.items():need(sha(name)==digest,'Changed prepared dependency '+name)
files={str(path):sha(path) for path in OUT.rglob('*') if path.is_file()}
source=dict(parent)
for stale in ('cmac_case','inherited_ew_specs','inherited_faults_and_deadlines_changed'):
    source.pop(stale,None)
source.update(status='PREPARED_ORIGINAL_TRAINED_TILE_CMAC_EW_CMAC_SAME_EPOCH_CONTROLLER_TEST_ONLY',
    inputs=inputs,files=files,bench=str(bench),top='tb_jtag_dual_ddr_async',
    vectors=str(OUT/'vectors'),parent_joined_source=str(PARENT/'preparation.json'),
    expected=dict(cmac_jobs=2,ew_tasks=2,engine_writes=96,safe_cmac_rearms=2,
                  full_bo_lines_each=1408,total_checked_bo_bytes=270336,host_upload_lines=285,
                  phy_user_returns=27614,read64_packets=4226,read64_axi_reads=4226),
    source_commands_or_layout_changed=False,same_epoch_alternation_executed=False,hardware_accessed=False,
    fault_matrix_qualified=False,scenario='Trained positive CMAC/EW/CMAC same-epoch only; wrong-state CSR/memory accesses remain explicit failures')
(OUT/'preparation.json').write_text(json.dumps(source,indent=2)+'\n')
print(json.dumps(dict(status=source['status'],hdl_count=len(source['hdl_sources']),expected=source['expected'])))
