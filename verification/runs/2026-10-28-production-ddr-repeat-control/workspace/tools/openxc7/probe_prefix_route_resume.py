#!/usr/bin/env python3
"""Real small placed-state reload/routing controls, never full-board signoff.

Keep the full-size placement inputs immutable. The pinned frontend restores
NEXTPNR_BEL/BEL_STRENGTH; Xilinx preRoute explicitly handles pre-placed input.
Post-route export uses a different site-name convention and is not admitted
as a generic checkpoint for another reload by this control.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from place_prefix_board import (ROOT, QUALIFICATION, DATABASE, CONSTIDS, digest,
    timestamp, audit, packing_xdc, native_export_module, verify_placed_module,
    verify_native_tool_transition)
from prepare_prefix_pack_input import assert_circuit_identity

PARENT = ROOT / 'build/openxc7/prefix-native-place-small-control-1791396691135662289/report.json'
ROUTER_OBJECT = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-cli-build/himbaechel/CMakeFiles/nextpnr-himbaechel.dir/__/common/route/router1.cc.o')
ROUTER_SYMBOL = '_ZN18nextpnr_himbaechel7router1EPNS_7ContextERKNS_10Router1CfgE'
CHECK_SYMBOL = '_ZNK18nextpnr_himbaechel7Context17checkRoutedDesignEv'
CONTROL = ROOT / 'tests/cmac/test_prefix_route_resume_control.py'


def duplicate_bel_rejection(code, text):
    # BaseArch::bindBel throws assertion_failure for entry != nullptr. This
    # happens during frontend import, outside executeMain's handled-log-error
    # path. CommandHandler::exec catches only log_execution_error_exception;
    # assertion_failure escapes and terminates via SIGABRT on this Linux host.
    assert code == -signal.SIGABRT, 'Wrong native duplicate-BEL termination'
    assert 'nextpnr_himbaechel::assertion_failure' in text
    assert 'Assertion failure: entry == nullptr (' in text
    assert '/common/kernel/base_arch.h:156)' in text


def checkpoint_annotation_view(design, parent, version):
    """Restore only omitted port annotations in a comparison view, not a file.

    frontend_base.h::create_iobuf returns early for synth-marked checkpoints,
    before filling ctx->ports. PAD cells and named external nets survive. This
    exact all-ports-absent producer case is explicit; partial/changed ports are
    not accepted. The later whole-primitive wire bijection is still required.
    """
    parent_module, _ = native_export_module(parent, version)
    assert len(design['modules']) == 1, 'Unexpected checkpoint export modules'
    label, module = next(iter(design['modules'].items()))
    assert module['ports'] == {}, 'Expected exact checkpoint all-ports-omitted case'
    ports = {}
    for name, spec in parent_module['ports'].items():
        nets = [name] if len(spec['bits']) == 1 else [f'{name}[{i}]' for i in range(len(spec['bits']))]
        bits = []
        for i, net in enumerate(nets):
            assert parent_module['netnames'][net]['bits'] == [spec['bits'][i]], 'Parent external net mismatch'
            named = module['netnames'][net]['bits']
            assert len(named) == 1 and type(named[0]) is int and named[0] >= 2
            original_pad, pad = parent_module['cells'][net], module['cells'][net]
            assert original_pad['type'] == pad['type'] == 'PAD'
            assert original_pad['parameters'] == pad['parameters'], 'Changed checkpoint pad parameters'
            assert original_pad['attributes'] == pad['attributes'], 'Changed checkpoint pad properties/BEL'
            assert pad['port_directions'] == original_pad['port_directions']
            assert original_pad['connections'] == {'PAD': [spec['bits'][i]]}
            assert pad['connections'] == {'PAD': named}, 'Changed checkpoint external pad wiring'
            bits.extend(named)
        ports[name] = dict(spec, bits=bits)
    view = dict(design, modules={label: dict(module, ports=ports)})
    native_export_module(view, version)
    return view, dict(contract='PINNED_CHECKPOINT_FRONTEND_OMITS_ALL_CTX_PORTS_BEFORE_PAD_RETURN',
        actual_export_has_port_annotations=False, comparison_annotations_restored=5,
        artifact_modified=False, circuit_data_changed=False,
        external_named_net_and_pad_properties_checked=True)


def resume_argv(executable, design, label, xdc, output, route=False):
    argv = list(map(str, [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
        '--top', label, '--json', design, '-o', 'xdc=' + str(xdc),
        '--no-pack', '--no-place', '--freq', '50', '--seed', '3588',
        '--Werror', '--verbose', '--write', output]))
    return argv + (['--router', 'router2'] if route else ['--no-route'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True,
                        help='Completed source-bound real small placement report')
    parser.add_argument('--precision-qualification', type=Path, required=True,
                        help='Fresh source-bound qualification of the double-exp engine')
    args = parser.parse_args()
    parent_path = (ROOT / args.parent).resolve(strict=True)
    assert parent_path.is_relative_to(ROOT / 'build/openxc7')
    qualification_path = args.precision_qualification.resolve(strict=True)
    assert qualification_path.is_relative_to(Path('/home/fedora/soDLA/build/ypcb'))
    out = ROOT / f'build/openxc7/prefix-route-resume-small-control-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(),
        supervisor_pid=os.getpid(), commands=[], small_native_reload_executed=False,
        small_native_routing_executed=False, full_board_native_routing_executed=False,
        full_board_numerical_acceptance=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, bitstream_emitted=False,
        hardware_programmed=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, expected=0, timeout=180):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT),
            expected_returncode=expected, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            result = subprocess.run(step['argv'], cwd=ROOT, text=True, capture_output=True,
                timeout=timeout, check=False,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
            text = result.stdout + result.stderr
            log = out / (label + '.log')
            log.write_text(text)
            step.update(returncode=result.returncode, log=str(log.relative_to(ROOT)))
            assert result.returncode == expected, text[-3500:]
            if expected == 0:
                assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY' if expected == 0 else 'PASS_EXPECTED_REJECTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    try:
        parent = json.loads(parent_path.read_text())
        assert parent['status'] == 'PASS_SMALL_REAL_NATIVE_PLACEMENT_BINDING_CONTROL_NOT_FULL_BOARD_OR_SIGNOFF'
        assert parent['small_native_placement_executed'] is True
        assert parent['full_board_native_placement_executed'] is False
        assert all(step['returncode'] == 0 for step in parent['commands'])
        before = dict(parent['source'])
        for name, sha in parent['artifacts'].items():
            path = Path(name).resolve(strict=True)
            assert path.is_relative_to(parent_path.parent) and digest(path) == sha
            before[str(path)] = sha
        before[str(parent_path)] = digest(parent_path)
        inventory, candidate, transition = verify_native_tool_transition(qualification_path)
        assert str(ROUTER_OBJECT) in candidate['inputs'], 'Unbound router object'
        before.update(candidate['inputs'])
        executable = Path(candidate['executable']['path'])
        for path in (QUALIFICATION, qualification_path, DATABASE, CONSTIDS, executable, Path(__file__)):
            before[str(path.resolve())] = digest(path)
        before[str(CONTROL)] = digest(CONTROL)
        for module in list(sys.modules.values()):
            if getattr(module, '__file__', None):
                path = Path(module.__file__).resolve()
                if path.is_relative_to(ROOT / 'tools'):
                    before[str(path)] = digest(path)
        xdc_source = ROOT / 'fpga/ypcb.xdc'
        before[str(xdc_source)] = digest(xdc_source)
        assert all(digest(path) == sha for path, sha in before.items())
        report.update(source=before, timing_inventory=inventory, native_tool_transition=transition,
                      parent_report=str(parent_path.relative_to(ROOT)))
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover',
            '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        version = run('version', [executable, '--version']).strip()
        report['native_version'] = version
        # Audit the actual final linked function, not CMAKE_BUILD_TYPE alone.
        assembly = run('linked_router_check', ['objdump', '-d', '--disassemble=' + ROUTER_SYMBOL, executable])
        assert re.search(r'\bcall\s+[0-9a-f]+ <' + CHECK_SYMBOL + r'>', assembly), 'Missing actual router connectivity-check call'
        report['router_connectivity_check'] = dict(caller=ROUTER_SYMBOL, callee=CHECK_SYMBOL,
            actual_linked_call_present=True, router_object_sha256=before[str(ROUTER_OBJECT)],
            executable_sha256=before[str(executable)])
        design = json.loads((parent_path.parent / 'placed.json').read_text())
        module, translation = native_export_module(design, version)
        expected = dict(Counter(cell['type'] for cell in module['cells'].values()))
        verify_placed_module(module, expected)
        assert len(module['cells']) == 18, 'Changed small-control scope'
        original_bels = {name: cell['attributes']['NEXTPNR_BEL'] for name, cell in module['cells'].items()}
        text, constraints = packing_xdc(xdc_source.read_text())
        xdc = out / 'literal.xdc'
        xdc.write_text(text)
        report.update(constraint_translation=constraints, checkpoint_label_translation=translation)
        label = translation['emitted_context_label']
        roundtrip_path = out / 'reloaded.json'
        report.update(stage='reload', small_native_reload_executed=True)
        run('reload', resume_argv(executable, parent_path.parent / 'placed.json', label, xdc, roundtrip_path))
        reloaded = json.loads(roundtrip_path.read_text())
        reloaded_view, annotations = checkpoint_annotation_view(reloaded, design, version)
        reload_module, _ = native_export_module(reloaded_view, version)
        report['checkpoint_port_annotation_translation'] = annotations
        report['reload_circuit_identity'] = assert_circuit_identity(design, reloaded_view)
        verify_placed_module(reload_module, expected)
        assert {name: cell['attributes']['NEXTPNR_BEL'] for name, cell in reload_module['cells'].items()} == original_bels
        report['exact_all_cell_bel_reload_identity'] = True
        bad = deepcopy(design)
        bad_cells = next(iter(bad['modules'].values()))['cells']
        first, second = [name for name, cell in bad_cells.items() if cell['type'] == 'SLICE_FFX'][:2]
        bad_cells[second]['attributes']['NEXTPNR_BEL'] = bad_cells[first]['attributes']['NEXTPNR_BEL']
        bad_path = out / 'duplicate-bel.json'
        bad_path.write_text(json.dumps(bad))
        report['stage'] = 'negative'
        negative = run('duplicate_bel_rejection', resume_argv(executable, bad_path, label, xdc, out / 'invalid.json'), -signal.SIGABRT)
        duplicate_bel_rejection(-signal.SIGABRT, negative)
        assert not (out / 'invalid.json').exists(), 'Rejected reload wrote a successful output'
        report['duplicate_bel_native_rejection'] = True
        report['duplicate_bel_rejection_contract'] = 'UNCAUGHT_FRONTEND_ASSERTION_FAILURE_SIGABRT_AND_EXACT_BIND_BEL_ENTRY_NULL_DIAGNOSTIC'
        report.update(stage='route', small_native_routing_executed=True)
        routed_path = out / 'routed.json'
        log = run('route', resume_argv(executable, parent_path.parent / 'placed.json', label, xdc, routed_path, True))
        for marker in ('Running router1 to check that route is legal...', 'Routing complete.', 'Program finished normally.'):
            assert marker in log, 'Missing native route completion: ' + marker
        routed = json.loads(routed_path.read_text())
        # postRouteArchInfo changes the BEL spelling. Only require its exact
        # all-ports-omitted checkpoint export here, not generic reload identity.
        assert len(routed['modules']) == 1 and next(iter(routed['modules'])) == label
        assert routed['creator'] == design['creator']
        routed_module = next(iter(routed['modules'].values()))
        assert routed_module['ports'] == {}, 'Unexpected routed checkpoint port annotations'
        assert dict(Counter(cell['type'] for cell in routed_module['cells'].values())) == expected
        assert int(routed_module['settings']['route'], 2) == 1
        routed_bels = [cell['attributes']['NEXTPNR_BEL'] for cell in routed_module['cells'].values()]
        assert len(set(routed_bels)) == len(routed_bels) == 18
        report['post_route_export_scope'] = 'SOURCE_DEFINED_SITE_BEL_AND_SITEWIRE_NAMES_NOT_ADMITTED_FOR_GENERIC_CHECKPOINT_RELOAD'
        assert all(digest(path) == sha for path, sha in before.items()), 'Changed routing-control input'
        report.update(status='PASS_SMALL_NATIVE_PLACED_RELOAD_AND_ROUTE_CONTROL_NOT_FULL_BOARD_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.iterdir()
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
