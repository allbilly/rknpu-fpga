"""Source-bound review of this startup candidate's intentional reset styles.

The reset output asserts at configuration and releases after a clock edge.
Synchronous ROM/controller reset keeps async controls away from BRAM; the
engine and bench retain immediate ownership abort. This is one clock domain,
with no runtime reset input. This review supplies no physical reset signoff.
No warning is disabled in Verilator or in the design sources.
"""
from pathlib import Path

from tools.cmac.startup import qualification as q

TOP = 'fpga/cmac/startup/ypcb_cmac_array_regmem_top.sv'
BENCH = 'tests/cmac/startup/tb_array_startup.sv'
REVIEWED_SOURCES = {
    TOP: '0a76b3e1362f85e20deaa7894ee3d92d039d4096b00ada28f46b3828d26ce775',
    'rtl/cmac/experimental/rk_cmac_array_bram_demo_regmem.sv': '6ebd923159eb1bb746b48052cf907b33cb6f78a54b7877eff0a3c2c86b281f13',
    'rtl/cmac/experimental/rk_cmac_demo_memory_regport.sv': 'c4ce96aa41db8616bfec1403886420ad27d0e524ccedd1f7fb191620eee03cb5',
    'rtl/rk_startup_reset.sv': '884afddfc59f0216a112990b63623251f3a951279ef6c5ea7ebb84e1a5d1bf09',
    BENCH: 'b861e0913aad677326a580880a167277e2218502ad52eed867848ff66842d3c0',
}


def reviewed_warnings(text, execution_root, *, compilation):
    root = Path(execution_root)
    for name, expected in REVIEWED_SOURCES.items():
        q.require(q.digest(root/name) == expected, 'Reset warning source requires new review: '+name)
    header = (f"%Warning-SYNCASYNCNET: {root/TOP}:14:10: Signal flopped as both "
              "synchronous and async: 'tb_array_startup.dut.reset_n'")
    q.require(text.splitlines().count(header) == int(compilation),
              'Registered-BRAM reset warning inventory changed')
    if compilation:
        for location in [f'{root/BENCH}:26:18: ... Location of async usage',
                         f'{root/TOP}:23:14: ... Location of sync usage']:
            q.require(text.count(location) == 1, 'Reset warning use site changed')
    # The existing donor/prefix inventory remains exact. Any different warning,
    # including another SYNCASYNCNET location, still reaches its strict parser.
    existing = q.reviewed_warnings(text.replace(header, ''), root)
    return existing + ([dict(kind='SYNCASYNCNET', path=TOP, line=14, column=10,
                             review='Source-bound startup-only mixed reset styles; no DRC waiver')]
                       if compilation else [])
