"""Closed source-specific diagnostic admission for one completed mapped kernel.

Original failed runner and vendor/RTL sources are unchanged. This qualifies
reuse of that exact binary kernel for fixture replay, not all-X equivalence,
full-array numerical acceptance or physical signoff. Unknown diagnostics fail.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from evidence import ROOT, fingerprint
import audit_dsp_prefix_compile_inventory as inventory
import audit_dsp_prefix_pin_cone as cone
import prove_dsp_prefix_actual_model as proof
import test_dsp_prefix_mapped_array as runner

MODEL_SHA = '10f8afc61bf708949ebf238294327dce95eaa68919bb0ab5938d40f24e39d15e'
COUNTS = {'COMBDLY': 12, 'DECLFILENAME': 2, 'GENUNNAMED': 74, 'PINMISSING': 1152,
    'PROCASSINIT': 1, 'SPECIFYIGN': 39, 'UNDRIVEN': 449, 'UNOPTFLAT': 1,
    'UNUSEDPARAM': 1, 'UNUSEDSIGNAL': 8853, 'WIDTHEXPAND': 8, 'WIDTHTRUNC': 2}


def key(entry):
    return tuple(entry[name] for name in ('kind', 'source', 'line', 'column', 'message'))


def verify_report(path, status):
    value = json.loads(path.read_text())
    assert value['status'] == status and value['finished_utc']
    for manifest in (value['source'], value['artifacts']):
        assert fingerprint([ROOT / name for name in manifest['files']]) == manifest
    return value


def validate_followup(text, admitted):
    """Only a subset of the exact already-audited warnings may recur."""
    entries = inventory.diagnostics(text)
    observed = Counter(key(entry) for entry in entries)
    assert observed <= admitted, 'New, changed or duplicated follow-up compiler diagnostic'
    return entries


def unobserved_aliases(entries, module, netlist):
    observed = {bit for port in module['ports'].values() for bit in port['bits'] if type(bit) is int}
    observed.update(bit for cell in module['cells'].values() for bits in cell['connections'].values()
        for bit in bits if type(bit) is int)
    lines = netlist.read_text().splitlines()
    selected_count = 0
    for entry in entries:
        assert Path(entry['source']) == netlist
        match = re.fullmatch(r"(?:Bits of signal are not driven|Signal is not driven): '(.+)'(?:\[([^]]+)\])?",
            entry['message'])
        assert match
        name, span = match.groups()
        assert re.search(r'\bwire\b', lines[entry['line'] - 1]) and name in lines[entry['line'] - 1]
        net = module['netnames'][name]
        bits, offset = net['bits'], net.get('offset', 0)
        indices = list(range(offset, offset + len(bits)))
        if span is not None:
            indices = []
            for term in span.split(','):
                assert re.fullmatch(r'\d+(?::\d+)?', term)
                limits = list(map(int, term.split(':')))
                if len(limits) == 1:
                    indices.append(limits[0])
                else:
                    high, low = limits
                    assert high >= low
                    indices.extend(range(low, high + 1))
        assert len(indices) == len(set(indices))
        positions = [index - offset for index in indices]
        assert all(0 <= index < len(bits) for index in positions)
        if net.get('upto', 0):
            positions = [len(bits) - 1 - index for index in positions]
        assert not any(type(bits[index]) is int and bits[index] in observed for index in positions), \
            'Diagnosed undriven alias reaches a real port or cell pin'
        selected_count += len(positions)
    return selected_count


def validate_model_sites(entries, model):
    """Exact functional-model sites supported by actual cone/proof/simulation."""
    sites = {'WIDTHEXPAND': {3544, 3547, 3828, 3531, 3689, 3744, 3747, 3871},
        'WIDTHTRUNC': {3650, 3870}, 'PROCASSINIT': {3672},
        'COMBDLY': {3585, 3586, 3613, 3614, 3620, 3624, 3629, 3632, 3635, 3638, 3659, 3677},
        'UNOPTFLAT': {374}}
    for kind, expected in sites.items():
        found = [entry for entry in entries if entry['kind'] == kind]
        assert len(found) == len(expected) and {entry['line'] for entry in found} == expected
        assert all(Path(entry['source']) == model for entry in found)
    lines = model.read_text().splitlines()
    for line in sites['COMBDLY']:
        assert 'always @*' in lines[line - 1] and '<=' in lines[line - 1]
    assert lines[3671].strip() == "reg  signed [42:0] Mr = 43'b0;"
    assert lines[3649].strip() == 'wire signed [24:0] Ar12_muxed = INMODEr[0] ? Ar1 : Ar2;'
    assert lines[3688].strip() == "2'b01: begin X = $signed(Mrx);"
    # A bit-level triangular carry recurrence, not a combinational cycle.
    assert lines[373].strip() == 'output [3:0] CO,'
    assert [line.strip() for line in lines[380:385]] == [
        'assign O = S ^ {CO[2:0], CI | CYINIT};',
        'assign CO[0] = S[0] ? CI | CYINIT : DI[0];',
        'assign CO[1] = S[1] ? CO[0] : DI[1];',
        'assign CO[2] = S[2] ? CO[1] : DI[2];',
        'assign CO[3] = S[3] ? CO[2] : DI[3];']
    return dict(width_expansions=8, width_truncations=2, zero_register_comb_assignments=12,
        inactive_multiplier_declaration_initializer=1, bitwise_acyclic_carry_vector_notice=1)


def admit(parent_path, inventory_path, cone_path, proof_path, verilator_path, iverilog_path, archive_path):
    parent = verify_report(parent_path, 'FAIL')
    assert parent['stage'] == 'compile' and parent['commands'][-1]['returncode'] == 0
    assert parent['commands'][-1]['status'] == 'FAIL'
    assert 'PINMISSING' in parent['error'] and parent['numerical_netlist_binary_fixture_acceptance'] is False
    account = verify_report(inventory_path, 'READ_ONLY_COMPLETED_DSP_PREFIX_COMPILER_INVENTORY_ONLY')
    cp = verify_report(cone_path, 'PASS_ISOLATED_ACTUAL_DSP_OMITTED_INPUT_CONE_ONLY')
    fp = verify_report(proof_path, 'PASS_ISOLATED_ACTUAL_DSP_MODEL_ALL_BINARY_OPERANDS_ONLY')
    assert account['completed_compile_report'] == str(parent_path.relative_to(ROOT))
    assert account['cone_report'] == fp['cone_report'] == str(cone_path.relative_to(ROOT))
    assert cp['installed_model_sha256'] == parent['installed_model']['sha256'] == MODEL_SHA
    assert cp['actual_parameters'] == fp['actual_parameters'] == cone.primitive.PARAMETERS
    assert fp['symbolic_input_bits'] == 74 and fp['relevant_operand_bits'] == 43
    assert fp['checked_output_bits'] == 48 and fp['input_assumptions'] == []
    assert fp['actual_model_binary_proof_acceptance'] is True
    actual = json.loads((cone_path.parent / 'positive.json').read_text())
    cone.validate_positive(cone.output_cone(actual))
    assert cp['registered_negative_control_pins'] == ['CEA2', 'CLK', 'RSTA']
    assert fp['actual_model_sha256'] == hashlib.sha256((cone_path.parent / 'positive.json').read_bytes()).hexdigest()
    for step, negative in zip(fp['commands'][1:], (True, False), strict=True):
        assert step['status'] == 'PASS'
        proof.validate_result((ROOT / step['log']).read_text(), step['returncode'], negative)
    primitive_paths = (verilator_path, iverilog_path)
    for path, simulator in zip(primitive_paths, ('verilator', 'iverilog'), strict=True):
        value = verify_report(path, 'PASS_ISOLATED_ACTUAL_DSP_CARRY_PRIMITIVE_MODEL_FIXTURES_ONLY')
        assert value['simulator'] == simulator and value['installed_model_sha256'] == MODEL_SHA
        assert value['parameters'] == cone.primitive.PARAMETERS and value['matched_actual_dsp_instances'] == 32
        assert value['dsp_comparisons'] == 4259904 and value['carry_binary_comparisons'] == 1024
        assert value['carry_four_state_comparisons'] == (1048576 if simulator == 'iverilog' else 0)
        assert value['primitive_fixture_acceptance'] is True
        for label, negative in (('dsp_negative_test', 'DSP'), ('carry_negative_test', 'CARRY'),
                ('positive_test', None)):
            matches = [step for step in value['commands'] if Path(step['log']).stem == label]
            assert len(matches) == 1 and matches[0]['status'] == 'PASS'
            cone.primitive.validate_result((ROOT / matches[0]['log']).read_text(),
                matches[0]['returncode'], simulator, negative)
    directory = parent_path.parent
    part, model, netlist = [directory / name for name in
        ('actual_partition.json', 'xilinx_functional_models.v', 'mapped_partition.v')]
    assert hashlib.sha256(model.read_bytes()).hexdigest() == MODEL_SHA
    raw = json.loads(part.read_text())
    assert cone.primitive.validate_configuration(raw, cone.primitive.BENCH.read_text()) == 32
    log = ROOT / parent['commands'][-1]['log']
    entries = inventory.diagnostics(log.read_text())
    assert dict(Counter(entry['kind'] for entry in entries)) == COUNTS == account['diagnostics']
    module = raw['modules'][cone.primitive.KERNEL]
    pins = inventory.missing_pin_provenance([entry for entry in entries if entry['kind'] == 'PINMISSING'],
        netlist.read_text().splitlines(), module, cone.model_ports(model.read_text()))
    assert pins == account['exact_missing_pin_provenance']
    aliases = unobserved_aliases([entry for entry in entries if entry['kind'] == 'UNDRIVEN'], module, netlist)
    assert aliases == 4673
    model_sites = validate_model_sites(entries, model)
    for entry in entries:
        if entry['kind'] in ('PINMISSING', 'UNDRIVEN', *model_sites_kind_names()):
            continue
        # Retain the original runner's already-supported metadata/unused gates.
        runner.validate_diagnostics('%Warning-' + entry['kind'] + ': ' + entry['source'] + ':' +
            str(entry['line']) + ':' + str(entry['column']) + ': ' + entry['message'] + '\n', directory)
    archive = json.loads(archive_path.read_text())
    assert archive['status'] == 'ARCHIVED_ACTUAL_DSP_PREFIX_MAPPED_COMPILE_DIAGNOSTIC_FAILURE'
    compiled = {name: sha for name, sha in archive['member_sha256'].items()
        if name.startswith(str((directory / 'cell').relative_to(ROOT)) + '/')}
    assert compiled and fingerprint([ROOT / name for name in compiled])['files'] == compiled
    library = directory / 'cell' / ('lib' + runner.BLOCK + '.a')
    wrapper = directory / 'cell' / (runner.BLOCK + '.sv')
    assert all(str(path.relative_to(ROOT)) in compiled for path in (library, wrapper))
    bound = [parent_path, inventory_path, cone_path, proof_path, *primitive_paths, archive_path,
        part, model, netlist, log, library, wrapper, Path(__file__).resolve()]
    certificate = dict(kind='EXACT_COMPLETED_PREFIX_DSP_KERNEL_COMPILER_DIAGNOSTIC_ADMISSION_ONLY',
        source=fingerprint(bound), warning_counts=COUNTS, omitted_pin_provenance=pins,
        undriven_alias_bits=aliases, undriven_observed_port_or_pin_bits=0, model_sites=model_sites,
        model_sha256=MODEL_SHA, compiled_products=fingerprint([ROOT / name for name in compiled]),
        model_cone_binary_proof_and_primitive_controls_verified=True,
        compiler_diagnostics_accepted=True, original_compile_report_remains='FAIL',
        full_array_numerical_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        scope='Only the source-identical completed 32-DSP combinational kernel: exact missing-pin '
        'bijection and disconnected omitted-input P cone; exact unobserved JSON aliases; '
        'fixed model width sites covered by unconstrained signed-product/bias proof and actual '
        'Icarus/Verilator primitives; zero-register combinational assignment/initializer sites; '
        'bitwise-acyclic CARRY4 with exhaustive binary and four-state controls. Follow-up '
        'warnings must be an exact counted subset. No RTL/model rewrite or numerical/physical PASS.')
    return certificate, Counter(key(entry) for entry in entries)


def model_sites_kind_names():
    return ('WIDTHEXPAND', 'WIDTHTRUNC', 'PROCASSINIT', 'COMBDLY', 'UNOPTFLAT')
