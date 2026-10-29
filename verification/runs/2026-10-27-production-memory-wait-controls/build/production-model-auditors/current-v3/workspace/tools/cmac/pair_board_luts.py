#!/usr/bin/env python3
"""Reversible same-fanin LUT6_2 preparation, never packed/physical acceptance."""
from collections import Counter, defaultdict
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from analyze_shared_kernel_cones import digest
from export_board_netlist import structural_board_verilog
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases
from prepare_shared_board import PRIVATE, SHARED, physical_counts

BENCH='rk_lut_pair_four_state'


def implementation_module_aliases(design):
    """Explicitly alias RTLIL-private module names before Verilog export.

    As with hardware_instance_aliases, an escaped Verilog '$paramod...' is
    read back as the public identifier '\\$paramod...', not the original
    private RTLIL identifier. Record a bijection, update every reference,
    and reverse it literally. The circuit verifier does not normalize names.
    """
    names=sorted(name for name in design['modules']
                 if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_$]*',name))
    aliases={name:'rk_lut_pair_module_'+str(i) for i,name in enumerate(names)}
    assert not set(aliases.values()) & set(design['modules']), 'Module alias collision'
    assert len(set(aliases.values()))==len(aliases)
    renamed=deepcopy(design)
    renamed['modules']={aliases.get(name,name):body for name,body in renamed['modules'].items()}
    for body in renamed['modules'].values():
        for cell in body.get('cells',{}).values():
            cell['type']=aliases.get(cell['type'],cell['type'])
    restored=deepcopy(renamed); inverse={alias:name for name,alias in aliases.items()}
    restored['modules']={inverse.get(name,name):body for name,body in restored['modules'].items()}
    for body in restored['modules'].values():
        for cell in body.get('cells',{}).values():
            cell['type']=inverse.get(cell['type'],cell['type'])
    assert restored==design, 'Module aliasing changed circuit data'
    return renamed,aliases


def lut_inputs(cell):
    assert re.fullmatch('LUT[1-5]',cell['type'])
    size=int(cell['type'][-1]); pins=['I'+str(i) for i in range(size)]
    assert set(cell['connections'])==set(pins+['O'])
    assert cell['port_directions']=={**{p:'input' for p in pins},'O':'output'}
    assert all(len(bits)==1 for bits in cell['connections'].values())
    assert set(cell['parameters'])=={'INIT'}
    init=cell['parameters']['INIT']
    assert re.fullmatch('[01]+',init) and len(init)==2**size, 'Nonbinary or wrong-width LUT INIT'
    inputs=[cell['connections'][p][0] for p in pins]
    assert all(type(bit) is int or bit in ('0','1') for bit in inputs), 'Unknown LUT input binding'
    output=cell['connections']['O'][0]
    assert type(output) is int and output not in inputs, 'Self-fed LUT or constant output'
    return inputs


def spec(cell,fanins):
    inputs=lut_inputs(cell)
    assert sorted({bit for bit in inputs if type(bit) is int})==list(fanins)
    return dict(kind=cell['type'],init=cell['parameters']['INIT'],
        pins=[fanins.index(bit) if type(bit) is int else bit for bit in inputs])


def value(function,assignment):
    index=sum((assignment[pin] if type(pin) is int else int(pin))<<i
              for i,pin in enumerate(function['pins']))
    return int(function['init'][-index-1])


def paired_cell(a,b,fanins):
    assert len(fanins)<=5 and len(set(fanins))==len(fanins)
    first,second=spec(a,fanins),spec(b,fanins)
    low=high=0
    for index in range(32):
        assignment=[(index>>i)&1 for i in range(len(fanins))]
        low|=value(first,assignment)<<index
        high|=value(second,assignment)<<index
    connections={**{'I'+str(i):[fanins[i] if i<len(fanins) else '0'] for i in range(5)},
        'I5':['1'],'O5':list(a['connections']['O']),'O6':list(b['connections']['O'])}
    return dict(hide_name=0,type='LUT6_2',parameters={'INIT':format((high<<32)|low,'064b')},
        attributes={},port_directions={**{'I'+str(i):'input' for i in range(6)},'O5':'output','O6':'output'},
        connections=connections)


