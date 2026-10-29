#!/usr/bin/env python3
"""Strict uncompressed Series-7 packet CRC verification, never FPGA signoff.

UG470 v1.17 pp.84/97-103 defines CRC writes/checks, RCRC and packet grammar.
The polynomial/37-bit data/address order is independently implemented from
Project X-Ray's pinned xc7series/crc.h (ISC). This reader accepts ordinary
scalar writes and FDRI only; debug LOUT, reads, encryption, compression and
per-frame CRC streams are unsupported, not silently skipped.
All physical, numerical, test-ready and hardware-use gates remain false.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import struct
import sys

POLY = 0x82F63B78
PART = 'xc7k480tffg1156-2'
IDCODE = 0x03751093
REGISTERS = {0, 1, 2, 4, 5, 6, 9, 12, 13, 14, 16, 17, 19, 24, 31}
COMMANDS = {0, 1, 3, 5, 7, 9, 10, 13}
MAX_BYTES = 64 * 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def byte_table():
    result = []
    for value in range(256):
        for _ in range(8):
            value = (value >> 1) ^ (POLY if value & 1 else 0)
        result.append(value)
    return tuple(result)


TABLE = byte_table()


def update(reg, data, previous):
    require(type(reg) is int and 0 <= reg < 32, 'Invalid CRC address')
    require(all(type(v) is int and 0 <= v <= 0xffffffff for v in (data, previous)), 'Invalid CRC word/state')
    value = previous
    for shift in (0, 8, 16, 24):
        value = TABLE[(value ^ (data >> shift)) & 255] ^ (value >> 8)
    for bit in range(5):
        value = (value >> 1) ^ (POLY if (value ^ (reg >> bit)) & 1 else 0)
    return value


def payload(raw, expected_part):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'Invalid/oversized input')
    position = 0

    def take(count):
        nonlocal position
        require(count >= 0 and position + count <= len(raw), 'Truncated bitstream')
        result = raw[position:position + count]
        position += count
        return result

    def u16():
        return struct.unpack('>H', take(2))[0]

    require(take(u16()) == bytes.fromhex('0ff00ff00ff00ff000'), 'Invalid .bit magic')
    require(u16() == 1, 'Invalid initial tag length')
    fields = {}
    for tag in b'abcd':
        require(take(1) == bytes([tag]), 'Invalid metadata tag')
        value = take(u16())
        require(value.endswith(b'\0') and b'\0' not in value[:-1], 'Invalid metadata terminator')
        fields[chr(tag)] = value[:-1].decode('ascii')
    require(fields['b'] == expected_part, 'Wrong exact declared part')
    require(take(1) == b'e', 'Missing payload tag')
    length = struct.unpack('>I', take(4))[0]
    data = take(length)
    require(position == len(raw) and length > 0 and length % 4 == 0, 'Invalid payload length/trailing bytes')
    return fields, data


def packets(data):
    require(len(data) % 4 == 0, 'Unaligned payload')
    count = len(data) // 4

    def word(index):
        return struct.unpack_from('>I', data, index * 4)[0]

    index = 0
    while index < min(count, 64) and word(index) == 0xffffffff:
        index += 1
    require(index > 0 and index + 2 < count, 'Unsupported bus-width preamble')
    require(word(index) == 0xbb and word(index + 1) == 0x11220044, 'Invalid bus-width detection')
    index += 2
    dummy = 0
    while index < min(count, 64) and word(index) == 0xffffffff:
        index += 1
        dummy += 1
    require(dummy > 0 and index < count and word(index) == 0xaa995566, 'Missing aligned sync word')
    index += 1
    pending = None
    while index < count:
        offset = index
        header = word(index)
        index += 1
        kind, operation = header >> 29, (header >> 27) & 3
        require(pending is None or kind == 2, 'Unfulfilled immediate type-2 owner')
        if kind == 1:
            require(header & 0x1800 == 0, 'Reserved type-1 bits')
            reg, size = (header >> 13) & 0x3fff, header & 0x7ff
            require(reg in REGISTERS, 'Unsupported register')
            if operation == 0:
                require(header == 0x20000000, 'Noncanonical NOP')
                pending = None
                yield offset, None, ()
                continue
            require(operation == 2, 'Unsupported read/reserved operation')
            require((reg == 2 and size >= 0) or (reg != 2 and size == 1), 'Unsupported scalar word count')
            pending = (reg, operation) if size == 0 else None
        elif kind == 2:
            require(pending == (2, 2) and operation == 2, 'Missing immediate empty type-1 FDRI owner')
            reg, size = 2, header & 0x7ffffff
            require(size > 0, 'Empty type-2 packet')
            pending = None
        else:
            raise ValueError('Unsupported packet type/debug padding')
        require(index + size <= count, 'Truncated packet data')
        yield offset, reg, memoryview(data)[index * 4:(index + size) * 4]
        index += size
    require(pending is None, 'Unfulfilled type-2 owner')


def verify(raw, expected_part=PART, expected_idcode=IDCODE):
    fields, data = payload(raw, expected_part)
    state, initialized, dirty, fdri_words = 0, False, 0, 0
    total, checked_words, resets, prologue_words = 0, 0, 0, 0
    checks, ids = [], []
    desynchronized = False
    for offset, reg, values in packets(data):
        total += 1
        if reg is None:
            continue
        require(not desynchronized, 'Register write after DESYNC')
        for (value,) in struct.iter_unpack('>I', values):
            if reg == 4:
                require(value in COMMANDS, 'Unsupported configuration command')
            if reg == 12:
                ids.append(value)
            if reg == 0:
                require(initialized and value == state, f'CRC mismatch at payload word {offset}: expected {state:08x}, got {value:08x}')
                checks.append(dict(payload_word=offset, expected=value, covered_words=dirty))
                checked_words += dirty
                dirty = 0
                state = update(0, value, state)
                require(state == 0, 'CRC residue did not clear')
            elif reg == 4 and value == 7:
                require(not initialized or dirty == 0, 'CRC reset discards unchecked register/frame writes')
                state, initialized = 0, True
                resets += 1
            elif reg == 4 and value == 13:
                require(initialized and dirty == 0 and checks, 'DESYNC before complete CRC coverage')
                desynchronized = True
            else:
                if initialized:
                    state = update(reg, value, state)
                    dirty += 1
                else:
                    require(reg in (4, 16, 17) and value == 0, 'Unsupported unchecked pre-reset prologue')
                    prologue_words += 1
                if reg == 2:
                    require(initialized, 'Frame data before CRC reset')
                    fdri_words += 1
    require(ids == [expected_idcode], 'Wrong/ambiguous exact IDCODE')
    require(checks and fdri_words > 0 and dirty == 0 and desynchronized, 'Missing complete CRC/frame/finalization coverage')
    return dict(status='PASS_SOFTWARE_PACKET_CRC_ONLY_NOT_SIGNOFF_OR_TEST_READY', part=fields['b'],
        idcode=expected_idcode, packet_count=total, fdri_words=fdri_words, crc_checks=checks,
        checked_register_words=checked_words, pre_reset_zero_prologue_words=prologue_words,
        crc_resets=resets, packet_crc_checks_match=True,
        physical_configuration_crc_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, numerical_acceptance=False, full_target_acceptance=False,
        test_ready_bitstream=False, hardware_accessed=False, input_modified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bitstream', type=Path)
    parser.add_argument('--expected-part', default=PART)
    parser.add_argument('--expected-idcode', type=lambda s: int(s, 0), default=IDCODE)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    path = args.bitstream.resolve(strict=True)
    require(path.stat().st_size <= MAX_BYTES, 'Oversized bitstream')
    raw = path.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    try:
        result = verify(raw, args.expected_part, args.expected_idcode)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == before, 'Input changed during verification')
        result.update(input=str(path), input_sha256=before, method=str(Path(__file__).resolve()),
            method_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), python_version=sys.version)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (ValueError, UnicodeError, struct.error) as error:
        print(json.dumps(dict(status='FAIL_SOFTWARE_PACKET_CRC', error=str(error), input=str(path),
            input_sha256=before, test_ready_bitstream=False, hardware_accessed=False, input_modified=False),
            indent=2, sort_keys=True))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
