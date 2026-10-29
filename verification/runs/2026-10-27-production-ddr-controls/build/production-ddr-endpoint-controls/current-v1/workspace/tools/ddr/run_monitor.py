#!/usr/bin/env python3
"""Execute the ECC monitor, optionally with the pinned vendor control leaf.

No controller/PHY or memory transaction is simulated. Never runs vendor tools.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import canonical, load_json, require
from tools.evidence import timestamp

LOCAL = ('rtl/ddr/rk_mig_ecc_monitor.sv', 'tests/ddr/tb_mig_ecc_monitor.sv',
         'tests/ddr/tb_mig_ecc_vendor.sv', 'tests/ddr/vendor_warnings.json',
         'fpga/ddr/xdma_archive_reference.json', 'fpga/ddr/xdma_lifecycle_contract.json',
         'fpga/ddr/monitor.mk', 'tools/ddr/run_monitor.py', 'tools/ddr/interface.py',
         'tools/ddr/__init__.py', 'tools/evidence.py', 'tests/ddr/monitor/test_runner.py')
PARAMETERS = dict(C_S_AXI_CTRL_ADDR_WIDTH=32, C_S_AXI_CTRL_DATA_WIDTH=32,
                  C_S_AXI_ADDR_WIDTH=31, C_S_AXI_BASEADDR=0, C_ECC_TEST='OFF',
                  C_DQ_WIDTH=72, C_ECC_WIDTH=8, C_MEM_ADDR_ORDER='BANK_ROW_COLUMN',
                  C_BANK_WIDTH=3, C_ROW_WIDTH=15, C_COL_WIDTH=10,
                  C_ECC_ONOFF_RESET_VALUE=1, C_ECC_CE_COUNTER_WIDTH=8,
                  C_NCK_PER_CLK=4, C_MC_ERR_ADDR_WIDTH=29)
CONTROL = tuple('mig_7series_v4_2_axi_ctrl_'+name+'.v'
                for name in ('addr_decode', 'read', 'reg_bank', 'reg', 'top', 'write'))
SCOPE = 'ECC control monitor and optional archived AXI-Lite register RTL only; no MIG memory/PHY, RMW retirement, FPGA or RK proof'
ENVIRONMENT = {'MAKEFLAGS':'', 'MFLAGS':''}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(paths):
    files = {str(Path(p).relative_to(ROOT)): digest(p) for p in sorted(paths)}
    return manifest(files)


def manifest(files):
    return dict(files=files, sha256=hashlib.sha256(canonical(files)).hexdigest())


def relative(name):
    path = Path(name)
    require(type(name) is str and path.parts and not path.is_absolute() and
            '..' not in path.parts and str(path) == name, 'Unsafe relative artifact path')
    require((ROOT/path).resolve().is_relative_to(ROOT.resolve()), 'Artifact path escapes source package')
    return path


def source_revision():
    return fingerprint([ROOT/p for p in LOCAL])


def tool_identity(path):
    # Preserve argv[0]: e.g. a ccache c++ symlink selects its compiler by name.
    return dict(path=os.path.abspath(path), sha256=digest(path))


def version_plan(simulator, tools):
    names = [('simulator-version', 'simulator', '-V' if simulator == 'iverilog' else '--version')]
    names += [('runtime-version', 'runtime', '-V')] if simulator == 'iverilog' else [('cxx-version', 'cxx', '--version')]
    return [(name, [tools[key]['path'], flag], key) for name,key,flag in names]


def vendor_plan(output, policy):
    """Reconstruct every extracted input and the literal parameter include."""
    output = relative(output)
    catalog_path = ROOT/'fpga/ddr/xdma_archive_reference.json'
    catalog = load_json(catalog_path)
    contract = load_json(ROOT/'fpga/ddr/xdma_lifecycle_contract.json')
    require(digest(catalog_path) == contract['catalog']['sha256'], 'Lifecycle catalog changed')
    require(catalog['archive']['sha256'] == contract['catalog']['archive_sha256'], 'Archive contract changed')
    values = contract['control_leaf_parameters']['values']
    require(set(values) == set(PARAMETERS) and all(type(values[k]) is type(v) and values[k] == v
            for k,v in PARAMETERS.items()), 'Control leaf parameters differ')
    require(contract['physical_integration_ready'] is False and contract['controller_simulated'] is False,
            'Unreviewed controller/physical claim')
    entries = {v['member']:v['sha256'] for v in contract['sources'].values()}
    for name in CONTROL:
        selected = [n for n in catalog['members'] if Path(n).name == name]
        require(len(selected) == 1, 'Missing/ambiguous control source: '+name)
        expected = catalog['members'][selected[0]]['sha256']
        require(selected[0] not in entries or entries[selected[0]] == expected, 'Contract source differs')
        entries[selected[0]] = expected
    files = {}; members = {}
    for index,(member,expected) in enumerate(sorted(entries.items())):
        require(catalog['members'][member]['sha256'] == expected, 'Contract source differs')
        name = str(output/'vendor'/str(index)/Path(member).name)
        files[name] = expected; members[name] = member
    compiled = []
    for basename in CONTROL:
        selected = [n for n in files if Path(n).name == basename]
        require(len(selected) == 1 and files[selected[0]] == policy['vendor_source_sha256'][basename],
                'Vendor warning policy source binding differs')
        compiled.append(selected[0])
    header = ',\n'.join('    .'+n+'('+json.dumps(v)+')' for n,v in values.items())+'\n'
    header_name = str(output/'monitor_vendor_params.svh')
    files[header_name] = hashlib.sha256(header.encode()).hexdigest()
    return dict(files=files, members=members, compiled=compiled, header=header,
                header_name=header_name, archive_sha256=catalog['archive']['sha256'])


def parameter_include(producer, output):
    path = Path(producer)/relative(output)/'monitor_vendor_params.svh'
    name = str(path)
    # Both preprocessors accept spaces inside this direct argv string literal.
    # Icarus does not accept escaped quotes/backslashes in include filenames.
    require(path.is_absolute() and not any(c in name for c in ('"','\\')) and
            all(ord(c) >= 32 and ord(c) != 127 for c in name),
            'Parameter include requires an absolute path without quote/backslash/control characters')
    return '-DRK_MIG_ECC_PARAMS_HEADER='+json.dumps(name,ensure_ascii=False)


def profile_plan(simulator, name, producer, output, tools, vendor_sources=()):
    producer = Path(producer); directory = producer/relative(output)
    top = 'tb_mig_ecc_monitor' if name == 'portable' else 'tb_mig_ecc_vendor'
    sources = [str(producer/'rtl/ddr/rk_mig_ecc_monitor.sv'), str(producer/f'tests/ddr/{top}.sv')]
    sources += [str(producer/relative(p)) for p in vendor_sources]
    definitions = [parameter_include(producer,output)] if name == 'vendor' else []
    if simulator == 'iverilog':
        image = str(relative(output)/(name+'.vvp'))
        build = [tools['simulator']['path'], *definitions, '-g2012', '-Wall', '-s', top,
                 '-I', str(directory), '-o', str(producer/image), *sources]
        run = [tools['runtime']['path'], str(producer/image)]
    else:
        image = str(relative(output)/name/'sim')
        build = [tools['simulator']['path'], *definitions, *(['-Wno-fatal'] if name == 'vendor' else []),
                 '--binary', '--timing', '--assert', '-Wall', '--top-module', top, '-j', '2',
                 '-MAKEFLAGS', 'CXX='+shlex.quote(tools['cxx']['path']),
                 '--Mdir', str(directory/name), '-o', 'sim', '-I'+str(directory), *sources]
        run = [str(producer/image)]
    expected = (f"PASS mig_ecc_monitor cases={29 if simulator == 'iverilog' else 23} scope=independent_control_slave_only"
                if name == 'portable' else
                'PASS mig_ecc_vendor scenarios=21 raw_event_vectors=16 held_snapshots=2 no_MIG_memory_or_retirement_proof')
    return dict(build=build, run=run, image=image, result=expected)


def check_inputs(expected):
    current = fingerprint([ROOT/relative(p) for p in expected['files']])
    require(current == expected, 'Source/generated input changed during execution')
    return current


def diagnostics(output, simulator):
    result = []
    for line in output.splitlines():
        if simulator == 'verilator':
            match = re.fullmatch(r'%Warning-([^:]+): (.*?):([0-9]+):([0-9]+): (.*)', line)
            if match:
                result.append(dict(code=match[1], file=Path(match[2]).name,
                                   line=int(match[3]), column=int(match[4]), message=match[5]))
            else:
                require('%Warning' not in line and 'warning:' not in line.lower(),
                        'Unrecognized compiler warning: '+line)
        else:
            match = re.fullmatch(r'(.*?):([0-9]+): (warning: .*|       : Padding .*)', line)
            if match:
                result.append(dict(file=Path(match[1]).name, line=int(match[2]), message=match[3]))
            else:
                require('warning:' not in line.lower(), 'Unrecognized compiler warning: '+line)
    return result


def extract(archive, out, policy):
    plan = vendor_plan(str(out.relative_to(ROOT)), policy)
    require(digest(archive) == plan['archive_sha256'], 'Archive identity differs')
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        require(len(names) == len(set(names)), 'Duplicate archive members')
        for name,member in plan['members'].items():
            data = bundle.read(member)
            require(hashlib.sha256(data).hexdigest() == plan['files'][name], 'Archive member changed: '+member)
            path = ROOT/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    (ROOT/plan['header_name']).write_text(plan['header'])
    check_inputs(manifest(plan['files']))
    return plan


def verify_report(path):
    """Check copied source, images and logs without tools or the original ZIP."""
    return verify_record(load_json(path))


def verify_record(report):
    require(type(report.get('execution_schema')) is int and report['execution_schema'] == 2,
            'Missing complete execution binding; rerun the current producer')
    require(report['status'] == 'PASS_ECC_MONITOR_CONTROL_ONLY', 'Completed control-only run required')
    require(report['source'] == source_revision(), 'Monitor source changed')
    require(report['scope'] == SCOPE, 'Execution scope changed')
    for key in ('vivado_executed', 'vendor_ip_executed', 'hardware_accessed',
                'controller_simulated', 'memory_retirement_verified', 'electrical_profile_adopted'):
        require(report[key] is False, 'Invalid execution/physical claim: '+key)
    simulator = report['simulator']
    require(simulator in ('iverilog', 'verilator') and type(report['vendor_control_test']) is bool,
            'Unsupported test profile')
    profiles = ['portable', 'vendor'] if report['vendor_control_test'] else ['portable']
    require([item['name'] for item in report['tests']] == profiles, 'Scenario profile inventory changed')
    policy = load_json(ROOT/'tests/ddr/vendor_warnings.json')
    producer = Path(report['execution_root'])
    require(producer.is_absolute(), 'Missing original execution root')
    output = str(relative(report['output_directory']))
    tools = report['tools']
    require(set(tools) == {'simulator', 'runtime' if simulator == 'iverilog' else 'cxx'}, 'Tool inventory changed')
    for role,identity in tools.items():
        basename = simulator if role == 'simulator' else 'vvp' if role == 'runtime' else 'c++'
        require(set(identity) == {'path','sha256'} and Path(identity['path']).is_absolute() and
                Path(identity['path']).name == basename and
                re.fullmatch('[0-9a-f]{64}', identity['sha256']), 'Invalid tool identity: '+role)
    versions = version_plan(simulator, tools)
    names = [n for n,_,_ in versions] + [p+'-'+stage for p in profiles for stage in ('build','run')]
    require([c['name'] for c in report['commands']] == names, 'Command inventory/order changed')
    commands = {c['name']:c for c in report['commands']}
    vendor = vendor_plan(output, policy) if report['vendor_control_test'] else dict(files={},compiled=[])
    if report['vendor_control_test']:
        require(report['archive_sha256'] == vendor['archive_sha256'] and
                report['tool_version'] == policy[simulator+'_version'], 'Vendor/tool identity changed')
    else:
        require('archive_sha256' not in report, 'Portable test cannot claim archived input')
    inputs = manifest(report['source']['files'] | vendor['files'])
    require(report['execution_inputs'] == inputs, 'Execution input inventory changed')
    check_inputs(inputs)
    files = report['artifacts']['files']
    require(manifest(files) == report['artifacts'], 'Artifact manifest changed')
    expected_files = set(vendor['files']) | {str(Path(output)/(name+'.log')) for name in names}
    for profile in profiles:
        expected_files.add(profile_plan(simulator, profile, producer, output, tools, vendor['compiled'] if profile == 'vendor' else ())['image'])
    require(set(files) == expected_files, 'Execution artifact inventory changed')
    for name,expected in files.items():
        require(digest(ROOT/relative(name)) == expected, 'Execution artifact changed: '+name)
    if report['vendor_control_test']:
        require((ROOT/vendor['header_name']).read_text() == vendor['header'], 'Generated control parameters changed')

    def admitted_command(name, argv, executable):
        command = commands[name]
        require(command['argv'] == argv, 'Execution argv changed: '+name)
        require(command['environment_overrides'] == ENVIRONMENT, 'Execution environment changed')
        require(command['status'] == 'PASS' and type(command['returncode']) is int and command['returncode'] == 0,
                'Execution did not pass: '+name)
        log = str(Path(output)/(name+'.log'))
        require(command['log'] == log and files[log] == command['log_sha256'], 'Execution/log binding changed')
        require(command['executable_before'] == command['executable_after'] == executable,
                'Executed tool/image identity changed: '+name)
        text = (ROOT/log).read_text()
        require(not re.search(r'(?m)^(?:FATAL:|ERROR:|FAIL|%Error)', text), 'Failure in execution log')
        return command,text

    for name,argv,role in versions:
        _,text = admitted_command(name, argv, tools[role])
        field = {'simulator':'tool_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
        require(text.splitlines() and text.splitlines()[0] == report[field] and report[field].strip(),
                'Tool version/log binding changed')
    for profile,result in zip(profiles, report['tests']):
        plan = profile_plan(simulator, profile, producer, output, tools, vendor['compiled'] if profile == 'vendor' else ())
        image = dict(path=plan['image'], sha256=files[plan['image']])
        require(result == dict(name=profile,status='PASS',result=plan['result'],image=image['path'],image_sha256=image['sha256']),
                'Scenario/image result changed')
        build,build_text = admitted_command(profile+'-build', plan['build'], tools['simulator'])
        executable = tools['runtime'] if simulator == 'iverilog' else dict(path=str(producer/image['path']),sha256=image['sha256'])
        run,run_text = admitted_command(profile+'-run', plan['run'], executable)
        require(build['output_image'] == image and run['image'] == image['path'] and
                run['image_sha256_before'] == run['image_sha256_after'] == image['sha256'],
                'Compiled/executed image binding changed')
        for command in (build,run):
            require(command['inputs_before'] == command['inputs_after'] == inputs, 'Execution input boundary changed')
        require([line for line in run_text.splitlines() if line.startswith('PASS ')] == [plan['result']],
                'Execution result changed')
        admitted = policy[simulator] if profile == 'vendor' else (policy['portable_iverilog'] if simulator == 'iverilog' else [])
        require(diagnostics(build_text, simulator) == admitted == build['admitted_diagnostics'], 'Warning admission changed')
    return dict(status='VERIFIED_ECC_MONITOR_CONTROL_ONLY', tests=profiles,
                vendor_control_test=report['vendor_control_test'], memory_retirement_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'), default='verilator')
    parser.add_argument('--archive', type=Path, help='Pinned existing XDMA ZIP; enables actual control-leaf test')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--verify', type=Path, help='Verify a completed report without executing tools')
    args = parser.parse_args()
    if args.verify:
        require(args.out is None and args.archive is None, 'Verification does not run a new test')
        print(json.dumps(verify_report(args.verify), indent=2))
        return 0
    out = (args.out or ROOT/'build/ddr-ecc-monitor'/f'{args.simulator}-{time.time_ns()}').resolve()
    require(out.is_relative_to(ROOT) and not out.exists(), 'Use a fresh in-workspace output directory')
    out.mkdir(parents=True)
    source = source_revision()
    report = dict(status='RUNNING', execution_schema=2, started_utc=timestamp(), execution_root=str(ROOT),
                  output_directory=str(out.relative_to(ROOT)), simulator=args.simulator,
                  scope=SCOPE, source=source, commands=[], tests=[], tools={}, vendor_control_test=args.archive is not None,
                  vivado_executed=False, vendor_ip_executed=False, hardware_accessed=False,
                  controller_simulated=False, memory_retirement_verified=False, electrical_profile_adopted=False)
    report_path = out/'report.json'
    artifacts = set()

    def save():
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')

    def execute(name, argv, image=None, timeout=300, bind_inputs=False):
        for identity in report['tools'].values():
            require(tool_identity(identity['path']) == identity, 'Selected tool changed before execution')
        entry = dict(name=name, argv=[str(v) for v in argv], status='RUNNING',
                     log=str((out/(name+'.log')).relative_to(ROOT)), environment_overrides=ENVIRONMENT,
                     executable_before=tool_identity(argv[0]))
        if image is not None:
            entry.update(image=str(image.relative_to(ROOT)), image_sha256_before=digest(image))
        if bind_inputs:
            entry['inputs_before'] = check_inputs(report['execution_inputs'])
        report['commands'].append(entry)
        save()
        start = time.monotonic()
        try:
            with (ROOT/entry['log']).open('w') as log:
                result = subprocess.run(entry['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                        check=False, timeout=timeout, env=dict(os.environ, **ENVIRONMENT))
            entry.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
            require(result.returncode == 0, 'Command failed: '+name)
            entry['executable_after'] = tool_identity(argv[0])
            require(entry['executable_after'] == entry['executable_before'], 'Executed program changed: '+name)
            for identity in report['tools'].values():
                require(tool_identity(identity['path']) == identity, 'Selected tool changed during execution')
            if bind_inputs:
                entry['inputs_after'] = check_inputs(report['execution_inputs'])
            if image is not None:
                entry['image_sha256_after'] = digest(image)
                require(entry['image_sha256_after'] == entry['image_sha256_before'], 'Execution image changed: '+name)
        except subprocess.TimeoutExpired:
            entry['status'] = 'TIMEOUT'
            raise
        finally:
            entry['seconds'] = round(time.monotonic()-start, 3)
            path = ROOT/entry['log']
            if path.exists():
                entry['log_sha256'] = digest(path)
                artifacts.add(path)
            save()
        output = (ROOT/entry['log']).read_text()
        require(not re.search(r'(?m)^(?:FATAL:|ERROR:|FAIL|%Error)', output), 'Failure in tool output: '+name)
        return output

    save()
    try:
        tool = shutil.which(args.simulator)
        require(tool is not None, 'UNAVAILABLE: '+args.simulator)
        report['tools']['simulator'] = tool_identity(tool)
        if args.simulator == 'iverilog':
            runtime = shutil.which('vvp')
            require(runtime is not None, 'UNAVAILABLE: vvp')
            report['tools']['runtime'] = tool_identity(runtime)
        else:
            compiler = shutil.which('c++')
            require(compiler is not None, 'UNAVAILABLE: c++')
            report['tools']['cxx'] = tool_identity(compiler)
        for name,argv,role in version_plan(args.simulator,report['tools']):
            field = {'simulator':'tool_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
            report[field] = execute(name, argv).splitlines()[0]
        policy = load_json(ROOT/'tests/ddr/vendor_warnings.json')
        profiles = ['portable']; vendor = dict(files={},compiled=[])
        if args.archive:
            vendor = extract(args.archive.expanduser().resolve(strict=True), out, policy)
            artifacts.update(ROOT/n for n in vendor['files'])
            report['archive_sha256'] = vendor['archive_sha256']
            require(report['tool_version'] == policy[args.simulator+'_version'], 'Vendor warning policy tool version differs')
            profiles.append('vendor')
        report['execution_inputs'] = manifest(source['files'] | vendor['files'])
        check_inputs(report['execution_inputs'])
        for name in profiles:
            plan = profile_plan(args.simulator,name,ROOT,report['output_directory'],report['tools'],
                                vendor['compiled'] if name == 'vendor' else ())
            binary = ROOT/plan['image']
            build = execute(name+'-build', plan['build'], bind_inputs=True)
            actual = diagnostics(build, args.simulator)
            admitted = policy[args.simulator] if name == 'vendor' else (
                policy['portable_iverilog'] if args.simulator == 'iverilog' else [])
            require(actual == admitted, 'Unexpected warning inventory: '+name)
            artifacts.add(binary)
            report['commands'][-1]['admitted_diagnostics'] = actual
            image = dict(path=plan['image'],sha256=digest(binary))
            report['commands'][-1]['output_image'] = image
            require(digest(binary) == image['sha256'], 'Compiled image changed before execution')
            output = execute(name+'-run', plan['run'], image=binary, bind_inputs=True)
            require(digest(binary) == image['sha256'], 'Compiled image changed during execution')
            require([line for line in output.splitlines() if line.startswith('PASS ')] == [plan['result']],
                    'Incorrect scenario inventory: '+name)
            report['tests'].append(dict(name=name,status='PASS',result=plan['result'],
                                        image=image['path'],image_sha256=image['sha256']))
        require(source_revision() == source, 'Monitor source changed during verification')
        check_inputs(report['execution_inputs'])
        report.update(status='PASS_ECC_MONITOR_CONTROL_ONLY', finished_utc=timestamp(), artifacts=fingerprint(artifacts))
        verify_record(report)
        save()
        verify_report(report_path)
        print(report_path)
        return 0
    except BaseException as error:
        report.update(status='UNAVAILABLE' if 'UNAVAILABLE:' in str(error) else 'FAIL',
                      finished_utc=timestamp(), error=repr(error), artifacts=fingerprint(artifacts))
        save()
        raise


if __name__ == '__main__':
    raise SystemExit(main())
