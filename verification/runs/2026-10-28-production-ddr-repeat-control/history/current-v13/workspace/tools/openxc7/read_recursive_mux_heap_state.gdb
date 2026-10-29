# Bounded read-only solver state; no inferior calls, writes or algorithm edits.
# Detach in finally, including unsupported layouts or debugger-read failures.
set pagination off
set print frame-arguments none
set may-call-functions off
python
import gdb
import json
try:
    gdb.execute('frame function nextpnr_himbaechel::HeAPPlacer::StrictLegaliser::legalise_cell', to_string=True)
    frame = gdb.selected_frame()
    cell = frame.read_var('ci').dereference()
    solver = frame.read_var('this').dereference()
    context = solver['ctx'].dereference()
    vector = context['idstring_idx_to_str'].dereference()['_M_impl']
    table = vector['_M_start']
    strings = int(vector['_M_finish'] - table)
    if not 0 < strings <= 16000000:
        raise gdb.GdbError('Unsupported native identifier-table bounds')
    def text(identifier):
        index = int(identifier['index'])
        if not 0 <= index < strings:
            raise gdb.GdbError('Out-of-range native identifier')
        value = table[index].dereference()
        length = int(value['_M_string_length'])
        if not 0 <= length <= 4096:
            raise gdb.GdbError('Unsupported native identifier length')
        return value['_M_dataplus']['_M_p'].string(encoding='utf-8', length=length)
    children = cell['constr_children']['_M_impl']
    count = int(children['_M_finish'] - children['_M_start'])
    if not 0 <= count <= 64:
        raise gdb.GdbError('Refusing unbounded native cluster traversal')
    def row(value):
        return dict(name=text(value['name']), type=text(value['type']), cluster=text(value['cluster']),
            x=int(value['constr_x']), y=int(value['constr_y']), z=int(value['constr_z']),
            absolute_z=bool(value['constr_abs_z']),
            bel=dict(tile=int(value['bel']['tile']), index=int(value['bel']['index'])))
    queue = solver['remaining']['c']['_M_impl']
    remaining = int(queue['_M_finish'] - queue['_M_start'])
    if not 0 <= remaining <= 600000:
        raise gdb.GdbError('Unsupported native legalizer queue bounds')
    state = dict(native_pid=gdb.selected_inferior().pid, children=count, identifier_count=strings,
        remaining_queued_entries=remaining, root=row(cell),
        members=[row(children['_M_start'][i].dereference()) for i in range(count)],
        counters={name:int(solver[name]) for name in ('radius', 'iter', 'iter_at_radius',
            'total_iters_for_cell', 'total_iters', 'total_iters_noreset', 'need_to_explore')},
        best_bel=dict(tile=int(solver['bestBel']['tile']), index=int(solver['bestBel']['index'])),
        currently_placed=bool(solver['placed']), inferior_calls_or_writes=False)
    gdb.write('READ_ONLY_HEAP_STATE_JSON ' + json.dumps(state, sort_keys=True) + '\n')
finally:
    gdb.execute('detach')
end
