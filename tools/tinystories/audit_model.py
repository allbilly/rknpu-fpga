#!/usr/bin/env python3
"""Read-only physical TinyStories audit from actual scans and complete BO bytes.

Accepts the fixed 32-position workload only after its physical producer has
completed. The separately named BOS control never qualifies full generation.
No transport, model engine, arithmetic oracle or hardware API is imported.
"""
from pathlib import Path
import argparse
import base64
import datetime
import hashlib
import json
import sys
import zlib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.interface import load_json,require
from tools.tinystories.audit_scans import commands
from tools.tinystories.check_progress import check as check_progress
from tools.tinystories.prepare import MODEL_SHA,TOKENIZER_SHA,verify

FIRST_FORWARD='one-complete-forward-position'
REPEATED_FORWARD='repeated-complete-forward-position'
FULL_MODEL='greedy32'


def physical_phase_contract(phase,memory_profile):
    require(memory_profile in ('bram','ddr'),'Unsupported raw-model memory profile')
    schedule=((FIRST_FORWARD,FULL_MODEL) if memory_profile=='bram'
              else (FIRST_FORWARD,REPEATED_FORWARD,FULL_MODEL))
    require(phase in schedule,'Unsupported physical model phase for memory profile')
    control=phase!=FULL_MODEL
    return control,1 if control else 32,schedule


def physical_phase_summaries(records,phase,memory_profile):
    """Require ordered incremental trials; every control remains a separate audit."""
    control,positions,schedule=physical_phase_contract(phase,memory_profile)
    names=[record['name'] for record in records]
    require(names==list(schedule[:len(names)]) and len(names)<=len(schedule),
            'Missing, duplicate or reordered physical model phases')
    phases={record['name']:record for record in records}
    require(phase in phases,'Missing physical workload phase')
    if not control:
        require(tuple(names)==schedule,'Incomplete physical workload phases')
    index=schedule.index(phase)
    for name in schedule[:index]:
        require(phases[name]['status']=='PASS' and phases[name]['forward_positions']==1,
                'Earlier physical BOS control has not completed')
    return phases


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def unpack(item):
    data=zlib.decompress(base64.b64decode(item['zlib_base64'],validate=True))
    require(len(data)==item['size'] and hashlib.sha256(data).hexdigest()==item['sha256'],
            'Changed original program BO')
    return data


def output_bo(item):
    data=zlib.decompress(base64.b64decode(item['output_zlib_base64'],validate=True))
    require(len(data)==item['whole_bo_bytes'] and hashlib.sha256(data).hexdigest()==item['output_sha256'],
            'Changed recorded complete output BO')
    return data


