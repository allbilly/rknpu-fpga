"""Pure evidence checks for one held CE/UE FI read; no transport or hardware."""
from dataclasses import FrozenInstanceError, replace
import unittest

from tools.ddr.fi_client import (
    FiResult, CLAIM, LINE_READ, CLAIMED, GRANTED, RESULT, MATCHED, RECOVERY,
    PARENT_FAULT, CONTROL_FAULT, LOCAL_FAULT, BUSY, STATUS_MASK,
    INITIALIZED, DISARMED, BOOTSTRAPPED,
)
from tools.ddr.fi_evidence import EccReadEvidence, validate_ecc_read
from tools.host.transport import ProtocolError


OBSERVATION_ADDRESSES = tuple(range(0x324, 0x358, 4))
LINE_ADDRESS = 0x1000
MC_ADDRESS = 0x123456
WORDS = tuple((0x10203040 + i * 0x01010101) & 0xFFFFFFFF for i in range(16))
BASELINE_STATUS = CLAIMED | GRANTED | RESULT | MATCHED | INITIALIZED | DISARMED | BOOTSTRAPPED
HELD_QUARANTINE_STATUS = CLAIMED | GRANTED | RESULT | MATCHED | RECOVERY | PARENT_FAULT


def observations(*, kind='ce', mc_address=MC_ADDRESS, meta=None,
                 ce=10, ue=20, clear=30, reads=40, line=LINE_ADDRESS,
                 local_fault=0, known=0x1FF, mask_high=0, ctrl=0):
    if meta is None:
        meta = 0x10001 if kind == 'ce' else 0x10100
    return (
        (0x324, local_fault),
        (0x328, known),
        (0x32C, 0),
        (0x330, 0),
        (0x334, mask_high),
        (0x338, ce),
        (0x33C, ue),
        (0x340, mc_address),
        (0x344, meta),
        (0x348, clear),
        (0x34C, reads),
        (0x350, line),
        (0x354, ctrl),
    )


def receipt(command, ordinal, status, response_word, words, obs):
    return FiResult(command, ordinal, status, response_word, tuple(words), tuple(obs))


def pair(kind='ce', *, bit17=False):
    old = observations(kind=kind, meta=0, ce=10, ue=20, clear=30, reads=40)
    old_receipt = receipt(CLAIM, 50, BASELINE_STATUS, (CLAIM << 16) | (1 << 8), (), old)
    meta = (0x10001 if kind == 'ce' else 0x10100) | (0x20000 if bit17 else 0)
    new = observations(kind=kind, meta=meta,
                       ce=11 if kind == 'ce' else 10,
                       ue=21 if kind == 'ue' else 20,
                       clear=31, reads=41)
    response = 0 if kind == 'ce' else 2
    read_receipt = receipt(LINE_READ, 51, HELD_QUARANTINE_STATUS,
                           (LINE_READ << 16) | (1 << 8) | response,
                           WORDS, new)
    return old_receipt, read_receipt


