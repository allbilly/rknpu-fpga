# Read-only diagnostic, not a placement/legality acceptance or native patch.
# Caller selects the audited PID and logging file, then detaches afterwards.
set pagination off
set may-call-functions off
frame function nextpnr_himbaechel::HeAPPlacer::StrictLegaliser::legalise_cell
python
import gdb
cell = gdb.selected_frame().read_var('ci').dereference()
solver = gdb.selected_frame().read_var('this').dereference()
table = solver['ctx'].dereference()['idstring_idx_to_str'].dereference()['_M_impl']['_M_start']
def text(identifier):
    return table[int(identifier['index'])].dereference()['_M_dataplus']['_M_p'].string()
name = text(cell['name'])
gdb.write('READ_ONLY_CLUSTER_ROOT ' + name + '\n')
if name != 'rk_mapped_cell_86668.rk_mapped_cell_22977':
    raise gdb.GdbError('Audited cell has advanced; this snapshot does not describe the old mux.')
children = cell['constr_children']['_M_impl']
count = int(children['_M_finish'] - children['_M_start'])
if not 0 < count <= 64:
    raise gdb.GdbError('Unexpected mux-cluster size; refusing unbounded memory traversal.')
gdb.write('attempts=%d radius=%d entries=%d children=%d\n' %
          (int(solver['total_iters_for_cell']), int(solver['radius']),
           int(solver['total_iters_noreset']), count))
for offset in range(-1, count):
    item = cell if offset == -1 else children['_M_start'][offset].dereference()
    gdb.write('%s type=%s cluster=%s relative=(%d,%d,%d) abs_z=%s bel=%s\n' %
              (text(item['name']), text(item['type']), text(item['cluster']),
               int(item['constr_x']), int(item['constr_y']), int(item['constr_z']),
               str(item['constr_abs_z']), str(item['bel'])))
end