def replay(wire,prepared,catalog,calls,oracle,events,tile_data,*,memory_profile='bram'):
    """Reconstruct actual memory ownership without computing expected products."""
    require(memory_profile in ('bram','ddr'),'Unsupported raw-model memory profile')
    identities_by_base=({0:0x524b4557,256:0x524b434d} if memory_profile=='bram'
                        else {0:0x524b4144,256:0x524b4344})
    if memory_profile=='ddr':
        from tools.ddr.model_lifecycle import ddr_lifecycle
        wire=ddr_lifecycle(wire)
    buffers=prepared['candidate_buffers'];projections={p['name']:p for p in prepared['projections']}
    programs={(p['projection'],p['first_output']):p for p in catalog['programs']}
    require(len(programs)==len(catalog['programs']),'Duplicate original tile program')
    schedule=[]
    for index,call in enumerate(calls):
        tiles=[t for t in prepared['tiles'] if t['projection']==call['name']]
        require(tiles and call['first_job']==len(schedule) and call['raw_jobs']==2*len(tiles),
                'Changed projection/raw-job boundary')
        for tile_index,tile in enumerate(tiles):
            program=programs[call['name'],tile['first_output']]
            for kind in ('cmac','compaction'):
                schedule.append(dict(call=index,tile=tile,kind=kind,original=program[kind],
                    first=tile_index==0 and kind=='cmac',last=tile_index==len(tiles)-1 and kind=='compaction'))
    require(len(schedule)==len(events),'Incomplete static raw-job schedule')
    memory={};unverified=set();staged={};active=None;finished=0;weight_checks=0;input_checks=0;output_checks=0
    identities=set();stats=dict(output_bo_bytes=0,tasks=0)
    def owned(address):
        return address%64==0 and any(b['address']<=address and address+64<=b['address']+b['bytes']
                                   for b in buffers.values())
    def mem(address,size):
        require(address%64==0 and size%64==0,'Nonphysical audit span')
        require(all(address+i in memory for i in range(0,size,64)),'Missing actual initialized BO bytes')
        return b''.join(memory[address+i] for i in range(0,size,64))
    for command in wire:
        op,address,value,response=(command[k] for k in ('op','address','data','response'))
        if op in (2,4):require(response==0,'Actual write command failed')
        if op==4:
            require(active is None and owned(address),'Upload outside owned BOs or during active job')
            memory[address]=value.to_bytes(64,'little');unverified.add(address)
        elif op==3:
            require(owned(address),'Unmapped/unaligned physical read')
            data=response.to_bytes(64,'little')
            if active is None:
                require(memory.get(address)==data,'Uploaded/delta BO bytes not verified on wire')
                unverified.discard(address)
            else:
                require(address not in active['reads'],'Repeated owned output line')
                active['reads'][address]=data
        elif op==2:
            require(address in {12,16,20,24,268,272,276,280},'Unmodeled CSR write')
            base=256 if address>=256 else 0;offset=address-base
            if offset in (16,20,24):
                require(active is None and (not staged or staged['base']==base) and offset not in staged,
                        'Descriptor namespace/ownership overlap')
                staged['base']=base;staged[offset]=value
            elif value==1:
                require(active is None and set(staged)=={'base',16,20,24} and not unverified,
                        'Incomplete submit or unverified uploaded bytes')
                require(finished<len(schedule),'Extra raw job beyond the original workload')
                plan=schedule[finished];job=plan['original'];call=oracle[plan['call']]
                projection=projections[call['name']]
                require((base,staged[16],staged[20],staged[24])==
                        (256 if job['profile']=='cmac' else 0,job['address'],job['amount'],finished+1),
                        'Actual raw descriptor differs from original final writer')
                command_bo=unpack(job['command_bo']);task_bo=unpack(job['task_bo'])
                require(mem(staged[16],buffers['command']['bytes'])==command_bo,
                        'Actual full command BO differs from original encoder')
                require(len(task_bo)<=buffers['tasks']['bytes'] and
                        mem(buffers['tasks']['address'],buffers['tasks']['bytes'])==
                        task_bo+bytes(buffers['tasks']['bytes']-len(task_bo)),
                        'Actual complete task BO differs from original writer')
                if plan['first']:
                    data=mem(buffers['input']['address'],buffers['input']['bytes']);logical=2*projection['inputs']
                    require(hashlib.sha256(data[:logical]).hexdigest()==call['input_fp16_sha256'] and
                            not any(data[logical:]),'Actual input bytes or physical padding differ')
                    input_checks+=1
                if finished==0:
                    require({'ew','cmac'}<=identities,'Missing both actual namespace identities/ABIs')
                    for tile in prepared['tiles']:
                        require(mem(tile['address'],tile['bytes'])==tile_data[tile['file']],
                                'Actual initial resident weight tile differs')
                if plan['kind']=='cmac':
                    tile=plan['tile']
                    require(mem(tile['address'],tile['bytes'])==tile_data[tile['file']],
                            'Actual weight changed before its CMAC use')
                    weight_checks+=1
                else:
                    unity=mem(buffers['unity']['address'],buffers['unity']['bytes'])
                    require(unity==b'\x00\x3c'*16+bytes(len(unity)-32),'Actual EW unity BO differs')
                active=dict(base=base,tag=staged[24],reads={},regs={},plan=plan);staged={}
            elif value==2:
                require(active is not None and active['base']==base,'Wrong ACK namespace/ownership')
                event=events[finished];plan=active['plan'];job=plan['original'];data=output_bo(event)
                require(event['profile']==job['profile'] and event['tag']==active['tag'] and
                        event['tasks']==job['task_count'] and event['ack_after_readback'] is True,
                        'Wrong captured completion/task/ACK record')
                require(active['regs'].get(base+28)==event['tag'] and
                        active['regs'].get(base+32)==event['tasks'] and active['regs'].get(base+36)==0,
                        'Actual wire completion differs')
                name='native_output' if plan['kind']=='cmac' else 'linear_output'
                output=buffers[name]['address']
                require(event['output']==name and len(data)==buffers[name]['bytes']==4096 and
                        active['reads']=={output+i:data[i:i+64] for i in range(0,len(data),64)},
                        'Actual complete output BO differs before ACK')
                allowed=[[0,32],[64,96]] if name=='native_output' else [
                    [2*plan['tile']['first_output'],2*plan['tile']['first_output']+64]]
                require(event['allowed_ranges']==allowed,'Changed compiled destination extents')
                before=mem(output,len(data))
                require(all(old==new or any(lo<=i<hi for lo,hi in allowed)
                            for i,(old,new) in enumerate(zip(before,data))),
                        'Actual output guard changed outside compiled destination')
                if plan['last']:
                    call=oracle[plan['call']];logical=2*projections[call['name']]['outputs']
                    padded=((projections[call['name']]['outputs']+31)//32*32)*2
                    require(hashlib.sha256(data[:logical]).hexdigest()==call['output_fp16_sha256'] and
                            not any(data[logical:padded]),'Actual contiguous dense output/padding differs')
                    output_checks+=1
                memory.update(active['reads']);stats['output_bo_bytes']+=len(data);stats['tasks']+=event['tasks']
                finished+=1;active=None
            else:raise ValueError('Unmodeled raw doorbell value')
        elif op==1:
            base=256 if address>=256 else 0;offset=address-base
            require(base in (0,256) and offset in (0,4,8,28,32,36),'Unmodeled CSR read')
            if offset==0:
                require(response==identities_by_base[base],'Wrong actual namespace identity')
                identities.add('cmac-id' if base else 'ew-id')
            if offset==4:
                require(response==0x10000 and ('cmac-id' if base else 'ew-id') in identities,
                        'Wrong actual namespace ABI')
                identities.add('cmac' if base else 'ew')
            if active is not None:active['regs'][address]=response
    require(active is None and not staged and not unverified and finished==len(events) and
            input_checks==output_checks==len(calls),'Incomplete actual job/memory ownership')
    return dict(raw_jobs=finished,actual_projection_pairs=input_checks,weight_tiles_checked_before_use=weight_checks,
                **stats)


def audit(run,package,catalog_path,reference,phase,*,memory_profile='bram'):
    control,positions,_=physical_phase_contract(phase,memory_profile)
    run,package,catalog_path,reference=map(lambda p:Path(p).resolve(),(run,package,catalog_path,reference))
    physical=run/'physical-tests';parent=load_json(physical/'report.json');review=load_json(run/'image-review.json')
    require(parent['status'] in (('RUNNING_AUTHORIZED_VOLATILE_USER2_TEST',
            'PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT') if control else
            ('PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT',)),
            'Physical producer has not completed the required scope')
    if not control:
        require(parent['owned_worker_exit']==0 and parent['owned_bridge_exit']==0 and
                parent['owned_hw_server_exit'] in (0,-15),'Physical worker/bridge cleanup failed')
    expected_review=('PASS_REVIEWED_TINYSTORIES_FULL512_DUAL_IMAGE' if memory_profile=='bram'
                     else 'PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE')
    expected_top='ypcb_tinystories_top' if memory_profile=='bram' else 'ypcb_ddr_dual_top'
    require(review['status']==expected_review and
            parent['image_review_sha256']==sha(run/'image-review.json'),'Wrong or changed image review')
    require(review['part']==parent['part']=='xc7k480tffg1156-2' and review['top']==expected_top and
            review['usr_access']==review['source_sha256'][:8] and review['programming_scope']=='volatile-sram',
            'Wrong physical image/profile')
    if memory_profile=='ddr':
        require(parent.get('memory_profile')==review.get('memory_profile')=='ddr' and
                parent.get('selected_physical_channel')==review.get('selected_physical_channel')==1 and
                review.get('product_dsps')==512 and review.get('total_dsps')==516 and
                review.get('bram_blocks')==0,'Wrong physical DDR source/profile census')
    for name,expected in review['bound_files'].items():require(sha(name)==expected,'Changed reviewed source '+name)
    require(sha(review['bitstream']['path'])==review['bitstream']['sha256']==parent['bitstream_sha256'],
            'Changed exact physical bitstream')
    require(parent['flash_written'] is False and len(parent['loads'])==1,'Wrong programming scope')
    load_path=physical/'load-1/load.json';load=load_json(load_path)
    require(sha(load_path)==parent['loads'][0]['receipt_sha256'] and load['status']=='PASS' and
            load['flash_written'] is False,'Changed or unsuccessful volatile load')
    require(load['bitstream_sha256']==parent['bitstream_sha256'] and
            load['source_sha256']==review['source_sha256'] and
            load['image_review_sha256']==parent['image_review_sha256'] and
            parent['hardware_programmed'] is True and load['hardware_programmed'] is True,
            'Load/image/source binding differs')
    expected=dict(DNA_PORT='004E544714C705C',IDCODE_BEFORE='23751093',IDCODE_AFTER='23751093',
        INIT_COMPLETE='1',DONE='1',USR_ACCESS=review['usr_access'],TCK_HZ='3000000',CLEANUP='1',PASS='1',
        TARGET=parent['target'])
    require(all(load['native'].get(k)==v for k,v in expected.items()),'Wrong actual target/configuration')
    phases=physical_phase_summaries(parent['tests'],phase,memory_profile)
    if not control:
        for name,expected_sha in parent['artifacts'].items():
            require(sha(physical/name)==expected_sha,'Changed physical artifact '+name)
    summary=phases[phase];worker=physical/phase/'jobs';child=load_json(worker/'report.json')
    require(summary['status']=='PASS' and summary['forward_positions']==positions and
            summary['report_sha256']==sha(worker/'report.json'),'Changed/incomplete physical phase')
    require(child['status']=='PASS_PHYSICAL_HYBRID_MODEL_EXECUTION_REQUIRES_INDEPENDENT_AUDIT' and
            child['backend']=='jtag' and child['hardware_accessed'] is True and child['flash_written'] is False and
            child['cpu_dense_fallback'] is False and child['bridge_quit_ack'] is True,'Wrong/incomplete worker')
    require(child.get('memory_profile','bram')==memory_profile,'Worker memory profile differs from physical audit')
    require(child['model_sha256']==MODEL_SHA and child['tokenizer_sha256']==TOKENIZER_SHA and
            child['completed_positions']==positions and child['completed_projections']==positions*36 and
            child['raw_jobs']==positions*232 and child['raw_completed_tasks']==positions*348 and
            child['steps']==positions and child['prompt']==('' if control else 'Once upon a time'),
            'Changed model workload/coverage')
    for name,expected_sha in child['artifacts'].items():require(sha(worker/name)==expected_sha,'Changed worker artifact '+name)
    prepared=verify(package);catalog=load_json(catalog_path)
    require(child['package_report_sha256']==catalog['source_package_report_sha256']==sha(package/'report.json') and
            child['catalog_sha256']==review['catalog_sha256']==sha(catalog_path) and
            catalog['status']=='PREPARED_ALL_TINYSTORIES_RAW_PROGRAMS_ONLY','Changed original raw-program inputs')
    reference_report=load_json(reference/'report.json')
    require(reference_report['status']=='PASS_CPU_FULL_TINYSTORIES_DONOR_POLICY_REFERENCE_ONLY' and
            reference_report['hardware_accessed'] is False,'Wrong numerical reference')
    for name in ('donor-dense-calls.json','donor-logits.bin','donor-result.json'):
        require(sha(reference/name)==reference_report['artifacts'][name],'Changed donor reference artifact')
    oracle=load_json(reference/'donor-dense-calls.json')[:positions*36]
    calls=load_json(worker/'dense-calls.json');events=load_json(worker/'raw-jobs.json')
    require(len(calls)==positions*36 and len(events)==positions*232 and
            all(all(a[k]==b[k] for k in ('name','input_fp16_sha256','output_fp16_sha256'))
                for a,b in zip(calls,oracle)),'Dense byte receipts differ from independent oracle')
    require((worker/'logits.bin').read_bytes()==(reference/'donor-logits.bin').read_bytes()[:positions*2048],
            'Complete actual logits differ')
    gold=(dict(prompt_tokens=[1],generated_tokens=[403],input_tokens=[1],text='Once',forward_positions=1,dense_calls=36)
          if control else load_json(reference/'donor-result.json'))
    require(all(child['result'][k]==v for k,v in gold.items()),'Actual generated tokens/text differ')
    progress=None if control else check_progress(worker,reference)
    stats={};tile_data={t['file']:(package/t['file']).read_bytes() for t in prepared['tiles']}
    result=replay(commands(worker/'native-scans.jsonl',stats),prepared,catalog,calls,oracle,events,tile_data,
                  memory_profile=memory_profile)
    require(result['raw_jobs']==positions*232 and result['tasks']==positions*348,'Incomplete wire job/task coverage')
    accepted_status=('PASS_INDEPENDENT_PHYSICAL_TINYSTORIES_BOS_CONTROL_ONLY' if control else
                     'PASS_INDEPENDENT_PHYSICAL_TINYSTORIES_32_POSITION_RAW_WIRE_MODEL_AUDIT')
    if memory_profile=='ddr':
        accepted_status=('PASS_INDEPENDENT_PHYSICAL_DDR_TINYSTORIES_BOS_CONTROL_ONLY' if control else
                         'PASS_INDEPENDENT_PHYSICAL_DDR_TINYSTORIES_32_POSITION_RAW_WIRE_MODEL_AUDIT')
        if phase==REPEATED_FORWARD:
            accepted_status='PASS_INDEPENDENT_PHYSICAL_DDR_TINYSTORIES_REPEATED_BOS_CONTROL_ONLY'
    return dict(status=accepted_status,memory_profile=memory_profile,
        full32_positions_accepted=not control,phase=phase,positions=positions,wire=stats,**result,
        logits_sha256=sha(worker/'logits.bin'),text=gold['text'],generated_tokens=gold['generated_tokens'],
        source_sha256=review['source_sha256'],bitstream_sha256=review['bitstream']['sha256'],
        image_review_sha256=sha(run/'image-review.json'),physical_report_sha256=sha(physical/'report.json'),
        worker_report_sha256=sha(worker/'report.json'),progress=progress,hardware_accessed=False,
        flash_written=False,learned_dense_cpu_fallback=False,
        scope=('Recorded physical raw-wire/whole-BO replay only; CPU host operators remain explicit; DDR/PCIe/RK equivalence unqualified'
               if memory_profile=='bram' else 'Recorded physical DDR raw-wire/whole-BO model replay only; CPU host operators explicit; full DDR capacity/ECC/recovery, PCIe and RK equivalence unqualified'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','package','catalog','reference','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=(FIRST_FORWARD,REPEATED_FORWARD,FULL_MODEL),default=FULL_MODEL)
    parser.add_argument('--memory-profile',choices=('bram','ddr'),default='bram')
    args=parser.parse_args();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh workspace audit receipt required')
    record=dict(status='FAIL',memory_profile=args.memory_profile,phase=args.phase,
                full32_positions_accepted=False,hardware_accessed=False)
    try:record=audit(args.run,args.package,args.catalog,args.reference,args.phase,memory_profile=args.memory_profile)
    except BaseException as error:record['error']=repr(error);raise
    finally:
        record['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        record['auditor_sha256']=sha(__file__)
        record['scan_decoder_sha256']=sha(ROOT/'tools/tinystories/audit_scans.py')
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'],record['positions'],record['raw_jobs'])


if __name__=='__main__':main()
