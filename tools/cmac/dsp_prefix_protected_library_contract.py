"""Audit exact generated DPI operand coverage, not a combinational-only API name."""
import re

BLOCK='rk_cmac_fp16_cell_dsp_prefix_xc7_b'
INPUTS={'data':512,'weight':512,'data_mask':32,'weight_mask':32}
OUTPUTS={'result':44,'invalid':1}
ROLES={'combo_update':{'data':512,'data_mask':32,'weight_mask':32},'seq_update':{'weight':512}}


def validate(wrapper,bridge,top_sources):
    ports=re.search(r'\bmodule '+BLOCK+r'\s*\((.*?)\);',wrapper,re.S)
    assert ports
    found=re.findall(r'\b(input|output) logic\s*(?:\[(\d+):0\])?\s*(\w+)',ports.group(1))
    assert {name:(direction,int(high)+1 if high else 1) for direction,high,name in found}=={
        **{name:('input',width) for name,width in INPUTS.items()},
        **{name:('output',width) for name,width in OUTPUTS.items()}}
    assert len(found)==6
    for role,expected in ROLES.items():
        signature=re.search(r'import "DPI-C" function longint '+BLOCK+'_protectlib_'+role+r'\((.*?)\);',wrapper,re.S)
        assert signature
        args=re.findall(r'\b(input|output) logic\s*(?:\[(\d+):0\])?\s*(\w+)',signature.group(1))
        assert {name:int(high)+1 if high else 1 for direction,high,name in args if direction=='input'}==expected
        assert {name:int(high)+1 if high else 1 for direction,high,name in args if direction=='output'}==OUTPUTS
        match=re.search(r'long long '+BLOCK+'_protectlib_'+role+r'\(.*?\) \{(.*?)\n    \}',bridge,re.S)
        assert match
        body=match.group(1)
        assigned=re.findall(r'VL_SET_[WI]_SVLV\((\d+),\s*handlep__V->(\w+),\s*(\w+) \+ 0\);',body)
        assert len(assigned)==len(expected) and {name:int(width) for width,name,argument in assigned}==expected
        assert all(name==argument for width,name,argument in assigned)
        assert body.count('handlep__V->eval();')==1
        assert body.count('VL_SET_SVLV_Q(44, result, handlep__V->result);')==1
        assert body.count('*invalid = handlep__V->invalid;')==1
    assert wrapper.count('always @(weight) begin')==1
    assert not re.search(r'always @\((?:pos|neg)edge weight',wrapper)
    wrapper_hash=re.findall(r'localparam int protectlib_hash__V = 32\'d(\d+);',wrapper)
    bridge_hash=re.findall(r'const int expected_hash__V = (\d+)U;',bridge)
    assert wrapper_hash==bridge_hash==['2969735049']
    assert 'if (protectlib_hash__V != expected_hash__V)' in bridge
    operations={operation for text in top_sources for operation in ('create','combo_update','seq_update')
        if re.search(r'\b'+BLOCK+'_protectlib_'+operation+r'\s*\(',text)}
    assert operations=={'create','combo_update','seq_update'}
    return dict(actual_library_operations=sorted(operations),generated_input_roles=ROLES,
        observed_outputs=OUTPUTS,wrapper_library_protection_hash=int(wrapper_hash[0]),
        weight_callback_trigger='any operand change, not posedge/negedge',
        native_kernel_combinational_api_required=False,
        source_interface_acceptance=True,full_array_numerical_acceptance=False,
        scope='Exact unchanged generated wrapper/bridge covers every operand/mask once across '
        'combo_update and seq_update, applies each exact-width input and evaluates the mapped '
        'model, returning result/invalid. The any-change weight callback is a simulator API '
        'classification, not added FPGA state. This interface audit does not prove numerical '
        'or wrapper startup/sequence-number behavior; the full original replay remains required.')
