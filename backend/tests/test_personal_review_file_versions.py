"""Descriptor/path clocks differ on Windows; neither ownership nor edits do."""
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.personal_review_context import _file_witness


def attributes(value, **changes):
    fields = {name: getattr(value, name) for name in
        ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
    return SimpleNamespace(**{**fields, **changes})


class PersonalReviewFileVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "source.txt"
        self.path.write_bytes(b"synthetic source")

    def test_real_platform_witness_is_stable_across_unchanged_reads(self):
        first = _file_witness(self.path)
        self.assertEqual(first, _file_witness(self.path))
        self.assertEqual(first["hash"], hashlib.sha256(b"synthetic source").hexdigest())

    def test_distinct_path_creation_and_descriptor_change_times_are_supported(self):
        original = os.fstat
        # Reproduce CPython's Windows path-stat/fstat ctime semantic difference.
        with patch("app.personal_review_context.os.fstat", side_effect=lambda fd: attributes(original(fd), st_ctime_ns=123)):
            first = _file_witness(self.path)
            self.assertEqual(first, _file_witness(self.path))
        self.assertNotEqual(first["generation"][-1], first["descriptor_generation"][-1])

    def test_descriptor_change_during_read_is_still_rejected(self):
        original = os.fstat
        count = 0
        def changing(fd):
            nonlocal count
            count += 1
            return attributes(original(fd), st_ctime_ns=count)
        with patch("app.personal_review_context.os.fstat", side_effect=changing):
            with self.assertRaisesRegex(ValueError, "source_changed"):
                _file_witness(self.path)

    def test_path_replacement_or_modification_during_read_is_still_rejected(self):
        original = Path.lstat
        for field in ("st_ino", "st_mtime_ns", "st_ctime_ns", "st_size"):
            calls = 0
            def changing(path):
                nonlocal calls
                calls += 1
                value = original(path)
                return attributes(value, **{field: getattr(value, field) + (1 if calls >= 3 else 0)})
            # is_symlink uses lstat first, followed by the before/final reads.
            with self.subTest(field=field), patch.object(Path, "lstat", changing):
                with self.assertRaisesRegex(ValueError, "source_changed"):
                    _file_witness(self.path)

    def test_descriptor_change_time_alone_is_part_of_next_context(self):
        original = os.fstat
        results = []
        for stamp in (123, 124):
            with patch("app.personal_review_context.os.fstat", side_effect=lambda fd: attributes(original(fd), st_ctime_ns=stamp)):
                results.append(_file_witness(self.path))
        self.assertEqual(results[0]["hash"], results[1]["hash"])
        self.assertNotEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
