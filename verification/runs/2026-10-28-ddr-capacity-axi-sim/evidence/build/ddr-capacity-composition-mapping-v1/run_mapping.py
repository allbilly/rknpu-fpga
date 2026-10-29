#!/usr/bin/env python3
"""Bounded Yosys XC7 mapping for the six-module DDR capacity diagnostic subsystem."""
from pathlib import Path
import datetime,hashlib,json,os,re,signal,subprocess,sys,time
BASE=Path(__file__).resolve().parent
ROOT=Path('/home/fedora/rknpu-fpga')
MANIFEST=BASE/'source-manifest.json';SCRIPT=BASE/'mapping.ys';REPORT=BASE/'report.json'
YOSYS=Path('/home/linuxbrew/.linuxbrew/bin/yosys');CHILD=None
TIMEOUT=600

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def cgroup_dir():
    rel=next(row[3:] for row in Path('/proc/self/cgroup').read_text().splitlines() if row.startswith('0::')).lstrip('/')
    return Path('/sys/fs/cgroup')/rel
def pids(pgid):
    result=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            f=(entry/'stat').read_text().rsplit(')',1)[1].split()
            if int(f[2])==pgid and f[0] not in {'Z','X'}:result.append(int(entry.name))
        except (FileNotFoundError,ProcessLookupError,PermissionError,ValueError,IndexError):pass
    return sorted(result)
def stop_owned(child):
    if child is None:return []
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:child.wait(timeout=5)
    except subprocess.TimeoutExpired:pass
    live=pids(child.pid)
    if live:
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:pass
    return pids(child.pid)
