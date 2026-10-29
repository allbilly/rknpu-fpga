#!/usr/bin/env python3
"""Prepare a reversible shared-cone board netlist, never a signed-off bitstream."""
from collections import Counter
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from analyze_shared_kernel_cones import COMBINATIONAL, digest, shared_cones
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases
from export_board_netlist import structural_board_verilog
from xc7_primitive_counts import PRIMITIVE, TIMING

SHARED = 'rk_cmac_fp16_data_shared_xc7'
PRIVATE = 'rk_cmac_fp16_cell_fixed_shared_xc7'
INSTANCE = 'rk_shared_data_cones'
NODES = 'shared_nodes'


def outputs(cell):
    return {bit for pin, bits in cell['connections'].items()
            if cell['port_directions'][pin] == 'output' for bit in bits}


def all_bits(module):
    bits = {bit for port in module.get('ports', {}).values() for bit in port['bits']}
    bits.update(bit for cell in module['cells'].values()
                for conn in cell['connections'].values() for bit in conn)
    bits.update(bit for net in module.get('netnames', {}).values() for bit in net['bits'])
    return {bit for bit in bits if type(bit) is int}


def shared_ports(kernel, analysis, nodes):
    ports = {}
    for name, indexes in analysis['shared_input_positions'].items():
        if indexes:
            spec = kernel['ports'][name]
            assert not spec.get('offset', 0) and not spec.get('upto', 0)
            ports[name] = dict(direction='input', bits=[spec['bits'][i] for i in indexes])
    assert NODES not in ports and nodes
    ports[NODES] = dict(direction='output', bits=list(nodes))
    return ports


def prepare(design, top, kernel, expected_instances):
    assert not {SHARED, PRIVATE} & set(design['modules']), 'Module alias collision'
    assert INSTANCE not in design['modules'][top]['cells'], 'Instance alias collision'
    analysis = shared_cones(design['modules'], top, kernel, expected_instances)
    names = set(analysis['eligible_cell_names'])
    body = design['modules'][kernel]
    assert names and all(COMBINATIONAL.fullmatch(body['cells'][n]['type']) for n in names)
    nodes = sorted({bit for name in names for bit in outputs(body['cells'][name])})
    assert all(type(bit) is int for bit in nodes)
    modified = dict(design, modules={name:deepcopy(module) for name,module in design['modules'].items()
                                    if name not in (top,kernel)})
    private = deepcopy(body)
    assert NODES not in private['ports']
    private['ports'][NODES] = dict(direction='input', bits=nodes)
    private['cells'] = {name: cell for name, cell in private['cells'].items() if name not in names}
    modified['modules'][PRIVATE] = private
    modified['modules'][SHARED] = dict(attributes={'keep_hierarchy': '1', 'hdlname': SHARED},
        ports=shared_ports(body, analysis, nodes),
        cells={name: deepcopy(body['cells'][name]) for name in sorted(names)})
    board = deepcopy(design['modules'][top])
    modified['modules'][top] = board
    first = next(cell for cell in board['cells'].values() if cell['type'] == kernel)
    base = max(all_bits(board)) + 1
    wires = list(range(base, base+len(nodes)))
    inputs = {port: [first['connections'][port][i] for i in indexes]
              for port, indexes in analysis['shared_input_positions'].items() if indexes}
    board['cells'][INSTANCE] = dict(type=SHARED, parameters={},
        port_directions={**{port:'input' for port in inputs}, NODES:'output'},
        connections={**inputs, NODES:wires})
    for cell in board['cells'].values():
        if cell['type'] == kernel:
            cell['type'] = PRIVATE
            cell['connections'][NODES] = list(wires)
            cell['port_directions'][NODES] = 'input'
    certificate = dict(top=top, original_kernel=kernel, instances=expected_instances,
        shared_cell_names=sorted(names), original_kernel_output_nodes=nodes,
        parent_shared_wires=wires, shared_input_positions=analysis['shared_input_positions'],
        potentially_removable_cells=analysis['potentially_removable_cells'])
    verify(design, modified, certificate)
    return modified, certificate