class EccReadEvidenceTests(unittest.TestCase):
    def validate(self, before, result, *, kind='ce', line=LINE_ADDRESS,
                 mc=MC_ADDRESS, words=WORDS):
        return validate_ecc_read(before, result, kind=kind, line_address=line,
                                 expected_mc_address=mc, expected_words=words)

    def test_accepts_lane_zero_ce_and_ue_with_read_valid_independent(self):
        for kind in ('ce', 'ue'):
            for read_valid in (False, True):
                with self.subTest(kind=kind, read_valid=read_valid):
                    before, result = pair(kind, bit17=read_valid)
                    evidence = self.validate(before, result, kind=kind)
                    self.assertIsInstance(evidence, EccReadEvidence)
                    self.assertEqual(evidence.kind, kind)
                    self.assertEqual(evidence.line_address, LINE_ADDRESS)
                    self.assertEqual(evidence.mc_address, MC_ADDRESS)
                    self.assertEqual((evidence.ce_delta, evidence.ue_delta),
                                     (1, 0) if kind == 'ce' else (0, 1))
                    self.assertEqual((evidence.clear_delta, evidence.read_delta), (1, 1))
                    self.assertIs(evidence.event_read_data_valid, read_valid)
                    self.assertEqual(evidence.raw_bytes,
                                     b''.join(w.to_bytes(4, 'little') for w in WORDS))

    def test_accepts_new_event_after_baseline_held_claim_before_arming(self):
        before, result = pair('ce')
        self.assertEqual(before.command, CLAIM)
        self.assertEqual(before.response_word, (CLAIM << 16) | (1 << 8))
        self.assertEqual(before.status, BASELINE_STATUS)
        self.assertTrue(before.status & (RESULT | MATCHED) == (RESULT | MATCHED))
        self.assertFalse(before.status & (RECOVERY | PARENT_FAULT | BUSY | CONTROL_FAULT | LOCAL_FAULT))
        self.assertTrue(result.status & HELD_QUARANTINE_STATUS == HELD_QUARANTINE_STATUS)
        evidence = self.validate(before, result)
        self.assertEqual(evidence.ce_delta, 1)

    def test_observation_shape_rejects_missing_duplicate_reordered_and_wrong_address(self):
        before, result = pair('ce')
        bad_sets = (
            result.observations[:-1],
            result.observations[:-1] + (result.observations[-2],),
            result.observations[1:] + result.observations[:1],
            ((0x320, 0),) + result.observations[1:],
        )
        for bad in bad_sets:
            with self.subTest(observations=bad[:2]):
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, observations=bad))
        with self.assertRaises(ProtocolError):
            self.validate(replace(before, observations=result.observations), result)

    def test_baseline_must_be_held_healthy_and_known_zero_before_arming(self):
        before, result = pair('ce')
        for missing in (CLAIMED, GRANTED, RESULT, MATCHED):
            with self.subTest(missing=missing):
                with self.assertRaises(ProtocolError):
                    self.validate(replace(before, status=before.status & ~missing), result)
        for forbidden in (BUSY, RECOVERY, PARENT_FAULT, CONTROL_FAULT, LOCAL_FAULT, 1 << 20):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ProtocolError):
                    self.validate(replace(before, status=before.status | forbidden), result)
        for index, value in ((1, 0), (2, 1), (3, 1), (4, 1), (0, 1)):
            with self.subTest(observation_index=index, value=value):
                bad = list(before.observations)
                bad[index] = (bad[index][0], value)
                with self.assertRaises(ProtocolError):
                    self.validate(replace(before, observations=tuple(bad)), result)

    def test_required_claim_grant_result_match_recovery_and_parent_fault(self):
        before, result = pair('ce')
        required = CLAIMED | GRANTED | RESULT | MATCHED | RECOVERY | PARENT_FAULT
        for flag in (CLAIMED, GRANTED, RESULT, MATCHED, RECOVERY, PARENT_FAULT):
            with self.subTest(missing_flag=flag):
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, status=result.status & ~flag))
        for forbidden in (BUSY, CONTROL_FAULT, LOCAL_FAULT, 1 << 20):
            with self.subTest(forbidden_flag=forbidden):
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, status=result.status | forbidden))
        self.assertEqual(result.status & required, required)

    def test_command_response_ordinal_and_expected_kind_must_match(self):
        before, result = pair('ce')
        for changed in (
            replace(result, command=LINE_READ + 1),
            replace(result, response_word=result.response_word ^ 1),
            replace(result, ordinal=before.ordinal),
            replace(result, ordinal=0x1_0000_0000),
        ):
            with self.subTest(result=changed):
                with self.assertRaises(ProtocolError):
                    self.validate(before, changed)
        with self.assertRaises(ValueError):
            self.validate(before, result, kind='unknown')
        ue_before, ue_result = pair('ue')
        with self.assertRaises(ProtocolError):
            self.validate(ue_before, ue_result, kind='ce')

    def test_exact_sixteen_words_including_tail_are_required(self):
        before, result = pair('ue')
        for words in (WORDS[:-1], WORDS + (0,), WORDS[:-1] + (WORDS[-1] ^ 1,),
                      WORDS[:-1] + (True,)):
            with self.subTest(last=words[-1] if words else None, length=len(words)):
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, words=tuple(words)), kind='ue')
        with self.assertRaises(ValueError):
            self.validate(before, result, words=WORDS[:-1])
        with self.assertRaises(ValueError):
            self.validate(before, result, words=WORDS[:-1] + (1 << 32,))

    def test_ecc_meta_requires_valid_exclusive_lane_zero_event(self):
        before, result = pair('ce')
        for meta in (0, 1, 0x10000, 0x10002, 0x10101, 0x40001):
            with self.subTest(meta=hex(meta)):
                bad_obs = list(result.observations)
                bad_obs[8] = (0x344, meta)
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, observations=tuple(bad_obs)))
        # UE is lane-zero multiple only; a single-bit indication is not UE.
        before_ue, result_ue = pair('ue')
        bad_obs = list(result_ue.observations)
        bad_obs[8] = (0x344, 0x10001)
        with self.assertRaises(ProtocolError):
            self.validate(before_ue, replace(result_ue, observations=tuple(bad_obs)), kind='ue')

    def test_line_mc_address_and_known_mask_metadata_are_exact(self):
        before, result = pair('ce')
        for index, value in ((1, 0), (1, 0x100), (4, 0x100), (7, MC_ADDRESS + 1),
                             (11, LINE_ADDRESS + 64)):
            with self.subTest(index=index, value=value):
                bad_obs = list(result.observations)
                bad_obs[index] = (bad_obs[index][0], value)
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, observations=tuple(bad_obs)))
        with self.assertRaises(ValueError):
            self.validate(before, result, line=LINE_ADDRESS + 1)
        with self.assertRaises(ValueError):
            self.validate(before, result, mc=1 << 29)

    def test_exactly_one_matching_event_and_no_opposite_event(self):
        before, result = pair('ce')
        cases = (
            (5, 0x338, 10),  # no CE increment
            (5, 0x338, 12),  # duplicate CE
            (6, 0x33C, 21),  # opposite UE also incremented
        )
        for index, address, value in cases:
            with self.subTest(address=hex(address), value=value):
                bad_obs = list(result.observations)
                bad_obs[index] = (address, value)
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, observations=tuple(bad_obs)))
        before_ue, result_ue = pair('ue')
        bad_obs = list(result_ue.observations)
        bad_obs[6] = (0x33C, 20)
        with self.assertRaises(ProtocolError):
            self.validate(before_ue, replace(result_ue, observations=tuple(bad_obs)), kind='ue')

    def test_counters_reject_regression_wrap_and_saturation(self):
        before, result = pair('ce')
        for old, new in ((11, 10), (0xFFFFFFFE, 0xFFFFFFFF), (0xFFFFFFFF, 0xFFFFFFFF)):
            with self.subTest(old=old, new=new):
                old_obs = list(before.observations)
                new_obs = list(result.observations)
                old_obs[5] = (0x338, old)
                new_obs[5] = (0x338, new)
                with self.assertRaises(ProtocolError):
                    self.validate(replace(before, observations=tuple(old_obs)),
                                  replace(result, observations=tuple(new_obs)))

    def test_clear_and_read_valid_counter_deltas_are_required(self):
        before, result = pair('ce')
        for index, address in ((9, 0x348), (10, 0x34C)):
            with self.subTest(address=hex(address)):
                bad_obs = list(result.observations)
                bad_obs[index] = (address, dict(before.observations)[address])
                with self.assertRaises(ProtocolError):
                    self.validate(before, replace(result, observations=tuple(bad_obs)))

    def test_counter_observations_are_uint32_and_inputs_are_explicit(self):
        before, result = pair('ce')
        bad_obs = list(result.observations)
        bad_obs[5] = (0x338, -1)
        with self.assertRaises(ValueError):
            self.validate(before, replace(result, observations=tuple(bad_obs)))
        with self.assertRaises(TypeError):
            self.validate(None, result)
        with self.assertRaises(TypeError):
            self.validate(before, object())
        with self.assertRaises(ValueError):
            self.validate(before, result, line=1 << 32)
        with self.assertRaises(ValueError):
            self.validate(before, result, words=())

    def test_result_is_unchanged_and_frozen_and_validation_has_no_io_callbacks(self):
        before, result = pair('ue', bit17=True)
        before_copy, result_copy = replace(before), replace(result)
        evidence = self.validate(before, result, kind='ue')
        self.assertEqual(before, before_copy)
        self.assertEqual(result, result_copy)
        self.assertEqual(evidence.raw_bytes, result.raw_bytes)
        with self.assertRaises(FrozenInstanceError):
            result.status = 0
        with self.assertRaises(TypeError):
            validate_ecc_read(before, result, kind='ue', line_address=LINE_ADDRESS,
                              expected_mc_address=MC_ADDRESS, expected_words=WORDS,
                              read_register=lambda *_: self.fail('must not access hardware'))


if __name__ == '__main__':
    unittest.main()
