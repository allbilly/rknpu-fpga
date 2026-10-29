#!/usr/bin/env python3
"""Read-only full-prefix DSP/BRAM configuration inventory, not FASM or signoff.

Bind the completed preparation's actual physical-input bytes, inventory all
515 DSPs/six BRAMs, and expose the pinned FASM writer's literal BRAM INIT bit
decomposition and x-to-zero behavior. Expected vectors are comparison data,
never hardware input, a bitstream, or a numerical/startup acceptance proof.
"""
from collections import Counter
import json
import mmap
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, QUALIFICATION, DATABASE, CONSTIDS, digest, timestamp, audit, verify_prepared_metadata
from evidence import source_revision
from test_dsp_prefix_primitive_models import PARAMETERS

PARENT = ROOT / 'build/openxc7/full-prefix-pack-input-1791392677842220299/report.json'
FASM_SOURCE = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/himbaechel/uarch/xilinx/fasm.cc')
CONTROL = ROOT / 'tests/cmac/test_prefix_config_contract_control.py'


def selected_cells(data):
    """Inventory the bound Yosys pretty format without loading its giant graph.

    Type fields are at the exact cell indentation. Decode every selected
    complete cell independently as JSON; full primitive counts must match
    the preparation plus physical buffers. This is not a new circuit proof.
    """
    counts, selected = Counter(), {}
    for match in re.finditer(rb'^          "type": "([^"\n]+)",$', data, re.MULTILINE):
        kind = match.group(1).decode('ascii')
        counts[kind] += 1
        if kind not in ('DSP48E1', 'RAMB36E1'):
            continue
        start = data.rfind(b'\n        "', 0, match.start())
        end = data.find(b'\n        }', match.end())
        assert start >= 0 and end > match.end(), 'Unsupported/incomplete physical-input cell format'
        record = json.loads(b'{' + data[start + 1:end + len(b'\n        }')] + b'}')
        assert len(record) == 1
        name, cell = next(iter(record.items()))
        assert name not in selected and cell['type'] == kind
        assert set(cell['port_directions']) == set(cell['connections'])
        selected[name] = cell
    return dict(counts), selected


