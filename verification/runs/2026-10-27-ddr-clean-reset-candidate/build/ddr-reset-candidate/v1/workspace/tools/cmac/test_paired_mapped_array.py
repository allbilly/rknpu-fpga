#!/usr/bin/env python3
"""Replay all C32/K16 frames through the actual LUT-paired mapped kernel.

The original mapped array registers/ports/protocol are retained byte-for-byte.
Only the independently verified paired C32 kernel is imported. This does not
validate the modified board shell, UNISIM/GSR, timing, electrical or FPGA state.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from map_fixed_board import partition
from test_fixed_array_board import verify_manifest
from pair_board_luts import (four_state_bench, implementation_module_aliases,
    structural_board_verilog, verify as verify_pairs)
from test_fixed_mapped_array import (BENCH, BLOCK, CMAC, SIM_KERNEL,
    circuit_signature, hardware_instance_aliases, mapped_bench, negative_vectors,
    simulation_partition, structural_verilog, validate_counterexample,
    validate_result, verify_area, verify_fixed_native)

EXPORT_IDENTITY='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
STEPS=('yosys_version','iverilog_version','vvp_version','datadir','negative_compile',
       'negative_test','actual_compile','actual_test','export','elaborate_check')


def validate_pair_metadata(report):
    assert report['status']=='PREPARED_LUT6_2_BOARD_CANDIDATE_ONLY', 'Completed LUT-pair preparation required'
    assert report['stage']=='complete'
    assert (report['channels'],report['kernels'],report['parallel_products'])==(32,16,512)
    assert report['circuit_pair_verified'] is True
    assert report['export_circuit_identity']==EXPORT_IDENTITY
    for key in ('numerical_netlist_acceptance','physical_fit_verified','bitstream_emitted','hardware_programmed'):
        assert report[key] is False, 'Misrepresented parent acceptance'
    assert report['physical_lut_pairs']>0 and report['unique_function_classes']>0
    assert report['expected_four_state_comparisons']>0
    expected='PASS LUT_PAIR_FOUR_STATE classes='+str(report['unique_function_classes'])+' comparisons='+str(report['expected_four_state_comparisons'])
    assert report['four_state_function_class_result']==expected
    commands=report['commands']
    assert [Path(c['log']).stem for c in commands]==list(STEPS), 'Missing, duplicated or reordered preparation gate'
    for label,command in zip(STEPS,commands):
        assert command['status']=='PASS'
        assert command['returncode']==(1 if label=='negative_test' else 0), 'Unexpected tool result'
    return expected


def validate_pair_parent(path):
    report=json.loads(path.read_text()); expected=validate_pair_metadata(report)
    verify_manifest(report['source']); verify_manifest(report['artifacts'])
    out=path.parent
    names=['paired_hierarchy.json','pair_certificate.json','function_classes.json',
           'actual.sv','negative.sv','actual.vvp','negative.vvp','xilinx_functional_models.v',
           'module_name_aliases.json','hardware_instance_aliases.json','paired_board.v',
           'export_roundtrip.json','export.ys','check.ys']
    files=[out/n for n in names]
    assert all(str(p.relative_to(ROOT)) in report['artifacts']['files'] for p in files)
    validate_pair_proof_metadata(report,out)
    for key in ('function_class_inputs','function_class_executables'):
        for manifest in report[key].values(): verify_manifest(manifest)
    classes=json.loads((out/'function_classes.json').read_text())
    assert len(classes)==report['unique_function_classes']
    assert 2*sum(4**c['fanins'] for c in classes)==report['expected_four_state_comparisons']
    assert (out/'actual.sv').read_text()==four_state_bench(classes)
    assert (out/'negative.sv').read_text()==four_state_bench(classes,True)
    assert hashlib.sha256((out/'xilinx_functional_models.v').read_bytes()).hexdigest()==report['primitive_model_original']['sha256']
    assert [s for s in (out/'actual_test.log').read_text().splitlines() if s.startswith('PASS ')]==[expected]
    failure=(out/'negative_test.log').read_text()
    assert re.search(r'LUT_PAIR_MISMATCH class=0 pattern=0(?:\s|$)',failure) and 'PASS ' not in failure
    parent_path=ROOT/report['parent_report']
    parent=json.loads(parent_path.read_text())
    # Shared cones are tied to actual board wiring, not arbitrary array masks.
    # This runner intentionally accepts only per-kernel LUT pairing of the
    # original board, never the cross-kernel shared-input candidate.
    assert parent['status']=='PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY', 'Standalone array requires private original kernel boundary'
    assert report['parent_source_sha256']==parent['source']['sha256']
    verify_manifest(parent['source']); verify_manifest(parent['artifacts'])
    original_path=parent_path.parent/'mapped_hierarchy.json'
    original=json.loads(original_path.read_text())
    candidate=json.loads((out/'paired_hierarchy.json').read_text())
    certificate=json.loads((out/'pair_certificate.json').read_text())
    class_map={json.dumps(c,sort_keys=True,separators=(',',':')):c for c in classes}
    assert len(class_map)==len(classes), 'Duplicated proof classes'
    verify_pairs(original,candidate,certificate,class_map)
    implementations={n:candidate['modules'][n] for n in certificate}
    verify_pair_export(dict(candidate,modules=implementations),
        json.loads((out/'module_name_aliases.json').read_text()),
        json.loads((out/'hardware_instance_aliases.json').read_text()),
        (out/'paired_board.v').read_text(),json.loads((out/'export_roundtrip.json').read_text()))
    return report,parent,original,candidate,files+[parent_path,original_path]


def validate_pair_proof_metadata(report,out):
    """Compile/run input bindings must equal the final accepted artifacts."""
    final=report['artifacts']['files']
    for key in ('function_class_inputs','function_class_executables'):
        assert set(report[key])=={'negative','actual'}, 'Missing compile/run proof bindings'
        for label,manifest in report[key].items():
            names=(['paired_hierarchy.json','pair_certificate.json','function_classes.json',
                'xilinx_functional_models.v',label+'.sv'] if key=='function_class_inputs' else [label+'.vvp'])
            expected={str((out/n).relative_to(ROOT)) for n in names}
            assert set(manifest['files'])==expected, 'Incomplete compile/run proof input set'
            assert all(final.get(name)==sha for name,sha in manifest['files'].items()), 'Changed compile/run proof artifacts'


def verify_pair_export(implementation,module_aliases,instance_aliases,verilog,roundtrip):
    """Reconstruct the exact exporter input without verifier name normalization."""
    modules,expected_modules=implementation_module_aliases(implementation)
    assert module_aliases==expected_modules, 'Changed module-name bijection'
    exported,expected_instances=hardware_instance_aliases(modules)
    assert instance_aliases==expected_instances, 'Changed instance-name bijection'
    assert verilog==structural_board_verilog(exported), 'Changed structural board export'
    assert circuit_signature(roundtrip)==circuit_signature(exported), 'Changed exported circuit'


def bind_array_kernel(array,board,candidate,kernel):
    """Retain the original array except the verified C32 cell bodies.

    The actual import changes only debug net names. Require literal identity
    of every other original kernel field, as well as full circuit identity.
    Candidate debug aliases are restored to the array's own original names;
    ports, parameters, cells, wire numbers and every array register are retained.
    """
    _,kind,_=partition(array)
    assert kind==kernel and kind in board['modules'] and kind in candidate['modules']
    a,b=array['modules'][kind],board['modules'][kind]
    assert {k:v for k,v in a.items() if k!='netnames'}=={k:v for k,v in b.items() if k!='netnames'}, 'Different original array/board kernel hardware'
    assert circuit_signature({'modules':{kind:a}})==circuit_signature({'modules':{kind:b}})
    paired=candidate['modules'][kind]
    assert {k:v for k,v in paired.items() if k not in ('cells','netnames')}=={k:v for k,v in b.items() if k not in ('cells','netnames')}, 'Changed paired kernel boundary'
    result=deepcopy(array)
    result['modules'][kind]=deepcopy(paired)
    if 'netnames' in a: result['modules'][kind]['netnames']=deepcopy(a['netnames'])
    else: result['modules'][kind].pop('netnames',None)
    restored=deepcopy(result); restored['modules'][kind]=deepcopy(a)
    assert restored==array, 'Changed array registers, shell, ports or library'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', required=True, type=Path)
    parser.add_argument('--fixed-report', required=True, type=Path)
    parser.add_argument('--paired-report', required=True, type=Path)
    args = parser.parse_args()
    ap, np = args.area_report.resolve(), args.fixed_report.resolve()
    pair_path=args.paired_report.resolve()
    assert all(p.is_relative_to(ROOT) for p in (ap, np, pair_path))
    # Refuse a failed/running preparation before even reading large unrelated
    # area/native dependencies, and always before any execution output exists.
    validate_pair_metadata(json.loads(pair_path.read_text()))
    area = json.loads(ap.read_text()); verify_area(area)
    native = verify_fixed_native(np)
    paired,parent_board,original_board,candidate_board,pair_files=validate_pair_parent(pair_path)
    partition_path = ap.parent / 'mapped_hierarchy.json'
    assert str(partition_path.relative_to(ROOT)) in area['artifacts']['files']
    original_array=json.loads(partition_path.read_text())
    bound=bind_array_kernel(original_array,original_board,candidate_board,parent_board['preserved_kernel'])
    design, counts = simulation_partition(bound)
    assert counts['LUT6_2']>0 and sum(c['type']==SIM_KERNEL for c in design['modules'][CMAC]['cells'].values())==16
    out = ROOT / f'build/rknpu-cmac-array/c32k16/paired-mapped-binary-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    exported = out / 'actual_partition.json'
    exported.write_text(json.dumps(design)+'\n')
    source_bench = ROOT / 'tests/cmac/tb_cmac_fp16_array.sv'
    bench = out / (BENCH+'.sv'); bench.write_text(mapped_bench(source_bench.read_text()))
    vectors = ROOT / 'build/rknpu-cmac-array/c32k16/vectors.hex'
    assert str(vectors.relative_to(ROOT)) in native['vectors']['artifacts']['files']
    assert len(vectors.read_text().splitlines()) == 208
    negative = out / 'negative_vectors.hex'; negative.write_text(negative_vectors(vectors.read_text()))
    control = out / 'mapped_hierarchy.vlt'
    control.write_text('`verilator_config\nhier_block -module "'+SIM_KERNEL+'"\n')
    params = ROOT / 'tools/cmac/empty_hier_parameters.v'
    snapshots = []
    for label, parent in (('area', area), ('native', native), ('paired', paired), ('board_mapping', parent_board)):
        path = out / (label+'_report_snapshot.json')
        path.write_text(json.dumps(parent, indent=2)+'\n'); snapshots.append(path)
    tracked = [Path(__file__).resolve(), ROOT/'tools/cmac/map_fixed_board.py',
        ROOT/'tools/cmac/test_fixed_array_board.py', ROOT/'tools/cmac/xc7_primitive_counts.py',
        ROOT/'tools/evidence.py', source_bench, bench, ap, np, partition_path,
        exported, vectors, negative, control, params, *snapshots, pair_path, *pair_files]
    tracked.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
        supervisor_pid=os.getpid(),
        channels=32, kernels=16, parallel_products=512, frames=208, seed='0x35883216',
        kernel_cells=dict(counts), area=area, native=native, paired=paired, commands=[],
        paired_source_sha256=paired['source']['sha256'],
        kernel_binding='Literal original array/board kernel equality except netnames, plus full circuit identity; original array register/shell/library data retained exactly',
        numerical_netlist_binary_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        scope='Actual per-kernel LUT-paired C32/K16 mapped arithmetic in the unchanged original mapped array register/shell partition; all sixteen kernels, all 208 original frames and all numerical/hold/tag/reset assertions. Not the modified board shell, cross-kernel sharing, UNISIM GSR/four-state, exhaustive array proof, raw-board integration, routed timing/DRC, FPGA or RK silicon.')

    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def run(argv, name, counterexample=False):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out/(name+'.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                def no_core():
                    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                      start_new_session=True, preexec_fn=no_core) as proc:
                    step['pid'] = proc.pid; save()
                    try:
                        code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            text = (ROOT/step['log']).read_text(); step['returncode'] = code
            if counterexample:
                validate_counterexample(code, text)
                step['expected'] = 'Real first-frame golden-bit mutation rejected by unchanged bench'
            else:
                assert code == 0 and not re.search(r'%Error|ERROR:|warning:|sorry:', text, re.I), text[-5000:]
                warnings = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M)
                assert len(warnings) == len(re.findall(r'^%Warning-', text, re.M))
                for kind, path, line in warnings:
                    immutable_export = path == str(out/'mapped_partition.v')
                    immutable_model = path == str(out/'xilinx_functional_models.v')
                    wrapper = path == str(out/'cell'/ (BLOCK+'.sv'))
                    timestamp_only = (wrapper and kind == 'UNUSEDSIGNAL' and
                        Path(path).read_text().splitlines()[int(line)-1].strip() == 'time last_combo_seqnum__V;')
                    ignored_model_metadata = immutable_model and kind in ('SPECIFYIGN','GENUNNAMED')
                    assert timestamp_only or ignored_model_metadata or ((immutable_export or immutable_model) and
                        kind in ('DECLFILENAME', 'UNUSEDSIGNAL', 'UNUSEDPARAM')), (name, kind, path, line)
                step['nonfunctional_export_diagnostics'] = [list(w) for w in warnings]
                step['timing_metadata_not_simulated'] = any(w[0]=='SPECIFYIGN' for w in warnings)
            step['status'] = 'PASS'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic()-started, 3); save()

    save()
    def terminate(signum, _frame):
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,terminate)
    try:
        report['tool_version'] = run(['verilator','--version'], 'version').splitlines()[0]
        assert report['tool_version'] == native['tool_version']
        report['cxx_version'] = run(['c++','--version'], 'cxx_version').splitlines()[0]
        report['export_tool_version'] = run(['yosys','-V'], 'export_version').strip()
        assert report['export_tool_version'] == area['tool_version']
        datadir = Path(run(['yosys-config','--datdir'], 'datadir').strip())
        installed = datadir/'xilinx/cells_sim.v'
        models = out/'xilinx_functional_models.v'; models.write_bytes(installed.read_bytes())
        report['primitive_model_original'] = dict(path=str(installed), sha256=hashlib.sha256(installed.read_bytes()).hexdigest(),
            frozen=str(models.relative_to(ROOT)), scope='Installed Yosys functional models, unchanged; no SDF or UNISIM GSR')
        netlist = out/'mapped_partition.v'
        report['ignored_yosys_debug_scopeinfo_cells'] = sum(c['type']=='$scopeinfo'
            for module in design['modules'].values() for c in module['cells'].values())
        export_design, aliases = hardware_instance_aliases(design)
        alias_path = out/'hardware_instance_aliases.json'
        alias_path.write_text(json.dumps(aliases,indent=2)+'\n')
        netlist.write_text(structural_verilog(export_design))
        roundtrip = out/'export_roundtrip.json'
        script = out/'export.ys'
        script.write_text('read_verilog -sv '+json.dumps(str(netlist))+';\nwrite_json '+json.dumps(str(roundtrip))+';\n')
        run(['yosys','-Q','-T','-s',script], 'export')
        assert circuit_signature(json.loads(roundtrip.read_text())) == circuit_signature(export_design), 'Structural export changed mapped circuit'
        report['export_circuit_identity'] = 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        report['instance_name_aliasing'] = 'Explicit reversible per-module bijection; no verifier name normalization'
        tracked.extend((models, netlist, script, roundtrip, alias_path))
        report['source'] = fingerprint(tracked)
        for path in tracked:
            dest = out/'snapshot'/path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
        save()
        flags = ['--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps']
        optimization = 'OPT_FAST=-O2 OPT_SLOW=-O2 OPT_GLOBAL=-O2'
        libdir, obj = out/'cell', out/'top'
        run(['verilator','--cc','--build','-j','2',*flags,'-MAKEFLAGS',optimization,
            '--Mdir',libdir,'--prefix','V'+BLOCK,'--mod-prefix','V'+BLOCK,
            '--top-module-encoded',BLOCK,'--lib-create',BLOCK,'--hierarchical-child','1',
            '--hierarchical-block',SIM_KERNEL+','+BLOCK,control,models,netlist], 'cell_compile')
        wrapper, library = libdir/(BLOCK+'.sv'), libdir/('lib'+BLOCK+'.a')
        assert wrapper.is_file() and library.is_file()
        for pattern in (r'input logic \[511:0\]\s+data', r'input logic \[511:0\]\s+weight',
                        r'input logic \[31:0\]\s+data_mask', r'output logic \[43:0\]\s+result'):
            assert re.search(pattern, wrapper.read_text()), pattern
        obj.mkdir(); (obj/('V'+BENCH+'_hier.mk')).write_text('VM_HIER_LIBS := '+str(library)+'\n')
        run(['verilator','--cc','--main','--exe',*flags,'-GATOMIC_C=32','-GATOMIC_K=16',
            '--top-module',BENCH,'--Mdir',obj,'-o','sim','--hierarchical-block',SIM_KERNEL+','+BLOCK,
            '--hierarchical-params-file',params,'-LDFLAGS',library,wrapper,models,netlist,bench], 'top_generate')
        cpp = list(obj.glob('V'+BENCH+'*.cpp')); operations = set()
        for path in cpp:
            for operation in ('create','combo_update','seq_update'):
                if re.search(r'\b'+BLOCK+'_protectlib_'+operation+r'\s*\(',path.read_text()): operations.add(operation)
        assert operations == {'create','combo_update'}, 'Mapped combinational library calls required'
        assert not any('LUT' in p.name or SIM_KERNEL in p.name for p in cpp), 'Embedded arithmetic bypasses mapped library'
        report['library_operations'] = sorted(operations); save()
        run(['make','-C',obj,'-f','V'+BENCH+'.mk','-j','2',*optimization.split()], 'top_compile')
        run([obj/'sim',f'+VECTORS={negative}','+COUNT=208'], 'negative_sanity', True)
        result = validate_result(run([obj/'sim',f'+VECTORS={vectors}','+COUNT=208'], 'test'))
        assert fingerprint(tracked) == report['source'], 'Source changed during run'
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == report['primitive_model_original']['sha256']
        verify_area(area); verify_fixed_native(np)
        assert validate_pair_parent(pair_path)[0]==paired, 'Changed completed LUT-pair parent'
        generated = [p for d in (libdir,obj) for p in d.rglob('*') if p.is_file()]
        report.update(status='PASS_LUT_PAIR_CMAC_MAPPED_FULL_BINARY_ONLY', result=result,
            numerical_netlist_binary_acceptance=True,
            artifacts=fingerprint(generated+[ROOT/c['log'] for c in report['commands']]))
    except BaseException as exc:
        report.update(status='FAIL', reason=str(exc) or repr(exc), exception_type=type(exc).__name__); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out/'report.json')
    print(report['status'], report['result'])


if __name__ == '__main__':
    main()
