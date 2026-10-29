"""Prepare real full512 + AXI/UI/MC tests, with an explicitly modeled PHY.

No native tool, tensor encoder, numerical oracle or hardware API is executed.
CMAC fixtures copy original encoded words and numerical goldens byte-for-byte.
"""
from pathlib import Path
import hashlib
import json
import re
import shutil

ROOT=Path('/home/fedora/rknpu-fpga')
OUT=ROOT/'build/full512-ddr-preparation/joined-model-source-v1'
PARENT=ROOT/'build/ddr-read-snapshot-candidate/v2/workspace/build/ddr-endpoint-async/native-read-snapshot-v3'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def load(path):return json.loads(Path(path).read_text())


need(not OUT.exists(),'Fresh joined model preparation required')
OUT.mkdir()
inputs={}
def bind(path,expected=None):
    path=Path(path);digest=sha(path)
    need(expected is None or digest==expected,'Changed preparation source: '+str(path))
    inputs[str(path)]=digest
    return digest


bind(__file__)
parent_report=PARENT/'report.json';parent=load(parent_report);bind(parent_report)
combined_report=ROOT/'build/full512-ddr-preparation/combined-source-v6/preparation.json'
combined=load(combined_report);bind(combined_report)
fixture_root=ROOT/'tests/cmac/array_data'
for path in fixture_root.iterdir():
    if path.is_file():bind(path)

# Use the real old harness for its owned bus/retirement/fault assertions.
parent_tb=next(Path(name) for name in parent['compiler_sources'] if name.endswith('/tb_jtag_ew_ddr_async.sv'))
text=parent_tb.read_text();bind(parent_tb,parent['inputs'][str(parent_tb)])
text=text.replace('module tb_jtag_ew_ddr_async;', 'module tb_jtag_dual_ddr_async;')
text=text.replace('  rk_jtag_ew_ddr_async #(', '  rk_jtag_dual_ddr_async #(')
text=text.replace('  logic [15:0] sequence_id;', '''  logic [31:0] csr_base;
  wire [31:0] selected_identity=csr_base==32'h100 ? 32'h524b4344 : 32'h524b4144;
  logic [15:0] sequence_id;''')
# Redirect only register transactions; raw memory addresses/data stay unchanged.
text=re.sub(r'\bcommand\(([12]),',r'register_command(\1,',text)
anchor='  logic [511:0] value,upload_line,expected_line;'
need(text.count(anchor)==1,'Unexpected harness structure')
wrapper='''  task automatic register_command(input logic[7:0]op,input logic[31:0]offset,
    input logic[511:0]data,output logic[511:0]result,input logic[7:0]status=0,
    input logic[3:0]strobes=15);
    command(op,offset<32'h100 ? csr_base+offset : offset,data,result,status,strobes);
  endtask
'''
text=text.replace(anchor,wrapper+anchor)
text=text.replace("expect_reg(0,32'h524b4144)",'expect_reg(0,selected_identity)')
text=text.replace('dut.engine.engine.completed_tasks','dut.engine.ew.engine.completed_tasks')
init='''    if(!$value$plusargs("CSR_BASE=%h",csr_base))csr_base=0;
    if(csr_base!==0&&csr_base!==32'h100)$fatal(1,"Unsupported CSR namespace");
'''
anchor='    original_negative=negative_mode;'
need(text.count(anchor)==1,'Unexpected negative-mode initialization')
text=text.replace(anchor,init+anchor+'''
    if(negative_mode==10&&csr_base!=0)
      $fatal(1,"Partial linked-task fault control is defined only for EW");''')
text=text.replace('PASS jtag_ew_ddr_read_snapshot jobs=%0d',
                  'PASS jtag_dual_ddr_read_snapshot csr_base=%h jobs=%0d')
text=text.replace('submissions,original_negative,recovered,upload_count,uploaded_nonzero,expected_tasks,read_return_count,read64_packets,read64_axi_reads);',
                  'csr_base,submissions,original_negative,recovered,upload_count,uploaded_nonzero,expected_tasks,read_return_count,read64_packets,read64_axi_reads);')
tb=OUT/'source/tb_jtag_dual_ddr_async.sv';tb.parent.mkdir();tb.write_text(text)

