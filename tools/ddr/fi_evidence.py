"""Pure checks for one isolated RKFI ECC read, before its explicit ACK.

No device access or recovery is performed. The caller retains image/target
ownership and records raw transactions. Passing these checks alone does not
qualify physical injection, quarantine, disarm or subsequent recovery.
Register meanings follow rk_mig_fi_management_regs and the actual-controller
CE/UE bench: last_ecc_meta is {read_valid, ecc_valid, multiple[7:0], single[7:0]}.
"""
from dataclasses import dataclass

from tools.ddr.fi_client import (
    FiResult, LINE_READ, CLAIMED, GRANTED, RESULT, MATCHED, RECOVERY,
    PARENT_FAULT, STATUS_MASK, BUSY, CONTROL_FAULT, LOCAL_FAULT, uint,
)
from tools.host.transport import ProtocolError


@dataclass(frozen=True)
class EccReadEvidence:
    kind: str
    line_address: int
    mc_address: int
    ce_delta: int
    ue_delta: int
    clear_delta: int
    read_delta: int
    event_read_data_valid: bool
    raw_bytes: bytes


def _observations(result):
    if type(result) is not FiResult:
        raise TypeError('An original FiResult is required')
    addresses = tuple(range(0x324, 0x358, 4))
    if tuple(address for address, _ in result.observations) != addresses:
        raise ProtocolError('Incomplete, reordered or duplicate RKFI observations')
    for _, value in result.observations:
        uint(value, 32, 'RKFI observation')
    return dict(result.observations)


def validate_ecc_read(before, result, *, kind, line_address,
                      expected_mc_address, expected_words):
    """Validate complete bytes, one new valid event and retained quarantine.

    ``before`` is the held receipt captured before arming the isolated test.
    The caller supplies the raw expected words and source-bound MC address;
    this function neither derives a silicon address map nor repairs UE data.
    Counts are sequential observations, so external ownership must exclude
    unrelated requests. A fresh receipt after disarm must be checked separately.
    No ACK is issued even when validation succeeds.
    """
    if kind not in ('ce', 'ue'):
        raise ValueError('Expected an explicit ce or ue test')
    uint(line_address, 32, 'controller line address')
    uint(expected_mc_address, 29, 'expected raw MC address')
    if line_address % 64:
        raise ValueError('Controller line address must be 64-byte aligned')
    words = tuple(expected_words)
    if len(words) != 16:
        raise ValueError('Exactly sixteen expected raw words are required')
    for word in words:
        uint(word, 32, 'expected raw result word')
    previous, fields = _observations(before), _observations(result)
    held = CLAIMED | GRANTED | RESULT | MATCHED
    if (type(before.status) is not int or before.status & ~STATUS_MASK or
            before.status & held != held or
            before.status & (BUSY | RECOVERY | PARENT_FAULT | CONTROL_FAULT | LOCAL_FAULT) or
            previous[0x324] or previous[0x328] != 0x1FF or
            any(previous[address] for address in (0x32C, 0x330, 0x334))):
        raise ProtocolError('ECC baseline is not a healthy, known-zero held receipt')
    required = CLAIMED | GRANTED | RESULT | MATCHED | RECOVERY | PARENT_FAULT
    if (type(result.status) is not int or result.status & ~STATUS_MASK or
            result.status & required != required or
            result.status & (BUSY | CONTROL_FAULT | LOCAL_FAULT)):
        raise ProtocolError('ECC read lacks held ownership and ordinary quarantine')
    response = 0 if kind == 'ce' else 2
    if (result.command != LINE_READ or
            result.response_word != (LINE_READ << 16 | 1 << 8 | response) or
            type(result.ordinal) is not int or type(before.ordinal) is not int or
            not 0 <= before.ordinal < result.ordinal <= 0xFFFFFFFF):
        raise ProtocolError('ECC read command/response/ordinal mismatch')
    if (len(result.words) != 16 or
            any(type(word) is not int or not 0 <= word <= 0xFFFFFFFF
                for word in result.words) or result.words != words):
        raise ProtocolError('ECC read differs from the complete raw expected line')
    if (fields[0x324] or fields[0x328] != 0x1FF or
            fields[0x334] > 0xFF or fields[0x350] != line_address or
            fields[0x340] != expected_mc_address):
        raise ProtocolError('ECC read fault/mask knowledge/line/MC address mismatch')
    meta = fields[0x344]
    expected_meta = 0x10001 if kind == 'ce' else 0x10100
    # Bit 17 is observed independently; the source does not require the ECC
    # event and the returned read-data-valid pulse to coincide.
    if meta & ~0x3FFFF or meta & 0x1FFFF != expected_meta:
        raise ProtocolError('ECC event lacks valid, exclusive lane-zero classification')
    deltas = []
    for address in (0x338, 0x33C, 0x348, 0x34C):
        old, new = previous[address], fields[address]
        if new < old or new == 0xFFFFFFFF:
            raise ProtocolError('RKFI counter wrapped, regressed or saturated')
        deltas.append(new - old)
    if tuple(deltas[:2]) != ((1, 0) if kind == 'ce' else (0, 1)):
        raise ProtocolError('ECC read did not produce exactly the expected single event')
    if deltas[2] <= 0 or deltas[3] <= 0:
        raise ProtocolError('ECC read lacks new FI-clear/read-data-valid witnesses')
    return EccReadEvidence(kind, line_address, expected_mc_address, *deltas,
                           bool(meta & 0x20000), result.raw_bytes)
