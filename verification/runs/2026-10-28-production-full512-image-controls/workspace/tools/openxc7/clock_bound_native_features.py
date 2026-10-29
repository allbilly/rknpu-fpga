"""Read-only native HCLK flag model, not generic duplicate folding/signoff.

The bound writer collects source wires once per routed PIP, then write_bit emits
bare Boolean flags. For HCLK_R BUFHCLK0..7 / HCLK_L BUFHCLK8..11, require every flag's
literal multiplicity to match distinct, one-owner clock PIPs in the exact chipdb.
Each flag must have one positive Boolean bit in the Kintex segbits database.
Keep old I/O STEPDOWN cardinality, all conflict checks and unknown-repeat errors.
Never rewrite FASM, routing, circuit/input or a frozen parser/failure report.
"""
import ast
import importlib.util
from pathlib import Path
import re
import struct

from himbaechel_site_bels import SiteBELMap
from pack_prefix_board import ROOT,DATABASE,CONSTIDS
from probe_prefix_native_config import parse_features

BASE=Path('/home/fedora/tiny-gpu/build/ypcb')
EMITTER=ROOT/'build/openxc7/dsp-constant-engine-1791414105309267504/himbaechel/uarch/xilinx/fasm.cc'
CHIP_HEADER=BASE/'nextpnr-himbaechel/himbaechel/chipdb.h'
EXTRA_HEADER=BASE/'nextpnr-himbaechel/himbaechel/uarch/xilinx/extra_data.h'
ARCH=BASE/'nextpnr-himbaechel/himbaechel/arch.cc'
XILINX=BASE/'nextpnr-himbaechel/himbaechel/uarch/xilinx/xilinx.cc'
BASECTX=BASE/'nextpnr-himbaechel/common/kernel/basectx.cc'
PROPERTY=BASE/'nextpnr-himbaechel/common/kernel/property.cc'
PROPERTY_HEADER=PROPERTY.with_suffix('.h')
JSONWRITER=BASE/'nextpnr-himbaechel/json/jsonwrite.cc'
OUTPUT=BASE/'prjxray/third_party/fasm/fasm/output.py'
MODEL=OUTPUT.with_name('model.py')
SEGBITS={side:BASE/f'prjxray-db/kintex7/segbits_hclk_{side.lower()}.db' for side in ('L','R')}
SOURCES=(EMITTER,CHIP_HEADER,EXTRA_HEADER,ARCH,XILINX,BASECTX,PROPERTY,PROPERTY_HEADER,JSONWRITER,
         OUTPUT,MODEL,DATABASE,CONSTIDS,*SEGBITS.values())
INDICES={'L':tuple(range(8,12)),'R':tuple(range(8))}
FLAG=r'(?:HCLK_L_X\d+Y\d+\.ENABLE_BUFFER\.HCLK_CK_BUFHCLK(?:8|9|10|11)|HCLK_R_X\d+Y\d+\.ENABLE_BUFFER\.HCLK_CK_BUFHCLK[0-7])'
STEPDOWN=r'[LR]IOB(?:18|33)_X\d+Y\d+\.IOB_Y[01]\.LVCMOS12_LVCMOS15_LVCMOS18_SSTL135_SSTL15\.STEPDOWN'


