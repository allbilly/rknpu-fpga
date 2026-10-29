#!/usr/bin/env python3
"""Freeze an original RZQ/7 RTL selection with one explicit arbiter overlay.

No project, synthesis, implementation, simulator or device is started.
Raw generated sources are copied unchanged; only the selected compile list
substitutes the already reviewed WIDTH1 definition. Cached IP/DCP is excluded.
"""
from pathlib import Path
import argparse
import json
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.interface import load_json,require,xml
from tools.ddr.original_binding import WRAPPER_SHA,sha,ports,binding_map

GENERATION_SHA='85761e96dd18edd537ac6b3b0392e522be3adcd3d985e5d1f5dc8d2f7239c42d'
RAW_ARBITER_SHA='a4b107a17899ee17b42c76e91f8789737d74b65d37c1be6f895bbe24b8b614ef'
DERIVED_ARBITER_SHA='ae6be8a3f77170c867bf076a4291bd6b0755c1250ab32215a8b679274b88368f'
ARBITER='mig_7series_v4_2_round_robin_arb'


def module_names(path):
    # Vendor comment headers contain legacy code-page punctuation. Preserve
    # every source byte and inspect only ASCII Verilog declaration tokens.
    text=re.sub(rb'/\*.*?\*/|//[^\n]*',b'',Path(path).read_bytes(),flags=re.S)
    return [name.decode('ascii') for name in re.findall(rb'(?m)^[ \t]*module\s+([A-Za-z_]\w*)\b',text)]


def synthesis_files(component):
    root=xml(Path(component).read_text());groups={}
    local=lambda node:node.tag.rsplit('}',1)[-1]
    for group in root.iter():
        if local(group)!='fileSet':continue
        name=next((c.text for c in group if local(c)=='name'),None)
        require(name not in groups,'Duplicate component file set')
        groups[name]=[next((c.text for c in f if local(c)=='name'),None)
                      for f in group if local(f)=='file']
    expected=('xilinx_anylanguagesynthesis_view_fileset','xilinx_verilogsynthesiswrapper_view_fileset')
    require(all(name in groups for name in expected),'Missing actual MIG synthesis view')
    selected=[];assets=[]
    for group in expected:
        for name in groups[group]:
            require(isinstance(name,str),'Missing synthesis source name')
            relative=Path(name)
            require(not relative.is_absolute() and '..' not in relative.parts,'Escaping synthesis source')
            path=Path(component).parent/relative
            if path.suffix in ('.v','.sv'):selected.append(path)
            else:assets.append(path)
    require(len(selected)==101 and len(selected)==len(set(selected)),'Changed original synthesis HDL inventory')
    require(not any(p.name.endswith('_mig_sim.v') for p in selected),'Simulation wrapper cannot enter synthesis')
    return selected,assets,expected


