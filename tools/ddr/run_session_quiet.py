#!/usr/bin/env python3
"""Reproduce the dual-host session-quiet comparison in fresh source and build copies."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.owned_process import run_owned
LEAF = ROOT / 'rtl/ddr/capacity/rk_job_control_admission.sv'
WRAPPER = ROOT / 'rtl/ddr/framework/rk_layout_job_control.sv'
VARIANT_LEAF = ROOT / 'rtl/ddr/dual_host/rk_job_control_admission.sv'
VARIANT_WRAPPER = ROOT / 'rtl/ddr/dual_host/rk_layout_job_control.sv'
BENCH = ROOT / 'tests/ddr/dual_host/tb_session_quiet.sv'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def rename_exact(source, replacements, label):
    result = source
    for old, new, count in replacements:
        observed = result.count(old)
        require(observed == count, f'{label}: expected {count} occurrences of {old!r}, got {observed}')
        result = result.replace(old, new)
    return result


def git_metadata():
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
    require(re.fullmatch(r'[0-9a-f]{40,64}', revision) is not None, 'Could not identify Git revision')
    dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT,
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout)
    return revision, dirty


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('both', 'iverilog', 'verilator'), default='both')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = (args.out if args.out is not None else ROOT / 'build/dual-host-quiet-public-runner-v1' / stamp).resolve()
    out.mkdir(parents=True, exist_ok=False)
    refs = out / 'reference'
    refs.mkdir()
    leaf_name = 'rk_job_control_admission_reference'
    wrapper_name = 'rk_layout_job_control_reference'
    leaf_text = LEAF.read_text()
    wrapper_text = WRAPPER.read_text()
    ref_leaf = rename_exact(leaf_text, [('module rk_job_control_admission #(', f'module {leaf_name} #(', 1)], 'leaf')
    ref_wrapper = rename_exact(wrapper_text,
        [('module rk_layout_job_control #(', f'module {wrapper_name} #(', 1),
         ('rk_job_control_admission #(.DEVICE_ID(ID)) control (', f'{leaf_name} #(.DEVICE_ID(ID)) control (', 2)], 'wrapper')
    leaf_copy, wrapper_copy = refs / 'rk_job_control_admission_reference.sv', refs / 'rk_layout_job_control_reference.sv'
    leaf_copy.write_text(ref_leaf)
    wrapper_copy.write_text(ref_wrapper)
    owned_helper = ROOT / 'tools/owned_process.py'
    originals = [LEAF, WRAPPER, VARIANT_LEAF, VARIANT_WRAPPER, BENCH, Path(__file__).resolve(), owned_helper]
    copied = [leaf_copy, wrapper_copy]
    selected = ['iverilog', 'verilator'] if args.simulator == 'both' else [args.simulator]
    tools = {name: shutil.which(name) for name in ('iverilog', 'vvp', 'verilator')}
    needed = ['iverilog', 'vvp'] if selected == ['iverilog'] else ['verilator'] if selected == ['verilator'] else list(tools)
    top = 'tb_session_quiet'
    revision, dirty = git_metadata()
    report = dict(status='RUNNING', scope='Native dual-host session-quiet comparison only; not full NPU, FPGA, CDC or RK qualification',
        source_revision=revision, workspace_dirty=dirty,
        stimulus='Deterministic directed protocol sequences; no random stimulus or random seed used',
        random_seed='not applicable; no random stimulus',
        source_hashes_before={str(p.relative_to(ROOT)): sha(p) for p in originals},
        transformed_sources={p.name: dict(sha256=sha(p), derived_from=sha(src)) for p, src in zip(copied, [LEAF, WRAPPER])},
        transformation='Exact module declaration renames and one wrapper child-instance type rename; all other bytes preserved',
        commands=[], simulators={}, hardware_accessed=False, vivado_executed=False, ram_limits_imposed=False)
    report_path = out / 'report.json'

    def save():
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(name, argv, cwd, timeout):
        log = out / (name + '.log')
        started = time.monotonic()
        with log.open('xb') as stream:
            try:
                result = run_owned(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                   timeout=timeout)
            except BaseException as error:
                cleanup = getattr(error, 'owned_process_cleanup', {})
                report['commands'].append(dict(name=name, argv=argv, returncode=None, timed_out=False,
                    status='EXCEPTION',
                    timeout_seconds=timeout, seconds=time.monotonic() - started, log=str(log),
                    log_sha256=sha(log), pid=cleanup.get('pid'), pgid=cleanup.get('pgid'),
                    live_before_cleanup=cleanup.get('live_before_cleanup'),
                    live_after_cleanup=cleanup.get('live_after_cleanup'), exception=repr(error)))
                save()
                raise
        rc = result.returncode
        report['commands'].append(dict(name=name, argv=argv, returncode=rc, timed_out=result.timed_out,
            status='PASS' if rc==0 and not result.timed_out and not result.live_before_cleanup and not result.live_after_cleanup else 'FAIL',
            timeout_seconds=timeout, seconds=time.monotonic() - started, log=str(log), log_sha256=sha(log),
            pid=result.pid, pgid=result.pid, live_before_cleanup=list(result.live_before_cleanup),
            live_after_cleanup=list(result.live_after_cleanup)))
        save()
        require(rc == 0 and not result.timed_out and not result.live_before_cleanup and
                not result.live_after_cleanup, 'Native command failed or left descendants: ' + name)
        output = log.read_text(errors='replace')
        require(not re.search(r'(?m)^%Warning-|^%Error|(?i:warning:|sorry:)', output), 'Unexpected tool diagnostics: ' + name)
        return output

    save()
    try:
        require(all(tools[name] for name in needed), 'UNAVAILABLE: required native simulator not installed')
        for name in needed:
            flag = '-V' if name in ('iverilog', 'vvp') else '--version'
            output = run(name + '_version', [tools[name], flag], out, 30)
            report['simulators'][name] = dict(path=tools[name], binary_sha256=sha(Path(tools[name]).resolve()), version=output.splitlines()[0])
        for sim in selected:
            d = out / sim
            d.mkdir()
            sources = [str(BENCH), str(VARIANT_LEAF), str(VARIANT_WRAPPER), str(leaf_copy), str(wrapper_copy)]
            if sim == 'iverilog':
                image = d / 'sim.vvp'
                compile_argv = [tools[sim], '-g2012', '-Wall', '-s', top, '-o', str(image)] + sources
                execute = [tools['vvp'], str(image)]
            else:
                image = d / 'obj/sim'
                compile_argv = [tools[sim], '--binary', '--timing', '--assert', '-Wall', '-j', '2', '--top-module', top,
                    '--Mdir', str(d / 'obj'), '-o', 'sim'] + sources
                execute = [str(image)]
            run(sim + '_compile', compile_argv, d, 600)
            output = run(sim + '_run', execute, d, 60)
            markers = re.findall(r'^PASS checks=(\d+) simulator=Icarus/Verilator$', output, re.M)
            require(markers == ['105'], 'Missing or changed complete 105-check marker: ' + sim)
            report['simulators'][sim].update(checks=105, image=str(image), image_sha256=sha(image), four_state_controls=(sim == 'iverilog'))
        after = {str(p.relative_to(ROOT)): sha(p) for p in originals}
        require(after == report['source_hashes_before'], 'Input sources changed during execution')
        report.update(status='PASS_DUAL_HOST_SESSION_QUIET_NATIVE_ONLY', source_hashes_after=after,
            note='Dual-host variant modules are compared with fresh reference copies of the public original modules under exact renamed identities.')
    except BaseException as error:
        report.update(status='FAIL_DUAL_HOST_SESSION_QUIET_NATIVE_ONLY', error=repr(error))
        save()
        raise
    save()
    print(json.dumps(dict(status=report['status'], report=str(report_path), simulators=selected)))


if __name__ == '__main__':
    main()
