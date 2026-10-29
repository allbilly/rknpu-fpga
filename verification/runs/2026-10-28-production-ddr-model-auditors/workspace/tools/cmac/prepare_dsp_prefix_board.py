#!/usr/bin/env python3
"""Compile full raw K65 board with a literal prefix-array substitution only.

Preparation/elaboration only. Do not simulate, promote, map, route, emit a
bitstream or program hardware. Full native-array and raw-board numerical
acceptance remain separate prerequisites, with unchanged bench assertions.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
from dsp_prefix_array_contract import ARRAY as DSP_ARRAY,CELL as DSP_CELL,validate_sources
from dsp_array_contract import FIXED_ARRAY,FIXED_CELL,replace_once
from test_dsp_prefix_array_native import validate_leaf_metadata
from test_mapped_prefix_dsp import verify_bindings
from vivado_array import SPEC

ORIGINAL_CELL='rtl/cmac/rk_cmac_fp16_cell.sv'
ORIGINAL_ARRAY='rtl/cmac/rk_cmac_fp16_array.sv'
JOIN='rtl/cmac/rk_cmac_cacc_fp16_array.sv'
ROWS=ROOT/'rtl/cmac/experimental/rk_cmac_fp16_rows.sv'
LANE=ROOT/'rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv'
HELPER=ROOT/'rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv'


def dsp_join(text):
    old='    rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K),.TAG_WIDTH(TAG_WIDTH+2)) cmac('
    return replace_once(text,old,old.replace('rk_cmac_fp16_array #','rk_cmac_fp16_array_dsp_prefix #'))


def simulation_sources(spec,generated_join):
    assert (spec['top'],spec['part'],spec['clock_period_ns'],spec['bench'],spec['constraints']) == (
        'ypcb_cmac_array_top','xc7k480tffg1156-2',20,
        'tests/cmac/tb_cmac_array_bram_demo.sv','fpga/ypcb.xdc')
    names=spec['simulation_helpers']+spec['synthesis']
    assert len(names)==len(set(names))
    assert all(names.count(name)==1 for name in (ORIGINAL_CELL,ORIGINAL_ARRAY,JOIN))
    result=[]
    for name in names:
        path=(ROOT/name).resolve();assert not Path(name).is_absolute() and path.is_relative_to(ROOT) and path.is_file()
        if name==ORIGINAL_CELL:result += [ROWS,HELPER,LANE,DSP_CELL]
        elif name==ORIGINAL_ARRAY:result.append(DSP_ARRAY)
        elif name==JOIN:result.append(generated_join)
        else:result.append(path)
    assert len(result)==len(set(result)) and len(result)==len(names)+3
    assert all(ROOT/name not in result for name in (ORIGINAL_CELL,ORIGINAL_ARRAY,JOIN))
    assert FIXED_ARRAY not in result and FIXED_CELL not in result
    return result


def validate_compiled_hierarchy(text):
    expected={'rk_cmac_fp16_array_dsp_prefix':1,'rk_cmac_fp16_cell_dsp_prefix':16,
        'rk_cmac_fp16_lane_dsp_prefix':512,'rk_cmac_fp16_discarded_carry':512}
    counts={name:len(re.findall(r'\.scope module, "[^"]*" "'+name+r'"',text)) for name in expected}
    assert counts==expected,('Missing full compiled DSP array hierarchy',counts)
    for name in ('rk_cmac_fp16_cell','rk_cmac_fp16_cell_fixed','rk_cmac_fp16_array','rk_cmac_fp16_array_fixed',
        'rk_cmac_fp16_cell_dsp','rk_cmac_fp16_lane_dsp','rk_cmac_fp16_array_dsp'):
        assert not re.search(r'\.scope module, "[^"]*" "'+name+r'"',text),('Unexpected baseline/fixed fallback',name)
    return counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane-report',type=Path,required=True)
    args=parser.parse_args();lane_path=args.lane_report.resolve()
    assert lane_path.is_relative_to(ROOT) and lane_path.is_file()
    leaf=json.loads(lane_path.read_text());validate_leaf_metadata(leaf);verify_bindings(leaf)
    validate_sources();spec=json.loads(SPEC.read_text())
    out=ROOT/f'build/rknpu-dsp-prefix-board-preparation/{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    join=out/Path(JOIN).name;join.write_text(dsp_join((ROOT/JOIN).read_text()))
    sources=simulation_sources(spec,join);bench=ROOT/spec['bench']
    imported=[Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools')]
    tracked=[Path(__file__).resolve(),lane_path,SPEC,bench,*sources,FIXED_CELL,FIXED_ARRAY,
        ROOT/ORIGINAL_CELL,ROOT/ORIGINAL_ARRAY,ROOT/JOIN,ROOT/spec['constraints'],
        *sorted((ROOT/'tests/cmac/array_data').iterdir()),*imported]
    tracked += list((ROOT/'rtl/vendor/nvdla').glob('*.vlib'))
    tracked += [ROOT/'rtl/vendor/nvdla'/name for name in ('LICENSE','assertion_header.h','assertion_task.h')]
    before=fingerprint(tracked)
    report=dict(status='RUNNING',stage='compile',started_utc=timestamp(),source=before,
        supervisor_pid=os.getpid(),python_version=sys.version,commands=[],
        channels=32,kernels=16,parallel_products=512,
        lane_report=str(lane_path.relative_to(ROOT)),lane_source_sha256=leaf['source']['sha256'],
        simulation_sources=[str(p.relative_to(ROOT)) for p in sources],
        native_array_fixture_acceptance=False,raw_board_numerical_acceptance=False,
        mapped_array_numerical_acceptance=False,physical_fit_verified=False,
        bitstream_emitted=False,hardware_programmed=False,
        scope='Actual prefix native full-board compile and hierarchy inspection only. One literal CMAC array substitution; all raw QWORD/DMA/profile/CACC/output/BRAM/reset/fault/watchdog/bench wiring unchanged. Not nine-mode execution, full-array numerical or mapped/physical/RK acceptance.')
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(argv,label):
        step=dict(argv=list(map(str,argv)),log=str((out/(label+'.log')).relative_to(ROOT)),status='RUNNING')
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                    step['pid']=proc.pid;save()
                    try:code=proc.wait(timeout=1800)
                    except BaseException:
                        try:os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                        proc.wait();raise
            step['returncode']=code;text=(ROOT/step['log']).read_text()
            assert code==0 and not re.search(r'(?im)\b(?:error|warning):|sorry:',text),text[-3000:]
            step['status']='PASS';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    save();generated=[join]
    try:
        for path in sorted(set(tracked)):
            target=out/'snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(path.read_bytes());generated.append(target)
        run([sys.executable,ROOT/'tools/cmac/gen_array_board.py','--check'],'rom_check')
        report['tool_version']=run(['iverilog','-V'],'version').splitlines()[0]
        assert report['tool_version']==leaf['iverilog_version']
        binary=out/'sim.vvp';generated.append(binary)
        report['compile_inputs']=fingerprint([*sources,bench]);save()
        run(['iverilog','-g2012','-DDESIGNWARE_NOEXIST','-DASSERT_ON',
            '-I'+str(ROOT/'rtl/vendor/nvdla'),'-s',bench.stem,'-o',binary,*sources,bench],'compile')
        assert fingerprint([*sources,bench])==report['compile_inputs']
        report['compiled_hierarchy']=validate_compiled_hierarchy(binary.read_text())
        assert join.read_text()==dsp_join((ROOT/JOIN).read_text()) and fingerprint(tracked)==before
        validate_sources();validate_leaf_metadata(json.loads(lane_path.read_text()));verify_bindings(json.loads(lane_path.read_text()))
        report.update(status='PREPARED_COMPILED_FULL_C32K16_DSP_PREFIX_RAW_BOARD_ONLY',stage='complete',
            finished_utc=timestamp(),artifacts=fingerprint([*generated,*out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL',finished_utc=timestamp(),error=repr(error),
            artifacts=fingerprint([p for p in [*generated,*out.glob('*.log')] if p.is_file()]));raise
    finally:save()
    print(out/'report.json',flush=True)


if __name__=='__main__':main()
