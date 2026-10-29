#!/usr/bin/env python3
"""Prepare actual 50-bit demo/response/DMA temporal safety model, not a proof.

Add the three native DMA state bits and actual request-valid/reset aliases to
the completed 47-bit controller work. Keep the full 503128-cell C32/K16 input,
all 512 simultaneous products and strict register/primitive producer rules.
The clocked test model keeps actual controller state initially unconstrained,
starts ghost checking only after an observed binary reset, and allows all
other producers to vary each cycle. Count actual accepted initialization
writes and track an arbitrary reset-sampled probe address. Prepare ownership,
prefix-coverage and write-before-core-request invariants, not a temporal PASS.
No original helper, model, RTL, input, live job or SHA256SUMS is changed.
"""
from collections import Counter
import inspect
import json
from pathlib import Path
import re
import sys

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
import audit_prefix_initialization_controller_cone as base
import prove_prefix_initialization_controller_independence as proof
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report,verify_bindings

ROOT=base.ROOT
PARENT=ROOT/'build/openxc7/prefix-initialization-controller-independence-1791446683425337841/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_temporal_controller_cone_control.py'
DMA_SOURCE=ROOT/'rtl/cmac/rk_cmac_array_dma.sv'
DMA_ENUM='typedef enum logic [2:0] {IDLE,CHECK,FETCH_REQ,FETCH_WAIT,SEND,RUN} state_t;'
REGISTERS={**base.REGISTERS,'demo.engine.state':3}
OUTPUTS=(*base.OUTPUTS,'demo.mem_req_valid')
WIDTHS={**REGISTERS,**dict.fromkeys(OUTPUTS,1),'demo.memory.host_rdata':16,'demo.memory.clk':1,'demo.rst_n':1}
PASS='EXTRACTED_ACTUAL_50_BIT_TEMPORAL_CONTROLLER_AND_FRONTEND_CHECKED_RESET_GUARDED_CLOCKED_MODEL_NOT_TEMPORAL_PROOF_OR_STARTUP_SIGNOFF'


def admit(before):
    r=json.loads(PARENT.read_text())
    assert r['status']==proof.PASS and r['stage']=='complete' and r['finished_utc']
    assert r['full_target_parallel_products']==512 and r['proof_is_binary_single_step_conditional_only']
    assert r['initialization_controller_data_independence_proved']
    assert r['temporal_port_ownership_proved'] is False and r['write_before_read_proved'] is False
    bind_report(PARENT,r,before)
    proof.admit(before)
    cmds={c['label']:c for c in r['commands']}
    bench=PARENT.parent/'binary_library_control.sv'
    footer=proof.prior.results.expected_finish(bench,bench.read_text())
    vendor=Path(cmds['vendor_test']['log']).read_text()
    assert proof.compare_corpora(vendor,Path(cmds['synthesis_test']['log']).read_text(),1413,footer)==r['binary_library_qualification']
    proof.validate_wrong_corpus(vendor,Path(cmds['synthesis_wrong_golden_test']['log']).read_text(),1413,footer)
    for label,negative in (('negative',True),('positive',False)):
        c=cmds[label];proof.controller.prior.state.raw.validate_result(Path(c['log']).read_text(),c['returncode'],negative)
    verify_bindings(before)
    return r['actual_full_primitive_counts']


NAMESPACE=dict(base.__dict__,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,PASS=PASS,
               REGISTERS=REGISTERS,OUTPUTS=OUTPUTS,WIDTHS=WIDTHS,admit=admit,DMA_SOURCE=DMA_SOURCE,DMA_ENUM=DMA_ENUM)
TRACE_SOURCE=source_shaped(inspect.getsource(base.trace_controller),(
    ('assert len(registers) == 47 and len({r[\'cell\'] for r in registers}) == 47',
     'assert len(registers) == 50 and len({r[\'cell\'] for r in registers}) == 50'),))
exec(compile(inspect.getsource(base.aliases),__file__+':exact-expanded-aliases','exec'),NAMESPACE)
expanded_aliases=NAMESPACE['aliases']
exec(compile(TRACE_SOURCE,__file__+':exact-expanded-controller-trace','exec'),NAMESPACE)
trace_controller=NAMESPACE['trace_controller']
MITER_SOURCE=source_shaped(inspect.getsource(base.miter),(
    ('assert len(host) == 16 and len(registers) == 47 and other','assert len(host) == 16 and len(registers) == 50 and other'),
    ('prefix_init_controller_miter','prefix_temporal_controller_miter'),))