def select(rtl,raw,derived):
    rtl=list(map(Path,rtl));raw,derived=Path(raw),Path(derived)
    require(len(rtl)==len(set(rtl)) and raw in rtl,'Missing/duplicate raw RTL selection')
    require(sha(raw)==RAW_ARBITER_SHA and sha(derived)==DERIVED_ARBITER_SHA,'Changed arbiter source identity')
    require(module_names(raw)==module_names(derived)==[ARBITER],'Unexpected arbiter definition')
    selected=[p for p in rtl if p!=raw]+[derived]
    counts={}
    for p in selected:
        for name in module_names(p):counts[name]=counts.get(name,0)+1
    require(counts.get(ARBITER)==1,'Original and corrected arbiter cannot both be selected')
    require(all(n==1 for n in counts.values()),'Duplicate generated module definition')
    return selected,counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generation-report',type=Path,required=True)
    parser.add_argument('--generated-root',type=Path,required=True)
    parser.add_argument('--port-map',type=Path,required=True)
    parser.add_argument('--variant',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();generated=args.generated_root.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh original RTL package required')
    require(sha(args.generation_report)==GENERATION_SHA,'Changed native original generation receipt')
    generation=load_json(args.generation_report)
    require(generation['status']=='PASS_GENERATED_ORIGINAL_MIG_SOURCES_ONLY' and generation['returncode']==0,
            'Incomplete original source generation')
    for name,h in generation['inputs'].items():require(sha(name)==h,'Changed original generation input '+name)
    for name,h in generation['artifacts'].items():
        p=Path(name);require(not p.is_absolute() and '..' not in p.parts,'Escaping generated artifact')
        require(sha(generated/p)==h,'Changed generated artifact '+name)
    mapping=load_json(args.port_map)
    require(mapping['status']=='PREPARED_COMPLETE_ORIGINAL_MIG_PORT_MAP_ONLY' and mapping['normal_ports']==169,
            'Incomplete original normal port map')
    for name,h in mapping['source_inputs'].items():require(sha(name)==h,'Changed port-map source '+name)
    wrapper=next(Path(n) for n,h in mapping['source_inputs'].items() if h==WRAPPER_SHA)
    require(wrapper.is_relative_to(generated),'Wrapper is outside the selected generated tree')
    endpoint=next(Path(n) for n in mapping['source_inputs'] if n.endswith('/rtl/ddr/rk_jtag_ew_ddr_async.sv'))
    require(mapping['ports']==binding_map(ports(wrapper.read_text(),'top_mig_7series_0_0'),
        ports(endpoint.read_text(),'rk_jtag_ew_ddr_async')),'Port map differs from actual declarations')
    user=wrapper.parents[1]
    rtl=sorted(p for p in (user/'rtl').rglob('*') if p.suffix in ('.v','.sv'))
    require(len(rtl)==102,'Changed original generated RTL inventory')
    for p in rtl:
        require(str(p.relative_to(generated)) in generation['artifacts'],'Unrecorded generated RTL')
    variant=load_json(args.variant)
    require(variant['status']=='PREPARED_REGENERATED_ORIGINAL_MIG_WIDTH1_ARBITER_VARIANT_ONLY' and
            variant['generation_report_sha256']==GENERATION_SHA,'Wrong derived original variant')
    raw,derived=Path(variant['origin']['path']),Path(variant['derived']['path'])
    component=wrapper.parents[3]/'top_mig_7series_0_0.xml'
    require(str(component.relative_to(generated)) in generation['artifacts'],'Missing bound generated component')
    synthesis,assets,file_sets=synthesis_files(component)
    require(set(synthesis)<=set(rtl),'Synthesis view references an unbound HDL source')
    selected,modules=select(synthesis,raw,derived)
    require(wrapper in selected and modules.get('top_mig_7series_0_0')==1,'Missing actual normal wrapper')
    source_inputs={str(p):sha(p) for p in rtl+assets+[component,derived,args.generation_report,args.port_map,args.variant,Path(__file__).resolve()]}
    out.mkdir(parents=True)
    copies={}
    for p in rtl:
        target=out/'source/generated'/p.relative_to(user)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        require(sha(target)==sha(p),'Frozen generated source differs');copies[p]=str(target.relative_to(out))
    overlay=out/'source/derived'/derived.name;overlay.parent.mkdir(parents=True)
    shutil.copyfile(derived,overlay);require(sha(overlay)==DERIVED_ARBITER_SHA,'Frozen overlay differs')
    copies[derived]=str(overlay.relative_to(out))
    constraints=user/'constraints/top_mig_7series_0_0.xdc'
    target=out/'source/generated/constraints'/constraints.name;target.parent.mkdir(parents=True)
    shutil.copyfile(constraints,target);source_inputs[str(constraints)]=sha(constraints)
    metadata={}
    for label,p in [('component.xml',component),('generation.json',args.generation_report),
                    ('port-map.json',args.port_map),('arbiter-variant.json',args.variant)]:
        copy=out/'evidence'/label;copy.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,copy);require(sha(copy)==sha(p),'Frozen source metadata differs')
        metadata[str(copy.relative_to(out))]=sha(copy)
    source_hashes={n:sha(out/n) for n in copies.values()}
    record=dict(status='PREPARED_CORRECTED_ORIGINAL_MIG_RTL_SELECTION_ONLY',scope=__doc__,
        source_inputs=source_inputs,compile_sources=[copies[p] for p in selected],
        copied_source_hashes=source_hashes,copied_metadata_hashes=metadata,
        raw_arbiter_preserved=copies[raw],raw_arbiter_selected=False,derived_arbiter_selected=copies[derived],
        module_count=len(modules),selected_hdl_count=len(selected),arbiter_definition_count=modules[ARBITER],
        source_file_sets=list(file_sets),simulation_wrapper_selected=False,
        constraints=dict(path=str(target.relative_to(out)),sha256=sha(target),scope_binding_review_required=True),
        normal_ports=169,source_drive_profile='RZQ/7',required_undefined=['SKIP_CALIB'],
        cached_checkpoint_allowed=False,managed_xci_selected=False,simulation_attribute_patch_applied=False,
        physical_integration_ready=False,hardware_accessed=False,vivado_executed=False,simulated=False,
        unresolved=['Fresh matched controller/PHY qualification','Clock/electrical and constraint scope review',
                    'Whole-platform reset/drain and ownership','Full512/DDR/host shell composition'])
    (out/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'],len(selected),modules[ARBITER])


if __name__=='__main__':main()
