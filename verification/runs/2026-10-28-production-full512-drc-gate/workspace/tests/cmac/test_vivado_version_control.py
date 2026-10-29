"""Full-tool banner admission controls; no Vivado process is launched."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import vivado_array
import vivado_fixed_array
import vivado_dsp_array
import vivado_dsp_prefix_array


class FullVivadoVersionControl(unittest.TestCase):
    def test_every_build_profile_accepts_real_full_tool_banners(self):
        for driver in (vivado_array, vivado_fixed_array, vivado_dsp_array, vivado_dsp_prefix_array):
            for banner in ('vivado v2026.1 (64-bit)\n', 'Vivado v2026.1 (64-bit)\n',
                           'VIVADO v2026.1.1 (64-bit)\n'):
                with self.subTest(driver=driver.__name__, banner=banner):
                    driver.validate_full_vivado_version(banner)

    def test_lab_and_incomplete_installs_stay_rejected(self):
        for driver in (vivado_array, vivado_fixed_array, vivado_dsp_array, vivado_dsp_prefix_array):
            for banner in ('Vivado Lab Edition v2026.1.1 (64-bit)', 'vivado v', '',
                           'Vivado MOCK_ONLY_NOT_EXECUTED', 'version unavailable',
                           'vivado v2026.1\nVivado Lab Edition v2026.1'):
                with self.subTest(driver=driver.__name__, banner=banner):
                    with self.assertRaises(AssertionError):
                        driver.validate_full_vivado_version(banner)


if __name__ == '__main__':
    unittest.main()
