import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class UiJs(unittest.TestCase):
    def test_node_suite(self):
        result = subprocess.run(["node", "--test", "tests/ui/"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lh_plugin(self):
        result = subprocess.run(["node", "--test", "tests/lh_plugin/"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
