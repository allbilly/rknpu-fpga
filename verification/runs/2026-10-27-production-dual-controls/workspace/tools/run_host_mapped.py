#!/usr/bin/env python3
"""Supplemental full mapped endpoint replay; no RTL DUT leaf substitutions."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from evidence import fingerprint, source_revision, timestamp

OUT = ROOT / 'build/yosys_host_mapped'
OUT.mkdir(exist_ok=True)
LOCK = threading.Lock()
report = {'status': 'RUNNING', 'started_utc': timestamp(), 'source_revision': source_revision(),
          'scope': 'Entire rk_ew_axi XC7 netlist with matched test parameters TIMEOUT_CYCLES=128 and MAX_TASKS=4, public-port host bench and behavioral AXI RAM. The generated bench only removes the now-fixed parameter override; all assertions remain unchanged. No RTL DUT leaf substitutions. Default-parameter production mapping is separate. Functional models only; no routed timing, MIG/ECC/DDR, PCIe or physical/RK silicon validation.',
          'commands': [], 'tests': [], 'seed': '0x3588c510', 'workers': 2,
          'timeout_seconds_per_run': 600, 'startup_clock_hold_ns': 200}


def save():
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


def execute(argv, name):
    log = OUT / f'{name}.log'
    record = {'argv': argv, 'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    with LOCK:
        report['commands'].append(record)
        save()
    start = time.monotonic()
    try:
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=600, check=False)
        with LOCK:
            record.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
    except subprocess.TimeoutExpired:
        with LOCK:
            record['status'] = 'TIMEOUT'
        raise
    finally:
        with LOCK:
            record['seconds'] = round(time.monotonic() - start, 3)
            save()
    output = log.read_text()
    with LOCK:
        record['warnings'] = [s for s in output.splitlines() if 'warning:' in s.lower()]
        save()
    if result.returncode:
        raise RuntimeError(f'{name}: exit {result.returncode}; {output[-2500:]}')
    return output


save()
missing = [name for name in ('yosys', 'iverilog', 'vvp') if not shutil.which(name)]
if missing:
    report.update(status='UNAVAILABLE', reason=f'Missing tools: {missing}', finished_utc=timestamp())
    save()
    print(report['reason'], file=sys.stderr)
    sys.exit(2)
try:
    mapping_path = ROOT / 'build/yosys_host/report.json'
    rtl_path = ROOT / 'build/rtl/report.json'
    mapping = json.loads(mapping_path.read_text())
    rtl = json.loads(rtl_path.read_text())
    for parent in (mapping, rtl):
        if parent['status'] != 'PASS' or parent['source_revision'] != report['source_revision']:
            raise RuntimeError('Require completed mapping and RTL reports for this exact source')
    report['parent_reports'] = fingerprint([mapping_path, rtl_path])
    production_netlist = ROOT / 'build/yosys_host/rk_ew_axi_netlist.v'
    if hashlib.sha256(production_netlist.read_bytes()).hexdigest() != mapping['artifacts']['files'][str(production_netlist.relative_to(ROOT))]:
        raise RuntimeError('Mapped netlist no longer matches its successful mapping report')
    report['test_parameters'] = {'TIMEOUT_CYCLES': 128, 'MAX_TASKS': 4}
    report['yosys_version'] = execute(['yosys', '-V'], 'yosys_version').strip()
    netlist = OUT / 'rk_ew_axi_test_netlist.v'
    design = OUT / 'rk_ew_axi_test.json'
    names = ['rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma',
             'rk_axi_mem', 'rk_job_control', 'rk_ew_axi']
    script = ('read_verilog -sv ' + ' '.join(json.dumps(str(ROOT / 'rtl' / f'{n}.sv')) for n in names) +
              '; chparam -set TIMEOUT_CYCLES 128 -set MAX_TASKS 4 rk_ew_axi; ' +
              'hierarchy -check -top rk_ew_axi; proc; opt_clean; check -assert; ' +
              'synth_xilinx -family xc7 -top rk_ew_axi -flatten; check -assert; ' +
              f'write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}')
    execute(['yosys', '-Q', '-T', '-p', script], 'matched_parameter_mapping')
    mapped = json.loads(design.read_text())['modules']['rk_ew_axi']
    actual_parameters = {k: int(v, 2) for k, v in mapped['parameter_default_values'].items()}
    if actual_parameters != report['test_parameters']:
        raise RuntimeError(f'Mapped parameters differ from bench: {actual_parameters}')
    if any(c['type'].startswith('$') and c['type'] != '$scopeinfo' for c in mapped['cells'].values()):
        raise RuntimeError('Unmapped internal cell in test-parameter netlist')
    report['mapped_parameters'] = actual_parameters
    report['mapping_artifacts'] = fingerprint([netlist, design])
    template = ROOT / 'tests/tb_host_axi.sv'
    bench = OUT / 'tb_host_axi_fixed.sv'
    original = template.read_text()
    override = 'rk_ew_axi #(.TIMEOUT_CYCLES(128), .MAX_TASKS(4)) dut(.*);'
    fixed = 'rk_ew_axi dut(.*);'
    if original.count(override) != 1:
        raise RuntimeError('Unexpected bench template; refusing a broad rewrite')
    adapted = original.replace(override, fixed)
    if adapted.replace(fixed, override) != original:
        raise RuntimeError('Bench adaptation changed more than the parameter override')
    bench.write_text(adapted)
    report['bench_adaptation'] = {'template': str(template.relative_to(ROOT)),
                                 'generated': str(bench.relative_to(ROOT)),
                                 'only_change': 'Remove the parameter override because the mapped netlist is already elaborated with exactly 128/4. No checks or stimulus changed.'}
    wrapper = ROOT / 'tests/tb_host_axi_netlist.sv'
    extra = [wrapper, Path(__file__).resolve(), netlist, bench]
    report['additional_sources'] = fingerprint(extra)
    report['iverilog_version'] = execute(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
    report['vvp_version'] = execute(['vvp', '-V'], 'vvp_version').splitlines()[0]
    vendor = ROOT / 'tests/vendor/xilinx-unisim'
    binary = OUT / 'host_netlist.vvp'
    execute(['iverilog', '-g2012', '-Wall', '-s', 'tb_host_axi_netlist', '-s', 'glbl',
             '-y', str(vendor / 'verilog/src/unisims'), '-o', str(binary),
             str(vendor / 'verilog/src/glbl.v'), str(netlist),
             str(bench), str(wrapper)], 'host_netlist_build')
    report['executable'] = fingerprint([binary])
    cases_path = ROOT / 'build/dma_vectors/cases.json'
    cases = [c for c in json.loads(cases_path.read_text()) if c['production_capture']]
    sub = next(c for c in cases if c['name'] == 'capture_sub_9')
    jobs = [(c['name'], c, 0, 1) for c in cases]
    jobs += [(f'fault_{f}', sub, f, 1) for f in (*range(1, 9), 10)]
    jobs += [('reset_partial_write', sub, 9, 1), ('repeat_sub_9', sub, 0, 2)]
    inputs = [cases_path]
    for c in cases:
        inputs += [ROOT / 'build/dma_vectors' / c['name'] / name for name in ('input.hex', 'check.txt')]
    report['stimuli'] = fingerprint(inputs)
    observed = []
    baselines = [ROOT / 'build/rtl' / f"{c['name']}_observed.hex" for c in cases]
    report['direct_memory_baselines'] = fingerprint(baselines)
    for name, digest in report['direct_memory_baselines']['files'].items():
        if digest != rtl['dma_observed_memory']['files'][name]:
            raise RuntimeError('Baseline image no longer matches its RTL report')

    def run(job):
        name, case, fault, repeats = job
        image = OUT / f'{name}_observed.hex'
        output = execute(['vvp', str(binary), f"+CASE={ROOT}/build/dma_vectors/{case['name']}",
                          f'+OUTPUT={image}', f"+START={case['address']:08x}", f"+AMOUNT={case['amount']}",
                          f"+NTASKS={case['tasks']}", f"+NTRANS={case['transactions']}", f"+NCHECKS={case['checks']}",
                          f'+FAULT={fault}', f'+REPEATS={repeats}'], name)
        passes = [line for line in output.splitlines() if line.startswith('PASS host_axi ')]
        if len(passes) != 1:
            raise RuntimeError(f'{name}: missing or duplicated PASS marker')
        if fault in (0, 9):
            baseline = ROOT / 'build/rtl' / f"{case['name']}_observed.hex"
            if image.read_bytes() != baseline.read_bytes():
                raise RuntimeError(f'{name}: mapped memory differs from direct-memory RTL')
            with LOCK:
                observed.append(image)
        with LOCK:
            report['tests'].append({'name': name, 'status': 'PASS', 'fault': fault,
                                    'repeats': repeats, 'results': passes})
            save()
        print(f'PASS mapped endpoint {name}', flush=True)

    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(run, job): job[0] for job in jobs}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                errors.append(f'{futures[future]}: {exc}')
    if errors:
        raise RuntimeError('\n'.join(errors))
    if len(report['tests']) != 20 or len(observed) != 11:
        raise RuntimeError('Incomplete mapped test/image count')
    report['observed_memory'] = fingerprint(observed)
    if (source_revision() != report['source_revision'] or fingerprint(extra) != report['additional_sources']
            or fingerprint(inputs) != report['stimuli'] or fingerprint([binary]) != report['executable']
            or fingerprint(baselines) != report['direct_memory_baselines']
            or fingerprint([mapping_path, rtl_path]) != report['parent_reports']):
        raise RuntimeError('Source, executable or stimulus changed during verification')
    report.update(status='PASS', finished_utc=timestamp())
    save()
    print('PASS all 20 full mapped-endpoint runs; 11 observed images equal direct-memory RTL', flush=True)
except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError) as exc:
    report.update(status='FAIL', finished_utc=timestamp(), reason=str(exc))
    save()
    print(str(exc), file=sys.stderr)
    sys.exit(1)