def source_contract():
    source=EMITTER.read_text()
    for text in ('std::vector<std::string> used_wires_starting_with(', 'int wire_index = is_source ? pd.src_wire : pd.dst_wire;',
                 'wires.push_back(wire);','auto used_sources = used_wires_starting_with(tile, "HCLK_CK_", true);',
                 'push("ENABLE_BUFFER");','for (auto s : used_sources) {','write_bit(s);',
                 'void write_bit(const std::string &name, bool value = true)', 'out << name << std::endl;'):
        assert text in source,'Changed compiled clock emitter contract'
    assert 'IdString(tdata.wires[pdata.dst_wire].name)' in ARCH.read_text()
    assert 'IdString(tdata.wires[pdata.src_wire].name)' in ARCH.read_text()
    assert 'data.name_prefix).c_str(ctx), data.tile_x, data.tile_y' in XILINX.read_text()
    assert 'int16_t tile_x, tile_y;' in EXTRA_HEADER.read_text()
    assert 'ni->attrs[id("ROUTING")] = routing;' in BASECTX.read_text()
    assert 'param.second.to_string()' in JSONWRITER.read_text()
    assert 'escaping literal strings matching /^[01xz]* *$/ by adding a space at the end' in PROPERTY_HEADER.read_text()
    for text in ('RelSlice<TileWireDataPOD> wires;', 'RelSlice<PipDataPOD> pips;',
                 'int32_t src_wire;', 'int32_t dst_wire;', 'RelSlice<int32_t> pips_downhill;',
                 'RelSlice<BelPinRefPOD> bel_pins;'):
        assert text in CHIP_HEADER.read_text()
    return dict(emitter_sources_per_bound_PIP=True,flag_value=1,wire_record_bytes=48,pip_record_bytes=24,
                supported_tiles=['HCLK_L','HCLK_R'],supported_BUFHCLK_indices={k:list(v) for k,v in INDICES.items()},
                not_clock_or_configuration_or_physical_signoff=True)


def bit_rows():
    result={}
    for side,path in SEGBITS.items():
        rows={}
        for line in path.read_text().splitlines():
            parts=line.split();assert parts and parts[0] not in rows
            rows[parts[0]]=parts[1:]
        for index in INDICES[side]:
            key=f'HCLK_{side}.ENABLE_BUFFER.HCLK_CK_BUFHCLK{index}';bits=rows[key]
            assert len(bits)==1 and re.fullmatch(r'\d+_\d+',bits[0]),'Clock enable is not one positive Boolean bit'
            frame,bit=map(int,bits[0].split('_'));assert 0<=frame<128 and 0<=bit<3232
            result[key]=bits[0]
    return result


def clock_contracts(module):
    """Count actual native source PIPs; a repeated flag needs matching fanout."""
    rows=bit_rows();result={};owners={};kinds={}
    with SiteBELMap(DATABASE,CONSTIDS) as db:
        for net,entry in module['netnames'].items():
            route=entry.get('attributes',{}).get('ROUTING')
            if route is None:continue
            # Native Property::to_string escapes the empty literal as one space.
            # Accept precisely its empty serialization, not arbitrary whitespace.
            assert isinstance(route,str);tokens=[] if route in ('',' ') else route.split(';');assert len(tokens)%3==0
            for offset in range(0,len(tokens),3):
                _,pip,strength=tokens[offset:offset+3]
                assert re.fullmatch(r'[0-5]',strength),'Unknown native routing strength'
                if not pip:continue
                parts=pip.split('/')
                if len(parts)<3 or not parts[2].startswith('HCLK_CK_BUFHCLK'):continue
                assert len(parts)==3,'Unsupported inverting/extended regional clock PIP'
                generic,dst,src=parts;match=re.fullmatch(r'([^/\s]*)X(\d+)Y(\d+)',generic);assert match
                prefix,x,y=match.groups();x,y=int(x),int(y);assert x<db.width and y<db.height
                tile_index=y*db.width+x;tile=db.tiles+16*tile_index;kind=db.integer(tile+4)
                assert db.name(db.integer(tile))==prefix and 0<=kind<db.type_count
                type_data=db.types+40*kind;tile_type=db.name(db.integer(type_data))
                assert tile_type in ('HCLK_L','HCLK_R'),'Unsupported regional-clock tile profile'
                source_match=re.fullmatch(r'HCLK_CK_BUFHCLK(\d+)',src)
                assert source_match and int(source_match[1]) in INDICES[tile_type[-1]],'Unsupported regional clock index'
                if kind not in kinds:
                    wires,nw=db.slice(type_data+12,48);pips,np=db.slice(type_data+20,24)
                    names=[db.name(db.integer(wires+48*i)) for i in range(nw)];assert len(set(names))==nw
                    pairs={}
                    for index in range(np):
                        a,b=db.integer(pips+24*index),db.integer(pips+24*index+4)
                        assert 0<=a<nw and 0<=b<nw
                        pairs.setdefault((names[a],names[b]),[]).append(index)
                    kinds[kind]=pairs
                indices=kinds[kind][(src,dst)];assert len(indices)==1,'Ambiguous native clock PIP'
                identity=(tile_index,indices[0]);assert identity not in owners,'Repeated or multiple-owner native clock PIP'
                owners[identity]=net
                extra=db.pointer(tile+12,16);tx,ty=struct.unpack_from('<hh',db.data,extra+4);assert tx>=0 and ty>=0
                label=db.name(db.integer(extra));assert label==tile_type
                key=f'{label}_X{tx}Y{ty}.ENABLE_BUFFER.{src}';row=rows[f'{tile_type}.ENABLE_BUFFER.{src}']
                value=result.setdefault(key,dict(value=1,net=net,relative_positive_bit=row,PIPs=[]))
                assert value['net']==net and value['relative_positive_bit']==row,'Multiple clock owners for one buffer'
                value['PIPs'].append(dict(generic_pip=pip,tile_index=tile_index,pip_index=indices[0]))
    for value in result.values():value['PIPs'].sort(key=lambda p:(p['tile_index'],p['pip_index']))
    assert result,'No source-bound HCLK contract in native output'
    return dict(sorted(result.items()))


