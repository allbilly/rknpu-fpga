from pathlib import Path
from datetime import datetime, timezone
import json, re, time
OUT=Path(__file__).resolve().parent
samples=[]
for idx in range(60):
    mem=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M).group(1))*1024
    cpu=Path('/proc/pressure/cpu').read_text(); mp=Path('/proc/pressure/memory').read_text()
    cpu_psi=float(re.search(r'^some avg10=([0-9.]+)',cpu,re.M).group(1))
    full_psi=float(re.search(r'^full avg10=([0-9.]+)',mp,re.M).group(1))
    row={'utc':datetime.now(timezone.utc).isoformat(),'memavailable_bytes':mem,
         'cpu_psi_some_avg10':cpu_psi,'memory_psi_full_avg10':full_psi,
         'pass':mem>=8589934592 and cpu_psi<5 and full_psi<1}
    samples.append(row)
    passing=[]
    for item in reversed(samples):
        if not item['pass']:break
        passing.append(item)
    if len(passing)>=3:
        break
    if idx<59:time.sleep(30)
status='RESOURCE_GATE_PASS_FOR_PRODUCTION_V16' if len(passing)>=3 else 'RESOURCE_GATE_PENDING_FOR_PRODUCTION_V16'
report={'status':status,'launch_performed':False,'required':{'MemAvailable_min_bytes':8589934592,
        'CPU_PSI_some_avg10_max_exclusive':5.0,'memory_PSI_full_avg10_max_exclusive':1.0,
        'cgroup':{'MemoryMax':'6442450944','MemorySwapMax':'0','CPUQuota':'200%','TasksMax':256}},
        'samples':samples,'last_three_pass':passing[:3] if len(passing)>=3 else []}
target=OUT/'admission.json'
if target.exists():raise SystemExit('admission.json already exists; preserve it and use a fresh directory')
target.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':status,'sample_count':len(samples),'last_three_pass':len(report['last_three_pass']),'admission':str(target.resolve())},indent=2))
