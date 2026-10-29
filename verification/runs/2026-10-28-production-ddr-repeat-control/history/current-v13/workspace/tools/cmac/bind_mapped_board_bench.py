#!/usr/bin/env python3
"""Fail-closed wire-only binding of the unchanged raw-board verification bench.

This is test infrastructure, not an FPGA arithmetic/layout repair or an
execution fallback. Missing, recoded, dead or unsafe forced signals fail.
It does not infer an error code from test mode, guess aliases or decode an FSM.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from test_fixed_array_board import verify_manifest

TOP='ypcb_cmac_array_top'
BENCH=ROOT/'tests/cmac/tb_cmac_array_bram_demo.sv'
REFERENCE=re.compile(r'\bdut\.([A-Za-z_][A-Za-z0-9_.]*)')
WIDTHS={'reset_n':1,'demo.core_busy':1,'demo.host_valid':1,'demo.host_ready':1,
    'demo.host_write':1,'demo.index':12,'demo.mem_req_valid':1,'demo.mem_req_ready':1,
    'demo.mem_req_write':1,'demo.mem_req_addr':32,'demo.mem_req_wdata':16,
    'demo.mem_rsp_valid':1,'demo.mem_rsp_error':1,'demo.unused_ack':1,
    'demo.pass':1,'demo.fail':1,'demo.error_code':8,'demo.host_rdata':16,
    'demo.state':4,'demo.engine.core.frame_valid':1,
    'demo.engine.core.frame_ready':1,'demo.watchdog':20}
FORCED={'demo.mem_rsp_error','demo.host_rdata','demo.watchdog'}


def analyze(module,bench):
    references=set(REFERENCE.findall(bench))
    assert references==set(WIDTHS), 'Unexpected raw-board bench signal contract'
    forced=set(re.findall(r'\bforce\s+dut\.([A-Za-z_][A-Za-z0-9_.]*)',bench))
    assert forced==FORCED, 'Changed raw-board fault-injection contract'
    live={b for p in module['ports'].values() for b in p['bits'] if type(b) is int}
    for cell in module['cells'].values():
        if cell['type']=='$scopeinfo': continue
        live.update(b for connection in cell['connections'].values() for b in connection if type(b) is int)
    bindings={}; issues=[]
    for name,width in sorted(WIDTHS.items()):
        net=module['netnames'].get(name)
        if net is None:
            issues.append(dict(signal=name,reason='Missing exact original signal name')); continue
        bits=net['bits']
        if len(bits)!=width:
            issues.append(dict(signal=name,reason='Width changed; recoding is not a wire alias',expected=width,actual=len(bits))); continue
        if any(net.get(key,0) for key in ('offset','upto','signed')):
            issues.append(dict(signal=name,reason='Changed bit order, range or signedness')); continue
        if any(type(b) is not int and b not in ('0','1','x','z') for b in bits):
            issues.append(dict(signal=name,reason='Unsupported bit encoding')); continue
        if any(type(b) is int and b not in live for b in bits):
            issues.append(dict(signal=name,reason='Debug-only wire absent from exported hardware')); continue
        if name in forced and (any(type(b) is not int for b in bits) or len(set(bits))!=len(bits)):
            issues.append(dict(signal=name,reason='Fault injection requires distinct live nonconstant wires')); continue
        terms=['dut.n_'+str(b) if type(b) is int else "1'b"+b for b in reversed(bits)]
        bindings[name]=dict(bits=bits,expression=terms[0] if width==1 else '{'+','.join(terms)+'}',forced=name in forced)
    return bindings,issues


def bind(module,bench):
    bindings,issues=analyze(module,bench)
    assert not issues, ('Mapped raw-board bench cannot preserve its checks',issues)
    # Rebuild from original spans. Outside these exact references, every byte
    # of the original stimulus, comparisons, forces and result parser remains.
    parts=[]; end=0; edits=[]
    for match in REFERENCE.finditer(bench):
        parts.extend((bench[end:match.start()],bindings[match.group(1)]['expression']))
        edits.append(dict(start=match.start(),end=match.end(),original=match.group(0),replacement=bindings[match.group(1)]['expression']))
        end=match.end()
    parts.append(bench[end:]); result=''.join(parts)
    assert result.count('$fatal(')==bench.count('$fatal(')
    assert result.count('!==')==bench.count('!==')
    return result,edits


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report',required=True,type=Path)
    args=parser.parse_args(); parent_path=args.mapping_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent=json.loads(parent_path.read_text())
    assert parent['status']=='PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY', 'Completed original board mapping required'
    assert (parent['channels'],parent['kernels'],parent['parallel_products'])==(32,16,512)
    verify_manifest(parent['source'])
    netlist=parent_path.parent/'mapped_hierarchy.json'
    assert str(netlist.relative_to(ROOT)) in parent['artifacts']['files']
    tracked=[Path(__file__).resolve(),parent_path,netlist,BENCH,ROOT/'tools/evidence.py',ROOT/'tools/cmac/test_fixed_array_board.py']
    source=fingerprint(tracked)
    assert source['files'][str(netlist.relative_to(ROOT))]==parent['artifacts']['files'][str(netlist.relative_to(ROOT))]
    design=json.loads(netlist.read_text()); original=BENCH.read_text()
    bindings,issues=analyze(design['modules'][TOP],original)
    out=ROOT/f'build/rknpu-mapped-board-bench-binding/{time.time_ns()}'
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='INCOMPLETE_MAPPED_RAW_BOARD_BENCH_BINDING_ONLY' if issues else 'PREPARED_WIRE_ONLY_MAPPED_RAW_BOARD_BENCH_ONLY',
        finished_utc=timestamp(),source=source,mapping_report=str(parent_path.relative_to(ROOT)),
        channels=32,kernels=16,parallel_products=512,bindings=bindings,issues=issues,
        numerical_netlist_acceptance=False,physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False,
        scope='Exact-name/width/live-wire observation and force-point analysis of the existing raw-board bench. No guessed signal aliases, FSM decoding, test-mode-derived error codes, CPU arithmetic/layout fixups, weakened checks, HDL execution, timing/DRC or FPGA acceptance.')
    if not issues:
        generated,edits=bind(design['modules'][TOP],original)
        bench=out/BENCH.name; bench.write_text(generated)
        report.update(edits=edits,artifacts=fingerprint([bench]))
    assert fingerprint(tracked)==source, 'Changed binding inputs'
    for path in tracked:
        if path==netlist: continue
        destination=out/'snapshot'/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(path.read_bytes())
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(out/'report.json'); print(report['status'],len(bindings),'bindings',len(issues),'issues')
    if issues: raise SystemExit(2)


if __name__=='__main__': main()
