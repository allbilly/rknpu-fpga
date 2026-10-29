"""Admission controls: per-instance counting and rejection of ambiguous trees."""
import copy
import unittest
from tools.tinystories.joined_hierarchy import census, EXPECTED


def fixture():
    names=['tb_jtag_dual_bram']+list(EXPECTED)
    nodes={name:dict(type='MODULE',addr=f'({i})',name=name,origName=name,stmtsp=[])
           for i,name in enumerate(names)}
    def add(parent,child,count=1):
        nodes[parent]['stmtsp'] += [dict(type='CELL',name=f'{child}_{i}',modp=nodes[child]['addr']) for i in range(count)]
    add('tb_jtag_dual_bram','rk_jtag_dual_bram')
    for name in ('rk_jtag_backend','rk_shared_bram_regport','rk_ew_dma','rk_cmac_success_rearm'):
        add('rk_jtag_dual_bram',name)
    add('rk_jtag_dual_bram','rk_job_control',2)
    add('rk_cmac_success_rearm','rk_cmac_array_dma')
    add('rk_cmac_array_dma','rk_cmac_fp16_array_dsp_prefix_pipe')
    add('rk_cmac_fp16_array_dsp_prefix_pipe','rk_cmac_fp16_cell_dsp_prefix_pipe',16)
    add('rk_cmac_fp16_cell_dsp_prefix_pipe','rk_cmac_fp16_lane_dsp_prefix',32)
    add('rk_cmac_fp16_lane_dsp_prefix','rk_cmac_fp16_discarded_carry')
    packages=[dict(type='PACKAGE',addr='($unit)',name='$unit',inLibrary=True),
              dict(type='PACKAGE',addr='(std)',name='std',inLibrary=True)]
    return dict(type='NETLIST',modulesp=list(nodes.values())+packages,dollarUnitPkgp='($unit)',stdPackagep='(std)'),nodes


class JoinedHierarchyTests(unittest.TestCase):
    def test_shared_module_definition_counts_all512_instances(self):
        tree,_=fixture()
        self.assertEqual(census(tree),EXPECTED)

    def test_removed_lane_or_kernel_is_not_accepted(self):
        for name in ('rk_cmac_fp16_cell_dsp_prefix_pipe','rk_cmac_fp16_array_dsp_prefix_pipe'):
            tree,nodes=fixture();nodes[name]['stmtsp'].pop()
            with self.subTest(name=name),self.assertRaises(ValueError):census(tree)

    def test_unknown_or_forged_system_package_fails(self):
        for mutation in ('name','reference','kind'):
            tree,_=fixture()
            if mutation=='name':tree['modulesp'][-1]['name']='user_package'
            elif mutation=='reference':tree['stdPackagep']='wrong'
            else:tree['modulesp'][-1]['type']='UNKNOWN'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):census(tree)

    def test_cell_cannot_resolve_to_package_or_black_box(self):
        for target in ('(std)','missing'):
            tree,nodes=fixture();nodes['rk_jtag_dual_bram']['stmtsp'][0]['modp']=target
            with self.subTest(target=target),self.assertRaises(ValueError):census(tree)

    def test_recursive_fallback_and_unelaborated_generates_fail(self):
        for mutation in ('recursive','fallback','generate'):
            tree,nodes=fixture()
            lane=nodes['rk_cmac_fp16_lane_dsp_prefix']
            if mutation=='recursive':lane['stmtsp'][0]['modp']=nodes['rk_cmac_fp16_array_dsp_prefix_pipe']['addr']
            elif mutation=='fallback':lane['origName']='rk_cmac_fp16_lane_dsp'
            else:lane['stmtsp'].append(dict(type='GENFOR'))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):census(tree)

    def test_duplicate_nodes_or_root_fail(self):
        tree,_=fixture();tree['modulesp'].append(copy.deepcopy(tree['modulesp'][0]))
        with self.assertRaises(ValueError):census(tree)
        tree,nodes=fixture();extra=copy.deepcopy(nodes['tb_jtag_dual_bram']);extra['addr']='(extra)';tree['modulesp'].append(extra)
        with self.assertRaises(ValueError):census(tree)


if __name__=='__main__':unittest.main()
