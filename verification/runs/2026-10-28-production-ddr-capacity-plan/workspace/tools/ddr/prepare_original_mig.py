#!/usr/bin/env python3
"""Prepare an unchanged RZQ/7 original MIG generation recipe; never execute it.

The two differential200MHz inputs and every pin/electrical/XML byte remain
the original project's values. This supplies no clock-delivery, generated
controller, timing, PHY training, DDR contents or physical integration claim.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import canonical, load_json, parse_project, require, xml
from tools.hardware.sample_ew import tcl_literal

TEMPLATE = ROOT/'fpga/ddr/generate_original_mig.tcl.in'
REFERENCE = ROOT/'fpga/ddr/mig_c0_reference.json'
ROLES = ('project', 'template', 'component', 'example', 'file_list', 'block_design')
LOCAL = ('tools/ddr/prepare_original_mig.py', 'tools/ddr/interface.py',
         'tools/hardware/sample_ew.py', 'fpga/ddr/generate_original_mig.tcl.in',
         'fpga/ddr/mig_c0_reference.json', 'tools/ddr/__init__.py',
         'tests/ddr/original_mig/test_prepare.py', 'fpga/ddr/original_mig.mk')
STATUS = 'PREPARED_UNCHANGED_ORIGINAL_MIG_GENERATION_RECIPE_ONLY'
REFERENCE_SCOPE = 'Workflow syntax reference only; not executed, copied as RTL, or inherited electrical/physical evidence'


def source_identity(inputs, output):
    relative = {str(Path(p).relative_to(output)): h for p, h in inputs.items()}
    return hashlib.sha256(canonical(relative)).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profile(data):
    text = data.decode('utf-8')
    result = parse_project(text)
    expected = dict(module='top_mig_7series_0_0', controllers=2, target='xc7k480t-ffg1156/-2',
        system_clock='Differential', reference_clock='Use System Clock', sys_reset='ACTIVE LOW',
        interface='AXI', ecc='Enabled', phy_ratio='4:1', physical_dq_width=72, size_bytes=2147483648,
        input_clock_mhz=200, memory_period_ps=1875, address_width=31, data_width=512,
        id_width=4, narrow_bursts=0)
    require(result == expected, 'Original MIG logical/clock/reset profile changed')
    tree = xml(text)
    controllers = tree.findall('Controller')
    require([c.get('number') for c in controllers] == ['0', '1'], 'Original channel order changed')
    pins = []
    for channel, controller in enumerate(controllers):
        fields = dict(PortInterface='AXI', ECC='Enabled', PHYRatio='4:1', DataWidth='72',
                      InputClkFreq='200', TimePeriod='1875', **{f'C{channel}_MEM_SIZE': '2147483648'})
        for name, value in fields.items():
            found = controller.findall(name)
            require(len(found) == 1 and found[0].text == value, 'Original channel field changed: '+name)
        for name, value in dict(ADDR_WIDTH='31', DATA_WIDTH='512', ID_WIDTH='4', SUPPORTS_NARROW_BURST='0').items():
            found = controller.findall(f'AXIParameters/C{channel}_S_AXI_{name}')
            require(len(found) == 1 and found[0].text == value, 'Original channel AXI field changed: '+name)
        drive = controller.findall('emrOutputDriveStrength')
        require(len(drive) == 1 and drive[0].text == 'RZQ/7', 'Original drive profile must remain RZQ/7')
        clocks = [p for p in controller.iter('Pin') if p.get('name') == f'c{channel}_sys_clk_p/n']
        require(len(clocks) == 1, 'Missing/duplicate original differential system clock')
        expected_pair, bank = (('AH27/AH28(CC_P/N)', '12') if channel == 0 else ('G25/G26(CC_P/N)', '17'))
        require(clocks[0].get('PADName') == expected_pair and clocks[0].get('Bank') == bank,
                'Original system-clock pin pair changed')
        pins.append(dict(channel=channel, pair=expected_pair, bank=bank,
                         source_pin_entries=len(list(controller.iter('Pin'))), output_drive='RZQ/7'))
    return dict(values=result, channels=pins, board_clock_delivery_verified=False,
                electrical_admission=False, physical_integration_ready=False)


def render(project_xml, output, inputs):
    require(bool(inputs) and all(re.fullmatch('[0-9a-f]{64}', h) for h in inputs.values()),
            'Nonempty valid frozen input hashes required')
    text = TEMPLATE.read_text()
    values = dict(PROJECT_XML=tcl_literal(project_xml), OUTPUT=tcl_literal(output),
                  INPUTS='[dict create '+' '.join(tcl_literal(p)+' '+h for p, h in sorted(inputs.items()))+']')
    for name, value in values.items():
        token = '@'+name+'@'
        require(text.count(token) == 1, 'Changed generation template marker '+name)
        text = text.replace(token, value)
    return text


def prepare(source_root, output, reference_generator=None):
    source_root, output = Path(source_root).expanduser().resolve(), Path(output).expanduser().resolve()
    require(source_root.is_dir() and output.is_relative_to(ROOT/'build') and not output.exists(),
            'Original source root and fresh in-workspace output required')
    reference = load_json(REFERENCE)
    original = {}
    for role in ROLES:
        entry = reference['sources'][role]
        name = Path(entry['path'])
        require(not name.is_absolute() and '..' not in name.parts, 'Unsafe original input path')
        path = source_root/name
        require(path.is_file() and sha(path) == entry['sha256'], 'Original reference input changed: '+role)
        original[role] = (path, path.read_bytes())
    facts = profile(original['project'][1])
    output.mkdir(parents=True)
    copied = {}
    for role, (path, data) in original.items():
        dest = output/'source/original'/role/path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        copied[str(dest)] = hashlib.sha256(data).hexdigest()
    for name in LOCAL:
        dest = output/'source/tool'/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, dest)
        copied[str(dest)] = sha(ROOT/name)
    project = output/'source/original/project'/original['project'][0].name
    script = output/'generate.tcl'
    script.write_text(render(project, output/'generation', copied))
    report = dict(schema=1, status=STATUS, scope=__doc__, profile=facts,
        original_sources={role: dict(path=str(path), sha256=hashlib.sha256(data).hexdigest())
                          for role, (path, data) in original.items()},
        frozen_inputs=copied, frozen_source_sha256=source_identity(copied, output),
        generate_tcl_sha256=sha(script), native_execution_required=True, vivado_executed=False,
        generated_controller_present=False, board_clock_delivery_verified=False,
        physical_integration_ready=False, hardware_accessed=False, flash_written=False)
    if reference_generator is not None:
        path = Path(reference_generator).expanduser().resolve(strict=True)
        report['readonly_workflow_reference'] = dict(path=str(path), sha256=sha(path),
            scope=REFERENCE_SCOPE)
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    verify(output)
    return report


def verify(output):
    output = Path(output).resolve()
    report = load_json(output/'report.json')
    keys = {'schema', 'status', 'scope', 'profile', 'original_sources', 'frozen_inputs',
            'frozen_source_sha256', 'generate_tcl_sha256', 'native_execution_required',
            'vivado_executed', 'generated_controller_present', 'board_clock_delivery_verified',
            'physical_integration_ready', 'hardware_accessed', 'flash_written'}
    require(set(report) in (keys, keys | {'readonly_workflow_reference'}), 'Unknown preparation fields')
    require(report['schema'] == 1 and report['status'] == STATUS, 'Invalid generation preparation receipt')
    require(report['scope'] == __doc__ and report['native_execution_required'] is True,
            'Changed preparation scope')
    if 'readonly_workflow_reference' in report:
        ref = report['readonly_workflow_reference']
        require(set(ref) == {'path', 'sha256', 'scope'} and Path(ref['path']).is_absolute() and
                re.fullmatch('[0-9a-f]{64}', ref['sha256']) is not None and ref['scope'] == REFERENCE_SCOPE,
                'Invalid workflow reference lineage')
    for flag in ('vivado_executed', 'generated_controller_present', 'board_clock_delivery_verified',
                 'physical_integration_ready', 'hardware_accessed', 'flash_written'):
        require(report[flag] is False, 'Preparation cannot claim execution or physical readiness')
    reference = load_json(REFERENCE)
    expected = {}
    require(set(report['original_sources']) == set(ROLES), 'Original source role inventory changed')
    for role in ROLES:
        name = Path(reference['sources'][role]['path']).name
        origin = report['original_sources'][role]
        require(set(origin) == {'path', 'sha256'} and Path(origin['path']).is_absolute() and
                Path(origin['path']).as_posix().endswith('/'+reference['sources'][role]['path']) and
                origin['sha256'] == reference['sources'][role]['sha256'], 'Original source lineage changed')
        expected[str(output/'source/original'/role/name)] = reference['sources'][role]['sha256']
    for name in LOCAL:
        expected[str(output/'source/tool'/name)] = sha(ROOT/name)
    require(report['frozen_inputs'] == expected and
            report['frozen_source_sha256'] == source_identity(expected, output),
            'Frozen source inventory/identity differs')
    found = {str(p) for p in (output/'source').rglob('*') if p.is_file()}
    require(found == set(expected), 'Extra/missing frozen generation source')
    for name, digest in expected.items():
        require(Path(name).is_file() and sha(name) == digest, 'Frozen generation input changed')
    project = output/'source/original/project'/Path(reference['sources']['project']['path']).name
    require(profile(project.read_bytes()) == report['profile'], 'Original profile receipt differs')
    require((output/'generate.tcl').read_text() == render(project, output/'generation', expected) and
            sha(output/'generate.tcl') == report['generate_tcl_sha256'], 'Generation script changed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--reference-generator', type=Path)
    p = sub.add_parser('verify')
    p.add_argument('--package', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.source_root, args.out, args.reference_generator) if args.action == 'prepare' else verify(args.package)
    print(report['status'])


if __name__ == '__main__':
    main()
