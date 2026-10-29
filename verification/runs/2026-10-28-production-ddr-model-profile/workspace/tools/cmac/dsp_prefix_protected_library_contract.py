"""Audit exact generated DPI operand coverage, not a combinational-only API name."""
import re

BLOCK='rk_cmac_fp16_cell_dsp_prefix_xc7_b'
INPUTS={'data':512,'weight':512,'data_mask':32,'weight_mask':32}
OUTPUTS={'result':44,'invalid':1}
ROLES={'combo_update':{'data':512,'data_mask':32,'weight_mask':32},'seq_update':{'weight':512}}


def sv_tokens(text):
    """Tokenize the emitted subset; comments and string contents are not code."""
    tokens=re.findall(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'
                      r'[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+|[^\s]',text,re.S)
    tokens=[token for token in tokens if not token.startswith(('//','/*'))]
    assert '"' not in tokens and all(pair not in (['/','*'],['*','/'])
                                    for pair in (tokens[i:i+2] for i in range(len(tokens)-1))), \
        'Unsupported generated SV lexical form'
    return tokens


def validate_initial_hash_check(wrapper,protection_hash):
    # V3ProtectLib 5.048 emits one direct module initializer, immediately after
    # the hash declaration. Support that exact sequence, not arbitrary SV
    # control flow or preprocessor/generate wrappers around matching text.
    tokens=sv_tokens(wrapper)
    assert tokens[:2]==['module',BLOCK] and tokens.count('endmodule')==1, \
        'Generated wrapper must be one unconditional top-level module'
    body=tokens[:tokens.index('endmodule')]
    assert body.count('module')==1 and '`' not in body and body.count('initial')==1, \
        'Generated initializer must not be conditional or duplicated'
    start=body.index('initial')
    prefix=body[:start]
    forbidden={'begin','end','generate','endgenerate','if','else','for','foreach',
               'case','casex','casez','while','repeat','forever','fork','join',
               'task','endtask','class','package','always','always_comb',
               'always_ff','always_latch'}
    assert not forbidden.intersection(prefix), 'Generated initializer must be at module scope'
    declaration=sv_tokens("localparam int protectlib_hash__V = 32'd"+str(protection_hash)+';')
    assert prefix[-len(declaration):]==declaration, 'Changed generated initializer placement'
    expected=sv_tokens('initial begin '+BLOCK+'_protectlib_check_hash(protectlib_hash__V); '
        'handle__V = '+BLOCK+'_protectlib_create($sformatf("%m")); end')
    assert body[start:start+len(expected)]==expected, \
        'Generated initializer must check the library hash unconditionally before create'
    # Exactly the DPI import and the direct call are present as active tokens.
    assert body.count(BLOCK+'_protectlib_check_hash')==2, \
        'Missing or duplicate generated library hash check'


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
    # Verilator 5.048 V3ProtectLib.cpp computes this from the emitted C++ AST
    # and writes it into this particular wrapper and bridge. It is a linkage
    # guard, not a fixed constant of the FPGA datapath.
    assert len(wrapper_hash)==len(bridge_hash)==1 and wrapper_hash==bridge_hash, \
        'Generated wrapper and bridge protection hashes disagree'
    protection_hash=int(wrapper_hash[0])
    assert 0<=protection_hash<=0xffffffff and str(protection_hash)==wrapper_hash[0], \
        'Unsupported generated protection hash encoding'
    validate_initial_hash_check(wrapper,protection_hash)
    assert 'if (protectlib_hash__V != expected_hash__V)' in bridge
    operations={operation for text in top_sources for operation in ('create','combo_update','seq_update')
        if re.search(r'\b'+BLOCK+'_protectlib_'+operation+r'\s*\(',text)}
    assert operations=={'create','combo_update','seq_update'}
    return dict(actual_library_operations=sorted(operations),generated_input_roles=ROLES,
        observed_outputs=OUTPUTS,wrapper_library_protection_hash=protection_hash,
        weight_callback_trigger='any operand change, not posedge/negedge',
        native_kernel_combinational_api_required=False,
        source_interface_acceptance=True,full_array_numerical_acceptance=False,
        scope='Exact unchanged generated wrapper/bridge covers every operand/mask once across '
        'combo_update and seq_update, applies each exact-width input and evaluates the mapped '
        'model, returning result/invalid. The any-change weight callback is a simulator API '
        'classification, not added FPGA state. This interface audit does not prove numerical '
        'or wrapper startup/sequence-number behavior; the full original replay remains required.')
