"""Pinned sources/parameters for the simulation-only AXI/UI/MC composition.

This reads an existing archive and functional primitive sources. It never runs
Vivado/IP generation and does not adopt the archive's electrical profile.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr import qualify_fence_order as mc
from tools.ddr.interface import canonical, load_json, require
from tools.ddr.run_monitor import PARAMETERS as CTRL_PARAMETERS

AXI_PARAMETERS=dict(C_S_AXI_ID_WIDTH=4,C_S_AXI_ADDR_WIDTH=31,C_S_AXI_DATA_WIDTH=512,
    C_S_AXI_SUPPORTS_NARROW_BURST=0,C_MC_DATA_WIDTH=512,C_MC_ADDR_WIDTH=29,
    C_MC_BURST_MODE='8',C_MC_nCK_PER_CLK=4,C_RD_WR_ARB_ALGORITHM='RD_PRI_REG',
    C_S_AXI_REG_EN0=0,C_S_AXI_REG_EN1=0,C_ECC='ON')
UI_PARAMETERS=dict(TCQ=100,APP_DATA_WIDTH=512,APP_MASK_WIDTH=64,BANK_WIDTH=3,COL_WIDTH=10,
    CWL=6,DATA_BUF_ADDR_WIDTH=5,ECC='ON',ECC_TEST='OFF',ORDERING='NORM',nCK_PER_CLK=4,
    RANKS=1,REG_CTRL='OFF',RANK_WIDTH=1,ROW_WIDTH=15,MEM_ADDR_ORDER='BANK_ROW_COLUMN')
PARAMETERS={'AXI':AXI_PARAMETERS,'UI':UI_PARAMETERS,'MC':mc.PARAMETERS,'CTRL':CTRL_PARAMETERS}
LOCAL=('tools/ddr/mig_logic_sources.py','tests/ddr/mig_logic_model.sv',
       'tools/ddr/qualify_fence_order.py','tools/ddr/interface.py','tools/ddr/run_monitor.py',
       'tools/ddr/__init__.py','tools/evidence.py','fpga/ddr/xdma_archive_reference.json',
       'fpga/ddr/xdma_retirement_contract.json','fpga/ddr/xdma_lifecycle_contract.json',
       'fpga/ddr/patches/round_robin_width_one.json','fpga/ddr/patches/axic_generate_attribute_simulation.json')
SCOPE='Actual archived AXI/UI/MC/control logic with WIDTH1 source fix, simulation-only generate-attribute compatibility, and encoded-beat PHY memory model; no pads, PHY training, FPGA or RK proof'


def source_inputs():
    return list(LOCAL)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def header(values):
    return ',\n'.join('    .'+name+'('+json.dumps(value)+')' for name,value in values.items())+'\n'


def definitions(output,producer_root=None):
    producer=Path(producer_root) if producer_root is not None else ROOT
    require(producer.is_absolute(),'Absolute producer root required')
    result=[]
    for kind in PARAMETERS:
        name=str(producer/output/('mc_parameters.svh' if kind=='MC' else 'logic_'+kind.lower()+'_parameters.svh'))
        require(not any(c in name for c in ('"','\\')) and all(ord(c)>=32 and ord(c)!=127 for c in name),
                'Unsupported absolute include path')
        result.append('-DRK_MIG_LOGIC_'+kind+'_PARAMS_HEADER='+json.dumps(name,ensure_ascii=False))
    return result


def expected_inputs(output,producer_root=None):
    mc.safe_path(output)
    plan=mc.expected_inputs(output);catalog=load_json(ROOT/'fpga/ddr/xdma_archive_reference.json')
    lifecycle=load_json(ROOT/'fpga/ddr/xdma_lifecycle_contract.json')
    require(lifecycle['catalog']['sha256']==sha(ROOT/'fpga/ddr/xdma_archive_reference.json') and
            canonical(lifecycle['control_leaf_parameters']['values'])==canonical(CTRL_PARAMETERS),
            'ECC control parameter contract changed')
    files=dict(plan['files']);compiled=list(plan['compiled']);headers={'MC':plan['header_name']}
    for member,name in plan['members'].items():
        if '/user_design/rtl/axi/' in member or '/user_design/rtl/ui/' in member:compiled.append(name)
    compatibility=load_json(ROOT/'fpga/ddr/patches/axic_generate_attribute_simulation.json')
    require(compatibility['simulation_only'] is True and compatibility['hardware_preparation_allowed'] is False and
            compatibility['archive_sha256']==catalog['archive']['sha256'] and
            compatibility['original_sha256']==catalog['members'][compatibility['member']]['sha256'],
            'Simulation compatibility lineage changed')
    original=plan['members'][compatibility['member']]
    require(original in compiled,'Compatibility source is not compiled')
    derived=str(Path(output)/'simulation_compatibility'/Path(original).name)
    files[derived]=compatibility['patched_sha256'];compiled.remove(original);compiled.append(derived)
    compatibility_info=dict(variant_id=compatibility['variant_id'],simulation_only=True,
        descriptor_sha256=sha(ROOT/'fpga/ddr/patches/axic_generate_attribute_simulation.json'),
        original=original,derived=derived,original_sha256=compatibility['original_sha256'],patched_sha256=compatibility['patched_sha256'])
    for kind,values in PARAMETERS.items():
        if kind=='MC':continue
        name=str(Path(output)/('logic_'+kind.lower()+'_parameters.svh'))
        files[name]=hashlib.sha256(header(values).encode()).hexdigest();headers[kind]=name
    compiled=['tests/ddr/mig_logic_model.sv']+sorted(compiled)
    producer=Path(producer_root) if producer_root is not None else ROOT
    require(producer.is_absolute(),'Absolute producer root required')
    return dict(scope=SCOPE,producer_root=str(producer),files=files,compiled_relative=compiled,
        compiled_sources=[str(producer/name) for name in compiled],definitions=definitions(output,producer),
        headers=headers,parameters=PARAMETERS,source_variant=plan['variant'],
        simulation_compatibility=compatibility_info,
        archive_sha256=catalog['archive']['sha256'],archive_members=plan['members'])


def check_parameters(output):
    base=mc.safe_path(str(Path(output)/'source/top_mig_7series_0_0/user_design/rtl'))
    core=(base/'top_mig_7series_0_0_mig.v').read_text()
    for name,expected in [('C0_C_S_AXI_ID_WIDTH',4),('C0_C_S_AXI_ADDR_WIDTH',31),
        ('C0_C_S_AXI_DATA_WIDTH',512),('C0_C_S_AXI_SUPPORTS_NARROW_BURST',0),
        ('C0_C_RD_WR_ARB_ALGORITHM','RD_PRI_REG'),('C0_C_S_AXI_REG_EN0',0),('C0_C_S_AXI_REG_EN1',0),
        ('C0_ADDR_WIDTH',29),('C0_ECC_TEST','OFF'),('C0_MEM_ADDR_ORDER','BANK_ROW_COLUMN')]:
        require(mc.literal_parameter(core,name)==expected,'Unsupported logical MIG parameter '+name)
    for name in ('TCQ','BANK_WIDTH','COL_WIDTH','CWL','DATA_BUF_ADDR_WIDTH','ECC','ORDERING',
                 'nCK_PER_CLK','RANKS','REG_CTRL','ROW_WIDTH'):
        require(mc.literal_parameter(core,'C0_'+name)==UI_PARAMETERS[name],'UI parameter differs: '+name)
    require(UI_PARAMETERS['APP_DATA_WIDTH']==2*mc.PARAMETERS['nCK_PER_CLK']*mc.PARAMETERS['PAYLOAD_WIDTH'] and
            UI_PARAMETERS['APP_MASK_WIDTH']==UI_PARAMETERS['APP_DATA_WIDTH']//8,'Derived UI widths changed')
    axi=(base/'axi/mig_7series_v4_2_axi_mc.v').read_text().replace('localparam','parameter')
    for stage in ('D1','D3'):
        for channel in ('AW','W','B','AR','R'):
            require(mc.literal_parameter(axi,'P_'+stage+'_REG_CONFIG_'+channel)==0,'Selected AXI slice is not bypass')
    mc.check_copied_parameters(output);mc.check_variant(mc.expected_inputs(output))


def verify_inputs(plan):
    expected=expected_inputs(next(iter(plan['headers'].values())).rsplit('/',1)[0],plan['producer_root'])
    for key in ('scope','producer_root','files','compiled_relative','compiled_sources','definitions','headers','parameters','source_variant','simulation_compatibility','archive_sha256','archive_members'):
        require(canonical(plan[key])==canonical(expected[key]),'Logical source plan differs: '+key)
    for name,value in expected['files'].items():require(sha(mc.safe_path(name))==value,'Logical input changed: '+name)
    output=next(iter(expected['headers'].values())).rsplit('/',1)[0]
    check_parameters(output)
    compatibility=load_json(ROOT/'fpga/ddr/patches/axic_generate_attribute_simulation.json')
    require(mc.apply_variant(mc.safe_path(expected['simulation_compatibility']['original']).read_bytes(),compatibility)==
            mc.safe_path(expected['simulation_compatibility']['derived']).read_bytes(),'Simulation compatibility bytes changed')
    if 'input_manifest' in plan:require(plan['input_manifest']==mc.manifest(expected['files']),'Logical manifest changed')
    return {'status':'VERIFIED_LOGICAL_MIG_INPUTS_ONLY','scope':SCOPE,'physical_integration_ready':False}


def prepare(archive,out,primitive_library=None):
    out=Path(out).expanduser().resolve()
    require(out.is_relative_to(ROOT) and not out.exists(),'Use a fresh in-workspace logical-source directory')
    out.mkdir(parents=True)
    if primitive_library is None:
        executable=shutil.which('vivado')
        require(executable is not None,'Supply primitive_library pointing to the pinned XECLIB sources')
        primitive_library=Path(executable).resolve().parents[1]/'data/verilog/src/xeclib'
    mc.prepare(Path(archive).expanduser().resolve(),Path(primitive_library).expanduser().resolve(),out)
    output=str(out.relative_to(ROOT));plan=expected_inputs(output)
    compatibility=load_json(ROOT/'fpga/ddr/patches/axic_generate_attribute_simulation.json')
    path=mc.safe_path(plan['simulation_compatibility']['derived']);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(mc.apply_variant(mc.safe_path(plan['simulation_compatibility']['original']).read_bytes(),compatibility))
    for kind,name in plan['headers'].items():
        if kind!='MC':mc.safe_path(name).write_text(header(PARAMETERS[kind]))
    verify_inputs(plan)
    plan['input_manifest']=mc.manifest(plan['files'])
    plan['source_manifest']=mc.fingerprints([ROOT/name for name in LOCAL])
    return plan
