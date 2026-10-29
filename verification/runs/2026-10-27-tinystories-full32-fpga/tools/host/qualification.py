"""Source and execution admission for the USER2 EW BRAM simulation profile."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DMA = ['rtl/' + n + '.sv' for n in
       ('rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma')]
BACKEND = 'rtl/host/rk_jtag_backend.sv'
MAILBOX = 'rtl/vendor/opentpu/otpu_jtag_mailbox.sv'
INNER = DMA + ['rtl/rk_bram.sv', 'rtl/rk_job_control.sv', BACKEND,
               'rtl/host/rk_jtag_ew_bram.sv', MAILBOX]
TOPS = {
    'backend': ('tb_jtag_backend', [BACKEND]),
    'mailbox': ('tb_jtag_mailbox', [MAILBOX]),
    'bram': ('tb_jtag_ew_bram', INNER),
    'async_bram': ('tb_jtag_ew_bram', INNER),
}
DONOR_SHA256 = '46f4a1148419279262fd274726eba0ab1f35285b91bf58138bc1997e692aeec9'
UNIT_RESULTS = {
    'backend': 'PASS jtag_backend 28 replies; independent AXIL channels, 32-word endian lines, rejection, stalls, timeout quarantine and joint reset',
    'mailbox': 'PASS jtag_mailbox 8 asynchronous 604-bit requests and 568-bit responses; seed=3588c640, stalls, polls, sequence wrap, reset retention',
}


def source_inputs():
    return sorted(set(INNER + [
        'rtl/vendor/opentpu/LICENSE', 'rtl/vendor/opentpu/PROVENANCE.json',
        'tests/host/tb_jtag_backend.sv', 'tests/host/tb_jtag_mailbox.sv',
        'tests/host/tb_jtag_ew_bram.sv', 'tests/host/mailbox_scan.svh',
        'tests/host/vendor.vlt', 'tests/host/test_transport.py',
        'tests/host/test_qualification.py',
        'tests/backend_ew_captures.json', 'tools/host/__init__.py',
        'tools/host/transport.py', 'tools/host/qualification.py', 'tools/host/run_rtl.py',
        'tools/dma_fixtures.py', 'tools/evidence.py',
        'model/__init__.py', 'model/dma.py', 'model/profile.py', 'model/sim.py', 'model/half.py',
    ]))


def safe_path(root, name):
    root = Path(root).resolve()
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError(f'nonrelative evidence path: {name}')
    result = root / path
    if not result.resolve().is_relative_to(root) or result.is_symlink():
        raise ValueError(f'evidence escapes root: {name}')
    return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(names, root=ROOT):
    files = {name: digest(safe_path(root, name)) for name in sorted(set(names))}
    manifest = ''.join(f'{sha}  {name}\n' for name, sha in files.items())
    return {'sha256': hashlib.sha256(manifest.encode()).hexdigest(), 'files': files}


def source_revision(root=ROOT):
    return fingerprint(source_inputs(), root)


def specs(root=ROOT):
    captures = json.loads((Path(root) / 'tests/backend_ew_captures.json').read_text())['cases']
    items = [{'name': 'backend', 'build': 'backend'}, {'name': 'mailbox', 'build': 'mailbox'}]
    for c in captures:
        d = c['tasks'][0]['descriptor']
        items.append({'name': 'capture_' + c['name'], 'build': 'bram',
                      'case': 'capture_' + c['name'], 'address': d['regcmd_addr'],
                      'amount': d['regcfg_amount'], 'tasks': len(c['tasks']),
                      'lines': sum(r['size'] // 64 for r in c['regions']),
                      'jobs': 1, 'negative': 0, 'reset_partial': 0})
    sub = next(c for c in items if c['name'] == 'capture_sub_9')
    items += [sub | {'name': 'repeat_sub_9', 'jobs': 2},
              sub | {'name': 'unknown_raw_register', 'negative': 1},
              sub | {'name': 'reset_partial_sub_9', 'reset_partial': 1},
              sub | {'name': 'async_sub_9', 'build': 'async_bram'}]
    return items


def stimulus_names(out, source_root=ROOT):
    """The complete input inventory, derived from the nine reviewed captures."""
    scenarios = specs(source_root)
    cases = {s['case'] for s in scenarios if 'case' in s}
    if len(cases) != 9:
        raise ValueError('expected exactly nine production fixture cases')
    names = {str(Path(out) / 'vectors' / case / filename)
             for case in cases for filename in ('upload.txt', 'expected.txt')}
    for scenario in scenarios:
        if scenario.get('reset_partial'):
            names.add(str(Path(out) / 'vectors' / scenario['case'] / 'partial.txt'))
    return sorted(names)


def stimulus_revision(out, artifact_root=ROOT, source_root=ROOT):
    """Reject changed inventory as well as content changes; ignore no input files."""
    root = Path(artifact_root).resolve()
    directory = safe_path(root, str(Path(out) / 'vectors'))
    expected = stimulus_names(out, source_root)
    actual = sorted(str(p.relative_to(root)) for p in directory.rglob('*') if p.is_file())
    if actual != expected:
        raise ValueError('host qualification stimulus inventory changed or is incomplete')
    return fingerprint(expected, root)


def verify_stimuli(report, artifact_root=ROOT, source_root=ROOT):
    """Compare preserved pre-execution identity to all current runtime inputs."""
    recorded = report.get('stimuli')
    actual = stimulus_revision(report['output_directory'], artifact_root, source_root)
    if recorded != actual:
        raise ValueError('host qualification stimuli changed after generation')
    if 'artifacts' in report and any(report['artifacts']['files'].get(name) != sha
            for name, sha in actual['files'].items()):
        raise ValueError('host qualification stimulus manifest does not match artifacts')
    return actual


def build_argv(simulator, compiler, execution_root, out, key):
    root = Path(execution_root)
    top, sources = TOPS[key]
    sources = sources + [f'tests/host/{top}.sv']
    if simulator == 'verilator':
        return [compiler, '--binary', '--timing', '--assert', '-Wall', '--timescale',
                '1ns/1ps', '-j', '2', '--top-module', top, '--Mdir', str(root / out / ('obj_' + key)),
                '-o', 'sim'] + (['-GTHROUGH_MAILBOX=1'] if key == 'async_bram' else []) + [
                str(root / 'tests/host/vendor.vlt')] + [str(root / s) for s in sources]
    return [compiler, '-g2012', '-Wall', '-s', top, '-o', str(root / out / (key + '.vvp'))] + (
        ['-Ptb_jtag_ew_bram.THROUGH_MAILBOX=1'] if key == 'async_bram' else []) + [
        str(root / s) for s in sources]


def binary_path(simulator, out, key):
    return str(Path(out) / ('obj_' + key) / 'sim' if simulator == 'verilator'
               else Path(out) / (key + '.vvp'))


def run_argv(report, spec):
    root, out = Path(report['execution_root']), report['output_directory']
    binary = str(root / binary_path(report['simulator'], out, spec['build']))
    command = [binary] if report['simulator'] == 'verilator' else [report['runtime']['path'], binary]
    if 'case' in spec:
        case_dir = root / out / 'vectors' / spec['case']
        observed = root / out / (spec['name'] + '_observed.txt')
        command += [f'+CASE={case_dir}', f'+OUTPUT={observed}', f"+START={spec['address']:08x}",
                    f"+AMOUNT={spec['amount']}", f"+NTASKS={spec['tasks']}",
                    f"+NLINES={spec['lines']}", f"+JOBS={spec['jobs']}",
                    f"+NEGATIVE={spec['negative']}", f"+RESET_PARTIAL={spec['reset_partial']}"]
    return command


def verify_report(path, source_root=ROOT, artifact_root=ROOT):
    """Reject stale/summary-only reports; also supports self-contained copied packages."""
    report = json.loads(Path(path).read_text())
    if report.get('status') != 'PASS' or report.get('execution_schema') != 1:
        raise ValueError('host qualification requires a completed execution-schema-1 report')
    sim = report.get('simulator')
    if sim not in ('verilator', 'iverilog'):
        raise ValueError('unsupported qualification simulator')
    if report.get('source_revision') != source_revision(source_root):
        raise ValueError('host qualification source mismatch')
    if digest(safe_path(source_root, MAILBOX)) != DONOR_SHA256:
        raise ValueError('frozen reference mailbox changed')
    artifacts = report['artifacts']
    if fingerprint(artifacts['files'], artifact_root) != artifacts:
        raise ValueError('host qualification artifact mismatch')
    verify_stimuli(report, artifact_root, source_root)
    commands = report['commands']
    by_name = {c['name']: c for c in commands}
    if len(by_name) != len(commands):
        raise ValueError('duplicate command history')
    for c in commands:
        if c.get('status') != 'PASS' or c.get('returncode') != 0:
            raise ValueError('failed/incomplete qualification command')
        if artifacts['files'].get(c['log']) != c.get('log_sha256'):
            raise ValueError('command log not bound to artifacts')
    version = by_name['version']
    if version['argv'] != [report['compiler']['path'], '--version' if sim == 'verilator' else '-V']:
        raise ValueError('compiler version command mismatch')
    if report['tool_version'] not in safe_path(artifact_root, version['log']).read_text():
        raise ValueError('tool version lacks actual log evidence')
    if sim == 'iverilog' and by_name['runtime_version']['argv'] != [report['runtime']['path'], '-V']:
        raise ValueError('runtime version command mismatch')
    tests = report['tests']
    expected = specs(source_root)
    if [t['spec'] for t in tests] != expected:
        raise ValueError('missing/reordered/changed host qualification scenarios')
    for key in TOPS:
        c = by_name['build_' + key]
        if c['argv'] != build_argv(sim, report['compiler']['path'], report['execution_root'], report['output_directory'], key):
            raise ValueError('selected compile differs from qualification profile')
        binary = binary_path(sim, report['output_directory'], key)
        if c.get('binary') != {'path': binary, 'sha256': artifacts['files'][binary]}:
            raise ValueError('compiled image missing from qualification')
    for t, spec in zip(tests, expected):
        c = by_name[spec['name']]
        if c['argv'] != run_argv(report, spec):
            raise ValueError('test execution command mismatch')
        binary = binary_path(sim, report['output_directory'], spec['build'])
        image = {'path': binary, 'sha256': artifacts['files'][binary]}
        if t.get('status') != 'PASS' or t.get('binary') != image or c.get('binary_before') != image or c.get('binary_after') != image:
            raise ValueError('test image/execution binding missing')
        passes = [line for line in safe_path(artifact_root, c['log']).read_text().splitlines() if line.startswith('PASS ')]
        if passes != t.get('results') or len(passes) != 1:
            raise ValueError('test result lacks exact log evidence')
        if spec['name'] in UNIT_RESULTS:
            if passes != [UNIT_RESULTS[spec['name']]]:
                raise ValueError('unit coverage result mismatch')
        else:
            case_dir = Path(report['execution_root']) / report['output_directory'] / 'vectors' / spec['case']
            prefix = (f'PASS jtag_ew_bram {case_dir} mailbox={int(spec["build"] == "async_bram")} '
                      f'jobs={spec["jobs"]} negative={spec["negative"]} reset_partial={spec["reset_partial"]} '
                      f'lines={spec["lines"]} commands=')
            if not passes[0].startswith(prefix) or not re.fullmatch(r'[1-9][0-9]*', passes[0][len(prefix):]):
                raise ValueError('raw-job coverage result mismatch')
            for name in ('upload.txt', 'expected.txt', 'partial.txt'):
                if name == 'partial.txt' and not spec['reset_partial']:
                    continue
                stimulus = str(Path(report['output_directory']) / 'vectors' / spec['case'] / name)
                if stimulus not in artifacts['files']:
                    raise ValueError('execution stimulus not frozen')
            if spec['negative'] == 0:
                observed = str(Path(report['output_directory']) / (spec['name'] + '_observed.txt'))
                golden = str(Path(report['output_directory']) / 'vectors' / spec['case'] / 'expected.txt')
                if artifacts['files'].get(observed) != artifacts['files'][golden]:
                    raise ValueError('observed memory differs from expected complete BO image')
                if spec['reset_partial']:
                    partial = str(Path(report['output_directory']) / 'vectors' / spec['case'] / 'partial.txt')
                    if artifacts['files'].get(observed + '.partial') != artifacts['files'][partial]:
                        raise ValueError('partial RAM writes not verified after joint reset')
    for label, filename in (('python_transport', 'test_transport.py'), ('python_qualification', 'test_qualification.py')):
        py = by_name[label]
        if py['argv'][1:] != ['-m', 'unittest', 'discover', '-s', 'tests/host', '-p', filename, '-v']:
            raise ValueError('host Python test selection mismatch')
        log = safe_path(artifact_root, py['log']).read_text()
        count_pattern = r'Ran 5 tests in ' if label == 'python_qualification' else r'Ran [1-9][0-9]* tests? in '
        if not re.search(count_pattern, log) or not log.rstrip().endswith('OK'):
            raise ValueError('host Python unit tests not executed successfully')
    expected_commands = {'version', 'python_transport', 'python_qualification'} | {'build_' + key for key in TOPS} | {s['name'] for s in expected}
    if sim == 'iverilog':
        expected_commands.add('runtime_version')
    if set(by_name) != expected_commands:
        raise ValueError('unexpected qualification command selection')
    return report
