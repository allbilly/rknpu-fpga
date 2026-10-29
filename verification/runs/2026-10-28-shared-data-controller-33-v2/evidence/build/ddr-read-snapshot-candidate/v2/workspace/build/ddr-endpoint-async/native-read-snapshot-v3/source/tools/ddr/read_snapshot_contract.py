"""Independent traffic contract for packet-scoped physical READ64 snapshots.

Schema3 deliberately cannot accept legacy halfword-read receipts. Numerical
vectors, command BOs, error expectations and whole-image comparison are shared.
"""
from pathlib import Path
import re
from tools.ddr import async_endpoint_contract as legacy
from tools.ddr.interface import require

TOP=legacy.TOP
CASE_COUNT=legacy.CASE_COUNT
SCHEMA=3
SCOPE=legacy.SCOPE+'; packet-scoped host READ64: exactlyone actual AXI read per successful packet'
sha=legacy.sha
selection=legacy.selection
check_warnings=legacy.check_warnings
MARKER=re.compile(r'PASS jtag_ew_ddr_read_snapshot jobs=(\d+) negative=(\d+) recovered=(\d+) '
    r'lines=(\d+) uploaded_nonzero=(\d+) rawtasks=(\d+) phy_user_returns=(\d+) '
    r'read64_packets=(\d+) read64_axi_reads=(\d+) scope=actual_AXI_UI_MC_modeled_PHY')

def metrics(spec,vector_root):
    data=legacy.metrics(spec,vector_root)
    # PHY counters reset at each joint epoch. Normal startup reads first/last
    # initialized lines; the recovery epoch instead reads one command line.
    startup_packets=1 if spec['reset_recovery'] else 2
    packets=startup_packets+data['lines']*data['successful_jobs']
    old=data['phy_user_returns']
    data.update(host_read64_packets=packets,host_read64_axi_reads=packets,
        uncached_phy_user_returns=old,
        # Each READ64 replaces32 physical reads with1. All write RMW/fences,
        # command/DMA reads and initialization remain untouched.
        phy_user_returns=None if old is None else old-31*packets,
        phy_user_returns_minimum=(1 if spec['reset_recovery'] else 65)+packets+data['uploaded_nonzero']*64)
    require(data['phy_user_returns'] is None or data['phy_user_returns']>=data['phy_user_returns_minimum'],
            'Impossible static snapshot traffic inventory')
    return data

def check_result(text,code,spec,data,observed,expected):
    require(type(code) is int and code==0,'Snapshot DDR simulation did not exit successfully')
    require(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|\$fatal|Assertion failed|\bwarning:',text),
            'Unadmitted snapshot runtime failure/diagnostic')
    markers=[line for line in text.splitlines() if line.startswith('PASS ')]
    require(len(markers)==1 and MARKER.fullmatch(markers[0]) is not None,'Missing/extra/malformed snapshot completion')
    values=list(map(int,MARKER.fullmatch(markers[0]).groups()))
    jobs=0 if spec['negative']==9 else spec['jobs']+int(bool(spec['reset_recovery']))
    require(values[:6]==[jobs,spec['negative'],int(bool(spec['reset_recovery'])),data['lines'],
            data['uploaded_nonzero'],spec['tasks']],'Changed snapshot scenario coverage')
    if spec['negative']==10:
        require(text.splitlines().count('CHECKED partial_task_fault completed=1 ui_code=5')==1,
                'Missing actual partial-task/first-cause assertion')
    require(values[7:]==[data['host_read64_packets'],data['host_read64_axi_reads']],
            'Missing/duplicate/bypassed physical READ64 packet inventory')
    if data['phy_user_returns'] is not None:
        require(values[6]==data['phy_user_returns'],'Actual snapshot PHY return inventory differs')
    else:
        require(values[6]>=data['phy_user_returns_minimum'],'Missing initialization/write/fence traffic')
    observed,expected=Path(observed),Path(expected)
    if data['successful_jobs']:
        require(observed.is_file() and observed.read_bytes()==expected.read_bytes(),'Complete DDR BO readback differs')
        require(len(observed.read_text().splitlines())==data['lines'],'Incomplete readback rows')
    else:require(not observed.exists(),'Fault-only snapshot case produced successful readback')
    return dict(marker=markers[0],phy_user_returns=values[6],read64_packets=values[7],read64_axi_reads=values[8],
        readback_physical_bytes=data['physical_bytes']*data['successful_jobs'],
        persisted_final_image_physical_bytes=data['physical_bytes'] if data['successful_jobs'] else 0,
        observed_text_bytes=observed.stat().st_size if observed.is_file() else 0,
        observed_sha256=sha(observed) if observed.is_file() else None,successful_jobs=data['successful_jobs'])