def bram_half_init(parameters):
    """Literal fasm.cc::write_bram_init interleaving; no runtime data repair.

    Binary strings are MSB first, unlike Property.str's LSB-first storage.
    Missing/short data is padded with zero exactly as the source writer;
    unknown bits become zero in the expected writer view and are separately
    counted. That coercion is not automatically accepted for observable RTL.
    """
    result, unknown = [{}, {}], Counter()
    init_keys = {k for k in parameters if re.fullmatch(r'INITP?_[0-9A-F]{2}', k)}
    supported = {f'INIT_{i:02X}' for i in range(128)} | {f'INITP_{i:02X}' for i in range(16)}
    assert init_keys <= supported, 'Unsupported BRAM initial-memory parameter index'
    for key in init_keys:
        bits = parameters[key]
        assert isinstance(bits, str) and re.fullmatch('[01x]{1,256}', bits), 'Unsupported BRAM memory INIT representation'
        unknown[key] = bits.count('x')
    for mode, count in (('', 64), ('P', 8)):
        for i in range(count):
            keys = [f'INIT{mode}_{2 * i + j:02X}' for j in range(2)]
            if not any(key in parameters for key in keys):
                continue
            for half in range(2):
                out = ['0'] * 256
                for j, key in enumerate(keys):
                    bits = parameters.get(key, '')[::-1]
                    for k in range(half, len(bits), 2):
                        out[j * 128 + k // 2] = '1' if bits[k] == '1' else '0'
                result[half][f'INIT{mode}_{i:02X}'] = ''.join(reversed(out))
    return result, dict(unknown)


def reconstruct_half_init(halves):
    """Independent inverse: interleave paired halves into two 256-bit words."""
    assert set(halves[0]) == set(halves[1])
    result = {}
    for key in halves[0]:
        match = re.fullmatch(r'INIT(P?)_([0-9A-F]{2})', key)
        assert match
        mode, number = match.groups()
        low, high = [half[key][::-1] for half in halves]
        assert len(low) == len(high) == 256 and set(low + high) <= {'0', '1'}
        for j in range(2):
            bits = ''.join(low[j * 128 + k] + high[j * 128 + k] for k in range(128))
            result[f'INIT{mode}_{2 * int(number, 16) + j:02X}'] = bits[::-1]
    return result


def dsp_contract(cell):
    assert cell['type'] == 'DSP48E1'
    params = {key: int(value, 2) if re.fullmatch('[01]+', value) else value
              for key, value in cell['parameters'].items()}
    assert params == PARAMETERS, 'Unmodeled actual DSP configuration'
    # All actual register stages are zero. The source emits these zero-register
    # controls directly; DIRECT/ONE48/FALSE are its defaults. USE_MULT has no
    # write_dsp_cell branch: its physical interpretation still needs independent
    # native feature/LVS evidence, not a software assertion from this inventory.
    return dict(literal_parameters=cell['parameters'],
        all_actual_register_stages_zero=True,
        unverified_physical_parameter_defaults=['USE_MULT=MULTIPLY'],
        physical_feature_match_verified=False)


def bram_contract(cell):
    assert cell['type'] == 'RAMB36E1'
    parameters = cell['parameters']
    plain = {key: value for key, value in parameters.items() if not re.fullmatch(r'INITP?_[0-9A-F]{2}', key)}
    expected_keys = {'DOA_REG', 'DOB_REG', 'INIT_A', 'INIT_B', 'SRVAL_A', 'SRVAL_B',
        'RAM_EXTENSION_A', 'RAM_EXTENSION_B', 'RAM_MODE', 'READ_WIDTH_A', 'READ_WIDTH_B',
        'WRITE_WIDTH_A', 'WRITE_WIDTH_B', 'WRITE_MODE_A', 'WRITE_MODE_B'}
    assert set(plain) == expected_keys, 'Unmodeled actual BRAM parameters'
    assert plain['RAM_MODE'] == 'TDP' and plain['RAM_EXTENSION_A'] == plain['RAM_EXTENSION_B'] == 'NONE'
    assert all(re.fullmatch('[01]{32}', plain[key]) and int(plain[key], 2) == 0 for key in ('DOA_REG', 'DOB_REG'))
    widths = {key: int(plain[key], 2) for key in ('READ_WIDTH_A', 'READ_WIDTH_B', 'WRITE_WIDTH_A', 'WRITE_WIDTH_B')}
    assert all(re.fullmatch('[01]{32}', plain[key]) for key in widths)
    assert set(widths.values()) <= {0, 9}, 'Unmodeled actual BRAM width'
    assert widths['READ_WIDTH_A'] == 9
    assert plain['WRITE_MODE_A'] == plain['WRITE_MODE_B'] == 'READ_FIRST'
    reset_symbols = {}
    for key in ('INIT_A', 'INIT_B', 'SRVAL_A', 'SRVAL_B'):
        bits = plain[key]
        assert re.fullmatch('[0x]{72}', bits), 'Unmodeled actual BRAM initial/reset-output value'
        reset_symbols[key] = dict(literal_bits=len(bits), unknown_bits=bits.count('x'))
    halves, unknown = bram_half_init(parameters)
    reconstructed = reconstruct_half_init(halves)
    for key, bits in parameters.items():
        if re.fullmatch(r'INITP?_[0-9A-F]{2}', key):
            assert reconstructed[key] == bits.replace('x', '0').zfill(256)
    return dict(literal_nonmemory_parameters=plain, widths=widths,
        expected_RAMB18_memory_INIT_vectors=halves,
        unknown_memory_INIT_bits_by_parameter=unknown,
        unknown_initial_reset_output_symbols=reset_symbols,
        writer_initial_reset_output_policy='SOURCE_HARD_CODES_ZERO_VIA_18_ONE_ZINIT_ZSRVAL_BITS_PER_HALF_NOT_LITERAL_INIT_A_B_SRVAL_A_B',
        observable_startup_reset_independence_proved=False,
        physical_feature_match_verified=False)


def main():
    out = ROOT / f'build/openxc7/prefix-config-contract-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        python_version=platform.python_version(), commands=[], native_packing_executed=False,
        native_placement_executed=False, native_routing_executed=False, native_FASM_executed=False,
        full_board_numerical_acceptance=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False, expected_vectors_used_for_execution=False,
        upstream_preparation_rerun=False, entire_upstream_parent_chain_revalidated=False,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    save()
    print(out / 'report.json', flush=True)
    before = {}
    try:
        parent = json.loads(PARENT.read_text())
        verify_prepared_metadata(parent)
        input_path = (ROOT / parent['pack_input']).resolve(strict=True)
        assert input_path.is_relative_to(PARENT.parent)
        expected_digest = parent['artifacts'][str(input_path.relative_to(ROOT))]
        assert digest(input_path) == expected_digest, 'Changed selected physical-input artifact'
        report['timing_inventory'] = audit(QUALIFICATION, DATABASE, CONSTIDS)
        candidate = json.loads(QUALIFICATION.read_text())
        assert str(FASM_SOURCE) in candidate['inputs'], 'Unbound inspected FASM source'
        before.update(candidate['inputs'])
        paths = {Path(__file__).resolve(), CONTROL, PARENT, input_path, QUALIFICATION}
        paths.update(Path(module.__file__).resolve() for module in list(sys.modules.values())
                     if getattr(module, '__file__', None)
                     and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in paths:
            sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha
            before[str(path)] = sha
            if path.is_relative_to(ROOT) and path.suffix == '.py':
                frozen = out / 'sources' / path.relative_to(ROOT)
                frozen.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, frozen)
        assert before[str(input_path)] == expected_digest
        report.update(source=before, preparation_report=str(PARENT.relative_to(ROOT)),
            actual_physical_input=str(input_path.relative_to(ROOT)),
            source_FASM_writer=str(FASM_SOURCE), source_FASM_writer_sha256=before[str(FASM_SOURCE)],
            production_source_before=source_revision())
        save()
        for label, argv in (
            ('controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
            ('generated_check', ['make', 'generated-check'])):
            log = out / (label + '.log')
            started = time.monotonic()
            with log.open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300, check=False)
            report['commands'].append(dict(label=label, argv=argv, cwd=str(ROOT), log=str(log.relative_to(ROOT)),
                returncode=result.returncode, seconds=round(time.monotonic() - started, 3)))
            save()
            assert result.returncode == 0, log.read_text()[-3000:]
        report['stage'] = 'actual_inventory'
        save()
        with input_path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            counts, selected = selected_cells(data)
        expected = dict(Counter(parent['primitive_counts']) + Counter(parent['physical_buffer_counts']))
        assert counts == expected, 'Changed/incomplete full physical-input primitive counts'
        groups = {group: sum(c['type'] == 'DSP48E1' for name, c in selected.items() if name.startswith(group + '.'))
                  for group in parent['retained_kernel_instances']}
        assert len(groups) == 16 and set(groups.values()) == {32}
        assert counts['DSP48E1'] == 515 and counts['RAMB36E1'] == 6 and len(selected) == 521
        contracts = {name: dsp_contract(cell) if cell['type'] == 'DSP48E1' else bram_contract(cell)
                     for name, cell in selected.items()}
        (out / 'actual-selected-primitives.json').write_text(json.dumps(selected, separators=(',', ':')))
        (out / 'comparison-only-configuration-contracts.json').write_text(json.dumps(contracts, indent=2, sort_keys=True) + '\n')
        brams = {name: value for name, value in contracts.items() if 'widths' in value}
        report.update(stage='source_revalidation', actual_primitive_counts=counts,
            retained_kernel_dsps=groups, retained_shell_dsps=3, checked_DSPs=515, checked_BRAMs=6,
            BRAM_initial_reset_output_unknown_bits=sum(v['unknown_bits'] for c in brams.values()
                for v in c['unknown_initial_reset_output_symbols'].values()),
            BRAM_memory_unknown_bits=sum(sum(c['unknown_memory_INIT_bits_by_parameter'].values()) for c in brams.values()),
            BRAM_known_memory_bits_preserved_by_source_defined_half_interleaving=True,
            remaining_configuration_acceptance=['ACTUAL_NATIVE_FASM_FEATURE_COMPARISON',
                'INDEPENDENT_DSP_MODE_FEATURE_OR_LVS_EVIDENCE', 'BRAM_OBSERVABLE_STARTUP_RESET_INDEPENDENCE',
                'FULL_PLACED_ROUTE_AND_DSP_MINUS2_TIMING_ELECTRICAL_DRC'])
        save()
        assert all(digest(path) == sha for path, sha in before.items()), 'Changed configuration inventory input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='AUDITED_ACTUAL_FULL_PREFIX_DSP_BRAM_CONFIGURATION_WITH_EXPLICIT_GAPS_NOT_FASM_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): digest(path) for path in out.rglob('*')
                               if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
