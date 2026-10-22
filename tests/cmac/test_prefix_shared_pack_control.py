"""Admission and pinned native-reader controls, not a new P&R/numeric result."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/openxc7')]
from pack_prefix_shared_board import (ROOT, TOP, PREPARED, QUALIFICATION, validate_prepared,
                                     validate_qualification, native_census, layout, records)


def fixture():
    counts = dict(CARRY4=8566, DSP48E1=515, FDCE=13981, FDPE=2, FDRE=3408, FDSE=128,
                  INV=22060, LUT1=798, LUT2=147030, LUT3=143590, LUT4=16586, LUT5=65410,
                  LUT6=57792, MUXF7=7138, MUXF8=1397, RAMB36E1=6)
    identity = {TOP: dict(cells=488407, bijective_wires=1, endpoint_bits=1)}
    labels = ['flatten_controls', 'admission_controls', 'generated_check', 'version', 'datadir',
              'independent_flatten', 'physical_IO_export']
    return dict(status=PREPARED, stage='complete', finished_utc='fixture-only', channels=32, kernels=16,
        parallel_products=512, retained_cmac_dsps=512, retained_shell_dsps=3, retained_kernel_instances=16,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        literal_expansion=dict(cells=counts, retained_private_instances=['kernel_' + str(i) for i in range(16)],
                               retained_shared_instances=['one_shared_input_cone']),
        physical_buffer_counts=dict(IBUF=2, OBUF=3, BUFG=1), flatten_controls=6, admission_controls=9,
        production_source_before={'fixture': 1}, production_source_after={'fixture': 1},
        independent_flatten_circuit_identity=deepcopy(identity), physical_buffer_roundtrip_identity=deepcopy(identity),
        commands=[dict(label=n, returncode=0, status='PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY') for n in labels],
        **dict.fromkeys(('arithmetic_optimized', 'runtime_BO_fixups', 'native_packing_executed',
                        'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff',
                        'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'), False))


class SharedPackAdmission(unittest.TestCase):
    def reject(self, mutation):
        value = fixture()
        mutation(value)
        with self.assertRaises(AssertionError):
            validate_prepared(value)

    def test_complete_full_preparation_admitted_without_mutation(self):
        value = fixture()
        before = deepcopy(value)
        validate_prepared(value)
        self.assertEqual(value, before)

    def test_running_failed_or_wrong_stage_rejected(self):
        for key, value in (('status', 'RUNNING'), ('status', 'FAIL_PREFIX_SHARED_PACK_INPUT'),
                           ('stage', 'physical_IO_export'), ('finished_utc', None)):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))

    def test_shrunk_target_wrong_part_clock_or_seed_rejected(self):
        for key, value in (('channels', 16), ('kernels', 8), ('parallel_products', 256), ('retained_cmac_dsps', 256),
                           ('retained_shell_dsps', 0), ('retained_kernel_instances', 8), ('intended_part', 'xc7a100t'),
                           ('intended_clock_period_ns', 40), ('seed', 0)):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))

    def test_missing_duplicate_kernel_or_shared_instance_rejected(self):
        self.reject(lambda r: r['literal_expansion']['retained_private_instances'].pop())
        self.reject(lambda r: r['literal_expansion']['retained_private_instances'].__setitem__(0, 'kernel_1'))
        self.reject(lambda r: r['literal_expansion']['retained_shared_instances'].clear())

    def test_changed_resource_buffer_or_source_rejected(self):
        self.reject(lambda r: r['literal_expansion']['cells'].update(DSP48E1=514))
        self.reject(lambda r: r['literal_expansion']['cells'].update(LUT6=57791))
        self.reject(lambda r: r['literal_expansion']['cells'].update(FDCE=13980))
        self.reject(lambda r: r['literal_expansion']['cells'].update(INV=22059))
        self.reject(lambda r: r['physical_buffer_counts'].update(BUFG=0))
        self.reject(lambda r: r.update(production_source_after={'fixture': 2}))

    def test_partial_identity_or_command_rejected(self):
        self.reject(lambda r: r['independent_flatten_circuit_identity'][TOP].update(cells=1))
        self.reject(lambda r: r['physical_buffer_roundtrip_identity'][TOP].update(bijective_wires=0))
        self.reject(lambda r: r['commands'].pop())
        self.reject(lambda r: r['commands'][-1].update(returncode=1))
        self.reject(lambda r: r['commands'][-1].update(status='RUNNING'))
        self.reject(lambda r: r.update(flatten_controls=0))

    def test_inferred_numerical_or_physical_acceptance_rejected(self):
        for key in ('arithmetic_optimized', 'runtime_BO_fixups', 'native_packing_executed', 'numerical_netlist_acceptance',
                    'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            self.reject(lambda r, k=key: r.update({k: True}))

    def test_actual_completed_encoder_qualification_admitted(self):
        report = json.loads(QUALIFICATION.read_text())
        before = deepcopy(report)
        validate_qualification(report)
        self.assertEqual(report, before)

    def test_running_or_waived_encoder_qualification_rejected(self):
        original = json.loads(QUALIFICATION.read_text())
        for key, value in (('status', 'RUNNING'), ('stage', 'full_native_pack'), ('finished_utc', None),
                           ('full_target_parallel_products', 256), ('timing_signoff', True)):
            report = deepcopy(original)
            report[key] = value
            with self.assertRaises(AssertionError):
                validate_qualification(report)
        report = deepcopy(original)
        next(s for s in report['commands'] if s['label'] == 'full_native_pack')['argv'].append('--timing-allow-fail')
        with self.assertRaises(AssertionError):
            validate_qualification(report)


class PinnedNativeReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = QUALIFICATION.parent / 'clock-admitted-packed.json'
        cls.raw = cls.path.read_bytes()
        report = json.loads(QUALIFICATION.read_text())
        cls.version = report['native_version']
        fixture_design = json.loads((QUALIFICATION.parent / 'test-only-config-input.json').read_text())
        cls.selected = {n: c for n, c in fixture_design['modules'][TOP]['cells'].items()
                        if c['type'] in ('DSP48E1', 'RAMB36E1')}

    def check_bytes(self, raw, selected=None, version=None):
        with tempfile.TemporaryDirectory(prefix='rknpu-shared-pack-reader-') as directory:
            path = Path(directory) / 'comparison-only.json'
            path.write_bytes(raw)
            return native_census(path, self.selected if selected is None else selected,
                                 self.version if version is None else version)

    def test_complete_saved_small_pack_reader(self):
        census, primitives = self.check_bytes(self.raw)
        self.assertEqual(set(primitives), set(self.selected))
        self.assertEqual(census['cells'], sum(census['primitive_counts'].values()))
        self.assertEqual(census['primitive_counts']['DSP48E1_DSP48E1'], 4)
        self.assertEqual(census['primitive_counts']['RAMB36E1_RAMB36E1'], 6)
        self.assertFalse(census['native_export_top_translation']['graph_data_changed'])

    def test_wrong_producer_or_clock_rejected(self):
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw, version=self.version.replace('c68c135', 'wrong'))
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw.replace(b'50000000.000000', b'25000000.000000'))

    def test_unknown_cell_type_rejected(self):
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw.replace(b'"type": "PAD"', b'"type": "UNKNOWN_PAD"', 1))

    def test_missing_or_extra_selected_resource_rejected(self):
        selected = deepcopy(self.selected)
        selected.pop(next(iter(selected)))
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw, selected=selected)
        selected = deepcopy(self.selected)
        selected['nonexistent'] = next(iter(selected.values()))
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw, selected=selected)

    def test_duplicate_cell_or_unparsed_record_rejected(self):
        begin, end = layout(self.raw)
        name, raw = next(records(self.raw, begin, end))
        self.assertTrue(name)
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw[:end] + b',\n' + raw + self.raw[end:])
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw[:begin] + b'garbage' + self.raw[begin:])

    def test_truncated_or_extra_export_rejected(self):
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw[:-20])
        with self.assertRaises(AssertionError):
            self.check_bytes(self.raw + b'extra')


if __name__ == '__main__':
    unittest.main()
