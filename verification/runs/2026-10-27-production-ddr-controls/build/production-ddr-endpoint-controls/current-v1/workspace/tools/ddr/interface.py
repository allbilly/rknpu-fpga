"""Inspect the original channel-0 MIG interface without executing vendor tools.

Consistent metadata is not a generated controller or DDR integration proof. This
auditor deliberately has no READY state: implementation, ECC event association,
allocated-memory initialization and joint reset require separate evidence.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

SPIRIT = 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'
XILINX = 'http://www.xilinx.com'
NS = {'s': SPIRIT, 'x': XILINX}
ORIGINAL_ROLES = {'project', 'template', 'component', 'example', 'file_list', 'block_design'}
BLOCKERS = ['ECC_AXI_EVENT_BINDING_UNKNOWN', 'MEMORY_INITIALIZATION_NOT_PROVEN',
            'JOINT_RESET_ACK_EXTERNAL']
PROFILE = dict(module='top_mig_7series_0_0', channel=0, interface='AXI',
               address_width=31, data_width=512, id_width=4, write_strobe_width=64,
               size_bytes=2147483648, local_byte_address_first=0,
               local_byte_address_last=2147483647, physical_dq_width=72,
               ecc='ON', supports_narrow_bursts=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def load_json(path):
    """Unlike json.load's default, reject duplicate keys and non-JSON numbers."""
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: '+key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Invalid JSON constant: '+value)
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=constant)


def xml(text):
    require(not re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I), 'XML declarations/entities are unsupported')
    try:
        return ET.fromstring(text.lstrip('\ufeff'))
    except ET.ParseError as error:
        raise ValueError('Invalid XML: '+str(error)) from error


def one(node, path):
    matches = node.findall(path, NS)
    require(len(matches) == 1, 'Expected exactly one XML field: '+path)
    return matches[0]


def value(node, path):
    result = one(node, path).text
    require(result is not None and result.strip(), 'Empty XML field: '+path)
    return result.strip()


def literal_metadata(field, namespace):
    for key in field.attrib:
        if key.rsplit('}',1)[-1] in ('resolve','dependency'):
            require(key in ('{'+namespace+'}resolve','{'+namespace+'}dependency'), 'Foreign metadata attribute')
    resolve = field.get('{'+namespace+'}resolve')
    dependency = field.get('{'+namespace+'}dependency')
    require(resolve in (None,'dependent','generated'), 'Unsupported metadata resolve mode')
    require(resolve != 'dependent' or dependency, 'Missing metadata dependency')
    return dependency


def enablement(node, kind, parameters):
    nodes = node.findall('s:vendorExtensions/x:'+kind+'/x:enablement/x:isEnabled',NS)
    require(len(nodes) <= 1 and len(nodes) == len([n for n in node.iter() if n.tag.rsplit('}',1)[-1]=='isEnabled']),
            'Unsupported/duplicate enablement namespace/location')
    if not nodes: return True,True,None
    field=nodes[0]; raw=(field.text or '').strip()
    require(raw in ('true','false'), 'Unknown cached enablement')
    dependency=literal_metadata(field,XILINX)
    cached=raw=='true'; computed=expression(dependency,parameters) if dependency else cached
    require(type(computed) is bool, 'Nonboolean enablement')
    return computed,cached,dependency


def integer(text):
    require(re.fullmatch(r'0|[1-9][0-9]*', text) is not None, 'Expected unsigned decimal integer: '+text)
    return int(text)


def parse_project(text):
    root = xml(text)
    require(root.tag == 'Project', 'Not a MIG project')
    controllers = root.findall('Controller')
    numbers = [node.get('number') for node in controllers]
    require(len(numbers) == len(set(numbers)) and numbers.count('0') == 1,
            'Missing/duplicate controller number')
    count = integer(root.get('NoOfControllers', ''))
    require(count == len(controllers), 'Controller count differs from project')
    c0 = controllers[numbers.index('0')]
    result = dict(module=value(root, 'ModuleName'), controllers=count,
                  target=value(root, 'TargetFPGA'), system_clock=value(root, 'SystemClock'),
                  reference_clock=value(root, 'ReferenceClock'), sys_reset=value(root, 'SysResetPolarity'),
                  interface=value(c0, 'PortInterface'), ecc=value(c0, 'ECC'),
                  phy_ratio=value(c0, 'PHYRatio'), physical_dq_width=integer(value(c0, 'DataWidth')),
                  size_bytes=integer(value(c0, 'C0_MEM_SIZE')),
                  input_clock_mhz=integer(value(c0, 'InputClkFreq')),
                  memory_period_ps=integer(value(c0, 'TimePeriod')))
    for key, field in [('address_width', 'ADDR_WIDTH'), ('data_width', 'DATA_WIDTH'),
                       ('id_width', 'ID_WIDTH'), ('narrow_bursts', 'SUPPORTS_NARROW_BURST')]:
        result[key] = integer(value(c0, 'AXIParameters/C0_S_AXI_'+field))
    return result


