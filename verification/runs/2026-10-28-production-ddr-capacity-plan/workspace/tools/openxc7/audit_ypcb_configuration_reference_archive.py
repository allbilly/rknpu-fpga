#!/usr/bin/env python3
"""Record historical YPCB reference constraints, not physical board signoff.

Read four exact text members from the existing XC7K480T reference archive.
Keep native extraction results and bind the archive, tool and source digests
inside JSON; do not create a SHA256SUMS file or extract a whole project.
The historical build's missing configuration properties and failed timing
cannot establish Bank 0 voltage, the CFGBVS strap, or this design's readiness.
No constraints, build acceptance gate, original archive or hardware is changed.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from evidence import source_revision, timestamp
from pack_prefix_board import ROOT, digest
from place_prefix_board import verify_bindings

ARCHIVE = Path('/home/fedora/ypcb/ref/LC480T/YPCB-00338-1P1/XC7K480T_XDMA_Test.zip')
PREFIX = 'XC7K480T_XDMA_Test/XC7K480T_XDMA_Test.'
MEMBERS = {
    'constraints': PREFIX + 'srcs/constrs_1/new/IO_Port.xdc',
    'implementation_log': PREFIX + 'runs/impl_1/runme.log',
    'routed_drc': PREFIX + 'runs/impl_1/top_wrapper_drc_routed.rpt',
    'placed_io': PREFIX + 'runs/impl_1/top_wrapper_io_placed.rpt',
}


def reference_contract(texts):
    assert set(texts) == set(MEMBERS)
    log, drc, io, xdc = (texts[k] for k in ('implementation_log', 'routed_drc', 'placed_io', 'constraints'))
    assert log.count('Loading part xc7k480tffg1156-2') == 1
    assert log.count('****** Vivado v2022.1.2 (64-bit)') == 1
    missing = 'Neither the CFGBVS nor CONFIG_VOLTAGE voltage property is set in the current_design.'
    assert log.count('WARNING: [DRC CFGBVS-1] Missing CFGBVS and CONFIG_VOLTAGE Design Properties: ' + missing) == 1
    assert drc.count(missing) == 1
    assert re.search(r'^\| CFGBVS-1\s+\| Warning\s+\| Missing CFGBVS and CONFIG_VOLTAGE Design Properties \| 1\s+\|$', drc, re.M)
    assert not re.search(r'^\s*set_property\s+(?:CFGBVS|CONFIG_VOLTAGE)\b', xdc, re.M)
    rows = [line for line in io.splitlines() if re.search(r'\|\s+VCCO_0\s+\|', line)]
    assert len(rows) == 2 and {line.split('|')[1].strip() for line in rows} == {'G14', 'H13'}
    assert all('any**' in line for line in rows)
    strap = [line for line in io.splitlines() if re.search(r'\|\s+CFGBVS_0\s+\|', line)]
    assert len(strap) == 1 and strap[0].split('|')[1].strip() == 'AL15'
    assert log.count('CRITICAL WARNING: [Timing 38-282] The design failed to meet the timing requirements.') == 1
    assert log.count('INFO: [Vivado 12-1842] Bitgen Completed Successfully.') == 1
    return dict(historical_part='xc7k480tffg1156-2', historical_tool='Vivado v2022.1.2',
                historical_configuration_properties_missing=True, historical_timing_requirements_met=False,
                historical_bitgen_completed=True, historical_bank_0_report_value='any**',
                package_bank_0_supply_pins=['G14', 'H13'], package_cfgbvs_pin='AL15',
                physical_bank_0_voltage_verified=False, physical_cfgbvs_strap_verified=False)


def main():
    out = ROOT / f'build/openxc7/ypcb-configuration-reference-archive-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='exact_archive_member_extraction', scope=__doc__,
                  started_utc=timestamp(), supervisor_pid=os.getpid(), python_version=sys.version,
                  production_source_before=source_revision(), source={}, commands=[],
                  electrical_verified=False, timing_signoff=False, drc_signoff=False,
                  bitstream_emitted=False, hardware_programmed=False, hardware_input_modified=False)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    save()
    print(out / 'report.json', flush=True)
    try:
        tool = shutil.which('7z')
        assert tool, 'UNAVAILABLE: 7z'
        sources = {ARCHIVE, Path(tool).resolve(), Path(__file__).resolve(), Path(sys.executable).resolve()}
        sources.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                       if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        report['source'] = {str(p): digest(p) for p in sources}
        verify_bindings(report['source'])
        shutil.copyfile(__file__, out / 'executed_source.py')
        texts = {}
        for label, member in MEMBERS.items():
            step = dict(label=label, argv=[tool, 'e', '-so', str(ARCHIVE), member],
                        timeout_seconds=60, status='RUNNING')
            report['commands'].append(step)
            save()
            start = time.monotonic()
            result = subprocess.run(step['argv'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            step.update(returncode=result.returncode, seconds=round(time.monotonic() - start, 3))
            assert result.returncode == 0 and result.stderr == b'', result.stderr.decode(errors='replace')
            assert 0 < len(result.stdout) <= 1024 * 1024, 'Unexpected selected reference size'
            texts[label] = result.stdout.decode('utf-8')
            target = out / (label + ('.xdc' if label == 'constraints' else '.txt'))
            target.write_bytes(result.stdout)
            step.update(status='PASS_NATIVE_EXTRACTION_ONLY', extracted_text=str(target.relative_to(ROOT)))
            save()
        report['reference_checks'] = reference_contract(texts)
        verify_bindings(report['source'])
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='AUDITED_HISTORICAL_REFERENCE_MISSING_CONFIGURATION_NOT_BOARD_ELECTRICAL_OR_TIMING_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