def verify(original, candidate, certificate):
    """Independently undo the lift and require literal original circuit data.

    The shared cells themselves, private cells and every original shell cell
    must be unchanged. Each shared input is checked against every original
    kernel caller. The additional bus has unique fresh parent wires and drives
    the identical original kernel node numbers in all instances. Therefore
    duplication back into each kernel gives exactly the original circuit.
    """
    top, kernel, count = [certificate[k] for k in ('top','original_kernel','instances')]
    analysis = shared_cones(original['modules'], top, kernel, count)
    names = set(analysis['eligible_cell_names'])
    body = original['modules'][kernel]
    nodes = sorted({bit for name in names for bit in outputs(body['cells'][name])})
    assert certificate['shared_cell_names'] == sorted(names)
    assert certificate['original_kernel_output_nodes'] == nodes
    assert certificate['shared_input_positions'] == analysis['shared_input_positions']
    assert certificate['potentially_removable_cells'] == analysis['potentially_removable_cells']
    assert set(candidate['modules']) == (set(original['modules'])-{kernel}) | {PRIVATE,SHARED}
    shared = candidate['modules'][SHARED]
    assert shared == dict(attributes={'keep_hierarchy':'1','hdlname':SHARED},
        ports=shared_ports(body,analysis,nodes),
        cells={name:body['cells'][name] for name in sorted(names)}), 'Changed shared function/wiring'
    private = deepcopy(candidate['modules'][PRIVATE])
    assert private['ports'].pop(NODES) == dict(direction='input',bits=nodes)
    assert not names & set(private['cells']), 'Shared cells still duplicated'
    assert set(private['cells']) == set(body['cells'])-names, 'Private hardware removed or added'
    private['cells'].update(shared['cells'])
    assert private == body, 'Private kernel changed beyond exact cone extraction'
    board = deepcopy(candidate['modules'][top])
    instance = board['cells'].pop(INSTANCE)
    assert instance['type'] == SHARED and instance['parameters'] == {}
    wires = instance['connections'][NODES]
    assert wires == certificate['parent_shared_wires'] and len(wires) == len(nodes)
    assert len(set(wires)) == len(wires) and all(type(bit) is int for bit in wires)
    assert not set(wires) & all_bits(original['modules'][top]), 'Shared wire collision'
    assert instance['port_directions'] == {port:spec['direction'] for port,spec in shared['ports'].items()}
    assert set(instance['connections']) == set(shared['ports']), 'Additional shared input constraint'
    originals = {name:cell for name,cell in original['modules'][top]['cells'].items() if cell['type']==kernel}
    assert len(originals) == count
    assert {name for name,cell in board['cells'].items() if cell['type']==PRIVATE} == set(originals)
    for name, old in originals.items():
        new = board['cells'][name]
        assert new['connections'].pop(NODES) == wires and new['port_directions'].pop(NODES) == 'input'
        new['type'] = kernel
        assert new == old, 'Original kernel boundary modified'
        for port,indexes in analysis['shared_input_positions'].items():
            if indexes:
                assert instance['connections'][port] == [old['connections'][port][i] for i in indexes], 'Private input shared'
    assert board == original['modules'][top], 'Raw board shell changed'
    restored = dict(candidate, modules=dict(candidate['modules']))
    restored['modules'].pop(PRIVATE); restored['modules'].pop(SHARED)
    restored['modules'][kernel] = private; restored['modules'][top] = board
    assert restored == original, 'Circuit restoration is not exact'


