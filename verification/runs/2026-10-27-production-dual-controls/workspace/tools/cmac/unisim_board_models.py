"""Pinned, unmodified functional XC7 models for the mapped C32/K16 board.

This inventory is simulation-only. No models are FPGA implementation sources;
unknown primitives fail explicitly and global startup is never disabled.
"""
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT

CACHE = ROOT / 'build/reference/xilinx-unisim'
COMMIT = '1c8e05fd1e9a79ceb8b996a0996674122eed086f'
LICENSE_SHA = 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'
GLBL_SHA = 'de59a57e3e0091f1b9162d9914dce24c469820a0c5b5a41d1d202d93fae0abdd'
PINS = {
    'CARRY4': 'f2f62f5b5736dfa889da76f24cf7fdc9b456282420ef6a203e06d34408d4d75d',
    'FDCE': '55f43d08c637cf7b734ed9e64484a70697748d2b6a5ad8e4c3fd8fa6405dbef0',
    'FDPE': '7182584d6e58aed739e76777cf1d1aee11fb5c67eaea14c660ff1b6d6fe30b40',
    'FDRE': 'c6fdb4feddc181a2e7ec5c3abef314fef6d5755f999fc9ccad3bf79d1b543a1c',
    'FDSE': '173afee3263388433ef35431935175575fea2b4592d77cf87641ea83d416de82',
    'INV': 'e7ff76ec57c6554d4c4da9bee3c9e3a7351d4f32e87434507059a38b6901e856',
    'LUT1': '23be0311d281a612284fb355fb0778ac83e4d3a484c93e6a5a9d27dc471cbfc2',
    'LUT2': '7d148945093cd956ad3e924290b8fc778f5ea4b323397ebf5a6f78a3f0bbde06',
    'LUT3': '86711b745e4b5a71bf71eb6ab2747a2467da354949b45c7c5e4851dab5f6ed96',
    'LUT4': 'e1785d5dc015e002bef5b249a536144bbf2c2b6932192701cb6c828e817a8b75',
    'LUT5': '5eb071b18bcc3d48cefccd19c42dc1f7db6087272480c3e6015921f4bfec9ead',
    'LUT6': '0b6aff98f29cb3cd2745269519d84efc04b6b1a4f1244906558b5b37d67f7d87',
    'LUT6_2': 'd4927b9fa9299db1332257c215c48fad31954dbab189d2bd2aa098571d65f945',
    'MUXF7': '9ea29291c201b0eac484317a1151d7597f98e5426dee30d0d68b4acde00d6aba',
    'MUXF8': 'e17c29c2acb76b3b90b6b6cc2371b51fdbf226ca29e0cdec96e93a8d3cb5afcf',
    'RAMB18E1': 'f04b8980e1565e9b622723334d48d687e6dc48b93d08cb99ecb1206a0700848b',
    'RAMB36E1': 'b6153b595696f7eebe6840b2b8d518e32df698cb8e8b2730c8838648ceec72fb',
}


def selected_models(kinds):
    assert kinds and set(kinds) <= set(PINS), ('Unpinned mapped primitive', set(kinds) - set(PINS))
    result = {CACHE / 'LICENSE': LICENSE_SHA, CACHE / 'verilog/src/glbl.v': GLBL_SHA}
    result.update({CACHE / ('verilog/src/unisims/' + kind + '.v'): PINS[kind] for kind in sorted(set(kinds))})
    return result


def freeze_models(destination, kinds):
    assert destination.resolve().is_relative_to(ROOT)
    source = selected_models(kinds)
    destination.mkdir(parents=True, exist_ok=False)
    frozen = []
    for path, expected in source.items():
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, ('Changed pinned model', path)
        target = destination / path.name
        target.write_bytes(data)
        assert target.read_bytes() == data
        frozen.append(target)
    return source, frozen
