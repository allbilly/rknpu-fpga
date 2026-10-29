"""Exact operational library-path correction and fail-closed build diagnostics.

No RTL, generated C++, model, operand or numerical expectation is changed.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile

from evidence import ROOT


def verify_preserved_errors(index_path):
    index = json.loads(index_path.read_text())
    assert index['status'] == 'ARCHIVED_ACTUAL_FULL_PREFIX_MAPPED_REPLAY_WITH_UNADMITTED_AR_TOOL_ERRORS'
    assert index['actual_full_binary_fixture_comparisons_matched'] is True
    assert index['complete_build_diagnostics_accepted'] is index['full_mapped_gate_accepted'] is False
    archive = index_path.parent / 'evidence.tar.gz'
    with archive.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == index['archive_sha256']
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        assert len(members) == index['verified_members'] == len(index['member_sha256'])
        assert {m.name for m in members} == set(index['member_sha256'])
        for member in members:
            assert member.isfile()
            assert hashlib.sha256(tar.extractfile(member).read()).hexdigest() == index['member_sha256'][member.name]
        report = json.loads(tar.extractfile(index['report']).read())
        compile_step = next(step for step in report['commands'] if Path(step['log']).stem == 'top_compile')
        text = tar.extractfile(compile_step['log']).read().decode()
    errors = [line for line in text.splitlines() if line.startswith('ar:')]
    assert errors == index['archive_merge_errors'] and len(errors) == 2
    assert compile_step['returncode'] == 0 and all('No such file or directory' in line for line in errors)
    template_names = [name for name in index['member_sha256'] if name.endswith('/observed_verilated_make_template.mk')]
    assert len(template_names) == 1
    template = ROOT / template_names[0]
    assert hashlib.sha256(template.read_bytes()).hexdigest() == index['member_sha256'][template_names[0]]
    return index, template


def relative_hierarchy_library(text, obj, library):
    """Change only one generated make variable; prove both path resolutions."""
    obj, library = obj.resolve(), library.resolve()
    assert library.is_file() and library.suffix == '.a'
    assert text == f'VM_HIER_LIBS := {library}\n', 'Unexpected generated hierarchy makefile'
    relative = os.path.relpath(library, obj)
    assert re.fullmatch(r'[A-Za-z0-9_./-]+', relative), 'Unsafe make/archive path'
    assert not Path(relative).is_absolute() and (obj / relative).resolve() == library
    extraction = obj / 'temporary_archive.tmpdir' / library.name
    assert (extraction / ('../../' + relative)).resolve() == library
    changed = f'VM_HIER_LIBS := {relative}\n'
    return changed, dict(original_library_path=str(library), relative_library_path=relative,
        make_dependency_resolves_to_same_library=True, stock_archive_extraction_resolves_to_same_library=True,
        changed_generated_variable='VM_HIER_LIBS', rtl_or_generated_cpp_changed=False)


def require_clean_build(text):
    # GNU make's archive shell recipe can return zero after failed ar commands.
    # Reject tool diagnostics independently of the final exit status.
    tools = r'(?:[\w.+-]+-)?(?:ar|ranlib|ld(?:\.bfd|\.gold|\.lld)?|collect2|nm|objcopy|strip)'
    assert not re.search(r'^\s*(?:[^\s:]+/)?' + tools + r':', text, re.M), 'Archive/link tool diagnostic'
    assert not re.search(r'\b(?:fatal error|error|warning):|undefined reference|cannot find|command not found|No such file or directory|\*\*\*', text, re.I), 'Build diagnostic'


def validate_archive_members(kernel_text, merged_text, top_objects):
    """Every original kernel object must actually be merged, not just linked later."""
    kernel, merged = kernel_text.splitlines(), merged_text.splitlines()
    assert kernel and top_objects and all(re.fullmatch(r'[A-Za-z0-9_.+-]+\.o', name) for name in kernel + merged + top_objects)
    expected = Counter(kernel) + Counter(top_objects)
    assert Counter(merged) == expected, 'Missing, additional or duplicated merged archive object'
    return dict(kernel_object_count=len(kernel), top_object_count=len(top_objects),
        merged_object_count=len(merged), exact_member_multiset_verified=True)
