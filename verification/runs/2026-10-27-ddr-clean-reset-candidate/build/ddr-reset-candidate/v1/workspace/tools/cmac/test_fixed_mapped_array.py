#!/usr/bin/env python3
"""Replay all C32/K16 vectors through the actual hierarchical XC7 partition.

Verilator and unchanged Yosys functional primitive models give binary mapped
simulation only. This is not UNISIM four-state/GSR, routed timing or FPGA proof.
The mapped C32 kernel is compiled once but instantiated sixteen times; no
arithmetic RTL replaces it and the existing complete unit bench is retained.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from map_fixed_board import CMAC, KERNEL, partition, verify_area
from test_fixed_array_board import NATIVE_RESULT, verify_fixed_native, verify_manifest

SIM_KERNEL = 'rk_cmac_fp16_cell_fixed_xc7'
BLOCK = 'rk_cmac_fp16_cell_fixed_xc7_b'
BENCH = 'tb_cmac_fp16_fixed_mapped'


def simulation_partition(design):
    """Alias only the encoded kernel module name, keeping every circuit bit."""
    original, kind, counts = partition(design)
    assert not any(n for t, n in counts.items() if t.startswith('FD')), 'Kernel must be combinational'
    expected = {'data': ('input', 512), 'weight': ('input', 512),
                'data_mask': ('input', 32), 'weight_mask': ('input', 32),
                'result': ('output', 44), 'invalid': ('output', 1)}
    ports = original['modules'][kind]['ports']
    assert {n: (p['direction'], len(p['bits'])) for n, p in ports.items()} == expected
    expected_array = {'clk': ('input', 1), 'rst_n': ('input', 1),
        'in_valid': ('input', 1), 'in_ready': ('output', 1),
        'in_data': ('input', 512), 'in_weight': ('input', 8192),
        'in_data_mask': ('input', 32), 'in_weight_mask': ('input', 512),
        'in_tag': ('input', 35), 'out_valid': ('output', 1),
        'out_ready': ('input', 1), 'out_groups': ('output', 704),
        'out_tag': ('output', 35), 'error': ('output', 1)}
    array_ports = original['modules'][CMAC]['ports']
    assert {n: (p['direction'], len(p['bits'])) for n, p in array_ports.items()} == expected_array
    assert all(isinstance(b, int) for p in array_ports.values() for b in p['bits']), 'Constant array port'
    renamed = deepcopy(original)
    renamed['modules'][SIM_KERNEL] = renamed['modules'].pop(kind)
    for cell in renamed['modules'][CMAC]['cells'].values():
        if cell['type'] == kind:
            cell['type'] = SIM_KERNEL
    # Independently reverse the only permitted edit and require exact equality
    # of parameters, ports, net names, cell types, truth tables and connections.
    restored = deepcopy(renamed)
    restored['modules'][kind] = restored['modules'].pop(SIM_KERNEL)
    for cell in restored['modules'][CMAC]['cells'].values():
        if cell['type'] == SIM_KERNEL:
            cell['type'] = kind
    assert restored == original, 'Mapping body changed during aliasing'
    return renamed, counts


def mapped_bench(text):
    changes = [('module tb_cmac_fp16_array #(', 'module '+BENCH+' #('),
        ('rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);',
         CMAC+' dut(.*); // Actual mapped C32/K16/TAG35 ports, no parameter override.'),
        ('        if(!$value$plusargs("VECTORS=%s",path)',
         '        #200; // Functional model startup; not a vendor GSR assertion.\n'
         '        if(!$value$plusargs("VECTORS=%s",path)'),
        ('$display("PASS sized FP16 CMAC', '$display("PASS binary mapped fixed FP16 CMAC')]
    for before, after in changes:
        assert text.count(before) == 1, 'Unexpected original bench: '+before
        text = text.replace(before, after)
    return text


def circuit_signature(design):
    """Circuit identity independent of unused debug aliases and wire numbering.

    Every port bit and every cell pin is an endpoint. Equality of their wire
    incidence groups proves connectivity, while cell names/types/parameters
    retain all primitive truth tables and FF INIT values. No cell may disappear.
    """
    result = {}
    for name, module in design['modules'].items():
        nodes = {}

        def endpoint(bit, label):
            assert isinstance(bit, int) or bit in ('0','1','x','z'), bit
            key = ('wire',bit) if isinstance(bit,int) else ('constant',bit)
            nodes.setdefault(key, []).append(label)

        ports = {}
        for port, value in module['ports'].items():
            ports[port] = (value['direction'],len(value['bits']))
            for index, bit in enumerate(value['bits']): endpoint(bit,('port',port,str(index)))
        cells = {}
        for cell, value in module.get('cells',{}).items():
            if value['type'] == '$scopeinfo':
                continue  # Yosys debugging metadata, never a hardware cell.
            cells[cell] = (value['type'], tuple(sorted(value.get('parameters',{}).items())))
            for pin, bits in value['connections'].items():
                for index, bit in enumerate(bits): endpoint(bit,('cell',cell,pin,str(index)))
        groups = sorted((key[0],key[1] if key[0]=='constant' else '',tuple(sorted(labels)))
                        for key,labels in nodes.items())
        result[name] = dict(ports=ports,cells=cells,wire_incidence=groups,
            parameter_defaults=tuple(sorted(module.get('parameter_default_values',{}).items())))
    return result


def hardware_instance_aliases(design):
    """Give RTLIL private/digit-leading instance names legal stable SV names.

    Yosys reads a Verilog escaped '$abc...' as a user identifier '\\$abc...',
    not the original internal RTLIL '$abc...' name. An explicit reversible
    per-module bijection avoids normalizing names in the circuit verifier.
    """
    renamed = deepcopy(design); maps = {}
    for module, body in renamed['modules'].items():
        hardware = sorted(n for n,c in body['cells'].items() if c['type']!='$scopeinfo')
        mapping = {name:'rk_mapped_cell_'+str(i) for i,name in enumerate(hardware)}
        metadata = {n for n,c in body['cells'].items() if c['type']=='$scopeinfo'}
        assert not set(mapping.values()) & metadata and len(set(mapping.values()))==len(mapping)
        body['cells'] = {mapping.get(n,n):c for n,c in body['cells'].items()}
        maps[module] = mapping
    restored = deepcopy(renamed)
    for module, mapping in maps.items():
        inverse = {alias:name for name,alias in mapping.items()}
        restored['modules'][module]['cells'] = {inverse.get(n,n):c for n,c in restored['modules'][module]['cells'].items()}
    assert restored == design, 'Instance aliasing changed circuit data'
    return renamed, maps


def structural_verilog(design):
    """Export only existing mapped cells and their bit wires, not debug aliases.

    This performs no synthesis, pruning, simulation, arithmetic or layout
    repair. The actual export is roundtripped through real Yosys and its full
    circuit signature must equal the original partition before HDL compilation.
    """
    def ident(value):
        assert value and not re.search(r'\s',value), 'Invalid structural identifier'
        return '\\'+value+' '

    def bit_name(bit):
        if isinstance(bit,int): return 'n_'+str(bit)
        assert bit in ('0','1','x','z')
        return "1'b"+bit

    def vector(bits):
        assert bits
        names = [bit_name(b) for b in reversed(bits)]
        return names[0] if len(names)==1 else '{'+', '.join(names)+'}'

    lines = ['// Structural verification export of actual mapped cells; no arithmetic substitution.']
    for name,module in sorted(design['modules'].items()):
        ports = module['ports']
        defaults = []
        for key,value in sorted(module.get('parameter_default_values',{}).items()):
            assert re.fullmatch('[01xz]+',value), 'Unsupported module parameter encoding'
            defaults.append('parameter '+ident(key)+'= '+str(len(value))+"'b"+value)
        settings = '#('+', '.join(defaults)+') ' if defaults else ''
        lines.append('module '+ident(name)+settings+'('+', '.join(ident(p) for p in ports)+');')
        for port,value in ports.items():
            assert value['direction'] in ('input','output'), 'Unsupported inout'
            width = len(value['bits']); assert width > 0
            shape = '' if width==1 else '['+str(width-1)+':0] '
            lines.append('  '+value['direction']+' wire '+shape+ident(port)+';')
        bits = {b for value in ports.values() for b in value['bits'] if isinstance(b,int)}
        hardware = {n:c for n,c in module.get('cells',{}).items() if c['type'] != '$scopeinfo'}
        for cell in hardware.values():
            bits.update(b for conn in cell['connections'].values() for b in conn if isinstance(b,int))
        lines.extend('  wire n_'+str(b)+';' for b in sorted(bits))
        for port,value in ports.items():
            if value['direction']=='input':
                assert all(isinstance(b,int) for b in value['bits']), 'Constant implementation input'
            lhs,rhs = (vector(value['bits']),ident(port)) if value['direction']=='input' else (ident(port),vector(value['bits']))
            lines.append('  assign '+lhs+' = '+rhs+';')
        for name,cell in sorted(hardware.items()):
            parameters = []
            for key,value in sorted(cell.get('parameters',{}).items()):
                assert re.fullmatch('[01xz]+',value), 'Unsupported primitive parameter encoding'
                parameters.append('.'+ident(key)+'('+str(len(value))+"'b"+value+')')
            settings = ' #('+', '.join(parameters)+')' if parameters else ''
            connections = ', '.join('.'+ident(pin)+'('+vector(bits)+')' for pin,bits in sorted(cell['connections'].items()))
            lines.append('  '+ident(cell['type'])+settings+' '+ident(name)+'('+connections+');')
        lines.append('endmodule')
    return '\n'.join(lines)+'\n'


def negative_vectors(text):
    rows = text.splitlines()
    assert len(rows) == 208 and all(re.fullmatch('[0-9a-fA-F]+', row) for row in rows)
    # The lowest vector bit is an expected output, not an operand. One flipped
    # golden bit must be detected by the actual unchanged case-inequality bench.
    rows[0] = rows[0][:-1] + format(int(rows[0][-1], 16) ^ 1, 'x')
    return '\n'.join(rows)+'\n'


def validate_result(text):
    expected = NATIVE_RESULT.replace('PASS sized FP16 CMAC', 'PASS binary mapped fixed FP16 CMAC')
    assert [line for line in text.splitlines() if line.startswith('PASS ')] == [expected], text[-4000:]
    return expected


def validate_counterexample(code, text):
    assert code != 0 and re.search(r'sized array mismatch frame=0(?:\s|$)',text)
    assert not any(line.startswith('PASS ') for line in text.splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', required=True, type=Path)
    parser.add_argument('--fixed-report', required=True, type=Path)
    args = parser.parse_args()
    ap, np = args.area_report.resolve(), args.fixed_report.resolve()
    assert all(p.is_relative_to(ROOT) for p in (ap, np))
    area = json.loads(ap.read_text()); verify_area(area)
    native = verify_fixed_native(np)
    partition_path = ap.parent / 'mapped_hierarchy.json'
    assert str(partition_path.relative_to(ROOT)) in area['artifacts']['files']
    design, counts = simulation_partition(json.loads(partition_path.read_text()))
    out = ROOT / f'build/rknpu-cmac-array/c32k16/fixed-mapped-binary-{time.time_ns()}'
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
    for label, parent in (('area', area), ('native', native)):
        path = out / (label+'_report_snapshot.json')
        path.write_text(json.dumps(parent, indent=2)+'\n'); snapshots.append(path)
    tracked = [Path(__file__).resolve(), ROOT/'tools/cmac/map_fixed_board.py',
        ROOT/'tools/cmac/test_fixed_array_board.py', ROOT/'tools/cmac/xc7_primitive_counts.py',
        ROOT/'tools/evidence.py', source_bench, bench, ap, np, partition_path,
        exported, vectors, negative, control, params, *snapshots]
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
        supervisor_pid=os.getpid(),
        channels=32, kernels=16, parallel_products=512, frames=208, seed='0x35883216',
        kernel_cells=dict(counts), area=area, native=native, commands=[],
        numerical_netlist_binary_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        scope='Actual full fixed C32/K16 mapped partition, all 208 original frames and numerical/hold/tag/reset assertions. Two-state Verilator with unchanged installed Yosys functional primitives, not vendor UNISIM GSR/four-state, exhaustive array proof, raw-board integration, routed timing/DRC, FPGA or RK silicon.')

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
        generated = [p for d in (libdir,obj) for p in d.rglob('*') if p.is_file()]
        report.update(status='PASS_FIXED_CMAC_MAPPED_FULL_BINARY_ONLY', result=result,
            numerical_netlist_binary_acceptance=True,
            artifacts=fingerprint(generated+[ROOT/c['log'] for c in report['commands']]))
    except BaseException as exc:
        report.update(status='FAIL', reason=str(exc) or repr(exc), exception_type=type(exc).__name__); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out/'report.json')
    print(report['status'], report['result'])


if __name__ == '__main__':
    main()
