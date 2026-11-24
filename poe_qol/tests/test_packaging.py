"""Packaged-build plumbing: app root resolution and release files."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class AppRootTests(unittest.TestCase):
    def test_source_root_is_project_folder(self) -> None:
        from poe_qol.paths import app_root, is_frozen
        self.assertFalse(is_frozen())
        self.assertEqual(app_root(), ROOT)
        self.assertTrue((app_root() / "config" / "default.yaml").exists())

    def test_frozen_root_is_exe_folder(self) -> None:
        from poe_qol import paths
        fake = ROOT / "dist" / "TwiceCorrupted" / "TwiceCorrupted.exe"
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(fake)):
            self.assertTrue(paths.is_frozen())
            self.assertEqual(paths.app_root(), fake.parent.resolve())


class ReleaseFilesTests(unittest.TestCase):
    def test_installer_and_spec_reference_real_files(self) -> None:
        self.assertTrue((ROOT / "assets" / "app_icon.ico").exists())
        iss = (ROOT / "packaging" / "installer.iss").read_text()
        for name in ("default.yaml", "map_mods.yaml"):
            self.assertIn(name, iss)
            self.assertTrue((ROOT / "config" / name).exists())
        self.assertIn("PrivilegesRequired=lowest", iss)   # writable install dir
        spec = (ROOT / "packaging" / "twice_corrupted.spec").read_text()
        self.assertIn("launcher.py", spec)
        self.assertTrue((ROOT / "packaging" / "launcher.py").exists())

    def test_versions_agree(self) -> None:
        from poe_qol import __version__
        pyproject = (ROOT / "pyproject.toml").read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
        self.assertEqual(m.group(1), __version__)


if __name__ == "__main__":
    unittest.main()