def parse_template(text):
    """Read the vendor .veo's named connections AND their declaration comments."""
    ports = {}
    for line in text.splitlines():
        if not re.match(r'\s*\.\w+\s*\(', line):
            continue
        match = re.fullmatch(r'\s*\.(\w+)\s*\(\s*(\w+)\s*\)\s*,?\s*//\s*'
                             r'(input|output|inout)\s*(?:\[(\d+):(\d+)\])?\s*(\w+)\s*', line)
        require(match is not None, 'Unsupported/missing .veo declaration: '+line.strip())
        name, connection, direction, left, right, declared = match.groups()
        require(name == connection == declared, 'Template port/declaration name differs: '+name)
        require(name not in ports, 'Duplicate template port: '+name)
        hi, lo = (integer(left), integer(right)) if left is not None else (0, 0)
        require(0 <= lo <= hi < 65536, 'Invalid template vector: '+name)
        ports[name] = dict(direction={'input': 'in', 'output': 'out', 'inout': 'inout'}[direction],
                           width=hi-lo+1)
    require(ports, 'No declared instantiation ports')
    return ports


def template_module(text):
    source=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    modules=re.findall(r'^\s*([A-Za-z_]\w*)\s+[A-Za-z_]\w*\s*\(',source,re.M)
    require(len(modules)==1,'Missing/duplicate template instantiation')
    return modules[0]


def expression(text, parameters):
    """Small arithmetic/boolean subset of IP-XACT expressions; never eval/Tcl."""
    names = {}
    def parameter(match):
        key = match.group(1)
        require(key in parameters, 'Unknown component parameter: '+key)
        token = 'p'+str(len(names)); names[token] = parameters[key]
        return token
    source = re.sub(r"spirit:decode\(id\('MODELPARAM_VALUE\.([A-Za-z0-9_]+)'\)\)", parameter, text)
    source = re.sub(r'(?<![<>=!])=(?!=)', '==', source).strip()
    require(len(source) <= 8192, 'Oversized component expression')
    try:
        tree = ast.parse(source, mode='eval')
    except (SyntaxError, RecursionError) as error:
        raise ValueError('Unsupported component expression: '+text) from error
    def read(node):
        if isinstance(node, ast.Constant) and type(node.value) in (str, int, bool):
            return node.value
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [read(item) for item in node.values]  # No short-circuit hiding unknown terms.
            require(all(type(item) is bool for item in values), 'Nonboolean enablement operand')
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            a, b = read(node.left), read(node.comparators[0]); op = node.ops[0]
            require(type(a) is type(b), 'Mixed component comparison types')
            if isinstance(op, ast.Eq): return a == b
            if isinstance(op, ast.NotEq): return a != b
            require(type(a) is int, 'Noninteger ordered comparison')
            if isinstance(op, ast.Lt): return a < b
            if isinstance(op, ast.LtE): return a <= b
            if isinstance(op, ast.Gt): return a > b
            if isinstance(op, ast.GtE): return a >= b
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = read(node.left), read(node.right)
            require(type(a) is type(b) is int and abs(a) < 2**32 and abs(b) < 2**32,
                    'Invalid width arithmetic')
            if isinstance(node.op, ast.Add): return a+b
            if isinstance(node.op, ast.Sub): return a-b
            if isinstance(node.op, ast.Mult): return a*b
            require(b != 0 and a % b == 0, 'Nonintegral width division')
            return a//b
        raise ValueError('Unsupported component expression: '+text)
    return read(tree.body)


