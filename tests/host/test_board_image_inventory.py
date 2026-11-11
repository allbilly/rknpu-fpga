"""Offline checker for the multi-image deployment inventory in BOARD_RUN_PREP.

Reads only repo files: the document, the bitstreams it names, and the host
entry points it lists. It never opens the cable, lease, a server or a socket,
and it treats explicit ``PENDING task-9``/``PENDING task-10`` placeholders as
allowed-but-not-loadable inventory rows (the real SHAs must be filled in when
those builds land).
"""
import hashlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from tools.host import run_jtag_dual_hardware as hw  # noqa: E402

DOC = ROOT / 'docs/BOARD_RUN_PREP.md'
SHA256_RE = re.compile(r'\b([0-9a-f]{64})\b')
BACKTICK_RE = re.compile(r'`([^`]+)`')
PENDING_RE = re.compile(r'PENDING task-(9|10)')
EW_SHA = 'b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a'


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def section(text, start_heading, end_heading):
    start = text.index(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]


def table_rows(block):
    rows = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if all(set(cell) <= set('-: ') for cell in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []  # drop header row


def exists_token(token):
    token = token.strip()
    if not token:
        return False
    if '*' in token:
        return bool(list(ROOT.glob(token)))
    return (ROOT / token).exists()


def repo_paths(text):
    paths = []
    for token in BACKTICK_RE.findall(text):
        if token.startswith(('build/', 'docs/', 'tools/', 'tests/', 'fpga/',
                             'verification/', 'handoff.md', 'progress.md')):
            paths.append(token)
    return paths


class MultiImageInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text()
        cls.inventory_block = section(cls.text, '### 15.1 Image inventory',
                                      '### 15.2 Volatile-load-only rule')
        cls.rows = table_rows(cls.inventory_block)

    def test_inventory_table_shape_and_families(self):
        self.assertGreaterEqual(len(self.rows), 6, 'inventory table lost rows')
        self.assertTrue(all(len(row) == 6 for row in self.rows),
                        'inventory rows must have 6 columns: family | image | '
                        'bitstream+sha | transport | coverage | status')
        joined = ' '.join(' '.join(row) for row in self.rows)
        for family in ('conv-simple', 'GEMM', 'pooling', 'ew-fp16',
                       'conv-fp16', 'ew-int'):
            self.assertIn(family, joined, f'inventory misses family {family}')
        # task-9 (EW) is emitted now; only the pooling-corpus row stays pending.
        self.assertNotIn('PENDING task-9', joined)
        self.assertIn('PENDING task-10', joined)
        self.assertIn(EW_SHA, joined)
        self.assertIn('SOURCE_INTACT_REVIEW_PENDING', joined)

    def test_real_bitstreams_exist_and_hashes_match(self):
        real_shas = {}
        for row in self.rows:
            family, image, bitstream, transport, coverage, status = row
            if image.startswith('PENDING') or image.startswith('not planned'):
                continue
            paths = repo_paths(bitstream)
            self.assertTrue(paths, f'{family}: real row needs a bitstream path')
            bit_paths = [token for token in paths if token.endswith('.bit')]
            self.assertEqual(len(bit_paths), 1,
                             f'{family}: expected exactly one .bit path')
            bit = ROOT / bit_paths[0]
            self.assertTrue(bit.is_file(), f'{family}: missing {bit}')
            shas = [value for value in SHA256_RE.findall(bitstream)]
            self.assertEqual(len(shas), 1, f'{family}: expected one SHA-256')
            self.assertEqual(sha_file(bit), shas[0],
                             f'{family}: SHA-256 does not match {bit}')
            self.assertNotIn(shas[0], real_shas,
                             f'{family}: duplicate bitstream SHA with {real_shas.get(shas[0])}')
            real_shas[shas[0]] = family
            receipt_dirs = [token for token in repo_paths(image)]
            for directory in receipt_dirs:
                self.assertTrue((ROOT / directory).is_dir(),
                                f'{family}: image receipt dir missing: {directory}')
            transport_paths = repo_paths(transport)
            self.assertTrue(transport_paths or 'pending task-9' in transport.lower()
                            or 'pending task-10' in transport.lower()
                            or 'simulation only' in transport.lower(),
                            f'{family}: no transport/entry point recorded')
            for entry in transport_paths:
                self.assertTrue(exists_token(entry),
                                f'{family}: missing transport path {entry}')
            self.assertTrue(coverage and status, f'{family}: empty coverage/status')
        expected = {
            '81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39',
            '73dd0365055b4664c2d8d05af634d05a754cc333808fd2ed1c5d974706c94cf7',
            EW_SHA,
        }
        self.assertEqual(set(real_shas), expected,
                         'real inventory rows must be exactly the adopted six-page, '
                         'historical four-page and emitted EW images')
        adopted = sha_file(ROOT / 'build/jtag-dual-image/20261109T160627Z/'
                                  'implementation/rk_jtag_dual.bit')
        self.assertEqual(adopted, '81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39')
        self.assertIn(adopted, real_shas, 'adopted six-page image is not in the inventory')
        ew_rows = [row for row in self.rows if 'ew-fp16' in row[0]]
        self.assertEqual(len(ew_rows), 1, 'expected exactly one EW image row')
        joined = ' '.join(ew_rows[0])
        for token in ('WNS +0.670', 'WHS +0.053', '6,157 LUTs', '256 BRAM',
                      '10,829/10,829', 'SOURCE_INTACT_REVIEW_PENDING',
                      'Missing board reviewer',
                      'PASS_SOURCE_REVIEWED_USER2_EW_BITSTREAM_EMISSION',
                      'ec9ecd41', '75fe964a…89c5'):
            self.assertIn(token, joined, f'EW row misses {token!r}')
        self.assertIn(EW_SHA, joined)
        dcp = ROOT / 'build/host-jtag-preparation/20261109T210015Z-emission/bitstream/image.dcp'
        self.assertTrue(dcp.is_file())
        self.assertEqual(sha_file(dcp),
                         '75fe964a6f6c29830a82f4635fd8ee44ed9fa1830e4db49d617bfcf2942689c5')

    def test_pending_rows_are_explicitly_unloadable(self):
        pending = [row for row in self.rows
                   if PENDING_RE.search(row[1]) or PENDING_RE.search(row[2])]
        self.assertGreaterEqual(len(pending), 1)
        for row in pending:
            family, image, bitstream, transport, coverage, status = row
            self.assertRegex(image, r'PENDING task-10')
            self.assertRegex(bitstream, r'PENDING task-10')
            self.assertIsNone(SHA256_RE.search(bitstream),
                              f'{family}: pending row must not carry a real SHA')
            self.assertIn('PENDING', status.upper())
        self.assertIn('cannot be loaded yet', self.text)

    def test_tooling_map_entry_points_exist(self):
        block = section(self.text, '### 15.4 Host tooling map', '## 16.')
        rows = table_rows(block)
        self.assertGreaterEqual(len(rows), 6, 'tooling map lost rows')
        self.assertTrue(all(len(row) == 5 for row in rows),
                        'tooling rows must have 5 columns')
        for row in rows:
            stage, entry, prerequisites, offline, status = row
            for token in repo_paths(entry) + repo_paths(offline):
                self.assertTrue(exists_token(token),
                                f'{stage}: tooling path missing: {token}')
            self.assertTrue(prerequisites or 'PENDING' in status.upper(),
                            f'{stage}: prerequisites are not recorded')
        joined = ' '.join(' '.join(row) for row in rows)
        self.assertIn('tools/host/run_jtag_dual_hardware.py', joined)
        self.assertIn('tools/host/jtag_preflight.py', joined)
        self.assertIn('tools/host/prepare.py', joined)
        self.assertIn('tools/host/run_jtag_dual.py', joined)

    def test_class_d_section_has_required_items_and_sources(self):
        block = section(self.text, '## 16. Class-D items', '## 17.')
        lowered = block.lower()
        for keyword in ('core_mask', 'subcore_task', 'pc_base_address',
                        'multi-task', 'dtype/shape', 'residual',
                        'conv_byk_c160_h14w14_oc320_k3x3',
                        'conv_h40_c160_h40w40_oc320_k3x3',
                        'conv_depthwise_3x3_c3_oc3_h11w28'):
            self.assertIn(keyword, lowered, f'class-D section misses {keyword}')
        # The class-D table ends at the §16.1 P1 subsection; the later
        # reference-hash table is not part of it.
        table_block = block[:block.index('### 16.1')]
        rows = table_rows(table_block)
        self.assertGreaterEqual(len(rows), 5, 'class-D table lost rows')
        self.assertTrue(all(len(row) == 4 for row in rows),
                        'class-D rows must be: item | cases/evidence | docs | lift')
        for row in rows:
            item, evidence, where, lift = row
            self.assertTrue(lift, f'{item}: no lift condition recorded')
            for token in repo_paths(where) + repo_paths(evidence):
                self.assertTrue(exists_token(token),
                                f'{item}: evidence path missing: {token}')

    def test_multi_image_checklist_and_switching_rule_present(self):
        switch = section(self.text, '### 15.2 Volatile-load-only rule',
                         '### 15.3 Per-image evidence requirements')
        normalized = ' '.join(switch.split())
        self.assertIn('Never write flash', normalized)
        self.assertIn('Volatile SRAM is replaced by the new load', normalized)
        checklist = self.text[self.text.index('## 17.'):]
        self.assertIn('Volatile load only', checklist)
        self.assertIn('Switch family only by repeating', checklist)


if __name__ == '__main__':
    unittest.main()