def parse_clock_bound_features(text,contracts):
    features,occurrences,io_repeated,clock_repeated={},{},{},{}
    assert contracts and all(re.fullmatch(FLAG,k) and v['value']==1 and v['PIPs'] for k,v in contracts.items())
    for lineno,line in enumerate(text.splitlines(),1):
        item=parse_features(line)
        if not item:continue
        name,value=next(iter(item.items()));is_clock='.ENABLE_BUFFER.HCLK_CK_BUFHCLK' in name
        if is_clock:
            assert re.fullmatch(FLAG,name) and name in contracts,'Unknown or unused HCLK flag'
            assert value=='1' and line==name,'Unsupported non-Boolean/noncanonical HCLK assignment'
        occurrences.setdefault(name,[]).append(lineno)
        if name in features:
            assert features[name]==value,'Conflicting native FASM feature: '+name
            if is_clock:
                assert len(occurrences[name])<=len(contracts[name]['PIPs']),'HCLK repetitions exceed actual source fanout'
                clock_repeated[name]=occurrences[name]
            else:
                assert value=='1' and re.fullmatch(STEPDOWN,name),'Unsupported repeated native FASM feature: '+name
                assert len(occurrences[name])==2,'Unexpected native STEPDOWN repetition count'
                io_repeated[name]=occurrences[name]
        else:features[name]=value
    for name,value in contracts.items():
        assert name in features and len(occurrences[name])==len(value['PIPs']),'Missing HCLK emission or changed fanout count'
    return features,io_repeated,clock_repeated


def consumer_merge_check():
    """Execute the unchanged F4PGA merge function with its real model types."""
    spec=importlib.util.spec_from_file_location('rknpu_bound_fasm_model',MODEL)
    model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
    nodes=[n for n in ast.parse(OUTPUT.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='merge_features']
    assert len(nodes)==1
    namespace=dict(SetFasmFeature=model.SetFasmFeature,ValueFormat=model.ValueFormat)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(OUTPUT),'exec'),namespace)
    merge=namespace['merge_features'];one=model.SetFasmFeature('HCLK_R.ENABLE_BUFFER.HCLK_CK_BUFHCLK0',None,None,1,None)
    assert merge([one,one]).value==1
    try:merge([one,one._replace(value=0)])
    except AssertionError:pass
    else:raise AssertionError('Consumer accepted conflicting enable assignments')
    return dict(actual_F4PGA_merge_function_executed=True,actual_model_types_used=True,
                repeated_positive_assignment_value=1,conflicting_assignment_rejected=True,
                parser_or_frame_converter_or_bitstream_executed=False)
