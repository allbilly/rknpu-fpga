"""Move identical data-side preparation outside the sixteen C32 kernels.

This unqualified area candidate changes no register profile, operand format,
rounding, accumulation order or pipeline stage. Original per-kernel payload
registers remain. Weight-side decode and weight-before-data NaN priority stay
local to each kernel. No native tool or hardware is run by this preparation.
"""
from pathlib import Path
import hashlib
import json
import re

ROOT=Path('/home/fedora/rknpu-fpga')
PARENT=ROOT/'build/tinystories-fpga-preparation/dual-v1/source/rtl/cmac/experimental'
OUT=ROOT/'build/full512-ddr-preparation/shared-data-candidate-v2'


def need(ok,message):
    if not ok:raise RuntimeError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


need(not OUT.exists(),'Fresh shared-data source candidate required')
OUT.mkdir()
cell_source=PARENT/'rk_cmac_fp16_cell_dsp_prefix_pipe.sv'
array_source=PARENT/'rk_cmac_fp16_array_dsp_prefix_pipe.sv'
cell=cell_source.read_text()
old='''    input wire [ATOMIC_C*16-1:0] data,weight,
    input wire [ATOMIC_C-1:0] data_mask,weight_mask,'''
new='''    input wire [ATOMIC_C*16-1:0] data_operand,weight,
    input wire [ATOMIC_C*3-1:0] data_exponent,
    input wire [ATOMIC_C-1:0] data_nonzero,weight_mask,
    input wire data_nan,
    input wire [10:0] data_payload,'''
need(cell.count(old)==1,'Unexpected old cell ports')
cell=cell.replace(old,new)
cell=cell.replace('    wire [15:0] a[ATOMIC_C],b[ATOMIC_C];','    wire [15:0] b[ATOMIC_C];')
cell=cell.replace('    wire [14:0] am[ATOMIC_C],bm[ATOMIC_C];','    wire [14:0] bm[ATOMIC_C];')
cell=cell.replace('        assign a[i]=data[i*16+:16];\n','')
cell=cell.replace('data_mask[i]&&weight_mask[i]&&(a[i][14:0]!=0)&&(b[i][14:0]!=0)',
                  'data_nonzero[i]&&weight_mask[i]&&(b[i][14:0]!=0)')
cell=cell.replace('        assign am[i]={4\'d0,(a[i][14:10]!=0),a[i][9:0]} << (a[i][14:10]==0 ? 2\'d1:a[i][11:10]);\n','')
cell=cell.replace("{1'b0,a[i][14:12]}+{1'b0,b[i][14:12]}",
                  "{1'b0,data_exponent[i*3+:3]}+{1'b0,b[i][14:12]}")
old='''        for(integer i=0;i<ATOMIC_C;i=i+1)
            if(!nan_found&&data_mask[i]&&a[i][14:10]==31&&a[i][9:0]!=0)begin
                nan_found=1;nan_payload={a[i][15],a[i][9:0]};
            end'''
need(cell.count(old)==1,'Unexpected data NaN scan')
cell=cell.replace(old,'''        if(!nan_found&&data_nan)begin
            nan_found=1;nan_payload=data_payload;
        end''')
cell=cell.replace('saved_b[i]<={a[i][15],am[i]};','saved_b[i]<=data_operand[i*16+:16];')
need(re.search(r'\ba\[i\]|\bam\[i\]|\bdata_mask\b',cell) is None,'Stale private data decode remains')
array=array_source.read_text()
anchor='    for(genvar k=0;k<ATOMIC_K;k=k+1)begin: kernels'
need(array.count(anchor)==1,'Unexpected array kernel structure')
common='''    wire [ATOMIC_C*16-1:0] shared_data_operand;
    wire [ATOMIC_C*3-1:0] shared_data_exponent;
    wire [ATOMIC_C-1:0] shared_data_nonzero;
    wire shared_data_nan;
    wire [10:0] shared_data_payload;
    rk_cmac_fp16_shared_data #(.ATOMIC_C(ATOMIC_C)) data_prep (
        .data(in_data),.mask(in_data_mask),.operand(shared_data_operand),
        .exponent(shared_data_exponent),.nonzero(shared_data_nonzero),
        .nan_found(shared_data_nan),.nan_payload(shared_data_payload));
'''
array=array.replace(anchor,common+anchor)
array=array.replace('            .clk,.capture,.data(in_data),',
    '            .clk,.capture,.data_operand(shared_data_operand),\n'
    '            .data_exponent(shared_data_exponent),.data_nonzero(shared_data_nonzero),\n'
    '            .data_nan(shared_data_nan),.data_payload(shared_data_payload),')
array=array.replace('.data_mask(in_data_mask),.weight_mask(','.weight_mask(')
shared='''// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact data-side expressions from the original cell, computed once per frame.
// Weight-side preparation and maximum alignment remain per kernel. This is
// combinational integer operand encoding, with no new rounding boundary.
module rk_cmac_fp16_shared_data #(parameter int unsigned ATOMIC_C=32) (
    input wire [ATOMIC_C*16-1:0] data,
    input wire [ATOMIC_C-1:0] mask,
    output wire [ATOMIC_C*16-1:0] operand,
    output wire [ATOMIC_C*3-1:0] exponent,
    output wire [ATOMIC_C-1:0] nonzero,
    output logic nan_found,
    output logic [10:0] nan_payload
);
    for(genvar i=0;i<ATOMIC_C;i=i+1)begin: lanes
        wire [15:0] a=data[i*16+:16];
        wire [14:0] magnitude={4'd0,(a[14:10]!=0),a[9:0]} << (a[14:10]==0 ? 2'd1:a[11:10]);
        assign operand[i*16+:16]={a[15],magnitude};
        assign exponent[i*3+:3]=a[14:12];
        assign nonzero[i]=mask[i]&&(a[14:0]!=0);
    end
    always @* begin
        nan_found=0;nan_payload=0;
        for(integer i=0;i<ATOMIC_C;i=i+1)
            if(!nan_found&&mask[i]&&data[i*16+10+:5]==31&&data[i*16+:10]!=0)begin
                nan_found=1;nan_payload={data[i*16+15],data[i*16+:10]};
            end
    end
endmodule
'''
paths={cell_source.name:cell,array_source.name:array,'rk_cmac_fp16_shared_data.sv':shared}
for name,text in paths.items():(OUT/name).write_text(text)
record=dict(status='PREPARED_UNQUALIFIED_SHARED_DATA_DECODE_AREA_CANDIDATE',
    inputs={str(cell_source):sha(cell_source),str(array_source):sha(array_source),str(Path(__file__)):sha(__file__)},
    files={str(OUT/name):sha(OUT/name) for name in paths},atomic_c_supported=[8,32,64],target_atomic_k=16,
    product_lanes_target=512,source_contract='Identical magnitude/sign/exponent/nonzero and lowest-data-NaN preparation shared across kernels; weight NaN still wins, even for masked pairs',
    per_kernel_capture_registers_retained=True,pipeline_stages_or_rounding_changed=False,
    raw_commands_or_layout_changed=False,equivalence_qualified=False,resource_fit_qualified=False,
    hardware_accessed=False)
(OUT/'preparation.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({key:value for key,value in record.items() if key not in ('inputs','files')}))
