#!/usr/bin/env python3
"""Isolated wire/PIP round-trip correction; retain the full original archcheck.

Reuse completed variantfix objects, replacing only arch.cc.o. The donor build,
checkout, binary and original chipdb are never modified. No placement/programming.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--base-report', type=Path, required=True)
p.add_argument('--repair-report', type=Path, required=True)
a = p.parse_args()
parent_path, repair_path = a.base_report.resolve(), a.repair_report.resolve()
parent, repair = json.loads(parent_path.read_text()), json.loads(repair_path.read_text())
assert parent['status'] == 'FAIL' and 'WIRE_NAME_MISMATCH' in parent['reason']
assert repair['status'] == 'GENERATED_ROUTING_Z_REPAIR_CANDIDATE'
assert repair['all_placeable_coordinates_unchanged'] and repair['all_other_bytes_unchanged']
assert repair['patched_bytes'] == 16 and len(repair['changes']) == 8

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert digest(ROOT / name) == sha, name

verify(parent['source']); verify(repair['source'])
assert all(c['status'] == 'PASS' for c in parent['commands'] if not c['log'].endswith('/integrity.log'))
checkout = ROOT / 'build/reference/nextpnr-xilinx-variantfix'
build = parent_path.parent / 'build'
donor_binary = build / 'nextpnr-xilinx'
assert digest(donor_binary) == parent['binary_sha256']
original_db = ROOT / 'build/openxc7/xc7k480tffg1156-2.bin'
chipdb = ROOT / repair['candidate']
assert digest(original_db) == repair['original_chipdb_sha256']
assert digest(chipdb) == repair['candidate_chipdb_sha256']
assert parent['base_revision'] == 'd486d8ef6a1c756ca72b2ba495e7e18e4c24815d'
assert subprocess.check_output(['git', '-C', checkout, 'rev-parse', 'HEAD'], text=True).strip() == parent['base_revision']

out = ROOT / f'build/openxc7/lookupfix-{time.time_ns()}'
out.mkdir(exist_ok=False)
original = (checkout / 'xilinx/arch.cc').read_text()
modified = original.replace('#include "bel_variant_name.h"', '#include "bel_variant_name.h"\n#include "pip_index_name.h"')
assert modified != original
start, end = modified.index('WireId Arch::getWireByName('), modified.index('IdString Arch::getWireType(')
wire = modified[start:end]
old = 'ret.tile = tile;\n                ret.index = i;'
assert wire.count(old) == 2
wire = wire.replace(old, 'ret = canonicalWireId(chip_info, tile, i);')
modified = modified[:start] + wire + modified[end:]
start, end = modified.index('PipId Arch::getPipByName('), modified.index('IdString Arch::getPipName(')
lookup = modified[start:end]
old = 'if (s.substr(0, 8) == "SITEPIP/") {'
assert lookup.count(old) == 1
new = '''if (s.compare(0, 4, "PIP/") == 0) {
        std::string tile_name;
        int index;
        if (!rk_openxc7::parse_pip_index_name(s, tile_name, index))
            return PipId();
        auto found = tile_by_name.find(tile_name);
        if (found == tile_by_name.end())
            return PipId();
        const int tile = found->second;
        const auto &tile_info = chip_info->tile_types[chip_info->tile_insts[tile].type];
        if (index >= tile_info.num_pips)
            return PipId();
        ret.tile = tile;
        ret.index = index;
    } else if (s.substr(0, 8) == "SITEPIP/") {'''
lookup = lookup.replace(old, new)
modified = modified[:start] + lookup + modified[end:]
start, end = modified.index('IdString Arch::getPipName('), modified.index('void Arch::setup_pip_blacklist(')
modified = modified[:start] + '''IdString Arch::getPipName(PipId pip) const
{
    NPNR_ASSERT(pip != PipId());
    NPNR_ASSERT(pip.tile >= 0 && pip.tile < chip_info->num_tiles);
    NPNR_ASSERT(pip.index >= 0 && pip.index < locInfo(pip).num_pips);
    // Identify the exact record, including site variants and parallel edges.
    // Fixed-route import/export has its own unchanged tile/src.dst format.
    return id(std::string("PIP/") + chip_info->tile_insts[pip.tile].name.get() +
              "/" + std::to_string(pip.index));
}

''' + modified[end:]
source = out / 'arch.cc'
source.write_text(modified)
patch = out / 'wire-pip.patch'
patch.write_text(''.join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True),
                                           fromfile='a/xilinx/arch.cc', tofile='b/xilinx/arch.cc')))
header = Path(__file__).with_name('pip_index_name.h')
test = Path(__file__).with_name('test_pip_index_name.cpp')
shutil.copy2(header, out / header.name)
flags_file, link_file = [build / ('CMakeFiles/nextpnr-xilinx.dir/' + n) for n in ('flags.make', 'link.txt')]
flags = {k: shlex.split(v) for line in flags_file.read_text().splitlines() if ' = ' in line
         for k, v in [line.split(' = ', 1)]}
link = shlex.split(link_file.read_text())
objects = [(build / arg).resolve() for arg in link if arg.endswith('.o')]
tracked = [Path(__file__).resolve(), header, test, source, patch, out / header.name,
           parent_path, repair_path, flags_file, link_file, donor_binary] + objects
tracked += [ROOT / n for n in parent['source']['files']]
tracked += sorted(checkout.rglob('*.h'))
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              base_revision=parent['base_revision'], source_patch=str(patch.relative_to(ROOT)),
              original_chipdb_sha256=repair['original_chipdb_sha256'],
              candidate_chipdb_sha256=repair['candidate_chipdb_sha256'], commands=[],
              memory_limit_bytes=8*1024**3, timeout_seconds=7200,
              scope='Experimental canonical wire/PIP lookup plus routing-only z repair. Full unchanged archcheck assertions, not physical timing/DRC, netlist validation or FPGA operation.')

def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')

def limits():
    resource.setrlimit(resource.RLIMIT_AS, (report['memory_limit_bytes'], report['memory_limit_bytes']))

def run(argv, name):
    step = dict(argv=list(map(str, argv)), cwd=str(build), status='RUNNING',
                log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            with subprocess.Popen(step['argv'], cwd=build, stdout=log, stderr=subprocess.STDOUT,
                                  start_new_session=True, preexec_fn=limits) as process:
                try:
                    process.wait(timeout=report['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait()
                    raise
        text = (ROOT / step['log']).read_text()
        step['returncode'] = process.returncode
        assert process.returncode == 0, text[-6000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-start, 3); save()

save()
try:
    report['compiler_version'] = run([link[0], '--version'], 'compiler_version').splitlines()[0]
    run([link[0], '-std=c++17', '-Wall', '-Wextra', '-Werror', test, '-o', out / 'parser_test'], 'parser_compile')
    report['parser_result'] = run([out / 'parser_test'], 'parser_test').strip()
    obj, binary = out / 'arch.cc.o', out / 'nextpnr-lookupfix'
    run([link[0], *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], *flags['CXX_FLAGS'],
         '-O1', '-c', source, '-o', obj], 'compile')
    replaced = 0
    for i, value in enumerate(link):
        if value == 'CMakeFiles/nextpnr-xilinx.dir/xilinx/arch.cc.o':
            link[i] = str(obj); replaced += 1
        elif value.startswith('-Wl,--dependency-file='):
            link[i] = '-Wl,--dependency-file=' + str(out / 'link.d')
    assert replaced == 1 and link.count('-o') == 1
    link[link.index('-o')+1] = str(binary)
    run(link, 'link')
    report['binary_sha256'] = digest(binary)
    report['tool_version'] = run([binary, '--version'], 'tool_version').strip()
    text = run([binary, '--chipdb', chipdb, '--test'], 'integrity')
    assert 'Checking pip names' in text and 'Checking all locations' in text, text
    assert fingerprint(tracked) == report['source']
    verify(parent['source']); verify(repair['source'])
    assert digest(original_db) == repair['original_chipdb_sha256']
    assert digest(chipdb) == repair['candidate_chipdb_sha256']
    report.update(status='PASS_EXPERIMENTAL_ARCHCHECK_ONLY',
                  artifacts=fingerprint([obj, binary, out / 'parser_test'] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