def parse_component(text, selected_ports=None):
    root = xml(text)
    require(root.tag == '{'+SPIRIT+'}component', 'Unsupported IP-XACT namespace/root')
    parameters = {}
    for parameter in root.findall('s:model/s:modelParameters/s:modelParameter', NS):
        name = value(parameter, 's:name'); raw = value(parameter, 's:value')
        require(name not in parameters, 'Duplicate component parameter: '+name)
        parameters[name] = int(raw) if re.fullmatch(r'[0-9]+', raw) else raw
    inventory = {}; ports = {}
    for port in root.findall('s:model/s:ports/s:port', NS):
        name = value(port, 's:name')
        require(name not in inventory, 'Duplicate component port: '+name)
        inventory[name] = True
        if selected_ports is not None and name not in selected_ports:
            continue
        direction = value(port, 's:wire/s:direction')
        require(direction in ('in', 'out', 'inout'), 'Invalid port direction: '+name)
        for local,path in [('wire','s:wire'),('direction','s:wire/s:direction'),('vector','s:wire/s:vector')]:
            require(len(port.findall(path,NS)) == len([n for n in port.iter() if n.tag.rsplit('}',1)[-1]==local]),
                    'Unsupported '+local+' namespace/location: '+name)
        vector = port.findall('s:wire/s:vector', NS)
        require(len(vector) <= 1, 'Duplicate vector: '+name)
        bounds = {}; cached = {}
        for end in ('left', 'right') if vector else ():
            field = one(vector[0], 's:'+end); raw = integer((field.text or '').strip())
            require(len(vector[0].findall('s:'+end,NS)) == len([n for n in vector[0].iter() if n.tag.rsplit('}',1)[-1]==end]),
                    'Unsupported vector bound namespace/location: '+name)
            dependency = literal_metadata(field,SPIRIT)
            computed = expression(dependency, parameters) if dependency else raw
            require(type(computed) is int and 0 <= computed < 65536, 'Invalid computed width: '+name)
            bounds[end] = computed; cached[end] = raw
        require(not vector or bounds['right'] <= bounds['left'], 'Reversed vector: '+name)
        enabled,cached_enabled,condition = enablement(port,'portInfo',parameters)
        ports[name] = dict(direction=direction, width=bounds['left']-bounds['right']+1 if vector else 1,
                           cached_width=cached['left']-cached['right']+1 if vector else 1,
                           enabled=enabled, cached_enabled=cached_enabled, condition=condition)
    require(ports, 'No selected component ports')
    bindings={}; seen=set()
    binding_fields={'C0_CLOCK':('FREQ_HZ','ASSOCIATED_BUSIF','ASSOCIATED_RESET','CLK_DOMAIN'),
                    'C0_RESET':('POLARITY',),'C0_ARESETN':('POLARITY',),'SYSTEM_RESET':('POLARITY',)}
    for bus in root.findall('s:busInterfaces/s:busInterface',NS):
        name=value(bus,'s:name'); require(name not in seen,'Duplicate bus interface: '+name); seen.add(name)
        if name not in binding_fields: continue
        fields={}
        for parameter in bus.findall('s:parameters/s:parameter',NS):
            key=value(parameter,'s:name'); require(key not in fields,'Duplicate bus parameter: '+key)
            fields[key]=parameter
        values={}; cached={}
        for key in binding_fields[name]:
            require(key in fields,'Missing clock/reset binding: '+name+'/'+key)
            field=one(fields[key],'s:value'); raw=(field.text or '').strip()
            require(raw,'Empty clock/reset binding')
            cached[key]=integer(raw) if key=='FREQ_HZ' else raw
            dependency=literal_metadata(field,SPIRIT)
            values[key]=expression(dependency,parameters) if dependency else cached[key]
        enabled,cached_enabled,condition=enablement(bus,'busInterfaceInfo',parameters)
        mapping=one(bus,'s:portMaps/s:portMap')
        bindings[name]=dict(port=value(mapping,'s:physicalPort/s:name'),logical_port=value(mapping,'s:logicalPort/s:name'),
            parameters=values,cached_parameters=cached,enabled=enabled,cached_enabled=cached_enabled,condition=condition)
    return dict(ports=ports, parameters=parameters,clock_reset_bindings=bindings)


def parse_example_ecc(text):
    """Only the original example's literal parameter and vector grammar."""
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    ratios = re.findall(r'\bparameter\s+C0_nCK_PER_CLK\s*=\s*([0-9]+)\s*[,;]', text)
    require(len(ratios) == 1, 'Missing/duplicate example PHY ratio')
    ratio = integer(ratios[0]); ports = {}
    for name in ('c0_app_ecc_single_err', 'c0_app_ecc_multiple_err'):
        pattern = r'\bwire\s*\[\s*\(\s*2\s*\*\s*C0_nCK_PER_CLK\s*\)\s*-\s*1\s*:\s*0\s*\]\s*'+name+r'\s*;'
        require(len(re.findall(pattern,text)) == 1, 'Unsupported/missing example ECC declaration: '+name)
        require(len(re.findall(r'\.'+name+r'\s*\(\s*'+name+r'\s*\)',text)) == 1,
                'Missing/duplicate example ECC connection: '+name)
        ports[name] = dict(width=2*ratio, instance_connected=True)
    return dict(phy_ratio=ratio, ports=ports)


