#!/usr/bin/env python3
"""Prepare/decode full512 passive SAMPLE evidence. Never invokes hardware.

The existing EW decoder remains unchanged. This profile observes only the
source-bound autonomous K65 scoreboard pads, not direct memory contents or
general GEMM/RK3588 equivalence. Image admission and audited execution belong
to the root hardware workflow, separately from this preparation/decoder.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import uuid

if __package__:
    from . import sample_ew as pads
else:
    # Keep copied observers runnable outside the checkout, including python -I.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sample_ew as pads

require, digest, canonical = pads.require, pads.digest, pads.canonical
load_json, bsdl_contract, tcl_literal = pads.load_json, pads.bsdl_contract, pads.tcl_literal
PART, PINS = pads.PART, pads.PINS
PROFILE = 'full512-regmem-startup'
SOURCE_SHA = 'ac6fee7e5ebd29b85c727349c5b2def80ba8f7876ceae76ff0bc0b47750ce25d'
TEMPLATE = Path(__file__).with_suffix('.tcl.in')
STATUS = 'PREPARED_CMAC512_SAMPLE_OBSERVER_ONLY'
SCOPE = ('Full C32/K16=512-product autonomous raw K65 scoreboard; '
         '49 command QWORDs,12 frames,64 numerical writes/acks and4096 checked halfwords '
         'inferred from bound source; no direct RAM readback, host/DDR/PCIe or RK3588 equivalence')


def selected_contract(report):
    require(report['status'] == 'PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY' and
            report['top'] == 'ypcb_cmac_array_regmem_top' and report['part'] == PART and
            (report['channels'], report['kernels'], report['parallel_products'], report['pipeline_stages'],
             report['clock_period_ns']) == (32, 16, 512, 2, 20), 'Expected reviewed full512 regmem source')
    require(report['source']['sha256'] == SOURCE_SHA, 'New hardware source requires a new profile review')
    files = report['source']['files']
    manifest = ''.join(h+'  '+n+'\n' for n, h in sorted(files.items()))
    require(hashlib.sha256(manifest.encode()).hexdigest() == SOURCE_SHA, 'Preparation manifest changed')
    selected = report['hardware_inputs']
    require(set(selected) == set(report['synthesis_sources']) and len(selected) == 31,
            'Changed full512 synthesis inventory')
    for name, expected in selected.items():
        require(files[name] == expected, 'Hardware selection differs from source manifest')
    # ROM images are synthesis inputs even though the historical selected list
    # enumerates HDL/XDC. Bind all frozen numerical fixtures explicitly.
    numerical = {n: h for n, h in files.items() if n.startswith('tests/cmac/array_data/')}
    require('tests/cmac/array_data/board_rom.hex' in numerical, 'Missing actual K65 ROM image')
    return {**selected, **numerical}


def source_contract(path):
    report = load_json(path)
    selected = selected_contract(report)
    root = Path(path).parent/'source'
    for name, expected in report['source']['files'].items():
        require(re.fullmatch('[0-9a-f]{64}', expected) and digest(root/name) == expected,
                'Full512 source snapshot changed: '+name)
    return dict(preparation_report_sha256=digest(path), source_sha256=SOURCE_SHA,
                hardware_inputs=dict(files=selected), profile=PROFILE)


def prepare(bitstream, source_report, bsdl, out, target, server, led_active_low=0,
            samples=101, interval_ms=50, tck_hz=3000000):
    bitstream = Path(bitstream).resolve(strict=True)
    source_report = Path(source_report).resolve(strict=True)
    bsdl, out = Path(bsdl).resolve(strict=True), Path(out).absolute()
    require(not out.exists(), 'Use a fresh full512 observer directory')
    require(type(led_active_low) is int and led_active_low in (0, 1), 'Invalid compiled LED generic')
    require(type(samples) is int and 10 <= samples <= 1000 and type(interval_ms) is int and
            20 <= interval_ms <= 500 and 3000 <= (samples-1)*interval_ms <= 30000,
            'Unsupported sample count/interval/duration')
    require(type(tck_hz) is int and tck_hz == 3000000, 'Require audited 3-MHz TCK')
    require(type(target) is str and target.startswith(server+'/') and
            not any(c in target for c in '\r\n\x00'), 'Require exact audited target URI')
    source, bsdl_info = source_contract(source_report), bsdl_contract(bsdl)
    binding = dict(schema_version=2, profile=PROFILE, trial_id=uuid.uuid4().hex,
        part=PART, idcode='0x23751093', target=target, server=server,
        bitstream=dict(path=str(bitstream), sha256=digest(bitstream), bytes=bitstream.stat().st_size),
        source_report=dict(path=str(source_report), sha256=digest(source_report), binding=source),
        bsdl=bsdl_info, led_active_low=led_active_low, samples=samples,
        interval_ms=interval_ms, requested_tck_hz=tck_hz, source_scope=SCOPE)
    binding_sha = hashlib.sha256(canonical(binding)).hexdigest()
    text = TEMPLATE.read_text()
    values = dict(TARGET=tcl_literal(target), SERVER=tcl_literal(server), OUTPUT=tcl_literal(out/'capture.tsv'),
                  BINDING=tcl_literal(binding_sha), SAMPLES=str(samples), INTERVAL=str(interval_ms), TCK=str(tck_hz))
    for key, value in values.items():
        token = '@'+key+'@'
        require(text.count(token) == 1, 'Unexpected template marker '+key)
        text = text.replace(token, value)
    out.mkdir(parents=True)
    snap = out/'source'
    snap.mkdir()
    for path, name in [(Path(__file__), 'sample_cmac512.py'), (Path(pads.__file__), 'sample_ew.py'),
                       (TEMPLATE, 'sample_cmac512.tcl.in'), (bsdl, 'xc7k480t_ffg1156.bsd'),
                       (source_report, 'source-report.json')]:
        shutil.copy2(path, snap/name)
    for name in source['hardware_inputs']['files']:
        destination = snap/'hardware'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_report.parent/'source'/name, destination)
    (out/'capture.tcl').write_text(text)
    plan = dict(status=STATUS, binding=binding, binding_sha256=binding_sha,
        tcl_sha256=digest(out/'capture.tcl'), observer_sha256=digest(__file__),
        pad_helper_sha256=digest(pads.__file__), template_sha256=digest(TEMPLATE),
        hardware_accessed=False, programming_performed=False, flash_written=False,
        image_admission=False)
    (out/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    return plan


def parse_capture(path,plan):
    lines=Path(path).read_text().splitlines();metadata={};cleanup={};rows=[];ended=False
    for line in lines:
        require(not ended,'Capture data after END')
        fields=line.split('|');require(fields[0]=='CMACSAMPLE1' and len(fields)>=3,'Unknown capture format')
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



def decode(plan_path, capture_path, kind, load_receipt=None):
    plan_path = Path(plan_path)
    plan = load_json(plan_path)
    binding = plan['binding']
    require(plan['status'] == STATUS and binding['schema_version'] == 2 and binding['profile'] == PROFILE and
            hashlib.sha256(canonical(binding)).hexdigest() == plan['binding_sha256'], 'Wrong/changed full512 plan')
    require(binding['part'] == PART and binding['idcode'] == '0x23751093' and
            binding['source_report']['binding']['profile'] == PROFILE and
            binding['source_report']['binding']['source_sha256'] == SOURCE_SHA and
            binding['source_scope'] == SCOPE and binding['bsdl']['pins'] == PINS and
            binding['bsdl']['boundary_length'] == 1395 and binding['bsdl']['instruction_length'] == 6,
            'Full512 source/pad/profile binding differs')
    package = plan_path.parent
    require(digest(__file__) == plan['observer_sha256'] and digest(pads.__file__) == plan['pad_helper_sha256'],
            'Use the exact copied observer and pad helper for this receipt')
    for name, field in [('sample_cmac512.py', 'observer_sha256'), ('sample_ew.py', 'pad_helper_sha256'),
                        ('sample_cmac512.tcl.in', 'template_sha256')]:
        require(digest(package/'source'/name) == plan[field], 'Observer source changed: '+name)
    require(digest(package/'capture.tcl') == plan['tcl_sha256'] and
            bsdl_contract(package/'source/xc7k480t_ffg1156.bsd') == binding['bsdl'], 'Observer Tcl/BSDL changed')
    require(digest(package/'source/source-report.json') == binding['source_report']['sha256'], 'Source report changed')
    require(selected_contract(load_json(package/'source/source-report.json')) ==
            binding['source_report']['binding']['hardware_inputs']['files'], 'Compiled source/ROM inventory differs')
    for name, expected in binding['source_report']['binding']['hardware_inputs']['files'].items():
        require(digest(package/'source/hardware'/name) == expected, 'Bound hardware/ROM changed: '+name)
    result = parse_capture(capture_path, plan)
    rows, low = result['samples'], binding['led_active_low']
    require(type(low) is int and low in (0, 1), 'Invalid compiled LED generic')
    heartbeat = [row['outputs']['heartbeat'] for row in rows]
    transitions = sum(a != b for a, b in zip(heartbeat, heartbeat[1:]))
    result.update(schema_version=2, profile=PROFILE, kind=kind,
        bitstream_sha256=binding['bitstream']['sha256'], source_sha256=SOURCE_SHA,
        source_report_sha256=binding['source_report']['sha256'], plan_sha256=digest(plan_path),
        capture_sha256=digest(capture_path), heartbeat_transitions=transitions,
        capture_hardware_accessed=True, decoder_hardware_accessed=False, programming_performed=False,
        flash_written=False, application_outputs_observed=False, optical_led_polarity_verified=False,
        direct_memory_readback=False, source_scope=SCOPE)
    require(kind in ('baseline', 'post-load', 'repeat', 'reconfiguration'), 'Unknown capture kind')
    if kind == 'baseline':
        require(load_receipt is None, 'Baseline must not imply an image load')
        result['status'] = 'CAPTURED_BASELINE_APPLICATION_UNKNOWN'
    else:
        require(load_receipt is not None, 'Require successful matching volatile-load receipt')
        receipt = load_json(load_receipt)
        require(receipt['status'] == 'PASS' and receipt['action'] == 'program-sram' and
                receipt['hardware_programmed'] is True and receipt['flash_written'] is False and
                receipt['bitstream_sha256'] == binding['bitstream']['sha256'] and
                receipt['idcode'] == '0x23751093' and receipt['target'] == binding['target'] and
                receipt.get('profile') == PROFILE and receipt.get('source_sha256') == SOURCE_SHA and
                receipt.get('source_report_sha256') == binding['source_report']['sha256'], 'Load identity/profile differs')
        compiled = receipt.get('compiled_led_active_low')
        require(type(compiled) is int and compiled == low, 'Load compiled LED generic differs')
        finished = datetime.fromisoformat(receipt['finished_utc'])
        require(finished.tzinfo is not None and rows[0]['epoch_us'] >= math.floor(finished.timestamp()*1000000),
                'Capture time predates load or lacks timezone')
        require(all((int(row['capture_ir'], 16)&0x33) == 0x31 and row['outputs']['pass_flag'] == (1^low) and
                    row['outputs']['fail_flag'] == low and not any(row['disabled'].values()) for row in rows),
                'INIT/DONE, PASS/fail or output-enable observation failed')
        require(transitions >= 2, 'Heartbeat did not keep toggling')
        result.update(status='PASS_OBSERVED_FULL512_STARTUP_SCOREBOARD_OUTPUTS', application_outputs_observed=True,
                      compiled_led_active_low=compiled, load_receipt_sha256=digest(load_receipt),
                      load_finished_utc=finished.astimezone(timezone.utc).isoformat())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    for name in ('bitstream', 'source-report', 'bsdl', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--target', required=True)
    p.add_argument('--server', required=True)
    p.add_argument('--led-active-low', type=int, choices=(0, 1), required=True)
    p.add_argument('--samples', type=int, default=101)
    p.add_argument('--interval-ms', type=int, default=50)
    p = sub.add_parser('decode')
    for name in ('plan', 'capture', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--kind', choices=('baseline', 'post-load', 'repeat', 'reconfiguration'), required=True)
    p.add_argument('--load-receipt', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.bitstream, args.source_report, args.bsdl, args.out, args.target, args.server,
                         args.led_active_low, args.samples, args.interval_ms)
    else:
        require(not args.out.exists(), 'Do not overwrite an observation receipt')
        result = decode(args.plan, args.capture, args.kind, args.load_receipt)
        args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(result['status'])


if __name__ == '__main__':
    main()