def pair(design,implementations):
    assert 'LUT6_2' in design['modules'], 'Missing actual primitive definition'
    definition=design['modules']['LUT6_2']
    assert int(definition['attributes'].get('blackbox','0'),2)==1
    assert {p:(v['direction'],len(v['bits'])) for p,v in definition['ports'].items()}=={
        **{'I'+str(i):('input',1) for i in range(6)},'O5':('output',1),'O6':('output',1)}
    candidate=deepcopy(design); certificate={}; classes={}
    for module in sorted(implementations):
        original=design['modules'][module]
        primary={b for p in original['ports'].values() if p['direction']=='input' for b in p['bits']}
        groups=defaultdict(list); skipped=0
        for name,cell in sorted(original['cells'].items()):
            if not re.fullmatch('LUT[1-5]',cell['type']): continue
            inputs=lut_inputs(cell)
            assert cell['connections']['O'][0] not in primary, 'LUT drives primary input'
            wires=[b for b in inputs if type(b) is int]
            # Correlated repeated unknown inputs can have order-sensitive X
            # propagation. Preserve such cells without pairing or claiming a proof.
            if len(wires)!=len(set(wires)):
                skipped+=1; continue
            groups[tuple(sorted(wires))].append(name)
        records=[]; cells=candidate['modules'][module]['cells']
        for fanins,names in sorted(groups.items()):
            for pos in range(0,len(names)-1,2):
                first,second=names[pos:pos+2]
                a,b=original['cells'][first],original['cells'][second]
                assert a['connections']['O']!=b['connections']['O'], 'Multiple LUT output drivers'
                name='rk_lut_pair_'+str(len(records))
                assert name not in original['cells'], 'Pair instance alias collision'
                cell=paired_cell(a,b,list(fanins)); cells[name]=cell
                del cells[first]; del cells[second]
                function=dict(fanins=len(fanins),first=spec(a,list(fanins)),second=spec(b,list(fanins)),init=cell['parameters']['INIT'])
                key=json.dumps(function,sort_keys=True,separators=(',',':'))
                classes[key]=function
                records.append(dict(name=name,first=first,second=second,fanins=list(fanins),function_key=key))
        certificate[module]=dict(pairs=records,unpaired_repeated_wire_luts=skipped)
    assert classes, 'No eligible pairs'
    verify(design,candidate,certificate,classes)
    return candidate,certificate,[classes[k] for k in sorted(classes)]


def verify(original,candidate,certificate,classes):
    restored=deepcopy(candidate); actual_classes={}
    for module,record in certificate.items():
        old=original['modules'][module]['cells']; new=restored['modules'][module]['cells']; used=set()
        skipped=0
        for cell in old.values():
            if not re.fullmatch('LUT[1-5]',cell['type']): continue
            wires=[bit for bit in lut_inputs(cell) if type(bit) is int]
            skipped+=len(wires)!=len(set(wires))
        assert record['unpaired_repeated_wire_luts']==skipped, 'Changed correlated-input count'
        for item in record['pairs']:
            name,first,second,fanins=[item[k] for k in ('name','first','second','fanins')]
            assert first!=second and not {first,second}&used and name not in old
            used.update((first,second))
            a,b=old[first],old[second]
            assert fanins==sorted({v for v in lut_inputs(a) if type(v) is int})
            assert fanins==sorted({v for v in lut_inputs(b) if type(v) is int})
            assert len([v for v in lut_inputs(a) if type(v) is int])==len(fanins)
            assert len([v for v in lut_inputs(b) if type(v) is int])==len(fanins)
            cell=new.pop(name)
            assert cell==paired_cell(a,b,fanins), 'Paired primitive truth table, pins or outputs changed'
            function=dict(fanins=len(fanins),first=spec(a,fanins),second=spec(b,fanins),init=cell['parameters']['INIT'])
            key=json.dumps(function,sort_keys=True,separators=(',',':'))
            assert item['function_key']==key
            actual_classes[key]=function
            assert first not in new and second not in new, 'Old functions still present'
            new[first]=deepcopy(a); new[second]=deepcopy(b)
    assert actual_classes==classes, 'Function proof domain does not cover every actual pair'
    assert restored==original, 'Nonpair hardware, boundary, parameter or metadata changed'