def expected_ports():
    ports = {}
    for channel in ('aw', 'ar'):
        for field, width in dict(id=4, addr=31, len=8, size=3, burst=2, lock=1,
                                 cache=4, prot=3, qos=4, valid=1, ready=1).items():
            ports['c0_s_axi_'+channel+field] = dict(direction='out' if field == 'ready' else 'in', width=width)
    for channel, fields in [('w', dict(data=512, strb=64, last=1, valid=1, ready=1)),
                            ('b', dict(id=4, resp=2, valid=1, ready=1)),
                            ('r', dict(id=4, data=512, resp=2, last=1, valid=1, ready=1))]:
        for field, width in fields.items():
            incoming = (channel == 'w') != (field == 'ready')
            ports['c0_s_axi_'+channel+field] = dict(direction='in' if incoming else 'out', width=width)
    for name in ('c0_ui_clk', 'c0_ui_clk_sync_rst', 'c0_init_calib_complete', 'c0_mmcm_locked'):
        ports[name] = dict(direction='out', width=1)
    for name in ('sys_rst', 'c0_aresetn'):
        ports[name] = dict(direction='in', width=1)
    return ports


def validate_reference(reference):
    keys = {'schema_version', 'status', 'scope', 'physical_integration_ready', 'source_roots',
            'sources', 'profile', 'ports', 'reset_observations', 'ecc_observations',
            'initialization', 'missing_generated_sources', 'blockers'}
    require(type(reference) is dict and set(reference) == keys, 'Unknown/missing reference fields')
    require(type(reference['schema_version']) is int and reference['schema_version'] == 1,
            'Unsupported reference schema')
    require(reference['status'] == 'REFERENCE_AUDITED_GENERATED_BINDING_INCOMPLETE' and
            reference['physical_integration_ready'] is False, 'Unsupported reference readiness claim')
    for key, expected in PROFILE.items():
        actual = reference['profile'].get(key)
        require(type(actual) is type(expected) and actual == expected, 'Unsafe reference profile: '+key)
    require(set(reference['profile']) == set(PROFILE) | {'channel_1_translation', 'evidence'},
            'Unknown profile fields')
    require(reference['profile']['channel_1_translation'].startswith('NONE:'), 'Channel-select truncation is unsupported')
    port_contract = {'c0_ui_clk':dict(direction='out', width=1,nominal_hz_from_component_metadata=133333333),
        'c0_ui_clk_sync_rst':dict(direction='out',width=1,active_level=1),
        'c0_init_calib_complete':dict(direction='out',width=1,asserted_level_in_example=1),
        'c0_aresetn':dict(direction='in',width=1,active_level=0),
        'sys_rst':dict(direction='in',width=1,active_level=0),
        'c0_app_ecc_single_err':dict(binding='UNRESOLVED',example_wire_width=8,
            example_instance_connection=True,present_in_instantiation_template=False,present_in_component_port_inventory=False),
        'c0_app_ecc_multiple_err':dict(binding='UNRESOLVED',example_wire_width=8,
            example_instance_connection=True,template_direction='out',template_width=8,component_cached_width=4,component_enabled=False)}
    require(set(reference['ports']) == set(port_contract), 'Unknown reference port contract')
    for name, fields in port_contract.items():
        for key, expected in fields.items():
            actual = reference['ports'][name].get(key)
            require(type(actual) is type(expected) and actual == expected, 'Unsafe reference port claim: '+name+'/'+key)
    require(reference['reset_observations']['joint_reset_ack_generated_port'] is None and
            reference['reset_observations']['joint_reset_ack_status'] == 'EXTERNAL_REQUIRED',
            'Reset acknowledgment is not a generated MIG readiness signal')
    require(reference['initialization']['allocated_data_and_ecc_initialized'] == 'UNKNOWN' and
            reference['initialization']['init_calib_complete_proves_allocated_memory_initialized'] is False,
            'Calibration cannot prove allocated data/ECC initialization')
    require(reference['ecc_observations']['installed_templates_resolve_original_binding'] is False,
            'Installed templates cannot resolve the original generated interface')
    for key in ('original_axi_read_event_correlation', 'original_axi_write_rmw_event_correlation',
                'original_ecc_event_address_correlation'):
        require(reference['ecc_observations'][key].startswith('UNKNOWN'), 'Unsupported original ECC readiness claim')
    require(reference['blockers'] == ['MISSING_GENERATED_CONTROLLER', 'ECC_PORT_METADATA_CONFLICT']+BLOCKERS,
            'Original binding blockers cannot be waived')
    require(set(reference['sources']) == ORIGINAL_ROLES | {'installed_axi_mc', 'installed_axi_read',
            'installed_axi_write_response', 'opentpu_native_project'}, 'Unknown/missing source roles')
    for role, entry in reference['sources'].items():
        require(set(entry) == ({'root', 'path', 'sha256', 'head_matches'} if role in ORIGINAL_ROLES else
                              {'root', 'path', 'sha256'}), 'Unknown source entry fields: '+role)
        require(entry['root'] in reference['source_roots'], 'Unknown source root')
        safe_relative(entry['path'])
        require(type(entry['sha256']) is str and re.fullmatch('[0-9a-f]{64}', entry['sha256']), 'Invalid source hash')
        if role in ORIGINAL_ROLES:
            require(entry['root'] == 'original_project' and entry['head_matches'] is True,
                    'Original source identity required')


