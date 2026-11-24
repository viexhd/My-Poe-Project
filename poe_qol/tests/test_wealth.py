"""Wealthy Exile CSV import, divine-per-hour maths, folder source, and
the Wealth tab / overlay (offscreen Qt).

The importer reads only files the user exported themselves (Wealthy
Exile: Stash -> ... -> Export CSV). No network access anywhere here.

NOTE: the real Wealthy Exile CSV layout has not been confirmed yet. The
fixtures below follow the columns shown in its stash table (Name, Tab,
Quantity, Price, Total); the importer matches headers loosely so small
naming differences still parse.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe_qol.economy.wealthy_exile_csv import (  # noqa: E402
    CsvFormatError, parse_number, parse_snapshot,
)
from poe_qol.economy.wealth_rate import (  # noqa: E402
    MIN_INTERVAL_MINUTES, CsvFolderSource, clamp_interval_minutes,
    compute_rate,
)

CSV_BASIC = (
    "Name,Tab,Quantity,Price,Total\n"
    "Divine Orb,Currency,10,180,1800\n"
    "Chaos Orb,Currency,500,1,500\n"
    "Scarab of Stability,Scarabs,4,2.5,10\n"
)


def _write(dir_: Path, name: str, text: str, mtime: float | None = None) -> Path:
    p = dir_ / name
    p.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


class ParseNumberTests(unittest.TestCase):
    def test_formats(self) -> None:
        cases = {
            "12": 12.0, "2.5": 2.5, "1,234.5": 1234.5, "1 234,5": 1234.5,
            "1.234,5": 1234.5, "1,234": 1234.0, "0,5": 0.5,
            " 1 000": 1000.0, " 7 ": 7.0, "-3.25": -3.25,
        }
        for text, want in cases.items():
            self.assertAlmostEqual(parse_number(text), want, msg=repr(text))

    def test_rejects_garbage(self) -> None:
        for bad in ("", "abc", "1.2.3,4,5x"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_number(bad)


class ParseSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tc_we_"))

    def test_basic_total_from_total_column(self) -> None:
        p = _write(self.tmp, "stash.csv", CSV_BASIC)
        snap = parse_snapshot(p)
        self.assertAlmostEqual(snap.total, 2310.0)
        self.assertEqual(snap.rows, 3)
        self.assertEqual(snap.skipped, 0)
        self.assertEqual(snap.unit, "unknown")   # header has no unit hint

    def test_total_falls_back_to_quantity_times_price(self) -> None:
        p = _write(self.tmp, "s.csv", "item;qty;unit price\nA;2;1,5\nB;3;10\n")
        snap = parse_snapshot(p)
        self.assertAlmostEqual(snap.total, 33.0)

    def test_unit_detected_from_header(self) -> None:
        p = _write(self.tmp, "d.csv", "Name,Quantity,Total (div)\nX,1,2.5\n")
        self.assertEqual(parse_snapshot(p).unit, "divine")
        p = _write(self.tmp, "c.csv", "Name,Quantity,Total chaos\nX,1,90\n")
        self.assertEqual(parse_snapshot(p).unit, "chaos")

    def test_bad_rows_are_skipped_not_fatal(self) -> None:
        p = _write(self.tmp, "b.csv", CSV_BASIC + "Broken,Tab,,n/a,\n")
        snap = parse_snapshot(p)
        self.assertEqual((snap.rows, snap.skipped), (3, 1))

    def test_utf8_bom_and_taken_at_from_mtime(self) -> None:
        when = time.time() - 3600
        p = _write(self.tmp, "bom.csv", "﻿" + CSV_BASIC, mtime=when)
        snap = parse_snapshot(p)
        self.assertAlmostEqual(snap.total, 2310.0)
        self.assertAlmostEqual(snap.taken_at.timestamp(), when, delta=2)

    def test_unrecognised_header_names_expected_columns(self) -> None:
        p = _write(self.tmp, "x.csv", "foo,bar\n1,2\n")
        with self.assertRaises(CsvFormatError) as ctx:
            parse_snapshot(p)
        self.assertIn("quantity", str(ctx.exception).lower())


FIXTURE = ROOT / "tests" / "fixtures" / "wealthy_exile_sample.csv"


class RealExportFormatTests(unittest.TestCase):
    """Layout confirmed from a real Wealthy Exile export (2026-11-23):
    quoted "Name","Tab","Quantity","Price","Total", prices in chaos,
    Total more precise than Quantity x Price, names may contain commas,
    tab names may be numbers. Fixture values are synthetic."""

    def test_fixture_parses_completely(self) -> None:
        snap = parse_snapshot(FIXTURE)
        self.assertEqual((snap.rows, snap.skipped), (6, 0))
        self.assertAlmostEqual(snap.total, 2004 + 500 + 700 + 9 + 34 + 0.02)

    def test_divine_price_comes_from_divine_orb_row(self) -> None:
        # Total / Quantity (2004 / 10) beats the rounded Price column (200).
        self.assertAlmostEqual(parse_snapshot(FIXTURE).divine_price, 200.4)

    def test_no_divine_row_means_no_divine_price(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="tc_nd_"))
        p = _write(tmp, "x.csv", '"Name","Tab","Quantity","Price","Total"\n'
                                 '"Chaos Orb","Currency","5","1","5"\n')
        self.assertIsNone(parse_snapshot(p).divine_price)

    def test_taken_at_from_export_filename(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="tc_fn_"))
        name = "Wealthy-Exile-export-11_23_2026 9_38.csv"
        morning = datetime(2026, 11, 23, 9, 38, 5).timestamp()
        p = _write(tmp, name, FIXTURE.read_text(encoding="utf-8"), morning)
        self.assertEqual(parse_snapshot(p).taken_at, datetime(2026, 11, 23, 9, 38))
        # Same name, file written in the evening: 9_38 is read as 21:38.
        evening = datetime(2026, 11, 23, 21, 38, 20).timestamp()
        os.utime(p, (evening, evening))
        self.assertEqual(parse_snapshot(p).taken_at, datetime(2026, 11, 23, 21, 38))
        # A copied file (fresh mtime days later) keeps the export time.
        later = datetime(2026, 11, 26, 9, 0).timestamp()
        os.utime(p, (later, later))
        self.assertEqual(parse_snapshot(p).taken_at.date(),
                         datetime(2026, 11, 23).date())


class ComputeRateTests(unittest.TestCase):
    def _snap(self, total: float, minutes: float, unit: str = "chaos"):
        from poe_qol.economy.wealthy_exile_csv import Snapshot
        base = datetime(2026, 11, 23, 12, 0, 0)
        return Snapshot(path=Path(f"{minutes}.csv"),
                        taken_at=base + timedelta(minutes=minutes),
                        total=total, unit=unit, rows=1, skipped=0)

    def test_chaos_rate_converted_to_divine(self) -> None:
        r = compute_rate(self._snap(1000, 0), self._snap(1360, 60),
                         chaos_per_divine=180)
        self.assertAlmostEqual(r.chaos_per_hour, 360.0)
        self.assertAlmostEqual(r.divine_per_hour, 2.0)
        self.assertAlmostEqual(r.span_minutes, 60.0)

    def test_divine_snapshots_need_no_rate(self) -> None:
        r = compute_rate(self._snap(10, 0, "divine"), self._snap(13, 90, "divine"),
                         chaos_per_divine=None)
        self.assertAlmostEqual(r.divine_per_hour, 2.0)
        self.assertIsNone(r.chaos_per_hour)

    def test_no_time_difference_gives_no_rate(self) -> None:
        r = compute_rate(self._snap(1, 30), self._snap(5, 30), chaos_per_divine=180)
        self.assertIsNone(r.divine_per_hour)
        self.assertTrue(r.message)

    def test_divine_rate_auto_from_export(self) -> None:
        from dataclasses import replace
        later = replace(self._snap(1360, 60), divine_price=180.0)
        r = compute_rate(self._snap(1000, 0), later, chaos_per_divine=None)
        self.assertAlmostEqual(r.divine_per_hour, 2.0)
        self.assertIn("auto", r.message.lower())
        # An explicit rate wins over the export's.
        r = compute_rate(self._snap(1000, 0), later, chaos_per_divine=360)
        self.assertAlmostEqual(r.divine_per_hour, 1.0)

    def test_mixed_units_rejected(self) -> None:
        r = compute_rate(self._snap(1, 0, "divine"), self._snap(500, 60, "chaos"),
                         chaos_per_divine=None)
        self.assertIsNone(r.divine_per_hour)
        self.assertIn("unit", r.message.lower())


class FolderSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tc_wf_"))

    def test_uses_two_newest_exports(self) -> None:
        now = time.time()
        _write(self.tmp, "old.csv", "Name,Quantity,Total\nA,1,100\n", now - 7200)
        _write(self.tmp, "mid.csv", "Name,Quantity,Total\nA,1,1000\n", now - 3600)
        _write(self.tmp, "new.csv", "Name,Quantity,Total\nA,1,1180\n", now)
        _write(self.tmp, "notes.txt", "ignore me", now)
        r = CsvFolderSource(self.tmp, chaos_per_divine=180,
                            assumed_unit="chaos").read()
        self.assertAlmostEqual(r.divine_per_hour, 1.0, places=2)
        self.assertEqual(r.snapshots_used, 2)

    def test_needs_two_exports(self) -> None:
        _write(self.tmp, "only.csv", "Name,Quantity,Total\nA,1,1\n")
        r = CsvFolderSource(self.tmp, chaos_per_divine=180).read()
        self.assertIsNone(r.divine_per_hour)
        self.assertIn("2", r.message)

    def test_missing_folder_is_reported(self) -> None:
        r = CsvFolderSource(self.tmp / "nope", chaos_per_divine=180).read()
        self.assertIsNone(r.divine_per_hour)
        self.assertTrue(r.message)

    def test_interval_floor_is_five_minutes(self) -> None:
        self.assertEqual(MIN_INTERVAL_MINUTES, 5)
        self.assertEqual(clamp_interval_minutes(1), 5)
        self.assertEqual(clamp_interval_minutes(0), 5)
        self.assertEqual(clamp_interval_minutes(90), 90)


def _qapp():
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return QApplication.instance() or QApplication([])


class WealthUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _qapp()

    def test_overlay_shows_divine_rate(self) -> None:
        from poe_qol.economy.wealth_rate import RateReading
        from poe_qol.ui.wealth_overlay import WealthOverlay
        ov = WealthOverlay()
        ov.show_reading(RateReading(divine_per_hour=2.0, chaos_per_hour=360.0,
                                    span_minutes=60, snapshots_used=2,
                                    latest_at=datetime(2026, 11, 23, 14, 2)))
        self.assertIn("2.00 div/h", ov.headline_text())
        ov.show_reading(RateReading(message="Need 2 exports"))
        self.assertIn("—", ov.headline_text())
        self.assertIn("Need 2 Exports", ov.detail_text())
        ov.close()

    def test_wealth_tab_interval_floor_and_refresh(self) -> None:
        from poe_qol.core.config import ConfigStore
        from poe_qol.ui.wealth_widget import WealthWidget
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="tc_wt_"))
        shutil.copytree(ROOT / "config", tmp / "config",
                        ignore=shutil.ignore_patterns("user.yaml"))
        exports = tmp / "exports"; exports.mkdir()
        now = time.time()
        _write(exports, "a.csv", "Name,Quantity,Total\nA,1,1000\n", now - 3600)
        _write(exports, "b.csv", "Name,Quantity,Total\nA,1,1360\n", now)
        cfg = ConfigStore(tmp)
        cfg.set("wealth.exports_dir", str(exports))
        cfg.set("wealth.chaos_per_divine", 180)
        w = WealthWidget(cfg)
        self.assertEqual(w.interval_spin.minimum(), 5)
        w.refresh()
        self.assertIn("2.00 div/h", w.overlay_headline())
        w.close()


if __name__ == "__main__":
    unittest.main()
