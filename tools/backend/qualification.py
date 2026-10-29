"""Admission for the production-backend-to-frame-RTL simulation increment."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import struct

from tools.host.qualification import digest, fingerprint, safe_path

ROOT = Path(__file__).resolve().parents[2]
PIN = '078eee94d8f1912bb63ce786c250d2c24984844a'
RTL = ['rtl/' + name + '.sv' for name in (
    'rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma', 'rk_bram', 'rk_job_control')
] + ['rtl/host/rk_jtag_backend.sv', 'rtl/host/rk_jtag_ew_bram.sv']


def source_inputs():
    return sorted(RTL + [
        'tools/backend/__init__.py', 'tools/backend/runtime.py', 'tools/backend/rtl_link.py',
        'tools/backend/worker.py', 'tools/backend/run.py', 'tools/backend/qualification.py',
        'tests/backend/test_runtime.py', 'tests/backend/rtl_endpoint.cpp',
        'tests/backend/test_trace_contract.py', 'tests/backend/test_runner.py', 'tests/backend_ew_captures.json', 'tools/evidence.py',
        'tools/host/transport.py', 'tools/host/qualification.py',
        'model/__init__.py', 'model/half.py', 'model/profile.py', 'model/sim.py', 'model/dma.py',
    ])


def source_revision(root=ROOT):
    return fingerprint(source_inputs(), root)


def specs():
    return [{'name': f'{op.lower()}_{count}', 'operation': op, 'count': count, 'repeat': 1}
            for op in ('ADD', 'SUB', 'MUL') for count in (8, 9, 33)] + [
            {'name': 'repeat_sub_9', 'operation': 'SUB', 'count': 9, 'repeat': 2},
            {'name':'reject_runtime_gather','operation':'ADD','count':9,'repeat':1,'expect_reject_runtime_gather':True}]


def binary_path(out):
    return str(Path(out) / 'obj/endpoint')


def build_argv(compiler, execution_root, out):
    root = Path(execution_root)
    return [compiler, '--cc', '--exe', '--build', '--assert', '-Wall', '-j', '2',
            '--top-module', 'rk_jtag_ew_bram', '--Mdir', str(root/out/'obj'), '-o', 'endpoint'] + [
            str(root/name) for name in RTL + ['tests/backend/rtl_endpoint.cpp']]


def run_argv(report, spec):
    root, out = Path(report['execution_root']), report['output_directory']
    return [report['python'], str(root/'tools/backend/worker.py'), '--backend', report['backend_root'],
            '--endpoint', str(root/binary_path(out)), '--out', str(root/out/spec['name']),
            '--operation', spec['operation'], '--count', str(spec['count']), '--repeat', str(spec['repeat'])] + (
            ['--expect-reject-runtime-gather'] if spec.get('expect_reject_runtime_gather') else [])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    require(isinstance(value, dict) and set(value) == {'base64', 'sha256', 'size'}, 'missing raw byte receipt')
    data = base64.b64decode(value['base64'], validate=True)
    require(len(data) == value['size'] and hashlib.sha256(data).hexdigest() == value['sha256'], 'raw byte receipt mismatch')
    return data


def validate_pipeline(worker, directory):
    """Bind the observed original code-object calls and locally compiled images."""
    pipeline = worker['pipeline']
    counts = pipeline['calls']
    locations = {
        'to_program':('tinygrad/codegen/__init__.py',484),
        'do_to_program':('tinygrad/codegen/__init__.py',454),
        'render':('tinygrad/renderer/rockchip.py',1479),
        'program_init':('tinygrad/runtime/ops_rockchip.py',87),
        'submit_bodies':('tinygrad/runtime/ops_rockchip.py',109),
        'submit':('tinygrad/runtime/ops_rockchip.py',93),
        'regular_gather':('tinygrad/runtime/ops_rockchip.py',23),
    }
    require(set(counts) == set(locations) and pipeline['foreign_compilation'] == [],
            'unverified or unexpected compilation target')
    rejected = worker.get('expect_reject_runtime_gather') is True
    required = ('to_program','do_to_program','render') if rejected else tuple(n for n in locations if n != 'regular_gather')
    require(counts['regular_gather'] == 0 and all(type(counts[n]) is int and counts[n] >= 1 for n in required),
            'original compiler/writer execution missing')
    require(counts['submit'] == counts['submit_bodies'] == (0 if rejected else worker['repeat']), 'writer execution count changed')
    if rejected:require(counts['program_init'] == 0, 'rejected graph entered the original runtime')
    backend = worker['backend']
    require(backend['clean'] is True and backend['commit'] == PIN and
            backend['pinned_files'].get('tinygrad/codegen/__init__.py') ==
            '182eb030bf673c2b5d342a005e0f9bbe5fa0f0dd0e802194e316e8cfba289e75',
            'production codegen source identity missing')
    require(set(pipeline['code']) == set(locations), 'pipeline code-object identity omitted')
    for name,(filename,line) in locations.items():
        require(pipeline['code'][name] == {'file':filename,'line':line,'source_sha256':backend['pinned_files'][filename]},
                'pipeline code identity changed')
    images = sorted(Path(directory).glob('program-*.bin'))
    require(len(images) == counts['program_init'] and [digest(p) for p in images] == pipeline['compiler_images'],
            'original compiled program images missing')
    return dict(counts)


def validate_execution(worker, trace, spec):
    """Compare actual transport bytes and post-execution BOs; never a runtime fallback."""
    from model.dma import DMAEmulator
    from model.half import alu, to_bits
    from model.sim import Memory

    require(worker.get('status') == 'PASS' and worker.get('native_returncode') == 0, 'worker/native execution failed')
    require(worker.get('numeric_cpu_fallback') is False and worker.get('hardware_access') is False, 'wrong execution scope')
    for key in ('operation', 'count', 'repeat'):
        require(worker.get(key) == spec[key], 'worker scenario mismatch')
    require(worker['backend']['commit'] == PIN, 'wrong production backend revision')
    if spec.get('expect_reject_runtime_gather'):
        require(worker.get('expect_reject_runtime_gather') is True and worker.get('expected_hex') is None and
                worker.get('outputs') == [] and worker.get('submissions') == [] and worker.get('submission_count') == 0 and
                worker.get('expected_rejection') == 'Runtime CPU gathers or post-EW layout operations are unsupported',
                'unsupported runtime gather was not explicitly rejected')
        frames = 0
        for line in Path(trace).read_text().splitlines():
            event = json.loads(line);packet = int(event['frame'],16)
            if not packet:continue
            opcode = packet >> 548 & 255
            require(opcode in (1,3,4), 'rejected graph reached descriptor/control writes')
            frames += 1
        require(frames == worker['frame_commands'], 'rejection trace coverage missing')
        return {'submissions':0,'tasks':0,'whole_bo_bytes_checked':0,'frame_commands':frames}
    count, op = spec['count'], spec['operation']
    a = [to_bits((i%13-6)/4) for i in range(count)]
    b = [to_bits((i%7-3)/2) for i in range(count)]
    expected = struct.pack('<'+'H'*count, *(alu(x,y,op) for x,y in zip(a,b))).hex()
    require(worker.get('expected_hex') == expected and worker.get('outputs') == [expected]*spec['repeat'],
            'production Tensor output mismatch')
    submissions = worker['submissions']
    require(len(submissions) == worker['submission_count'] == spec['repeat'], 'missing/repeated submission')
    memory, registers, submitted, frames = {}, {}, 0, 0
    pending = None
    total_tasks, total_memory = 0, 0
    for line in Path(trace).read_text().splitlines():
        event = json.loads(line)
        require(set(event) == {'frame', 'rtl_response'}, 'unexpected frame trace fields')
        packet = int(event['frame'], 16)
        response = int(event['rtl_response'], 16)
        require(len(event['frame']) == len(event['rtl_response']) == 160, 'truncated wire frame')
        require(response >> 536 & 0xffffffff == 0x4f54504a and response >> 568 == 0, 'response framing changed')
        if not packet:
            continue
        frames += 1
        require(packet >> 572 & 0xffffffff == 0x4f54504a and packet >> 604 == 0, 'request framing changed')
        opcode, address = packet >> 548 & 255, packet >> 512 & 0xffffffff
        data, seq = packet & ((1<<512)-1), packet >> 556 & 0xffff
        require(packet >> 544 & 15 == 15, 'unexpected transport strobes')
        require(response >> 520 & 0xffff == seq and response >> 512 & 255 == 0, 'uncorrelated/failed RTL command')
        if opcode == 4:
            require(pending is None, 'Host data write before pending job readback and ACK')
            require(address % 64 == 0 and 0x10000000 <= address <= 0x100fffc0, 'bulk upload range changed')
            for i, byte in enumerate(data.to_bytes(64, 'little')):
                memory[address+i] = byte
        elif opcode == 2:
            require(data >> 32 == 0, 'unexpected register payload')
            registers[address] = data
            if address == 0x0c and data == 1:
                require(pending is None, 'new job before prior output readback/ACK')
                require(submitted < len(submissions), 'unexpected wire submission')
                job = submissions[submitted]
                require(job['status'] == 'PASS', 'driver submission failed')
                require((registers.get(0x10), registers.get(0x14), registers.get(0x18)) ==
                        (job['address'], job['amount'], job['tag']), 'descriptor changed before hardware submission')
                before = {int(k): raw(v) for k,v in job['before'].items()}
                after = {int(k): raw(v) for k,v in job['after'].items()}
                require(before.keys() == after.keys(), 'BO inventory changed during job')
                for base, image in before.items():
                    require(all(base+i in memory for i in range(len(image))), 'BO/padding not uploaded in full')
                    require(bytes(memory[base+i] for i in range(len(image))) == image, 'BO bytes changed in transport')
                tasks = job['tasks']
                require(len(tasks) == job['task_count'] == (2 if op == 'SUB' else 1), 'task count mismatch')
                require(type(job['command_bytes']) is list and len(job['command_bytes']) == len(tasks),
                        'incomplete or extra per-task command receipt inventory')
                task_fields = ('flags', 'op_idx', 'enable_mask', 'int_mask', 'int_clear',
                               'int_status', 'regcfg_amount', 'regcfg_offset', 'regcmd_addr')
                fixed_fields = dict(flags=0, op_idx=4, enable_mask=0x18, int_mask=0x300,
                                    int_clear=0x1ffff, int_status=0, regcfg_offset=0)
                for desc in tasks:
                    require(type(desc) is dict and set(desc) == set(task_fields) and
                            all(type(desc[name]) is int and 0 <= desc[name] <
                                (1 << (64 if name == 'regcmd_addr' else 32)) for name in task_fields),
                            'invalid raw task descriptor fields')
                    require(all(desc[name] == value for name, value in fixed_fields.items()) and
                            4 <= desc['regcfg_amount'] <= 65539,
                            'unsupported raw task descriptor values')
                packed_tasks = b''.join(struct.pack('<8IQ', *(desc[name] for name in task_fields)) for desc in tasks)
                require(raw(job['task_bytes']) == packed_tasks, 'raw task bytes differ from recorded descriptors')
                require(any(len(image) >= 16384 and image.startswith(packed_tasks) for image in before.values()),
                        'raw task descriptors missing from uploaded task BO')
                require(job['address'] == tasks[0]['regcmd_addr'] and job['amount'] == tasks[0]['regcfg_amount'], 'first descriptor rewritten')
                for desc, command in zip(tasks, job['command_bytes']):
                    body = raw(command)
                    require(len(body) == 8*desc['regcfg_amount'], 'raw command amount changed')
                    base = next((base for base,image in before.items()
                                 if base <= desc['regcmd_addr'] and desc['regcmd_addr']+len(body) <= base+len(image)), None)
                    require(base is not None, 'commands outside owned BO')
                    offset = desc['regcmd_addr']-base
                    require(before[base][offset:offset+len(body)] == body, 'raw commands changed after final writer')
                reference = Memory()
                for base, image in before.items():
                    reference.map(base, image)
                emulator = DMAEmulator(reference)
                emulator.submit_dma(job['address'], job['amount'])
                require(emulator.completed == len(tasks), 'oracle task count mismatch')
                require({base: bytes(image) for base,image in reference.regions.items()} == after,
                        'actual complete BO memory differs from independent raw-DMA oracle')
                # Subsequent protocol reads must return the actual post-job bytes,
                # including intermediate scratch, padding, guards and inputs.
                for base, image in after.items():
                    memory.update((base+i, byte) for i,byte in enumerate(image))
                result = job['result']
                require(result['tag'] == job['tag'] and result['completed_tasks'] == len(tasks) and result['error_code'] == 0,
                        'FPGA completion mismatch')
                pending = {'addresses': {base+i for base,image in after.items() for i in range(len(image))},
                           'read': set(), 'registers': {}, 'tag': job['tag'], 'tasks': len(tasks)}
                submitted += 1
                total_tasks += len(tasks)
                total_memory += sum(map(len, before.values()))
            elif address == 0x0c and data == 2:
                require(pending is not None and pending['read'] >= pending['addresses'],
                        'ACK before every actual BO byte was read from RTL')
                registers_read = pending['registers']
                require(registers_read.get(0x1c) == pending['tag'] and registers_read.get(0x20) == pending['tasks'] and
                        registers_read.get(0x24) == 0 and registers_read.get(8,0) & 0x6e == 4,
                        'completion not supported by actual RTL register reads')
                pending = None
        elif opcode == 3:
            actual = (response & ((1<<512)-1)).to_bytes(64, 'little')
            # Before allocation uploads, the two-state model's unused BRAM is
            # not accepted as evidence of physical SRAM initialization.
            if all(address+i in memory for i in range(64)):
                require(actual == bytes(memory[address+i] for i in range(64)), 'readback differs from observed job memory')
            if pending is not None:
                pending['read'].update(range(address,address+64))
        else:
            require(opcode == 1, 'unknown wire opcode')
            if pending is not None:
                pending['registers'][address] = response & 0xffffffff
    require(submitted == spec['repeat'] and pending is None and frames == worker['frame_commands'], 'trace coverage mismatch')
    return {'submissions': submitted, 'tasks': total_tasks, 'whole_bo_bytes_checked': total_memory,
            'frame_commands': frames}


def verify_report(path, source_root=ROOT, artifact_root=ROOT):
    report = json.loads(Path(path).read_text())
    require(report.get('status') == 'PASS' and report.get('execution_schema') == 1, 'incomplete backend qualification')
    require(report['source_revision'] == source_revision(source_root), 'backend qualification source changed')
    require(report['backend_commit'] == PIN, 'wrong audited backend pin')
    artifacts = report['artifacts']
    require(fingerprint(artifacts['files'], artifact_root) == artifacts, 'backend artifacts changed')
    commands = {c['name']: c for c in report['commands']}
    require(len(commands) == len(report['commands']), 'duplicate execution record')
    for command in commands.values():
        require(command['status'] == 'PASS' and command['returncode'] == 0, 'failed qualification command')
        require(artifacts['files'].get(command['log']) == command['log_sha256'], 'command log binding changed')
    for name, tool, field in (('version','compiler','tool_version'),('cxx_version','cxx','cxx_version')):
        require(commands[name]['argv'] == [report[tool]['path'],'--version'], 'tool version selection changed')
        require(report[field] in safe_path(artifact_root,commands[name]['log']).read_text(), 'tool version has no log evidence')
    require(commands['compile']['argv'] == build_argv(report['compiler']['path'], report['execution_root'], report['output_directory']),
            'native compile profile changed')
    binary = binary_path(report['output_directory'])
    image = {'path': binary, 'sha256': artifacts['files'][binary]}
    require(commands['compile']['binary'] == image, 'compile image missing')
    require([t['spec'] for t in report['tests']] == specs(), 'backend scenario inventory changed')
    for test, spec in zip(report['tests'], specs()):
        command = commands[spec['name']]
        require(command['argv'] == run_argv(report, spec), 'production runtime invocation changed')
        require(command['binary_before'] == image and command['binary_after'] == image, 'executed image changed')
        passes = [line for line in safe_path(artifact_root, command['log']).read_text().splitlines() if line.startswith('PASS ')]
        expected = ('PASS backend_runtime_gather explicitly_rejected_before_final_writer_and_submission' if
                    spec.get('expect_reject_runtime_gather') else
                    f'PASS backend_tensor {spec["operation"]} count={spec["count"]} repeats={spec["repeat"]} actual_final_writer_and_RTL')
        require(passes == test['results'] == [expected], 'worker result not supported by actual log')
        directory = Path(report['output_directory']) / spec['name']
        worker = json.loads(safe_path(artifact_root, str(directory/'report.json')).read_text())
        require(validate_pipeline(worker,safe_path(artifact_root,str(directory))) == test['pipeline_calls'],
                'compiler execution evidence changed')
        scope = validate_execution(worker, safe_path(artifact_root, str(directory/'frames.jsonl')), spec)
        require(scope == test['coverage'], 'backend numerical/wire coverage changed')
    unit = commands['unit']
    require(unit['argv'][1:] == ['-m','unittest','discover','-s','tests/backend','-p','test_runtime.py','-v'], 'unit selection changed')
    unit_log = safe_path(artifact_root, unit['log']).read_text()
    require(re.search(r'Ran [1-9][0-9]* tests? in ',unit_log) is not None and unit_log.rstrip().endswith('OK'),
            'runtime unit tests did not pass')
    trace_unit = commands['trace_unit']
    require(trace_unit['argv'][1:] == ['-m','unittest','discover','-s','tests/backend','-p','test_trace_contract.py','-v'],
            'trace-control selection changed')
    log = safe_path(artifact_root,trace_unit['log']).read_text()
    require(re.search(r'Ran 9 tests in ',log) is not None and log.rstrip().endswith('OK'), 'trace controls did not pass')
    runner_unit = commands['runner_unit']
    require(runner_unit['argv'][1:] == ['-m','unittest','discover','-s','tests/backend','-p','test_runner.py','-v'],
            'runner-control selection changed')
    log = safe_path(artifact_root,runner_unit['log']).read_text()
    require(re.search(r'Ran 2 tests in ',log) is not None and log.rstrip().endswith('OK'), 'runner controls did not pass')
    require(set(commands) == {'version','cxx_version','unit','trace_unit','runner_unit','compile'} | {s['name'] for s in specs()}, 'unexpected command selection')
    return report