exec(compile(MITER_SOURCE,__file__+':exact-expanded-controller-miter','exec'),NAMESPACE)
miter=NAMESPACE['miter']


def aliases(logical,physical):
    result=expanded_aliases(logical,physical)
    record=base.prior.state.named_net(logical,'demo.engine.state',base.prior.state.netname_region(logical))
    expected={f'enum_value_{i:03b}':'\\'+name for i,name in enumerate(('IDLE','CHECK','FETCH_REQ','FETCH_WAIT','SEND','RUN'))}
    actual={k:v for k,v in record['attributes'].items() if k.startswith('enum_value_')}
    assert actual==expected,'Changed native three-bit DMA state encoding'
    assert result['demo.rst_n']==[15190],'Changed literal outer reset producer'
    return result


def clock_model(cone):
    nodes=cone['cells'];cuts={int(w):r for w,r in cone['producer_cuts'].items()}
    regs=cone['controller_registers'];assert len(regs)==50
    q={r['original_primitive']['connections']['Q'][0]:i for i,r in enumerate(regs)}
    assert len(q)==50 and all(q[w]==sum(list(REGISTERS.values())[:list(REGISTERS).index(name)])+i
        for name in REGISTERS for i,w in enumerate(cone['signals'][name]))
    other={w:i for i,w in enumerate(sorted(set(cuts)-set(q)))}
    reset=cone['signals']['demo.rst_n'][0]
    assert reset in other and cuts[reset]['original_primitive']['type']=='FDCE'
    def bit(w,copy):
        if w in ('0','1'):return "1'b"+w
        if w in q:return ('storage_state' if copy==0 else 'next_clock')+'['+str(q[w])+']'
        if w in other:return 'producer_input['+str(other[w])+']'
        return 't'+str(copy)+'_'+str(w)
    def bus(bits,copy):return '{'+','.join(bit(w,copy) for w in reversed(bits))+'}'
    lines=['module prefix_temporal_controller_model #(parameter NEGATIVE=0)(',
        'input clk,input ['+str(len(other)-1)+':0] producer_input,input [11:0] arbitrary_probe,output ok);',
        '// Actual state has no initial assignment; all producer inputs are free each cycle.',
        'reg [49:0] storage_state;','wire [49:0] next_clock;']
    for copy in (0,1):
        wires={w for c in nodes.values() for b in c['connections'].values() for w in b if type(w) is int and w not in cuts}
        lines+=['wire '+bit(w,copy)+';' for w in sorted(wires)]
        for i,(name,cell) in enumerate(sorted(nodes.items())):
            _,outputs=base.prior.state.coherent.validate_cell(cell)
            assert not any(w in cuts for p in outputs for w in cell['connections'][p])
            parameter=''
            if cell['type'].startswith('LUT'):
                init=cell['parameters']['INIT'];parameter=' #(.INIT('+str(len(init))+"'b"+init+'))'
            lines.append(cell['type']+parameter+' temporal_'+str(copy)+'_'+str(i)+'('+','.join(
                '.'+p+'('+bus(b,copy)+')' for p,b in sorted(cell['connections'].items()))+');')
    folded=[];settled=[]
    for i,r in enumerate(regs):
        c=r['original_primitive'];base.validate_fold_register(c,cone['signals']['demo.memory.clk'])
        p=c['connections']
        folded.append('('+bit(p['CLR'][0],0)+" ? 1'b0 : "+bit(p['CE'][0],0)+' ? '+bit(p['D'][0],0)+' : '+bit(p['Q'][0],0)+')')
        settled.append('('+bit(p['CLR'][0],1)+" ? 1'b0 : next_clock["+str(i)+'])')
    lines+=['assign next_clock={'+','.join(reversed(folded))+'};',
        '// Re-evaluate actual async clear roots after the clocked Q change.',
        'wire [49:0] after_async_clear={'+','.join(reversed(settled))+'};',
        'always @(posedge clk) storage_state<=after_async_clear;']
    for name,signal in (('reset_n','demo.rst_n'),('host_fire','demo.memory.host_fire'),
        ('core_fire','demo.memory.core_fire'),('host_write','demo.host_write'),('request_valid','demo.mem_req_valid')):
        lines.append('wire '+name+'='+bit(cone['signals'][signal][0],0)+';')
    for name,signal in (('demo_state','demo.state'),('index','demo.index'),('dma_state','demo.engine.state')):
        width=len(cone['signals'][signal]);lines.append('wire ['+str(width-1)+':0] '+name+'='+bus(cone['signals'][signal],0)+';')
    lines+=['// Only the ghost enable is initialized; real state is not assigned an INIT.',
        "reg seen_reset=1'b0;reg [12:0] writes_seen;reg [11:0] probe;reg probe_written;",
        'always @(posedge clk) begin',
        "  if(!reset_n) begin seen_reset<=1'b1;writes_seen<=13'd0;probe<=arbitrary_probe;probe_written<=1'b0;end",
        '  else if(host_fire&&host_write) begin',
        "    writes_seen<=writes_seen+13'd1;",
        "    if(index==probe) probe_written<=1'b1;",
        '  end','end',
        "wire init_address_phase=(demo_state==4'd0||demo_state==4'd1);",
        "wire init_response_phase=(demo_state==4'd2);",
        "wire normal_after_init=(demo_state>=4'd3&&demo_state<=4'd9);",
        "wire idle_owned_phase=(demo_state!=4'd4);",
        'wire prefix_coverage=(probe_written==({1\'b0,probe}<writes_seen));',
        "wire index_relation=(!init_address_phase||(writes_seen=={1'b0,index}))&&",
        " (!init_response_phase||(writes_seen==({1'b0,index}+13'd1)));",
        "wire coverage_bound=(writes_seen<=13'd4096)&&(!normal_after_init||writes_seen==13'd4096);",
        "wire state_bound=(demo_state<=4'd10)&&(dma_state<=3'd5);",
        "wire dma_idle_relation=(!idle_owned_phase||dma_state==3'd0);",
        'wire ports_exclusive=!(host_fire&&core_fire);',
        "wire core_after_complete=(!request_valid||writes_seen==13'd4096);",
        'wire safe=prefix_coverage&&index_relation&&coverage_bound&&state_bound&&dma_idle_relation&&ports_exclusive&&core_after_complete;',
        'assign ok=(!seen_reset||!reset_n)||(safe ^ (NEGATIVE!=0));','endmodule']
    text='\n'.join(lines)+'\n'
    assert not re.search(r'\b(?:assume|anyseq|anyconst|force)\b',text)
    assert text.count('reg [49:0] storage_state;')==1 and 'storage_state=' not in text
    return text