def physical_counts(modules, top, implementations):
    def visit(name, stack):
        assert name in implementations and name not in stack
        result = Counter()
        for cell in modules[name]['cells'].values():
            kind = cell['type']
            if kind == '$scopeinfo':
                continue
            if kind in implementations:
                result.update(visit(kind,stack+(name,)))
            else:
                assert PRIMITIVE.fullmatch(kind) or kind in ('RAMB18E1','RAMB36E1'), ('Unknown hardware',kind)
                definition = modules[kind]
                assert int(definition['attributes'].get('blackbox','0'),2)==1
                assert {c['type'] for c in definition.get('cells',{}).values()} <= TIMING
                result[kind] += 1
        return result
    return visit(top,())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report',type=Path,required=True)
    args = parser.parse_args()
    parent_path = args.mapping_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text())
    assert parent['status']=='PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    assert (parent['channels'],parent['kernels'],parent['parallel_products'])==(32,16,512)
    assert all(c['status']=='PASS' and c['returncode']==0 for c in parent['commands'])
    for name,sha in parent['source']['files'].items():
        assert digest(ROOT/name)==sha, ('Stale parent source',name)
    netlist = parent_path.parent/'mapped_hierarchy.json'
    assert digest(netlist)==parent['artifacts']['files'][str(netlist.relative_to(ROOT))]
    original = json.loads(netlist.read_text())
    tops = [name for name,module in original['modules'].items() if int(module.get('attributes',{}).get('top','0'),2)]
    assert len(tops)==1
    top,kernel = tops[0],parent['preserved_kernel']
    candidate, certificate = prepare(original,top,kernel,16)
    before = physical_counts(original['modules'],top,{top,kernel})
    after = physical_counts(candidate['modules'],top,{top,PRIVATE,SHARED})
    assert dict(before)==parent['cells']
    assert before-after==Counter(certificate['potentially_removable_cells'])
    assert not after-before
    out = ROOT/f'build/rknpu-shared-board-prepare/{time.time_ns()}'
    out.mkdir(parents=True,exist_ok=False)
    used = [Path(module.__file__).resolve() for module in list(sys.modules.values())
            if getattr(module,'__file__',None) and Path(module.__file__).resolve().is_relative_to(ROOT/'tools')]
    tracked = [parent_path,netlist,Path(__file__).resolve(),*used]
    report = dict(status='RUNNING',started_utc=timestamp(),supervisor_pid=os.getpid(),
        source=fingerprint(tracked),mapping_report=str(parent_path.relative_to(ROOT)),
        mapping_source_sha256=parent['source']['sha256'],commands=[],python_version=sys.version,
        channels=32,kernels=16,parallel_products=512,circuit_lift_verified=True,
        numerical_netlist_acceptance=False,physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False,
        cells_before=dict(before),cells_after=dict(after),removed_cells=dict(before-after),
        scope='Separate actual complete-board mapped shared-cone candidate. Literal reverse expansion restores every original circuit cell/parameter/wire/boundary, with identical-input combinational induction. No full numeric/raw-board replay, packed utilization, timing/electrical/DRC, bitstream, physical FPGA or RK acceptance.')
    def save():
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(argv,name):
        step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                    step['pid']=proc.pid; save()
                    try: code=proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode']=code
            text=(ROOT/step['log']).read_text()
            assert code==0 and 'ERROR:' not in text, text[-6000:]
            step['status']='PASS'; return text
        except BaseException:
            step['status']='FAIL'; raise
        finally:
            step['seconds']=round(time.monotonic()-started,3); save()
    def terminate(signum,_frame):
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,terminate)
    save()
    try:
        # Snapshot before exporting as well: failed attempts remain replayable.
        for path in tracked:
            if path==netlist: continue
            dest=out/'snapshot'/path.relative_to(ROOT)
            dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(path.read_bytes())
        report['tool_version']=run(['yosys','-V'],'version').strip()
        assert report['tool_version']==parent['tool_version']
        certificate_path=out/'lift_certificate.json'
        certificate_path.write_text(json.dumps(certificate,indent=2)+'\n')
        candidate_path=out/'shared_hierarchy.json'
        candidate_path.write_text(json.dumps(candidate)+'\n')
        implementation=dict(candidate,modules={n:candidate['modules'][n] for n in (top,PRIVATE,SHARED)})
        exported,aliases=hardware_instance_aliases(implementation)
        aliases_path=out/'hardware_instance_aliases.json'
        aliases_path.write_text(json.dumps(aliases,indent=2)+'\n')
        sv=out/'shared_board.v'; sv.write_text(structural_board_verilog(exported))
        roundtrip=out/'export_roundtrip.json'
        script=out/'export.ys'
        script.write_text('read_verilog -sv '+json.dumps(str(sv))+';\nwrite_json '+json.dumps(str(roundtrip))+';\n')
        run(['yosys','-Q','-T','-s',script],'export')
        assert circuit_signature(json.loads(roundtrip.read_text()))==circuit_signature(exported), 'Shared export circuit changed'
        report['export_circuit_identity']='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        check=out/'check.ys'
        check.write_text('read_verilog -lib +/xilinx/cells_sim.v;\nread_verilog -sv '+json.dumps(str(sv))+';\nhierarchy -check -top '+top+';\ncheck -assert;\nstat -tech xilinx;\n')
        run(['yosys','-Q','-T','-s',check],'elaborate_check')
        verify(original,json.loads(candidate_path.read_text()),certificate)
        assert fingerprint(tracked)==report['source'], 'Source changed during candidate preparation'
        generated=[candidate_path,certificate_path,aliases_path,sv,roundtrip,script,check]
        report.update(status='PREPARED_SHARED_CONE_BOARD_NETLIST_ONLY',
            lut_count=sum(c for n,c in after.items() if n.startswith('LUT')),
            ff_count=sum(c for n,c in after.items() if n.startswith('FD')),
            artifacts=fingerprint(generated+[ROOT/c['log'] for c in report['commands']]))
        for path in tracked:
            if path==netlist: continue  # The independently archived parent binds this exact large file.
            dest=out/'snapshot'/path.relative_to(ROOT)
            dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(path.read_bytes())
    except BaseException as exc:
        report.update(status='FAIL',reason=str(exc)); raise
    finally:
        report['finished_utc']=timestamp(); save(); print(out/'report.json')
    print(report['status'],report['lut_count'])


if __name__=='__main__':
    main()