def main():
    global CHILD
    started=time.monotonic();source_before={};record={'status':'PREFLIGHT','scope':'six-module DDR capacity subsystem Yosys XC7 mapping only; no whole-design fit/timing/physical claim',
        'hardware_accessed':False,'vivado_executed':False,'bitstream_emitted':False,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    require(not REPORT.exists(),'Fresh mapping output required')
    try:
        manifest=json.loads(MANIFEST.read_text());require(len(manifest['sources'])==6,'Expected six frozen HDL inputs')
        source_before={row['original_path']:sha(row['original_path']) for row in manifest['sources']}
        copies_before={row['copied_path']:sha(row['copied_path']) for row in manifest['sources']}
        require(source_before=={r['original_path']:r['original_sha256'] for r in manifest['sources']},'Original source changed before mapping')
        require(copies_before=={r['copied_path']:r['copied_sha256'] for r in manifest['sources']},'Frozen source copy changed before mapping')
        lint_report=Path(manifest['source_report_path'])
        require(lint_report.is_file() and sha(lint_report)==manifest['source_report_sha256'],
                'Composition lint source report changed')
        runner_path=Path(__file__).resolve()
        group=cgroup_dir();limits={k:(group/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        require(limits=={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},'Wrong mapping cgroup resource limits')
        available=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
        mempsi=Path('/proc/pressure/memory').read_text();cpupsi=Path('/proc/pressure/cpu').read_text()
        require(available>=8388608 and float(re.search(r'^full avg10=([0-9.]+)',mempsi,re.M)[1])<1 and
                float(re.search(r'^some avg10=([0-9.]+)',cpupsi,re.M)[1])<5,'Host admission failed')
        version=subprocess.run([str(YOSYS),'-V'],capture_output=True,text=True,timeout=30,check=True)
        argv=[str(YOSYS),'-Q','-s',str(SCRIPT)]
        record.update(status='RUNNING',argv=argv,yosys_path=str(YOSYS),yosys_sha256=sha(YOSYS),yosys_version=version.stdout.strip(),
          source_manifest_path=str(MANIFEST),source_manifest_sha256=sha(MANIFEST),mapping_script_path=str(SCRIPT),mapping_script_sha256=sha(SCRIPT),
          input_hashes_expected={**source_before,**copies_before,str(MANIFEST):sha(MANIFEST),str(SCRIPT):sha(SCRIPT),
                                 str(runner_path):sha(runner_path),str(lint_report):sha(lint_report),str(YOSYS):sha(YOSYS)},
          input_hashes_before={**source_before,**copies_before,str(MANIFEST):sha(MANIFEST),str(SCRIPT):sha(SCRIPT),
                               str(runner_path):sha(runner_path),str(lint_report):sha(lint_report),str(YOSYS):sha(YOSYS)},
          kernel_limits=limits,host_available_kib=available,memory_psi=mempsi,cpu_psi=cpupsi,timeout_seconds=TIMEOUT,design_top='rk_ddr_capacity_bist',
          defines=['SYNTHESIS'],synthesis='synth_xilinx -family xc7 -top rk_ddr_capacity_bist -flatten')
        with (BASE/'stdout.log').open('x') as out,(BASE/'stderr.log').open('x') as err:
            CHILD=subprocess.Popen(argv,cwd=BASE,stdout=out,stderr=err,start_new_session=True)
            record.update(pid=CHILD.pid,pgid=CHILD.pid)
            REPORT.write_text(json.dumps(record,indent=2)+'\n')
            try:record['returncode']=CHILD.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                record['status']='TIMEOUT';record['cleanup_live_pids']=stop_owned(CHILD);raise TimeoutError('Yosys mapping exceeded 600 seconds')
        outtext=(BASE/'stdout.log').read_text(errors='replace');errtext=(BASE/'stderr.log').read_text(errors='replace')
        record['stdout_sha256']=sha(BASE/'stdout.log');record['stderr_sha256']=sha(BASE/'stderr.log')
        require(record['returncode']==0,'Yosys XC7 mapping failed; see preserved stderr/stdout')
        mapped=BASE/'mapped.json';netlist=BASE/'mapped.v';stat=BASE/'stat.json'
        for q in (mapped,netlist,stat):require(q.is_file(),'Missing Yosys output '+q.name)
        design=json.loads(mapped.read_text());module=design['modules']['rk_ddr_capacity_bist'];counts={}
        for cell in module.get('cells',{}).values():counts[cell['type']]=counts.get(cell['type'],0)+1
        def cat(t):
            if t.startswith(('IBUF','OBUF','IOBUF')):return 'IO'
            if t.startswith('DSP'):return 'DSP'
            if t.startswith('RAM'):return 'RAM'
            if t.startswith('LUT'):return 'LUT'
            if t.startswith(('FD','LD')):return 'FF'
            return 'CORE_OTHER'
        categories={}
        for typ,count in counts.items():categories[cat(typ)]=categories.get(cat(typ),0)+count
        cell_inventory={'scope':'mapped six-module DDR capacity subsystem only; no full design or physical claim',
          'top':'rk_ddr_capacity_bist','cell_count':sum(counts.values()),'io_cells':categories.get('IO',0),
          'core_lut':categories.get('LUT',0),'core_ff':categories.get('FF',0),'core_dsp':categories.get('DSP',0),
          'core_ram':categories.get('RAM',0),'core_other':categories.get('CORE_OTHER',0),
          'core_total':sum(v for k,v in categories.items() if k!='IO'),
          'category_counts':categories,'cell_type_counts':dict(sorted(counts.items()))}
        inventory_path=BASE/'cell-inventory.json';inventory_path.write_text(json.dumps(cell_inventory,indent=2,sort_keys=True)+'\n')
        record.update(status='PASS_YOSYS_XC7_MAPPING_SUBSYSTEM_ONLY',cell_count=sum(counts.values()),cell_type_counts=dict(sorted(counts.items())),
          cell_categories=categories,cell_inventory_path=str(inventory_path),cell_inventory_sha256=sha(inventory_path),
          output_hashes={q.name:sha(q) for q in (mapped,netlist,stat,inventory_path)},
          output_bytes={q.name:q.stat().st_size for q in (mapped,netlist,stat,inventory_path)},tool_stdout_contains_error=bool(re.search(r'(^|\n)ERROR:',outtext+errtext)))
    except BaseException as error:
        record.update(status=('TIMEOUT' if record.get('status')=='TIMEOUT' else 'FAIL_YOSYS_XC7_MAPPING'),error=repr(error))
        if CHILD is not None and CHILD.poll() is None:record['cleanup_live_pids']=stop_owned(CHILD)
    finally:
        if CHILD is not None:
            if CHILD.poll() is None:record['cleanup_live_pids']=stop_owned(CHILD)
            record['owned_process_group_live_pids_after']=pids(CHILD.pid)
            record['owned_process_group_stopped']=not bool(record['owned_process_group_live_pids_after'])
        try:
            after={p:sha(p) for p in source_before}
            manifest=json.loads(MANIFEST.read_text());copy_after={r['copied_path']:sha(r['copied_path']) for r in manifest['sources']}
            record['source_hashes_after']=after;record['copy_hashes_after']=copy_after
            all_after={**after,**copy_after}
            for pin in [MANIFEST,SCRIPT,Path(__file__).resolve(),lint_report,YOSYS]:
                all_after[str(pin)]=sha(pin)
            record['input_hashes_after']=all_after
            record['all_frozen_inputs_unchanged']=(all_after==record['input_hashes_before'])
            if not record['all_frozen_inputs_unchanged'] and record.get('status','').startswith('PASS_'):record['status']='FAIL_SOURCE_MUTATION_AFTER_MAPPING'
        except BaseException as error:record['rehash_error']=repr(error);record['all_frozen_inputs_unchanged']=False
        try:
            cg=cgroup_dir();record['memory_peak_bytes']=(cg/'memory.peak').read_text().strip();record['memory_events']=(cg/'memory.events').read_text().strip()
        except BaseException as error:record['cgroup_error']=repr(error)
        record['elapsed_seconds']=time.monotonic()-started;record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        record.update(hardware_accessed=False,vivado_executed=False,bitstream_emitted=False)
        REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    return 0 if record.get('status')=='PASS_YOSYS_XC7_MAPPING_SUBSYSTEM_ONLY' and record.get('all_frozen_inputs_unchanged') and record.get('owned_process_group_stopped') else 1
if __name__=='__main__':raise SystemExit(main())
