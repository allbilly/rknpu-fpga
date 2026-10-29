#!/usr/bin/env python3
"""Prepare/decode root-executed native Vivado SAMPLE scans. No hardware calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_suffix('.tcl.in')
PART = 'xc7k480tffg1156-2'
PINS = dict(pass_flag=dict(pin='P30', output_cell=852, disable_cell=851, input_cell=853),
            fail_flag=dict(pin='M30', output_cell=846, disable_cell=845, input_cell=847),
            heartbeat=dict(pin='N30', output_cell=849, disable_cell=848, input_cell=850))


def require(condition, message):
    if not condition:raise ValueError(message)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def load_json(path):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON key: '+key);result[key]=value
        return result
    def constant(value):raise ValueError('Nonfinite JSON constant: '+value)
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=constant)


def bsdl_contract(path):
    text=Path(path).read_text()
    require(len(re.findall(r'(?im)^entity\s+XC7K480T_FFG1156\s+is\s*$',text))==1,'Wrong BSDL entity')
    for name,value in [('INSTRUCTION_LENGTH',6),('BOUNDARY_LENGTH',1395)]:
        found=re.findall(r'attribute\s+'+name+r'\s+of\s+XC7K480T_FFG1156\s*:\s*entity\s+is\s+(\d+)\s*;',text,re.I)
        require(found==[str(value)],'Wrong BSDL '+name)
    for name,opcode in [('IDCODE','001001'),('SAMPLE','000001'),('BYPASS','111111')]:
        require(re.findall(r'"\s*'+name+r'\s*\(([01]+)\)',text)==[opcode],'Wrong BSDL opcode: '+name)
    capture=re.findall(r'attribute\s+INSTRUCTION_CAPTURE\s+of\s+XC7K480T_FFG1156\s*:\s*entity\s+is[\s\S]*?"([X01]+)"',text,re.I)
    require(capture==['XXXX01'],'Wrong BSDL instruction capture contract')
    for signal,pin in PINS.items():
        out=re.findall(r'"\s*(\d+)\s*\(BC_2,\s*IO_'+pin['pin']+r',\s*output3,\s*X,\s*(\d+),\s*1,\s*Z\)',text)
        inp=re.findall(r'"\s*(\d+)\s*\(BC_2,\s*IO_'+pin['pin']+r',\s*input,\s*X\)',text)
        require(out==[(str(pin['output_cell']),str(pin['disable_cell']))] and inp==[str(pin['input_cell'])],
                'Wrong BSDL cells: '+signal)
        control=re.findall(r'"\s*'+str(pin['disable_cell'])+r'\s*\(BC_2,\s*\*,\s*controlr,\s*1\)',text)
        require(len(control)==1,'Missing disable cell: '+signal)
        require('IO_'+pin['pin']+':'+pin['pin']+',' in text,'Wrong physical pin map')
    return dict(entity='XC7K480T_FFG1156',sha256=digest(path),boundary_length=1395,
                instruction_length=6,opcodes=dict(IDCODE='09',SAMPLE='01',BYPASS='3f'),pins=PINS)


def tcl_literal(value):
    encoded=str(value).encode().hex()
    return '[encoding convertfrom utf-8 [binary format H* {'+encoded+'}]]'


def source_contract(path):
    report=load_json(path)
    require(type(report.get('schema')) is int and report['schema']==1 and report['status']=='PREPARED_EW_CHECKPOINT_ONLY' and report['profile']=='startup'
            and report['part']==PART and report['clock_hz']==50000000,'Expected EW startup preparation report')
    files=report['hardware_inputs']['files']
    required={'fpga/ypcb_ew_startup_top.sv','fpga/ypcb_ew_startup.xdc','rtl/rk_ew_dma_demo.sv',
              'rtl/rk_dma_demo_rom.sv','rtl/rk_demo_memory.sv','rtl/rk_startup_reset.sv',
              'rtl/rk_ew_dma.sv','rtl/rk_ew_engine.sv','rtl/rk_ew_regs.sv','rtl/rk_fp16_alu.sv','rtl/rk_bram.sv'}
    require(set(files)==required,'Unexpected compiled EW hardware inventory')
    root=Path(path).parent/'source'
    for name,expected in files.items():
        require(re.fullmatch('[0-9a-f]{64}',expected) and digest(root/name)==expected,'EW source snapshot changed: '+name)
    return dict(preparation_report_sha256=digest(path),hardware_inputs=report['hardware_inputs'],
                production_source_sha256=report['production_revision']['sha256'])


def prepare(bitstream,source_report,bsdl,out,target,server,led_active_low=0,samples=101,interval_ms=50,tck_hz=3000000):
    bitstream=Path(bitstream).resolve(strict=True);source_report=Path(source_report).resolve(strict=True)
    bsdl=Path(bsdl).resolve(strict=True);out=Path(out).absolute()
    require(not out.exists(),'Use a fresh observer directory')
    require(type(led_active_low) is int and led_active_low in (0,1),'LED polarity must be the compiled integer generic')
    require(type(samples) is int and 10<=samples<=1000 and type(interval_ms) is int and 20<=interval_ms<=500,
            'Unsupported sample count/interval')
    require(3000<=(samples-1)*interval_ms<=30000,'Capture must span 3..30 seconds')
    require(type(tck_hz) is int and tck_hz==3000000,'Use the audited 3-MHz cable setting')
    require(type(target) is str and target.startswith(server+'/') and not any(c in target for c in '\r\n\x00'),
            'Require an exact audited target URI')
    contract=bsdl_contract(bsdl)
    source=source_contract(source_report)
    binding=dict(schema_version=1,trial_id=uuid.uuid4().hex,part=PART,idcode='0x23751093',target=target,server=server,
        bitstream=dict(path=str(bitstream),sha256=digest(bitstream),bytes=bitstream.stat().st_size),
        source_report=dict(path=str(source_report),sha256=digest(source_report),binding=source),bsdl=contract,
        led_active_low=led_active_low,samples=samples,interval_ms=interval_ms,requested_tck_hz=tck_hz,
        source_scope='EWstartup SUB9; two completed tasks and336checked halfwords inferred from bound built-in scoreboard; no direct memory readback')
    binding_sha=hashlib.sha256(canonical(binding)).hexdigest()
    text=TEMPLATE.read_text()
    values=dict(TARGET=tcl_literal(target),SERVER=tcl_literal(server),OUTPUT=tcl_literal(out/'capture.tsv'),
        BINDING=tcl_literal(binding_sha),SAMPLES=str(samples),INTERVAL=str(interval_ms),TCK=str(tck_hz))
    for key,value in values.items():
        token='@'+key+'@';require(text.count(token)==1,'Unexpected template marker: '+key);text=text.replace(token,value)
    out.mkdir(parents=True);snap=out/'source';snap.mkdir()
    for path,name in [(Path(__file__),'sample_ew.py'),(TEMPLATE,'sample_ew.tcl.in'),(bsdl,'xc7k480t_ffg1156.bsd')]:
        shutil.copy2(path,snap/name)
    shutil.copy2(source_report,snap/'source-report.json')
    for name in source['hardware_inputs']['files']:
        target=snap/'hardware'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source_report.parent/'source'/name,target)
    script=out/'capture.tcl';script.write_text(text)
    plan=dict(status='PREPARED_SAMPLE_OBSERVER_ONLY',binding=binding,binding_sha256=binding_sha,
        tcl_sha256=digest(script),observer_sha256=digest(__file__),template_sha256=digest(TEMPLATE),
        hardware_accessed=False,programming_performed=False,flash_written=False)
    (out/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return plan


def parse_capture(path,plan):
    lines=Path(path).read_text().splitlines();metadata={};cleanup={};rows=[];ended=False
    for line in lines:
        require(not ended,'Capture data after END')
        fields=line.split('|');require(fields[0]=='EWSAMPLE1' and len(fields)>=3,'Unknown capture format')
        key=fields[1]
        if key in ('BINDING','TOOL','TARGET','TCK','IDCODE'):
            require(len(fields)==3 and key not in metadata and not rows,'Duplicate/misordered capture metadata')
            metadata[key]=fields[2]
        elif key=='ROW':
            require(len(fields)==7 and not cleanup,'Wrong capture row')
            index,epoch,elapsed=map(int,fields[2:5]);ir,raw=fields[5:7]
            require(index==len(rows) and epoch>0 and elapsed>=0,'Capture sequence/time differs')
            require(re.fullmatch('[0-9a-f]{2}',ir) and int(ir,16)<64,'Wrong captured IR')
            require(re.fullmatch('[0-9a-f]{349}',raw) and int(raw,16).bit_length()<=1395,'Wrong boundary width/padding')
            if rows:require(elapsed>rows[-1]['elapsed_us'],'Capture times must increase')
            value=int(raw,16)
            rows.append(dict(index=index,epoch_us=epoch,elapsed_us=elapsed,capture_ir=ir,boundary_hex=raw,
                outputs={name:(value>>pin['output_cell'])&1 for name,pin in PINS.items()},
                disabled={name:(value>>pin['disable_cell'])&1 for name,pin in PINS.items()},
                inputs={name:(value>>pin['input_cell'])&1 for name,pin in PINS.items()}))
        elif key=='CLEANUP':
            require(len(fields)==4 and fields[2] in ('BYPASS','TARGET','SERVER','MANAGER') and
                    fields[2] not in cleanup and fields[3]=='1','Capture cleanup failed')
            cleanup[fields[2]]=True
        elif key=='END':
            require(len(fields)==4 and int(fields[2])==len(rows) and fields[3]=='1','Capture did not complete')
            ended=True
        else:raise ValueError('Capture failed/contains unsupported record: '+key)
    require(ended and set(metadata)=={'BINDING','TOOL','TARGET','TCK','IDCODE'} and
            set(cleanup)=={'BYPASS','TARGET','SERVER','MANAGER'},'Incomplete capture receipt')
    binding=plan['binding']
    require(metadata['BINDING']==plan['binding_sha256'] and metadata['IDCODE']=='23751093' and
            bytes.fromhex(metadata['TARGET']).decode()==binding['target'] and int(metadata['TCK'])==binding['requested_tck_hz'],
            'Capture identity/binding differs')
    tool=bytes.fromhex(metadata['TOOL']).decode();require(tool.strip(),'Missing actual tool version')
    require(len(rows)==binding['samples'] and rows[-1]['elapsed_us']-rows[0]['elapsed_us']>=3000000,
            'Sample count/duration differs')
    return dict(tool_version=tool,target=binding['target'],reported_tck_hz=int(metadata['TCK']),samples=rows,cleanup=cleanup)


def decode(plan_path,capture_path,kind,load_receipt=None):
    plan_path=Path(plan_path);plan=load_json(plan_path);binding=plan['binding']
    require(plan['status']=='PREPARED_SAMPLE_OBSERVER_ONLY' and
            hashlib.sha256(canonical(binding)).hexdigest()==plan['binding_sha256'],'Plan binding changed')
    require(binding['part']==PART and binding['idcode']=='0x23751093' and binding['bsdl']['pins']==PINS and
            binding['bsdl']['boundary_length']==1395 and binding['bsdl']['instruction_length']==6,'Plan part/pins differ')
    package=plan_path.parent
    require(digest(package/'capture.tcl')==plan['tcl_sha256'] and
            digest(package/'source/sample_ew.py')==plan['observer_sha256'] and
            digest(package/'source/sample_ew.tcl.in')==plan['template_sha256'] and
            bsdl_contract(package/'source/xc7k480t_ffg1156.bsd')==binding['bsdl'],'Observer source/BSDL changed')
    require(digest(package/'source/source-report.json')==binding['source_report']['sha256'],
            'Bound preparation report changed')
    for name,expected in binding['source_report']['binding']['hardware_inputs']['files'].items():
        require(digest(package/'source/hardware'/name)==expected,'Bound hardware source changed: '+name)
    result=parse_capture(capture_path,plan)
    rows=result['samples'];low=binding['led_active_low'];heartbeat=[r['outputs']['heartbeat'] for r in rows]
    require(type(low) is int and low in (0,1),'Plan LED polarity must be an integer 0 or 1')
    transitions=sum(a!=b for a,b in zip(heartbeat,heartbeat[1:]))
    result.update(schema_version=1,kind=kind,bitstream_sha256=binding['bitstream']['sha256'],
        source_report_sha256=binding['source_report']['sha256'],plan_sha256=digest(plan_path),
        capture_sha256=digest(capture_path),heartbeat_transitions=transitions,
        capture_hardware_accessed=True,decoder_hardware_accessed=False,programming_performed=False,
        flash_written=False,application_outputs_observed=False,optical_led_polarity_verified=False,
        direct_memory_readback=False,source_scope=binding['source_scope'])
    require(kind in ('baseline','post-load','repeat','reconfiguration'),'Unknown capture kind')
    if kind=='baseline':
        require(load_receipt is None,'Baseline must not imply a candidate image load')
        result['status']='CAPTURED_BASELINE_APPLICATION_UNKNOWN'
    else:
        require(load_receipt is not None,'Post-load observation requires a successful matching load receipt')
        receipt=load_json(load_receipt)
        require(receipt['status']=='PASS' and receipt['action']=='program-sram' and receipt['hardware_programmed'] is True
                and receipt['flash_written'] is False and receipt['bitstream_sha256']==binding['bitstream']['sha256']
                and receipt['idcode']=='0x23751093' and receipt['target']==binding['target'],'Load receipt differs')
        require(receipt.get('source_report_sha256')==binding['source_report']['sha256'],
                'Load receipt source report differs')
        compiled_low=receipt.get('compiled_led_active_low')
        require(type(compiled_low) is int and compiled_low in (0,1) and compiled_low==low,
                'Load receipt compiled LED polarity differs')
        finished=datetime.fromisoformat(receipt['finished_utc']);require(finished.tzinfo is not None,'Load time must include timezone')
        require(rows[0]['epoch_us']>=math.floor(finished.timestamp()*1000000),'Capture predates load completion')
        require(all((int(row['capture_ir'],16)&0x33)==0x31 and row['outputs']['pass_flag']==(1^low) and
                    row['outputs']['fail_flag']==low and not any(row['disabled'].values()) for row in rows),
                'INIT/DONE, PASS/fail or output-enable observation failed')
        require(transitions>=2,'Heartbeat did not keep toggling')
        result.update(status='PASS_OBSERVED_EW_STARTUP_SCOREBOARD_OUTPUTS',application_outputs_observed=True,
                      compiled_led_active_low=compiled_low,load_receipt_sha256=digest(load_receipt),
                      load_finished_utc=finished.astimezone(timezone.utc).isoformat())
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--bitstream',type=Path,required=True);p.add_argument('--source-report',type=Path,required=True)
    p.add_argument('--bsdl',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--target',required=True);p.add_argument('--server',required=True);p.add_argument('--led-active-low',type=int,choices=(0,1),required=True)
    p.add_argument('--samples',type=int,default=101);p.add_argument('--interval-ms',type=int,default=50)
    p=sub.add_parser('decode');p.add_argument('--plan',type=Path,required=True);p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--kind',choices=('baseline','post-load','repeat','reconfiguration'),required=True)
    p.add_argument('--load-receipt',type=Path);p.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.action=='prepare':
        result=prepare(args.bitstream,args.source_report,args.bsdl,args.out,args.target,args.server,args.led_active_low,args.samples,args.interval_ms)
        print(json.dumps(dict(status=result['status'],plan=str(args.out/'plan.json'),capture_tcl=str(args.out/'capture.tcl')),indent=2))
    else:
        require(not args.out.exists(),'Do not overwrite an observation receipt')
        result=decode(args.plan,args.capture,args.kind,args.load_receipt)
        args.out.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])


if __name__=='__main__':main()
