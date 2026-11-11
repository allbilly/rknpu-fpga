#!/usr/bin/env python3
"""Render or (explicitly) build Image A of the two-image split.

This is the S1 tooling for ``docs/MERGED_IMAGE_PLAN.md`` / ``docs/MERGED_INTEGRATION_NOTES.md``. It is a **fail-closed**
renderer: by default it only writes and validates the rendered Tcl for a fresh
package directory below ``build/merged-image/`` and never invokes Vivado.

The profile is ``fpga/merged/merged_sources.json``. The tool refuses a profile
whose top/part/clock/JTAG chain/memory window/pins/CDC file/page table changed,
or whose sources are missing/unsafe/duplicated.

Actions
-------
``render``  render ``build_merged.tcl.in`` into a fresh output directory and
            record source hashes before/after (no Vivado).
``verify``  re-check an already rendered package: input files unchanged, page
            table/mask valid, rendered Tcl byte-identical, no unexpanded token.
``check``   dry-run: render into a fresh scratch directory and verify it in one
            step; never invokes Vivado. This is the offline gate for CI/tests.
``synth``   **explicitly authorized**: render and invoke Vivado batch synthesis
            + implementation for the package. It refuses without ``--execute``
            and must be launched through the shared heavy-job wrapper
            (``build/verif/host_guard/safe_run.sh``) by the caller; no hardware
            is touched and no bitstream is emitted unless the Tcl's own
            ``RK_EMIT_BITSTREAM=1`` gate plus the board/voltage env are set.

Source-hash discipline follows ``tools/ppu/vivado_pool_corpus.py``: every input
is hashed before and after the run, a mid-run change marks the receipt FAIL, and
the rendered Tcl binds the exact manifest sha256/tag (``RK_MERGED_SOURCE_SHA``,
``BITSTREAM.CONFIG.USR_ACCESS``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = 'fpga/merged/merged_sources.json'
TEMPLATE = 'fpga/merged/build_merged.tcl.in'
TOP = 'ypcb_merged_top'
PART = 'xc7k480tffg1156-2'
CLOCK_NS = 20.0
TCK_NS = 166.666
JTAG_CHAIN = 2
MEMORY_BYTES = 65536
MEMORY_BASE = '00000000'
CONSTRAINTS = 'fpga/jtag_dual.xdc'
CDC = 'fpga/host/mailbox_cdc.tcl'
BITSTREAM = 'host-merged.bit'
PROFILE = 'host-jtag-image-a'
PAGE_MASK_BITS = 7

# Page table contract (docs/MERGED_IMAGE_PLAN.md §3.2); the profile must match it.
EXPECTED_PAGES = {
    'memory': dict(target='T_MEMORY', base=0x0000_0000, bytes=65536, bit=0, id=None,
                   ref='rk_bram'),
    # S1 flipped this slot from the ABI reference stub to the real runtime page.
    # The expectation table follows the plan, so the profile's `ref` field must
    # name the module the merged top actually instantiates.
    'conv_runtime_page': dict(target='T_RKCV', base=0x0001_0000, bytes=4096, bit=1,
                              id='524b4356', ref='rk_conv_runtime_page_axi'),
    # S2 flipped this slot from the plain stub to the real CMAC GEMM page.
    'gemm_page': dict(target='T_RKCM', base=0x0001_1000, bytes=4096, bit=2,
                      id='524b434d', ref='rk_cmac_gemm_axi'),
}
S0_REQUIRED_PAGES = {'memory', 'conv_runtime_page'}

IMAGE_B_PAGES = {
    'memory': dict(target='T_MEMORY', base=0x0000_0000, bytes=65536, bit=0, id=None,
                   ref='rk_bram'),
    # S3 flipped this slot to the real 19 x 4 KiB pooling-corpus band.
    'pool_band_page': dict(target='T_RKPP_BAND', base=0x0001_0000, bytes=77824, bit=1,
                           id='524b5050', ref='rk_ppu_pool_band_axi'),
    'ew_page': dict(target='T_RKEW', base=0x0002_3000, bytes=4096, bit=2,
                    id='524b4557', ref='rk_ew_axi'),
    'ew_aperture_page': dict(target='T_EW_APERTURE', base=0x1000_0000, bytes=1048576,
                             bit=3, id='524b4557', ref='rk_ew_aperture'),
    'ew_int_page': dict(target='T_EWINT', base=0x0002_4000, bytes=4096, bit=4,
                        id='524b4549', ref='rk_ew_int_page_axi'),
    'ew_int_aperture_page': dict(target='T_EWINT_APERTURE', base=0x1100_0000,
                                 bytes=1048576, bit=5, id='524b4549',
                                 ref='rk_ew_int_aperture'),
}

# Two-image split: each image has its own fail-closed profile. Everything that
# is image-specific lives here; the renderer/verifier logic is shared.
PROFILES = {
    'image-a': dict(
        profile=PROFILE, spec=SPEC, template=TEMPLATE, top=TOP, part=PART,
        defines=['DESIGNWARE_NOEXIST', 'SYNTHESIS'], pages=EXPECTED_PAGES,
        s0_required=S0_REQUIRED_PAGES, reserved_from=3,
        bitstream=BITSTREAM,
        build_inputs=(
            'tests/merged/test_merged_map_contract.py',
            'tools/merged/ew_aperture_audit.py',
            'docs/MERGED_IMAGE_PLAN.md',
            'docs/MERGED_INTEGRATION_NOTES.md',
        ),
        scope=('Image A S1 scaffolding package: rendered gates only, page '
               'slaves are scaffold placeholders. Not a built image; no '
               'bitstream; no hardware.')),
    'image-b': dict(
        profile='host-jtag-image-b', spec='fpga/image_b/image_b_sources.json',
        template='fpga/image_b/build_image_b.tcl.in', top='ypcb_image_b_top',
        part=PART, defines=['DESIGNWARE_NOEXIST'], pages=IMAGE_B_PAGES,
        s0_required={'memory', 'pool_band_page'}, reserved_from=6,
        bitstream='host-image-b.bit',
        build_inputs=(
            'tests/merged/test_image_b_contract.py',
            'tools/merged/ew_aperture_audit.py',
            'docs/EW_APERTURE_AUDIT.md',
            'docs/MERGED_IMAGE_PLAN.md',
            'docs/MERGED_INTEGRATION_NOTES.md',
        ),
        scope=('Image B S3/S4 scaffolding package: rendered gates only, page '
               'slaves are scaffold placeholders. Not a built image; no '
               'bitstream; no hardware.')),
}
DEFAULT_PROFILE = 'image-a'


def profile_cfg(profile: str = DEFAULT_PROFILE) -> dict:
    try:
        return PROFILES[profile]
    except KeyError as error:
        raise ProfileError(f'Unknown image profile {profile!r}') from error


# Rendered Tcl must keep these admission gates; a missing marker is a tool error.
REQUIRED_GATES = (
    'RK_CONFIRM_BOARD', 'RK_CONFIG_VOLTAGE', 'RK_CFGBVS', 'RK_LED_ACTIVE_LOW',
    'RK_EMIT_BITSTREAM', 'RK_MERGED_SOURCE_SHA',
    'double($clock_period) == 20.0', 'fresh output directory',
    'REF_NAME ==', 'Expected exactly one', 'rk_host_cdc_audit',
    'report_timing_summary', 'report_drc', 'check_timing', 'write_bitstream',
    'BITSTREAM.CONFIG.USR_ACCESS', 'ROUTED_FULLY', 'ERRORS_IN_ROUTES',
    'Waivers are forbidden',
)
FORBIDDEN_TCL = ('open_hw', 'program_hw', 'write_cfgmem', 'reset_hw')

BUILD_INPUTS = PROFILES[DEFAULT_PROFILE]['build_inputs']


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tcl_path(path: Path) -> str:
    value = str(path)
    if any(char in value for char in '{}\\\n\r'):
        raise ValueError(f'Unsupported Tcl path characters: {value}')
    return '{' + value + '}'


def manifest_sha(files: dict) -> str:
    text = ''.join(f'{digest}  {name}\n' for name, digest in sorted(files.items()))
    return hashlib.sha256(text.encode()).hexdigest()


def page_mask_value(names) -> int:
    mask = 0
    for name in names:
        mask |= 1 << EXPECTED_PAGES[name]['bit']
    return mask


class ProfileError(ValueError):
    """The merged profile or an input is not in the reviewed state."""


def load_spec(root: Path = ROOT, profile: str = DEFAULT_PROFILE) -> dict:
    cfg = profile_cfg(profile)
    spec = json.loads((root / cfg['spec']).read_text())
    validate_spec(spec, root, profile)
    return spec


def validate_spec(spec: dict, root: Path = ROOT, profile: str = DEFAULT_PROFILE) -> None:
    """Fail closed unless the profile is the reviewed image state."""
    cfg = profile_cfg(profile)
    expected = dict(profile=cfg['profile'], top=cfg['top'], part=cfg['part'],
                    clock_period_ns=CLOCK_NS, tck_period_ns=TCK_NS,
                    jtag_chain=JTAG_CHAIN, memory_bytes=MEMORY_BYTES,
                    memory_base=MEMORY_BASE, constraints=CONSTRAINTS, cdc=CDC)
    for key, value in expected.items():
        if spec.get(key) != value:
            raise ProfileError(f'merged profile {key} changed: {spec.get(key)!r} != {value!r}')
    page_mask = spec.get('page_mask')
    if not isinstance(page_mask, str) or not re.fullmatch(r'[01]{%d}' % PAGE_MASK_BITS, page_mask):
        raise ProfileError('merged profile page_mask must be 7 binary digits')
    required_mask = spec.get('required_page_mask')
    if not isinstance(required_mask, str) or not re.fullmatch(r'[01]{%d}' % PAGE_MASK_BITS, required_mask):
        raise ProfileError('merged profile required_page_mask must be 7 binary digits')
    defines = spec.get('verilog_define')
    if defines != cfg['defines']:
        raise ProfileError(f'{profile} must define exactly {cfg["defines"]}')
    if int(page_mask, 2) >> cfg['reserved_from']:
        raise ProfileError(f'{profile} page mask bits [{PAGE_MASK_BITS - 1}:'
                           f'{cfg["reserved_from"]}] are reserved and must be zero')
    pages = spec.get('pages')
    if not isinstance(pages, list) or sorted(p['name'] for p in pages) != sorted(cfg['pages']):
        raise ProfileError('image profile page table changed')
    for page in pages:
        expected_page = cfg['pages'][page['name']]
        if page.get('target') != expected_page['target']:
            raise ProfileError(f'page {page["name"]} target changed')
        if int(str(page.get('base')).replace('_', ''), 16) != expected_page['base']:
            raise ProfileError(f'page {page["name"]} base changed')
        if int(page.get('bytes', 0)) != expected_page['bytes']:
            raise ProfileError(f'page {page["name"]} size changed')
        if page.get('id') != expected_page['id']:
            raise ProfileError(f'page {page["name"]} identity changed')
        if page.get('ref') != expected_page['ref']:
            raise ProfileError(f'page {page["name"]} REF_NAME expectation changed')
    required = spec.get('required_pages')
    if not isinstance(required, list) or not required or len(required) != len(set(required)):
        raise ProfileError('merged profile required_pages is empty or duplicated')
    for name in required:
        if name not in cfg['pages']:
            raise ProfileError(f'required page {name} is not in the planned map')
        if not (int(page_mask, 2) >> cfg['pages'][name]['bit']) & 1:
            raise ProfileError(f'required page {name} is not enabled by page_mask')
    required_bits = sum(1 << cfg['pages'][name]['bit'] for name in required)
    if f'{required_bits:0{PAGE_MASK_BITS}b}' != required_mask:
        raise ProfileError('required_page_mask does not encode the required pages')
    if not set(cfg['s0_required']) <= set(required):
        raise ProfileError(f'{profile} profile must require at least '
                           f'{sorted(cfg["s0_required"])}')
    sources = spec.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ProfileError('merged profile has no sources')
    if len(sources) != len(set(sources)):
        raise ProfileError('merged profile lists a source twice')
    for name in list(sources) + [CONSTRAINTS, CDC, cfg['spec'], cfg['template']] + \
            list(cfg['build_inputs']):
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ProfileError(f'Missing or unsafe merged input: {name}')
    if spec.get('benches') not in ({}, None):
        raise ProfileError('scaffold profile must not claim benches')


def inputs(spec: dict, root: Path = ROOT,
           profile: str = DEFAULT_PROFILE) -> list[Path]:
    cfg = profile_cfg(profile)
    names = list(spec['sources']) + [CONSTRAINTS, CDC, cfg['spec'], cfg['template']]
    names += list(cfg['build_inputs'])
    files = [root / name for name in names]
    files.append(Path(__file__).resolve())
    return files


def source_hashes(spec: dict, root: Path = ROOT,
                  profile: str = DEFAULT_PROFILE) -> dict:
    return {str(path.relative_to(root)): sha(path)
            for path in inputs(spec, root, profile)}


def page_gates(spec: dict) -> str:
    """Render the REF_NAME-checked page-presence Tcl block for required pages."""
    pages = {page['name']: page for page in spec['pages']}
    lines = []
    for name in spec['required_pages']:
        page = pages[name]
        lines.append(f'foreach {{page ref_name}} [list {name} {page["ref"]}] {{')
        lines.append('    set cells [get_cells -hierarchical -filter '
                     '"NAME =~ *$page && REF_NAME == $ref_name"]')
        lines.append('    if {[llength $cells] != 1} {')
        lines.append('        error "Expected exactly one $ref_name instance for page '
                     '$page, found [llength $cells]"')
        lines.append('    }')
        lines.append('}')
    return '\n'.join(lines)


def render_text(spec: dict, out: Path, source_sha: str, root: Path = ROOT,
                profile: str = DEFAULT_PROFILE) -> str:
    cfg = profile_cfg(profile)
    if not re.fullmatch('[0-9a-f]{64}', source_sha):
        raise ProfileError('Invalid source manifest sha256')
    template = (root / cfg['template']).read_text()
    sources = '\n'.join('read_verilog -sv ' + tcl_path(root / name)
                        for name in spec['sources'])
    # The NVDLA donor files include `nv_assert_never.vlib` / `nv_assert_no_x.vlib`
    # from rtl/vendor/nvdla, so that directory must be on the include path (it was
    # missing, and Vivado synthesis failed with Synth 8-9263 on the first run
    # after the runtime/GEMM sources were added to the profile).
    include_dirs = ' '.join(tcl_path(root / name) for name in
                            ('rtl', 'rtl/host', 'rtl/vendor/nvdla'))
    replacements = {
        '@ROOT@': tcl_path(root),
        '@OUT@': tcl_path(out / 'implementation'),
        '@PART@': cfg['part'],
        '@TOP@': cfg['top'],
        '@CONSTRAINTS@': tcl_path(root / CONSTRAINTS),
        '@CDC@': tcl_path(root / CDC),
        '@INCLUDE_DIRS@': include_dirs,
        '@READ_SOURCES@': sources,
        '@SOURCE_SHA@': source_sha,
        '@SOURCE_TAG@': source_sha[:8],
        '@PAGE_LIST@': ' '.join(spec['required_pages']),
        '@PAGE_MASK@': spec['page_mask'],
        '@PAGE_GATES@': page_gates(spec),
    }
    allowed = {'@PART@': 2}  # create_project + synth_design both name the part
    for token, value in replacements.items():
        count = template.count(token)
        expected = allowed.get(token, 1)
        if count != expected:
            raise ProfileError(f'Template token {token} appears {count} times '
                               f'(expected {expected})')
        template = template.replace(token, value)
    leftover = re.search(r'@[A-Z_]+@', template)
    if leftover:
        raise ProfileError(f'Unexpanded Tcl token remains: {leftover.group(0)}')
    for gate in REQUIRED_GATES:
        if gate not in template:
            raise ProfileError(f'Rendered Tcl lost the admission gate: {gate}')
    for forbidden in FORBIDDEN_TCL:
        if forbidden in template:
            raise ProfileError(f'Rendered Tcl contains a forbidden hardware command: {forbidden}')
    required_pages = ' '.join(spec['required_pages'])
    if '{' + required_pages + '}' not in template:
        raise ProfileError('Rendered Tcl page-presence list mismatch')
    pages_by_name = {page['name']: page for page in spec['pages']}
    for name in spec['required_pages']:
        ref = pages_by_name[name]['ref']
        if f'list {name} {ref}' not in template:
            raise ProfileError(f'Rendered Tcl lost the REF_NAME gate for {name}')
    if f'set page_mask {spec["page_mask"]}' not in template:
        raise ProfileError('Rendered Tcl page mask mismatch')
    if "-generic PAGE_MASK=7'b$page_mask" not in template:
        raise ProfileError('Rendered Tcl lost the page-mask generic')
    define_line = 'set_property verilog_define {' + ' '.join(cfg['defines']) + \
                  '} [current_fileset]'
    if define_line not in template:
        raise ProfileError(f'Rendered Tcl lost the required verilog_define: {define_line}')
    return template


def new_record(spec: dict, files: dict, build_tcl_sha: str, mode: str,
               profile: str = DEFAULT_PROFILE) -> dict:
    cfg = profile_cfg(profile)
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    return {
        'schema': 1, 'status': 'RENDERED', 'mode': mode,
        'image_profile': profile,
        'profile': spec['profile'], 'stage': spec.get('stage'), 'top': cfg['top'],
        'part': cfg['part'], 'clock_period_ns': CLOCK_NS, 'tck_period_ns': TCK_NS,
        'jtag_chain': JTAG_CHAIN, 'memory_bytes': MEMORY_BYTES,
        'memory_base': MEMORY_BASE,
        'verilog_define': cfg['defines'],
        'bitstream': cfg['bitstream'],
        'page_list': spec['required_pages'], 'page_mask': spec['page_mask'],
        'required_page_mask': spec['required_page_mask'],
        'source_hashes': files, 'source_manifest_sha256': manifest_sha(files),
        'source_tag': manifest_sha(files)[:8],
        'build_tcl_sha256': build_tcl_sha,
        'rendered_utc': now,
        'vivado_executed': False, 'hardware_accessed': False,
        'bitstream_emitted': False,
        'scope': cfg['scope'],
    }


def check_out_path(out: Path, root: Path = ROOT) -> Path:
    out = out.resolve()
    build = (root / 'build').resolve()
    if not out.is_relative_to(build) or out == build:
        raise ProfileError('Output must be a fresh directory below build/')
    if out.exists():
        raise ProfileError('Output already exists; preserve earlier evidence')
    return out


def render(spec: dict, out: Path, root: Path = ROOT,
           profile: str = DEFAULT_PROFILE) -> Path:
    out = check_out_path(out, root)
    before = source_hashes(spec, root, profile)
    source_sha = manifest_sha(before)
    out.mkdir(parents=True)
    text = render_text(spec, out, source_sha, root, profile)
    (out / 'build.tcl').write_text(text)
    after = source_hashes(spec, root, profile)
    if after != before:
        changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
        raise ProfileError('Sources changed while rendering: ' + ', '.join(changed))
    record = new_record(spec, before, sha(out / 'build.tcl'), 'render', profile)
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return out


def verify(directory: Path, root: Path = ROOT) -> dict:
    directory = Path(directory).resolve()
    record_path = directory / 'inputs.json'
    tcl = directory / 'build.tcl'
    if not record_path.is_file() or not tcl.is_file():
        raise ProfileError('Not a rendered image package (missing inputs.json/build.tcl)')
    record = json.loads(record_path.read_text())
    profile = record.get('image_profile', DEFAULT_PROFILE)
    cfg = profile_cfg(profile)
    if record.get('profile') != cfg['profile'] or record.get('top') != cfg['top']:
        raise ProfileError('Wrong package profile/top')
    if record.get('status') != 'RENDERED':
        raise ProfileError('Package is not in RENDERED state')
    if record.get('vivado_executed') or record.get('bitstream_emitted') or record.get('hardware_accessed'):
        raise ProfileError('Package claims a physical artifact; verify the build receipt instead')
    spec = load_spec(root, profile)
    live = source_hashes(spec, root, profile)
    recorded = record.get('source_hashes') or {}
    if live != recorded:
        changed = sorted(name for name in set(live) | set(recorded) if live.get(name) != recorded.get(name))
        raise ProfileError('Live sources differ from the package manifest: ' + ', '.join(changed))
    source_sha = manifest_sha(live)
    if record.get('source_manifest_sha256') != source_sha or record.get('source_tag') != source_sha[:8]:
        raise ProfileError('Package source manifest/tag mismatch')
    expected_tcl = render_text(spec, directory, source_sha, root, profile)
    if tcl.read_text() != expected_tcl:
        raise ProfileError('Rendered build.tcl is not byte-identical for the current spec/sources')
    if sha(tcl) != record.get('build_tcl_sha256'):
        raise ProfileError('build.tcl sha256 mismatch')
    if record.get('page_list') != spec['required_pages'] or record.get('page_mask') != spec['page_mask']:
        raise ProfileError('Package page list/mask mismatch')
    return {'status': 'VERIFIED_RENDER_ONLY', 'package': str(directory),
            'image_profile': profile,
            'source_manifest_sha256': source_sha, 'source_tag': source_sha[:8],
            'build_tcl_sha256': sha(tcl), 'page_list': spec['required_pages'],
            'page_mask': spec['page_mask'], 'vivado_executed': False,
            'bitstream_emitted': False, 'hardware_accessed': False}


def parse_reports(directory: Path) -> dict:
    for name in ('timing.rpt', 'drc.rpt', 'utilization.rpt', 'routed.dcp'):
        if not (directory / name).is_file():
            raise ProfileError(f'Missing required implementation report: {name}')
    lines = (directory / 'timing.rpt').read_text().splitlines()
    wns = whs = None
    for index, line in enumerate(lines):
        if line.strip().startswith('WNS(ns)'):
            for row in lines[index + 1:index + 6]:
                columns = row.split()
                if len(columns) >= 6:
                    try:
                        wns, whs = float(columns[0]), float(columns[4])
                    except ValueError:
                        continue
                    break
            break
    if wns is None or whs is None:
        raise ProfileError('Could not read WNS/WHS from timing.rpt')
    luts = None
    for line in (directory / 'utilization.rpt').read_text().splitlines():
        match = re.search(r'\| Slice LUTs\*?\s*\|\s*(\d+)', line)
        if match:
            luts = int(match.group(1))
            break
    drc_rows = [line.strip() for line in (directory / 'drc.rpt').read_text().splitlines()
                if re.match(r'^\|\s*[A-Z][A-Z0-9_]+-\d+\s*\|', line)]
    if any('| Error' in row for row in drc_rows):
        raise ProfileError('DRC reports an error severity finding')
    return {'wns_ns': wns, 'whs_ns': whs, 'slice_luts': luts,
            'drc_rows': drc_rows, 'timing_met': wns >= 0 and whs >= 0}


def synth(spec: dict, out: Path, vivado: str, execute: bool, root: Path = ROOT,
          profile: str = DEFAULT_PROFILE) -> Path:
    if not execute:
        raise ProfileError(
            'synth is fail-closed: re-run with --execute inside an explicitly '
            'authorized build window, through '
            'build/verif/host_guard/safe_run.sh with BENCH_CPUS/BENCH_CPU_QUOTA set, '
            'and with RK_CONFIRM_BOARD/RK_CONFIG_VOLTAGE/RK_CFGBVS/RK_LED_ACTIVE_LOW '
            'exported as required by the rendered Tcl. This tool never touches hardware.')
    if shutil.which(vivado) is None and not Path(vivado).is_file():
        raise ProfileError(f'Vivado executable not found: {vivado}')
    cfg = profile_cfg(profile)
    out = check_out_path(out, root)
    before = source_hashes(spec, root, profile)
    source_sha = manifest_sha(before)
    out.mkdir(parents=True)
    tcl = out / 'build.tcl'
    tcl.write_text(render_text(spec, out, source_sha, root, profile))
    record = new_record(spec, before, sha(tcl), 'synth', profile)
    record.update(status='RUNNING', vivado_executed=True)
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    argv = [vivado, '-mode', 'batch', '-source', str(tcl),
            '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    started = time.monotonic()
    result = subprocess.run(argv, cwd=root, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False, timeout=7200)
    (out / 'vivado-stdout.log').write_text(result.stdout)
    record['commands'] = [{'argv': argv, 'returncode': result.returncode,
                           'seconds': round(time.monotonic() - started, 3)}]
    failed = result.returncode != 0
    if failed:
        record['failure'] = result.stdout[-4000:]
    else:
        try:
            record['reports'] = parse_reports(out / 'implementation')
            if not record['reports']['timing_met']:
                raise ProfileError('Implementation timing gate failed')
        except ProfileError as error:
            failed = True
            record['failure'] = str(error)
    bit = out / 'implementation' / cfg['bitstream']
    record['bitstream_emitted'] = bit.is_file()
    if bit.is_file():
        record['bitstream_sha256'] = sha(bit)
    after = source_hashes(spec, root, profile)
    if after != before:
        failed = True
        record['source_match'] = False
        record['source_changed_during_build'] = sorted(
            name for name in set(before) | set(after) if before.get(name) != after.get(name))
    else:
        record['source_match'] = True
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    record['status'] = 'FAIL' if failed else 'PASS'
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    if failed:
        raise ProfileError(f'Build failed; see {out / "inputs.json"}')
    return out


def default_out(action: str) -> Path:
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    return ROOT / 'build/merged-image' / f'{action}-{stamp}'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('render', 'verify', 'check', 'synth'))
    parser.add_argument('--profile', choices=sorted(PROFILES), default=DEFAULT_PROFILE,
                        help='which split image to render (default: image-a)')
    parser.add_argument('--out', type=Path,
                        help='fresh output directory below build/ (render/check/synth)')
    parser.add_argument('--execute', action='store_true',
                        help='explicit authorization for the synth action (default: refuse)')
    parser.add_argument('--vivado', default=shutil.which('vivado') or 'vivado')
    args = parser.parse_args()
    try:
        profile = args.profile
        spec = load_spec(profile=profile)
        if args.action == 'verify':
            if args.out is None:
                raise ProfileError('verify needs the rendered package directory as --out')
            print(json.dumps(verify(args.out), indent=2, sort_keys=True))
            return 0
        if args.action == 'synth':
            directory = synth(spec, args.out or default_out('synth'), args.vivado,
                              args.execute, profile=profile)
            print(json.dumps(json.loads((directory / 'inputs.json').read_text()),
                             indent=2, sort_keys=True))
            return 0
        if args.action == 'check':
            directory = check_out_path(args.out or default_out('check'))
            before = source_hashes(spec, ROOT, profile)
            source_sha = manifest_sha(before)
            directory.mkdir(parents=True)
            text = render_text(spec, directory, source_sha, ROOT, profile)
            (directory / 'build.tcl').write_text(text)
            record = new_record(spec, before, sha(directory / 'build.tcl'), 'check',
                                profile)
            (directory / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
            result = verify(directory)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        directory = render(spec, args.out or default_out('render'), profile=profile)
        print(directory / 'build.tcl')
        return 0
    except (ProfileError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