# Merge actual handwritten and logical controller sources, never declaration stubs.
selected=[];by_name={}
def add(path,expected=None):
    path=Path(path);digest=bind(path,expected)
    if path.name in by_name:
        need(by_name[path.name]['sha256']==digest,'Nonidentical duplicate source '+path.name)
        return
    target=OUT/'source/hdl'/f'{len(selected):03d}'/path.name
    target.parent.mkdir(parents=True)
    shutil.copyfile(path,target)
    row=dict(path=str(target),sha256=sha(target),original=str(path),original_sha256=digest)
    by_name[path.name]=row;selected.append(row)

for name in combined['frontend_sources']:add(name,combined['files'][name])
for name in parent['compiler_sources']:
    if Path(name).name in ('tb_jtag_ew_ddr_async.sv','rk_jtag_ew_ddr_async.sv'):continue
    add(name,parent['inputs'][name])
assertions=ROOT/'build/tinystories-fpga-preparation/dual-v1/source/rtl/vendor/nvdla/compat'
for name in ('nv_assert_never.v','nv_assert_no_x.v'):add(assertions/name)

headers={}
for argument in parent['compile_plan'][0]:
    match=re.fullmatch(r'-D(RK_\w+_HEADER)="([^"]+)"',argument)
    if match is None:continue
    macro,source=match.groups();source=Path(source)
    bind(source,parent['inputs'][str(source)])
    target=OUT/'headers'/source.name;target.parent.mkdir(exist_ok=True)
    shutil.copyfile(source,target);headers[macro]=str(target)
need(len(headers)==5,'Missing actual controller/test parameter headers')

# Form BOs from the exact original hex dumps. No arithmetic or layout is derived.
def values(name,count,bits):
    rows=(fixture_root/name).read_text().splitlines()
    need(len(rows)==count and all(re.fullmatch(r'[0-9a-fA-F]+',s) for s in rows),'Malformed original fixture '+name)
    result=[int(s,16) for s in rows]
    need(all(0<=x<1<<bits for x in result),'Original fixture width changed')
    return result
commands=values('commands.hex',49,64)
operands=values('input.hex',192,16)
weights=values('weight.hex',3072,16)
writes=values('writes.hex',64,48)
regions={0x10010000:bytearray(4096),0x10020000:bytearray(8192),
         0x10040000:bytearray(b'\x5a\xa5'*2048),0x100e0000:bytearray(4096)}
for address,items,size in [(0x10010000,operands,2),(0x10020000,weights,2),(0x100e0000,commands,8)]:
    raw=b''.join(value.to_bytes(size,'little') for value in items)
    regions[address][:len(raw)]=raw
before={a:bytes(data) for a,data in regions.items()}
seen=set()
for write in writes:
    address,value=write>>16,write&65535
    need(address%2==0 and 0x10040000<=address<0x10041000 and address not in seen,
         'Invalid original physical write inventory')
    seen.add(address);offset=address-0x10040000
    regions[0x10040000][offset:offset+2]=value.to_bytes(2,'little')
vector=OUT/'vectors/cmac_k65';vector.mkdir(parents=True)
for name,memory in [('upload.txt',before),('expected.txt',regions)]:
    lines=[]
    for address,data in sorted(memory.items()):
        for offset in range(0,len(data),64):
            lines.append(f'{address+offset:08x} {int.from_bytes(data[offset:offset+64],"little"):0128x}\n')
    (vector/name).write_text(''.join(lines))
need(len(lines)==320,'Changed complete physical CMAC BO inventory')
files={str(path):sha(path) for path in OUT.rglob('*') if path.is_file()}
report=dict(status='PREPARED_REAL_FULL512_DUAL_AXI_UI_MC_TEST_WITH_MODELED_PHY_ONLY',
    inputs=inputs,files=files,hdl_sources=selected,hdl_count=len(selected),bench=str(tb),
    top='tb_jtag_dual_ddr_async',headers=headers,verilog_defines=['DESIGNWARE_NOEXIST','ASSERT_ON'],
    parameter_span=dict(base=0x10000000,bytes=1048576),
    cmac_case=dict(name='cmac_k65',case_dir=str(vector),address=0x100e0000,amount=45,tasks=1,
                   lines=320,complete_bo_bytes=20480,csr_base=0x100,expected_write_halfwords=64),
    inherited_ew_specs=parent['specs'],inherited_faults_and_deadlines_changed=False,
    command_words_or_numerics_changed=False,cpu_arithmetic_or_layout_repair=False,
    numerical_execution_performed=False,logical_controller_execution_performed=False,
    physical_phy_or_training_qualified=False,hardware_accessed=False)
(OUT/'preparation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({key:value for key,value in report.items() if key not in ('inputs','files','hdl_sources','inherited_ew_specs')}))
