import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_tag", ROOT / "scripts/ensure-release-tag.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = "a" * 40
TAG = "v" + json.loads((ROOT / "web/release-notes.json").read_text())["current"]


def result(out="", error="", code=0):
    return subprocess.CompletedProcess([], code, out, error)


def ref(sha=SHA, kind="commit"):
    return result(json.dumps({"object": {"type": kind, "sha": sha}}))


class ReleaseTagTests(unittest.TestCase):
    def invoke(self, responses):
        with patch.object(MODULE, "run", side_effect=responses) as run:
            MODULE.ensure_tag(TAG, SHA, "fixture/repo")
            return run.call_args_list

    def test_existing_tag_is_read_only(self):
        self.assertEqual(len(self.invoke([result(SHA), ref()])), 2)

    def test_new_tag_created_once_then_read_back(self):
        calls = self.invoke([result(SHA), result(error="HTTP 404", code=1), ref(), ref()])
        self.assertIn("POST", calls[2].args)
        self.assertIn(f"sha={SHA}", calls[2].args)
        self.assertEqual(calls[1], calls[3])

    def test_existing_annotated_tag_is_dereferenced(self):
        self.assertEqual(len(self.invoke([result(SHA), ref("b" * 40, "tag"), ref()])), 3)

    def test_tag_mismatch_never_writes(self):
        with patch.object(MODULE, "run", side_effect=[result(SHA), ref("b" * 40)]) as run:
            with self.assertRaisesRegex(RuntimeError, "never overwritten"):
                MODULE.ensure_tag(TAG, SHA, "fixture/repo")
            self.assertEqual(run.call_count, 2)

    def test_permission_and_network_failures_never_create_tag(self):
        for error in ("HTTP 403", "HTTP 500", "connection failed"):
            with self.subTest(error=error), patch.object(MODULE, "run", side_effect=[result(SHA), result(error=error, code=1)]) as run:
                with self.assertRaisesRegex(RuntimeError, "Cannot inspect"):
                    MODULE.ensure_tag(TAG, SHA, "fixture/repo")
                self.assertEqual(run.call_count, 2)

    def test_input_and_checkout_mismatch_fail_before_network(self):
        for tag, sha, head in (("v99.99.99", SHA, SHA), (TAG, "main", SHA), (TAG, SHA, "b" * 40)):
            with self.subTest(tag=tag, sha=sha), patch.object(MODULE, "run", return_value=result(head)) as run:
                with self.assertRaises(ValueError):
                    MODULE.ensure_tag(tag, sha, "fixture/repo")
                self.assertLessEqual(run.call_count, 1)

    def test_creation_race_fails_without_retry_or_update(self):
        with patch.object(MODULE, "run", side_effect=[result(SHA), result(error="HTTP 404", code=1), result(error="HTTP 422", code=1)]) as run:
            with self.assertRaisesRegex(RuntimeError, "Tag creation failed"):
                MODULE.ensure_tag(TAG, SHA, "fixture/repo")
            self.assertEqual(run.call_count, 3)

    def test_workflow_tags_only_after_build_and_upgrade_gates(self):
        source = (ROOT / ".github/workflows/desktop-release.yml").read_text()
        for gate in ("python scripts/reliability-suite.py", "test-upgrade-installer.ps1", "Attest release build provenance"):
            self.assertLess(source.index(gate), source.index("python scripts/ensure-release-tag.py"))
        self.assertLess(source.index("python scripts/ensure-release-tag.py"), source.index("./scripts/publish-release.ps1"))
        self.assertIn("Exact release commit and version tag are required", source)