def safe_relative(name):
    require(type(name) is str and '\\' not in name and name and '\x00' not in name,
            'Unsafe source path')
    path = PurePosixPath(name)
    require(path.parts and not path.is_absolute() and '..' not in path.parts and str(path) == name, 'Unsafe source path')
    return path


def checked(root, name):
    relative = safe_relative(name); path = root.joinpath(*relative.parts)
    require(path.resolve().is_relative_to(root.resolve()) and
            not any(root.joinpath(*relative.parts[:i]).is_symlink() for i in range(1,len(relative.parts)+1)),
            'Escaping/symlinked source: '+name)
    return path


def audit(source_root, reference):
    """Return deterministic observations; never execute or authorize a build."""
    validate_reference(reference)
    root = Path(source_root).resolve(); texts = {}; inputs = {}
    for role in sorted(ORIGINAL_ROLES):
        entry = reference['sources'][role]; data = checked(root, entry['path']).read_bytes()
        require(digest(data) == entry['sha256'], 'Changed reference source: '+role)
        texts[role] = data.decode('utf-8-sig'); inputs[entry['path']] = digest(data)
    project = parse_project(texts['project']); template = parse_template(texts['template'])
    module = template_module(texts['template'])
    example = parse_example_ecc(texts['example'])
    selected = {n for n in template if not re.match(r'c[1-9]_', n)} | set(expected_ports()) | {
        'c0_app_ecc_single_err', 'c0_app_ecc_multiple_err'}
    inventory = xml(texts['component'])
    selected |= {value(p,'s:name') for p in inventory.findall('s:model/s:ports/s:port',NS)
                 if value(p,'s:name').startswith('c0_')}
    component = parse_component(texts['component'], selected)
    problems = []
    if module != project['module']: problems.append('TEMPLATE_MODULE')
    expected_project = dict(module=PROFILE['module'], controllers=2, target='xc7k480t-ffg1156/-2',
        system_clock='Differential', reference_clock='Use System Clock', sys_reset='ACTIVE LOW',
        interface='AXI', ecc='Enabled', phy_ratio='4:1', physical_dq_width=72, size_bytes=2147483648,
        input_clock_mhz=200, memory_period_ps=1875, address_width=31, data_width=512, id_width=4, narrow_bursts=0)
    for key, expected in expected_project.items():
        if project[key] != expected: problems.append('PROJECT_CONFIGURATION:'+key)
    for name, expected in expected_ports().items():
        if template.get(name) != expected: problems.append('TEMPLATE_REQUIRED_PORT:'+name)
    for name in sorted(selected):
        a, b = template.get(name), component['ports'].get(name)
        if a is None and b is not None and not b['enabled'] and not b['cached_enabled']:
            continue
        if a is None or b is None:
            problems.append('PORT_MISSING:'+name); continue
        if not b['enabled']: problems.append('COMPONENT_DISABLED_PORT:'+name)
        if b['enabled'] != b['cached_enabled']: problems.append('COMPONENT_ENABLE_CACHE:'+name)
        if b['width'] != b['cached_width']: problems.append('COMPONENT_WIDTH_CACHE:'+name)
        if a != {key:b[key] for key in ('direction', 'width')}: problems.append('PORT_DECLARATION_CONFLICT:'+name)
    for name, observed in example['ports'].items():
        if template.get(name) != dict(direction='out',width=observed['width']):
            problems.append('EXAMPLE_TEMPLATE_CONFLICT:'+name)
    if example['phy_ratio'] != 4: problems.append('EXAMPLE_PHY_RATIO')
    parameter_expected = {'NoOfControllers':2,'C0_USE_AXI':1,'C0_ECC':'ON','C0_MEM_TYPE':'DDR3',
                          'C0_DDRX_nCK_PER_CLK':4,'C0_C_S_AXI_ADDR_WIDTH':31,
                          'C0_C_S_AXI_DATA_WIDTH':512,'C0_C_S_AXI_ID_WIDTH':4}
    for key, expected in parameter_expected.items():
        actual = component['parameters'].get(key)
        if type(actual) is not type(expected) or actual != expected: problems.append('COMPONENT_PARAMETER:'+key)
    expected_bindings={'C0_CLOCK':('c0_ui_clk','CLK',dict(FREQ_HZ=133333333,ASSOCIATED_BUSIF='S0_AXI:S0_AXI_CTRL',
        ASSOCIATED_RESET='c0_aresetn:c0_ui_clk_sync_rst',CLK_DOMAIN='top_mig_7series_0_0_c0_ui_clk')),
        'C0_RESET':('c0_ui_clk_sync_rst','RST',dict(POLARITY='ACTIVE_HIGH')),
        'C0_ARESETN':('c0_aresetn','ARESETN',dict(POLARITY='ACTIVE_LOW')),
        'SYSTEM_RESET':('sys_rst','RST',dict(POLARITY='ACTIVE_LOW'))}
    for name,(port,logical,parameters) in expected_bindings.items():
        actual=component['clock_reset_bindings'].get(name)
        if actual is None or actual['port'] != port or actual['logical_port'] != logical or actual['parameters'] != parameters or \
                actual['cached_parameters'] != parameters or not actual['enabled'] or not actual['cached_enabled']:
            problems.append('CLOCK_RESET_BINDING:'+name)
    # These exact generated files are named by the original file-list metadata.
    # Presence is only an observation, never a claim that HDL is a real controller.
    ip = PurePosixPath(reference['sources']['template']['path']).parent
    generated = []
    for entry in reference['missing_generated_sources']['referenced_by_file_list']:
        name = str(ip/safe_relative(entry['path']))
        require(entry['path'] in texts['file_list'], 'Generated path absent from source file list')
        path = checked(root, name)
        item = dict(path=name, exists=path.is_file(), implementation_verified=False)
        if path.is_file():
            data = path.read_bytes(); item['sha256'] = inputs[name] = digest(data)
        generated.append(item)
    controller = 'PRESENT_UNQUALIFIED' if generated and all(v['exists'] for v in generated) else 'MISSING_GENERATED_CONTROLLER'
    blockers = [controller] + (['ECC_PORT_METADATA_CONFLICT'] if problems else []) + BLOCKERS
    return dict(schema_version=1, status='BLOCKED_DDR_INTEGRATION',
        scope='Original channel-0 source metadata audit only; no generated-controller admission or physical proof',
        interface_status='INCONSISTENT_SOURCE_INTERFACE' if problems else 'CONSISTENT_SOURCE_INTERFACE_ONLY',
        reference_sha256=digest(canonical(reference)), inputs=dict(files=inputs, sha256=digest(canonical(inputs))),
        project=project, template_module=module, template_ports={n:template[n] for n in sorted(selected) if n in template},
        component=component, example_ecc=example, conflicts=sorted(problems), generated_sources=generated,
        controller_source_status=controller, blockers=blockers,
        external_reference_only={k:v for k,v in reference['sources'].items() if k not in ORIGINAL_ROLES},
        external_references_revalidated=False, physical_integration_ready=False,
        controller_implementation_verified=False, vivado_executed=False, hardware_accessed=False)


def verify(report, source_root, reference):
    current = audit(source_root, reference)
    require(type(report) is dict and canonical(report) == canonical(current), 'Changed source audit/report contract')
    return current