NEW_FRONTEND="""        temporal_source=out/'actual-binary-temporal-controller.v';temporal_source.write_text(clock_model(cone))
        temporal_script=out/'temporal_frontend_check.ys'
        temporal_script.write_text('read_verilog '+str(library)+'\\nread_verilog '+str(temporal_source)+'\\nhierarchy -check -top prefix_temporal_controller_model\\nproc\\nflatten\\nopt -full\\ncheck -assert\\nstat\\n')
        execution.update({str(p):digest(p) for p in (temporal_source,temporal_script)})
        report.update(stage='actual_reset_guarded_clocked_model_frontend_only',actual_controller_state_initially_unconstrained=True,
            ghost_checking_starts_only_after_observed_reset=True,other_producers_free_each_cycle=True,
            arbitrary_probe_sampled_only_on_reset=True,actual_post_edge_async_clear_roots_recomputed=True,
            temporal_port_ownership_proved=False,write_before_read_proved=False)
        save();run('temporal_frontend_check',['yosys','-Q','-T','-s',temporal_script])
"""
MAIN_SOURCE=source_shaped(inspect.getsource(base.main),(
    ('prefix-initialization-controller-cone-','prefix-temporal-controller-cone-'),
    ('controller_state_bits=47, observed_control_bits=9','controller_state_bits=50, observed_control_bits=10'),
    ('fresh_full_driver_census_and_47_bit_controller_cone','fresh_full_driver_census_and_50_bit_temporal_controller_cone'),
    ("ROOT/'rtl/cmac/rk_cmac_demo_memory.sv',","ROOT/'rtl/cmac/rk_cmac_demo_memory.sv', DMA_SOURCE,"),
    ('assert prior.state.STATE_ENUM in prior.state.STATE_SOURCE.read_text()',
     'assert prior.state.STATE_ENUM in prior.state.STATE_SOURCE.read_text()\n        assert DMA_ENUM in DMA_SOURCE.read_text()'),
    ('compared_output_bits=56,','compared_output_bits=60,'),
    ('prefix_init_controller_miter','prefix_temporal_controller_miter'),
    ('        verify_bindings(before); verify_bindings(execution)\n',NEW_FRONTEND+'        verify_bindings(before); verify_bindings(execution)\n'),))
NAMESPACE.update(aliases=aliases,clock_model=clock_model)
exec(compile(MAIN_SOURCE,__file__+':full-expanded-controller-and-clock-model-preparation','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