def four_state_bench(classes,negative=False):
    assert classes and all(0<=c['fanins']<=5 for c in classes)
    lines=['`timescale 1ns/1ps','module '+BENCH+';',
        '  reg ['+str(len(classes)-1)+':0] done=0;', '  integer comparisons=0;']
    for i,function in enumerate(classes):
        size=function['fanins']; base='c'+str(i)
        lines+=['  reg [4:0] '+base+'_inputs=0;', '  wire '+base+'_a, '+base+'_b, '+base+'_o5, '+base+'_o6;']
        for label,which in (('a','first'),('b','second')):
            f=function[which]
            pins=['.I'+str(j)+'('+base+'_inputs['+str(p)+']' if type(p) is int else '.I'+str(j)+"(1'b"+p for j,p in enumerate(f['pins'])]
            lines.append('  '+f['kind']+' #(.INIT('+str(len(f['init']))+"'b"+f['init']+')) '+base+'_'+label+'_ref('+', '.join(p+')' for p in pins)+', .O('+base+'_'+label+'));')
        init=function['init']
        if negative and i==0: init=format(int(init,2)^1,'064b')
        bindings=['.I'+str(p)+'('+base+'_inputs['+str(p)+'])' if p<size else '.I'+str(p)+"(1'b0)" for p in range(5)]
        lines.append("  LUT6_2 #(.INIT(64'b"+init+')) '+base+'_dut('+', '.join(bindings)+", .I5(1'b1), .O5("+base+'_o5), .O6('+base+'_o6));')
        lines+=['  initial begin: '+base+'_test', '    integer pattern, pin;',
            '    for(pattern=0;pattern<'+str(4**size)+';pattern=pattern+1) begin',
            '      for(pin=0;pin<'+str(size)+';pin=pin+1)',
            '        case((pattern>>(2*pin))&3)',
            "          0: "+base+"_inputs[pin]=1'b0;", "          1: "+base+"_inputs[pin]=1'b1;",
            "          2: "+base+"_inputs[pin]=1'bx;", "          3: "+base+"_inputs[pin]=1'bz;", '        endcase',
            '      #1;', '      if('+base+'_o5 !== '+base+'_a || '+base+'_o6 !== '+base+'_b)',
            '        $fatal(1,"LUT_PAIR_MISMATCH class='+str(i)+' pattern=%0d",pattern);',
            '      comparisons=comparisons+2;', '    end', '    done['+str(i)+']=1;', '  end']
    expected=2*sum(4**c['fanins'] for c in classes)
    lines+=['  initial begin', '    wait(&done);',
        '    if(comparisons!='+str(expected)+') $fatal(1,"comparison count");',
        '    $display("PASS LUT_PAIR_FOUR_STATE classes='+str(len(classes))+' comparisons=%0d",comparisons);',
        '    $finish;', '  end', '  initial begin #2048; $fatal(1,"LUT_PAIR_WATCHDOG"); end', 'endmodule']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--mapping-report',type=Path)
    group.add_argument('--shared-report',type=Path)
    args=parser.parse_args(); parent_path=(args.shared_report or args.mapping_report).resolve()
    assert parent_path.is_relative_to(ROOT)
    parent=json.loads(parent_path.read_text())
    assert parent['status']==('PREPARED_SHARED_CONE_BOARD_NETLIST_ONLY' if args.shared_report else 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY')
    assert (parent['channels'],parent['kernels'],parent['parallel_products'])==(32,16,512)
    assert all(c['status']=='PASS' and c['returncode']==0 for c in parent['commands'])
    for name,sha in parent['source']['files'].items(): assert digest(ROOT/name)==sha, ('Stale parent source',name)
    netlist=parent_path.parent/('shared_hierarchy.json' if args.shared_report else 'mapped_hierarchy.json')
    assert digest(netlist)==parent['artifacts']['files'][str(netlist.relative_to(ROOT))]
    out=ROOT/f'build/rknpu-paired-board-prepare/{time.time_ns()}'; out.mkdir(parents=True,exist_ok=False)
    used=[Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools')]
    tracked=[Path(__file__).resolve(),parent_path,netlist,*used]
    report=dict(status='RUNNING',stage='load',started_utc=timestamp(),supervisor_pid=os.getpid(),
        source=fingerprint(tracked),parent_report=str(parent_path.relative_to(ROOT)),parent_source_sha256=parent['source']['sha256'],
        commands=[],python_version=sys.version,seed='none; exhaustive 0/1/X/Z function-class enumeration',
        channels=32,kernels=16,parallel_products=512,
        numerical_netlist_acceptance=False,physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False,
        scope='Same-variable-fanin LUT1..5 pairs replaced with one LUT6_2 using I5=1 and two exact INIT halves. Literal restoration and actual unchanged Yosys-model 0/1/X/Z proof required for every function class, plus real export and hierarchy checks. Not a full raw-board numeric/hold/reset/fault suite, vendor UNISIM/GSR, packed utilization, timing/electrical/DRC, bitstream, FPGA or RK acceptance.')
    def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(argv,name,negative=False):
        step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                    step['pid']=proc.pid; save()
                    try: code=proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode']=code; text=(ROOT/step['log']).read_text()
            if negative:
                assert code!=0 and re.search(r'LUT_PAIR_MISMATCH class=0 pattern=0(?:\s|$)',text) and 'PASS ' not in text,text[-3000:]
            else: assert code==0 and 'ERROR:' not in text,text[-3000:]
            step['status']='PASS'; return text
        except BaseException:
            step['status']='FAIL'; raise
        finally: step['seconds']=round(time.monotonic()-started,3); save()
    def terminate(signum,_frame): raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,terminate); save()
    try:
        for path in tracked:
            if path==netlist: continue
            dest=out/'snapshot'/path.relative_to(ROOT); dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(path.read_bytes())
        original=json.loads(netlist.read_text())
        tops=[n for n,m in original['modules'].items() if int(m.get('attributes',{}).get('top','0'),2)]
        assert len(tops)==1; top=tops[0]
        implementations={top,PRIVATE,SHARED} if args.shared_report else {top,parent['preserved_kernel']}
        report['stage']='pair_and_verify'; save()
        candidate,certificate,classes=pair(original,implementations)
        before=physical_counts(original['modules'],top,implementations); after=physical_counts(candidate['modules'],top,implementations)
        assert dict(before)==parent['cells_after' if args.shared_report else 'cells']
        assert after['LUT6_2']>before['LUT6_2']
        assert before['LUT6_2']==0
        assert sum(before.values())-sum(after.values())==after['LUT6_2']
        report.update(circuit_pair_verified=True,cells_before=dict(before),cells_after=dict(after),physical_lut_pairs=after['LUT6_2'],
            lut_count=sum(v for k,v in after.items() if k.startswith('LUT')),unique_function_classes=len(classes),
            expected_four_state_comparisons=2*sum(4**c['fanins'] for c in classes),stage='four_state')
        save()
        certificate_path=out/'pair_certificate.json'; certificate_path.write_text(json.dumps(certificate,indent=2)+'\n')
        classes_path=out/'function_classes.json'; classes_path.write_text(json.dumps(classes,indent=2)+'\n')
        candidate_path=out/'paired_hierarchy.json'; candidate_path.write_text(json.dumps(candidate)+'\n')
        report['tool_version']=run(['yosys','-V'],'yosys_version').strip(); assert report['tool_version']==parent['tool_version']
        report['iverilog_version']=run(['iverilog','-V'],'iverilog_version').splitlines()[0]
        report['vvp_version']=run(['vvp','-V'],'vvp_version').splitlines()[0]
        datadir=Path(run(['yosys-config','--datdir'],'datadir').strip())
        installed=datadir/'xilinx/cells_sim.v'; frozen=out/'xilinx_functional_models.v'; frozen.write_bytes(installed.read_bytes())
        report['primitive_model_original']=dict(path=str(installed),sha256=digest(installed),frozen=str(frozen.relative_to(ROOT)))
        generated=[candidate_path,certificate_path,classes_path,frozen]
        for label,negative in (('negative',True),('actual',False)):
            bench=out/(label+'.sv'); bench.write_text(four_state_bench(classes,negative)); executable=out/(label+'.vvp')
            inputs=[candidate_path,certificate_path,classes_path,frozen,bench]
            report.setdefault('function_class_inputs',{})[label]=fingerprint(inputs)
            assert digest(frozen)==report['primitive_model_original']['sha256'], 'Changed frozen primitive model'
            save()
            run(['iverilog','-g2012','-s',BENCH,'-o',executable,frozen,bench],label+'_compile')
            assert fingerprint(inputs)==report['function_class_inputs'][label], 'Function-class inputs changed during compile'
            report.setdefault('function_class_executables',{})[label]=fingerprint([executable]); save()
            result=run(['vvp',executable],label+'_test',negative)
            assert fingerprint(inputs)==report['function_class_inputs'][label], 'Function-class inputs changed during simulation'
            assert fingerprint([executable])==report['function_class_executables'][label], 'Changed compiled function-class executable'
            if not negative:
                expected='PASS LUT_PAIR_FOUR_STATE classes='+str(len(classes))+' comparisons='+str(report['expected_four_state_comparisons'])
                assert [line for line in result.splitlines() if line.startswith('PASS ')]==[expected]
                report['four_state_function_class_result']=expected
            generated.extend((bench,executable))
        report['stage']='export'; save()
        implementation=dict(candidate,modules={n:candidate['modules'][n] for n in sorted(implementations)})
        module_export,module_aliases=implementation_module_aliases(implementation)
        module_alias_path=out/'module_name_aliases.json'
        module_alias_path.write_text(json.dumps(module_aliases,indent=2)+'\n')
        exported,aliases=hardware_instance_aliases(module_export)
        alias_path=out/'hardware_instance_aliases.json'; alias_path.write_text(json.dumps(aliases,indent=2)+'\n')
        report['module_name_aliasing']='Explicit reversible module bijection and all cell-type references; no verifier name normalization'
        save()
        sv=out/'paired_board.v'; sv.write_text(structural_board_verilog(exported))
        roundtrip=out/'export_roundtrip.json'; script=out/'export.ys'
        script.write_text('read_verilog -sv '+json.dumps(str(sv))+';\nwrite_json '+json.dumps(str(roundtrip))+';\n')
        run(['yosys','-Q','-T','-s',script],'export')
        assert circuit_signature(json.loads(roundtrip.read_text()))==circuit_signature(exported),'Export changed circuit'
        report['export_circuit_identity']='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        check=out/'check.ys'; check.write_text('read_verilog -lib +/xilinx/cells_sim.v;\nread_verilog -sv '+json.dumps(str(sv))+';\nhierarchy -check -top '+module_aliases.get(top,top)+';\ncheck -assert;\nstat -tech xilinx;\n')
        report['stage']='hierarchy'; save(); run(['yosys','-Q','-T','-s',check],'elaborate_check')
        verify(original,json.loads(candidate_path.read_text()),certificate,{json.dumps(c,sort_keys=True,separators=(',',':')):c for c in classes})
        assert fingerprint(tracked)==report['source'],'Inputs changed during preparation'
        assert digest(installed)==report['primitive_model_original']['sha256']
        for manifest in [*report['function_class_inputs'].values(),*report['function_class_executables'].values()]:
            assert fingerprint([ROOT/name for name in manifest['files']])==manifest, 'Proof artifacts changed during preparation'
        generated.extend((module_alias_path,alias_path,sv,roundtrip,script,check))
        report.update(status='PREPARED_LUT6_2_BOARD_CANDIDATE_ONLY',stage='complete',artifacts=fingerprint(generated+[ROOT/c['log'] for c in report['commands']]))
    except BaseException as exc:
        report.update(status='FAIL',reason=str(exc) or repr(exc)); raise
    finally: report['finished_utc']=timestamp(); save(); print(out/'report.json')
    print(report['status'],report['physical_lut_pairs'],report['lut_count'])


if __name__=='__main__': main()
