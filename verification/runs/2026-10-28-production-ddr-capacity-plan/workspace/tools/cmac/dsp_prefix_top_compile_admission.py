"""Two exact top-generation notices, with actual INIT=X and alias provenance."""
from collections import Counter
import json
from pathlib import Path
import re

from evidence import ROOT, fingerprint
import dsp_prefix_compile_admission as kernel
import test_dsp_prefix_fdce_startup as startup

ALIAS = '$techmap215377$abc$213134$auto$blifparse.cc:557:parse_blif$213141.A'


def admit(top_path, fdce_verilator_path, fdce_iverilog_path, archive_path):
    report = kernel.verify_report(top_path, 'FAIL')
    assert report['stage']=='top_generation' and report['commands'][-1]['returncode']==0
    assert report['error']=="AssertionError('New, changed or duplicated follow-up compiler diagnostic')"
    archive=json.loads(archive_path.read_text())
    assert archive['status']=='ARCHIVED_ACTUAL_REUSED_PREFIX_MAPPED_TOP_GENERATION_DIAGNOSTIC_FAILURE'
    assert archive['report']==str(top_path.relative_to(ROOT))
    assert all(fingerprint([ROOT/name for name in manifest['files']])==manifest for manifest in
        (report['compiler_admission']['source'],report['compiler_admission']['compiled_products']))
    paths={name:ROOT/path for name,path in report['parent_reports'].items()}
    certificate, admitted=kernel.admit(*(paths[name] for name in
        ('compile','inventory','cone','proof','verilator','iverilog','archive')))
    assert certificate==report['compiler_admission']
    for path,simulator in ((fdce_verilator_path,'verilator'),(fdce_iverilog_path,'iverilog')):
        control=kernel.verify_report(path,'PASS_ISOLATED_ACTUAL_PREFIX_FDCE_STARTUP_RESET_FIXTURES_ONLY')
        assert control['simulator']==simulator and control['compile_report']==str(paths['compile'].relative_to(ROOT))
        assert control['model_sha256']==kernel.MODEL_SHA
        assert control['actual_array_fdce_count']==742 and control['actual_array_fdce_init']=='x'
        assert control['checks']==129 and control['fdce_startup_reset_fixture_acceptance'] is True
        for label,negative in (('negative_test',True),('positive_test',False)):
            steps=[step for step in control['commands'] if Path(step['log']).stem==label]
            assert len(steps)==1 and steps[0]['status']=='PASS'
            startup.validate_result((ROOT/steps[0]['log']).read_text(),steps[0]['returncode'],negative)
    old=paths['compile'].parent
    model,netlist,part,bench=[old/name for name in ('xilinx_functional_models.v','mapped_partition.v',
        'actual_partition.json',kernel.runner.BENCH+'.sv')]
    assert bench.read_text()==kernel.runner.mapped_bench(kernel.runner.SOURCE_BENCH.read_text())
    assert '#200; // Functional-model startup' in bench.read_text()
    assert '$readmemh(path,vectors,0,count-1);reset_all();' in bench.read_text()
    raw=json.loads(part.read_text());body=raw['modules'][kernel.runner.CMAC]
    flops=[cell for cell in body['cells'].values() if cell['type'].startswith('FD')]
    assert len(flops)==742 and all(cell['type']=='FDCE' and cell['parameters']=={'INIT':'x'} for cell in flops)
    assert model.read_text().splitlines()[691].strip()=='initial Q <= INIT;'
    invalid=body['netnames']['invalid']['bits'];alias=body['netnames'][ALIAS]['bits']
    assert len(invalid)==16 and len(alias)==6 and alias[:2]==[invalid[8],invalid[6]]
    lines=netlist.read_text().splitlines()
    assert lines[776].strip()=='wire [5:0] \\'+ALIAS+' ;'
    for bit,index in ((0,8),(1,6)):
        occurrences=[line.strip() for line in lines if re.search(re.escape('\\'+ALIAS)+r'\s+\['+str(bit)+r'\]',line)]
        assert occurrences==[f'assign \\{ALIAS} [{bit}] = invalid[{index}];'], 'Alias bit is read by real hardware'
        wire=invalid[index]
        drivers=[(name,pin) for name,cell in body['cells'].items() for pin,bits in cell['connections'].items()
            if wire in bits and cell['port_directions'][pin]=='output']
        consumers=[(name,pin) for name,cell in body['cells'].items() for pin,bits in cell['connections'].items()
            if wire in bits and cell['port_directions'][pin]=='input']
        assert len(drivers)==1 and drivers[0][1]=='invalid'
        assert body['cells'][drivers[0][0]]['type']==kernel.runner.SIM_KERNEL
        assert consumers and all(body['cells'][name]['type']=='LUT6' for name,pin in consumers)
    log=ROOT/report['commands'][-1]['log']
    entries=kernel.inventory.diagnostics(log.read_text())
    extras=[dict(kind='INITIALDLY',source=str(model),line=692,column=13,
        message="Non-blocking assignment '<=' in initial/final block"),
        dict(kind='UNUSEDSIGNAL',source=str(netlist),line=777,column=14,
        message=f"Bits of signal are not used: '{ALIAS}'[1:0]")]
    delta=Counter(kernel.key(entry) for entry in entries)-admitted
    assert delta==Counter(kernel.key(entry) for entry in extras)
    assert archive['new_unadmitted_diagnostics']==[dict(zip(('kind','source','line','column','message'),entry))
        for entry in delta]
    full=admitted+delta
    kernel.validate_followup(log.read_text(),full)
    bound=[top_path,fdce_verilator_path,fdce_iverilog_path,archive_path,model,netlist,part,bench,log,
        Path(__file__).resolve(),Path(startup.__file__).resolve()]
    value=dict(kind='EXACT_CLOSED_PREFIX_MAPPED_TOP_COMPILER_DIAGNOSTIC_ADMISSION_ONLY',source=fingerprint(bound),
        admitted_new_notices=extras, actual_fdce_count=742, actual_fdce_init='x',
        reset_establishes_state_before_first_observation=True, redundant_invalid_alias_only=[6,8],
        invalid_driver_and_lut_consumers_retained=True, top_diagnostics_accepted=True,
        original_failed_top_report_remains='FAIL',full_array_numerical_acceptance=False,
        physical_fit_verified=False,bitstream_emitted=False,
        scope='Exact FDCE initial nonblocking assignment at unchanged model line 692: actual INIT=X '
        'does not establish binary state; completed Icarus/Verilator controls verify reset, enabled '
        'clock, hold and real negatives, and unchanged full bench resets before observation after '
        '200 ns startup. Exact unused alias [1:0] at netlist line 777 has only two redundant '
        'assign-LHS occurrences; real invalid[6/8] kernel drivers and shell LUT consumers remain. '
        'No model/RTL rewrite, unknown-warning waiver, array numerical or physical acceptance.')
    return report,certificate,value,full
