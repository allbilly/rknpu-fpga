#!/usr/bin/env python3
"""Check a YPCB XC7K480T Vivado .bit file without accessing hardware.

This validates the file container, board-device identification, packet bounds,
and basic configuration contents. The speed grade is often absent from the
Vivado .bit header, so the project/XSA remains the authority for that detail.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


TARGET_PART = "xc7k480tffg1156-2"
TARGET_IDCODE = 0x03751093
MIN_FDRI_WORDS = 100_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def target_header_parts(target_part):
    target = target_part.lower()
    require(target.startswith("xc"), "Expected a full XC part name")
    without_prefix = target[2:]
    match = re.fullmatch(r"(7k480tffg1156)-(\d+[a-z]?)", without_prefix)
    require(match is not None, f"Unsupported YPCB target part: {target_part}")
    base = match.group(1)
    # Some Vivado releases omit the speed grade from the .bit header. Accept
    # that exact device/package string, while rejecting a different explicit
    # speed grade when one is present.
    return {target, without_prefix, base, "xc" + base}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_bitstream(data, target_part=TARGET_PART):
    require(len(data) > 1_000_000, "Bitstream is unexpectedly small")
    pos = 0

    def take(size):
        nonlocal pos
        require(0 <= size <= len(data) - pos, "Truncated bitstream header")
        result = data[pos:pos + size]
        pos += size
        return result

    def u16():
        return struct.unpack(">H", take(2))[0]

    require(take(u16()) == bytes.fromhex("0ff00ff00ff00ff000"),
            "Invalid .bit header signature")
    require(u16() == 1, "Invalid .bit header marker")
    fields = {}
    while True:
        tag = take(1).decode("ascii")
        if tag == "e":
            payload_bytes = struct.unpack(">I", take(4))[0]
            break
        require(tag in "abcd" and tag not in fields,
                "Unexpected or duplicate .bit header field")
        fields[tag] = take(u16()).rstrip(b"\0").decode("ascii")
    require(set(fields) == set("abcd"), "Missing required .bit header field")
    require(len(data) - pos == payload_bytes,
            "Declared payload length differs from file")

    allowed_parts = target_header_parts(target_part)
    header_part = fields["b"].lower()
    require(header_part in allowed_parts,
            f"Header part {fields['b']!r} does not match YPCB target {target_part}")

    payload = data[pos:]
    require(len(payload) % 4 == 0, "Configuration payload is not word-aligned")
    sync = payload.find(bytes.fromhex("aa995566"))
    require(0 <= sync < 128 and sync % 4 == 0,
            "Missing or misaligned configuration sync word")

    cursor = sync + 4
    last_register = None
    idcodes, commands = [], []
    fdri_words = 0
    packet_count = 0
    while cursor < len(payload):
        offset = cursor
        word = struct.unpack_from(">I", payload, cursor)[0]
        cursor += 4
        if word in (0, 0xFFFFFFFF):
            continue

        kind, opcode = (word >> 29) & 7, (word >> 27) & 3
        require(kind in (1, 2), f"Unknown packet type at payload offset {offset}")
        require(opcode in (0, 1, 2), "Reserved configuration opcode")
        if kind == 1:
            register, count = (word >> 13) & 0x3FFF, word & 0x7FF
            last_register = register
        else:
            require(last_register is not None, "Type-2 packet has no register context")
            register, count = last_register, word & 0x7FFFFFF

        require(cursor + 4 * count <= len(payload),
                f"Packet data overruns payload at offset {offset}")
        packet_count += 1
        if opcode == 2 and register == 12:
            idcodes.extend(struct.unpack_from(">" + "I" * count, payload, cursor))
        elif opcode == 2 and register == 4:
            commands.extend(struct.unpack_from(">" + "I" * count, payload, cursor))
        elif opcode == 2 and register == 2:
            fdri_words += count
        cursor += 4 * count

    require(idcodes == [TARGET_IDCODE],
            f"Configuration IDCODE does not match XC7K480T: {idcodes!r}")
    require(fdri_words > MIN_FDRI_WORDS,
            "Configuration contains no substantial frame-data packet")
    require(5 in commands and 13 in commands,
            "Configuration is missing START or DESYNC")

    speed_grade = "NOT_ENCODED_IN_BIT_HEADER"
    if header_part.endswith("-2"):
        speed_grade = "MATCHED_IN_BIT_HEADER"
    return {
        "header": fields,
        "target_part": target_part,
        "package_device_match": True,
        "speed_grade_evidence": speed_grade,
        "payload_offset": pos,
        "payload_bytes": len(payload),
        "sync_offset": sync,
        "idcode": hex(idcodes[0]),
        "fdri_words": fdri_words,
        "packet_count": packet_count,
        "commands": commands,
    }


def check(bit, expected_sha256=None):
    bit = Path(bit).resolve()
    data = bit.read_bytes()
    digest = sha256(data)
    if expected_sha256:
        require(digest.lower() == expected_sha256.lower(),
                "Bitstream SHA256 differs from expected provenance")
    structure = parse_bitstream(data)
    return {
        "status": "PASS",
        "scope": "Vivado .bit container, YPCB device/package header, IDCODE, packet bounds and configuration markers",
        "bit": str(bit),
        "bytes": len(data),
        "sha256": digest,
        "expected_sha256_checked": bool(expected_sha256),
        "structure": structure,
        "crc": "NOT_CHECKED",
        "vivado_drc": "NOT_CHECKED",
        "timing": "NOT_CHECKED",
        "speed_grade_source": "PROJECT_OR_XSA_REQUIRED_IF_HEADER_OMITS_IT",
        "programming": "NOT_RUN",
        "physical_hardware": "NOT_RUN",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bit", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"Refusing to overwrite report: {args.out}")

    try:
        report = check(args.bit, args.expected_sha256)
    except (OSError, UnicodeError, ValueError, struct.error) as error:
        report = {"status": "FAIL", "error": str(error),
                  "programming": "NOT_RUN", "physical_hardware": "NOT_RUN"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(args.out)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
