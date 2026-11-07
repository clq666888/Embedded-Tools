import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from firmware import FirmwareError
from project_scan import ScanSession, scan_project


class ProjectScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_scan_and_bin_unknown_address(self):
        (self.root / "build").mkdir()
        (self.root / "build" / "app.bin").write_bytes(b"ABC")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "ignore.bin").write_bytes(b"NO")
        result = scan_project(self.root)
        self.assertEqual([a.name for a in result.artifacts], ["build/app.bin"])
        self.assertEqual(result.valid[0].firmware.address_range, "未确定（BIN 不含地址）")
        self.assertEqual(result.valid[0].firmware.image_size, 3)

    def test_zip_scan_without_extracting(self):
        archive = self.root / "project.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("release/app.bin", b"1234")
            z.writestr("source/main.c", b"code")
        result = scan_project(archive)
        self.assertEqual([a.name for a in result.artifacts], ["release/app.bin"])
        self.assertFalse((self.root / "release").exists())

    def test_bad_zip(self):
        archive = self.root / "broken.zip"
        archive.write_bytes(b"not zip")
        with self.assertRaises(FirmwareError):
            scan_project(archive)

    def test_single_firmware_file(self):
        file = self.root / "one.bin"
        file.write_bytes(b"ABC")
        result = scan_project(file)
        self.assertEqual([a.name for a in result.artifacts], ["one.bin"])
        self.assertEqual(result.valid[0].firmware.image_size, 3)

    def test_cancel_before_folder_scan(self):
        (self.root / "firmware.bin").write_bytes(b"ABC")
        cancel = threading.Event()
        cancel.set()
        result = scan_project(self.root, cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.artifacts, [])

    def test_cancel_during_directory_walk(self):
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        cancel = threading.Event()
        visits = []

        def progress(dirs, _files):
            visits.append(dirs)
            cancel.set()

        result = scan_project(self.root, cancel=cancel, progress=progress)
        self.assertTrue(result.cancelled)
        self.assertEqual(visits[0], 1)

    def test_resume_folder_keeps_partial_results_without_duplicates(self):
        (self.root / "a.bin").write_bytes(b"A")
        (self.root / "b.bin").write_bytes(b"B")
        session = ScanSession(self.root)
        cancel = threading.Event()
        original = session._add_file

        def stop_after_first(*args):
            completed = original(*args)
            cancel.set()
            return completed

        session._add_file = stop_after_first
        partial = session.run(cancel)
        self.assertTrue(partial.cancelled)
        self.assertEqual(len(partial.artifacts), 1)
        session._add_file = original
        live_rows = []
        final = session.run(threading.Event(), on_artifact=lambda index, artifact: live_rows.append((index, artifact.name)))
        self.assertTrue(session.finished)
        self.assertEqual(sorted(a.name for a in final.artifacts), ["a.bin", "b.bin"])
        self.assertEqual(live_rows, [(1, "b.bin")])

    def test_resume_zip_keeps_position(self):
        archive = self.root / "project.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("a.bin", b"A")
            z.writestr("b.bin", b"B")
        session = ScanSession(archive)
        cancel = threading.Event()
        original = session._add_file

        def stop_after_first(*args):
            completed = original(*args)
            cancel.set()
            return completed

        session._add_file = stop_after_first
        self.assertTrue(session.run(cancel).cancelled)
        self.assertEqual(session.zip_index, 1)
        session._add_file = original
        final = session.run(threading.Event())
        self.assertEqual([a.name for a in final.artifacts], ["a.bin", "b.bin"])


if __name__ == "__main__":
    unittest.main()
