"""Closed Icarus -Wall inventory for the unchanged frozen full512 arithmetic.

Only inherited timeunit metadata and @* array sensitivity enumeration were
reviewed. This preserves diagnostics and checks exact source/content/counts;
it changes no compiler flag, RTL, electrical, CDC, DRC or timing rule.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from tools.cmac.startup import qualification as q

INVENTORY = Path(__file__).resolve().parents[2]/'fpga/tinystories/iverilog_arithmetic_warnings.json'


def validate(text, arithmetic_root):
    root = Path(arithmetic_root).resolve()
    expected = json.loads(INVENTORY.read_text())
    for name, value in expected['source_files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != value:
            raise ValueError('Changed source in reviewed Icarus arithmetic inventory')
    actual = Counter(line.replace(str(root)+'/', '<arithmetic>/')
                     for line in text.splitlines() if line.strip())
    if actual != Counter(expected['messages']):
        raise ValueError('Unreviewed/missing/changed Icarus compilation diagnostic')
    return dict(lines=expected['total_lines'], kinds=len(actual), source_files=len(expected['source_files']))


RESET_REVIEW = {
    'rtl/tinystories/rk_cmac_success_rearm.sv':'495d5374268bfb52aaeb896b6b25373a6e4d84ab6df4b33c53f0dbf4fd18ad6e',
    'rtl/tinystories/rk_jtag_dual_bram.sv':'fdc1e954eab8f83c317f40f705339ae0dbee06af1024d64d9076b6c201f071d9',
    'rtl/tinystories/rk_shared_bram_regport.sv':'2a62a55bb6cc4ea6946f361726f6c53d347b5ed5b3fea337cad2082c3d8bffc1',
    'tests/tinystories/tb_jtag_dual_bram.sv':'1a113f62588f091d08107185fcb5ab304a97a594d8c9e6534996582fa3d0bb27',
}


def validate_verilator(text, arithmetic_root, execution_root, *, compilation):
    # Both reset styles occur under the same SYS clock. The local reset is
    # now a separate registered release FF, qualified only after memory drain;
    # it never resets RAM or the mailbox. Native review is not routed signoff.
    root, arithmetic = Path(execution_root), Path(arithmetic_root)
    for name, value in RESET_REVIEW.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != value:
            raise ValueError('Changed source in registered-reset warning review')
    extra = (f'%Warning-SYNCASYNCNET: {arithmetic}/rtl/cmac/rk_nvdla_cacc.sv:6:21: '
             "Signal flopped as both synchronous and async: 'tb_jtag_dual_bram.dut.cm_engine.engine.core.datapath.arithmetic.cacc.kernels[0].accumulator.rst_n'")
    count = text.splitlines().count(extra)
    if count != int(compilation):
        raise ValueError('Changed joined reset diagnostic inventory')
    if compilation:
        for use in ('async','sync'):
            site=f'{arithmetic}/rtl/cmac/rk_nvdla_cacc.sv:6:21: ... Location of {use} usage'
            if text.count(site) != 1:
                raise ValueError('Changed registered-reset use-site review')
    baseline = q.reviewed_warnings(text.replace(extra,''),arithmetic)
    if re.search(r'(?im)%Error|\b(?:error|warning):|sorry:|FATAL:',text):
        raise ValueError('Unadmitted Verilator diagnostic')
    return dict(baseline_locations=len(baseline), registered_reset_notice=count)
