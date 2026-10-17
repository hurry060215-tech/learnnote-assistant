from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_version_rollback_build", ROOT / "scripts/native-version-rollback-build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
OLD_SPEC = (ROOT / "scripts/fixtures/native-version-rollback-old.macos.spec").read_bytes()
NEW_SPEC = (ROOT / "scripts/fixtures/native-version-rollback-new.macos.spec").read_bytes()


class RollbackBuildPatchTests(unittest.TestCase):
    def test_backport_changes_only_collect_and_bundle_argument(self):
        self.assertEqual(hashlib.sha256(OLD_SPEC).hexdigest(), BUILD.OLD_SPEC_SHA256)
        patched = BUILD.patch_old_spec(OLD_SPEC)
        self.assertEqual(patched.replace(BUILD.COLLECT_BUNDLE, BUILD.OLD_BUNDLE, 1), OLD_SPEC)
        self.assertEqual(patched.count(b"collection = COLLECT("), 1)
        self.assertIn(b"exe, a.binaries, a.datas", patched)
        self.assertIn(b"BUNDLE(\n    collection,", patched)
        self.assertEqual(patched.split(b"collection = COLLECT(")[0], OLD_SPEC.split(b"BUNDLE(")[0])

    def test_backport_rejects_any_unapproved_source_change_or_second_application(self):
        for changed in (OLD_SPEC + b"\n", OLD_SPEC.replace(b"upx=False", b"upx=True"),
                        BUILD.patch_old_spec(OLD_SPEC)):
            with self.subTest(changed=hashlib.sha256(changed).hexdigest()):
                with self.assertRaisesRegex(ValueError, "approved immutable"):
                    BUILD.patch_old_spec(changed)

    def test_new_spec_is_the_immutable_unmodified_candidate_spec(self):
        self.assertEqual(BUILD.sha256(NEW_SPEC), BUILD.NEW_SPEC_SHA256)

    def test_frozen_specs_keep_exact_bytes_with_windows_git_line_endings(self):
        # Exercise Git's real checkout filter without changing global config.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
            paths = []
            for label, expected in (("old", BUILD.OLD_SPEC_SHA256), ("new", BUILD.NEW_SPEC_SHA256)):
                relative = f"scripts/fixtures/native-version-rollback-{label}.macos.spec"
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
                paths.append((relative, expected))
            subprocess.run(["git", "-c", "core.autocrlf=true", "add", "."], cwd=root, check=True, capture_output=True)
            for relative, _ in paths:
                (root / relative).unlink()
            subprocess.run(["git", "-c", "core.autocrlf=true", "checkout-index", "--all", "--force"], cwd=root, check=True)
            for relative, expected in paths:
                checked_out = (root / relative).read_bytes()
                self.assertNotIn(b"\r\n", checked_out)
                self.assertEqual(BUILD.sha256(checked_out), expected)

    def make_source(self, root, label):
        source = root / label
        (source / "backend/app").mkdir(parents=True)
        (source / "backend/app/__init__.py").write_text(f'APP_VERSION = "0.2.{14 if label == "old" else 15}"\n')
        (source / "LearnNote.macos.spec").write_bytes(OLD_SPEC if label == "old" else NEW_SPEC)
        return source

    def fake_git(self, source, *args):
        if args == ("rev-parse", "HEAD"):
            return BUILD.OLD_COMMIT if source.name == "old" else BUILD.NEW_COMMIT
        if args == ("rev-parse", "refs/tags/v0.2.14^{commit}"):
            return BUILD.OLD_COMMIT
        if args == ("rev-parse", "HEAD^{tree}"):
            return "synthetic-git-tree"
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        self.fail(f"Unexpected git call: {args}")

    def test_preparation_retains_spec_hashes_inventories_and_only_old_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(BUILD, "git", side_effect=self.fake_git), patch.object(BUILD, "tracked_inventory", side_effect=BUILD.tree_inventory):
                old_source = self.make_source(root, "old")
                new_source = self.make_source(root, "new")
                old = BUILD.prepare_source(old_source, "old", root / "evidence/old")
                new = BUILD.prepare_source(new_source, "new", root / "evidence/new")
            self.assertEqual(old["source_commit"], BUILD.OLD_COMMIT)
            self.assertEqual(old["tag_commit"], BUILD.OLD_COMMIT)
            self.assertEqual(old["app_version"], "0.2.14")
            self.assertEqual(new["app_version"], "0.2.15")
            self.assertNotEqual(old["source_tree_sha256"], old["build_source_tree_sha256"])
            self.assertNotEqual(old["spec_original_sha256"], old["spec_used_sha256"])
            self.assertEqual(new["source_tree_sha256"], new["build_source_tree_sha256"])
            self.assertEqual(new["spec_original_sha256"], new["spec_used_sha256"])
            self.assertIsNone(new["packaging_backport"])
            self.assertIn("Only insert COLLECT", old["packaging_backport"])
            self.assertEqual((root / "evidence/new/packaging-only.patch").read_text(), "")
            self.assertIn("+collection = COLLECT(", (root / "evidence/old/packaging-only.patch").read_text())
            self.assertEqual((root / "evidence/old/LearnNote.macos.original.spec").read_bytes(), OLD_SPEC)
            for label in ("old", "new"):
                self.assertTrue((root / f"evidence/{label}/source-original-tree.json").is_file())
                self.assertTrue((root / f"evidence/{label}/source-build-tree.json").is_file())

    def test_preparation_rejects_wrong_commit_tag_dirty_checkout_or_version(self):
        cases = [(("rev-parse", "HEAD"), "unexpected", "commit mismatch"),
                 (("rev-parse", "refs/tags/v0.2.14^{commit}"), "unexpected", "tag does not resolve"),
                 (("status", "--porcelain", "--untracked-files=all"), " M backend/app/main.py", "pristine")]
        for arguments, value, error in cases:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self.make_source(root, "old")
                def fake(source, *args):
                    return value if args == arguments else self.fake_git(source, *args)
                with patch.object(BUILD, "git", side_effect=fake):
                    with self.assertRaisesRegex(ValueError, error):
                        BUILD.prepare_source(source, "old", root / "evidence")
                self.assertEqual((source / "LearnNote.macos.spec").read_bytes(), OLD_SPEC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_source(root, "old")
            (source / "backend/app/__init__.py").write_text('APP_VERSION = "0.2.15"\n')
            with patch.object(BUILD, "git", side_effect=self.fake_git):
                with self.assertRaisesRegex(ValueError, "APP_VERSION mismatch"):
                    BUILD.prepare_source(source, "old", root / "evidence")

    def test_version_reader_does_not_import_or_run_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_source(Path(directory), "old")
            (source / "backend/app/__init__.py").write_text('raise RuntimeError("must not run")\nAPP_VERSION = "0.2.14"\n')
            self.assertEqual(BUILD.app_version(source), "0.2.14")
            (source / "backend/app/__init__.py").write_text('APP_VERSION = "0.2.14"\nAPP_VERSION = "0.2.15"\n')
            with self.assertRaises(ValueError):
                BUILD.app_version(source)


class RollbackBuildProvenanceTests(unittest.TestCase):
    def test_tree_digest_tracks_bytes_modes_links_and_relative_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "app"
            root.mkdir()
            (root / "z").write_bytes(b"payload")
            (root / "a").mkdir()
            (root / "a/inner").write_bytes(b"nested")
            (root / "outside-link").symlink_to("../missing", target_is_directory=True)
            inventory = BUILD.tree_inventory(root)
            self.assertEqual([entry["path"] for entry in inventory], ["a/inner", "outside-link", "z"])
            self.assertEqual(inventory[1]["target"], "../missing")
            self.assertEqual(BUILD.tree_digest(root), BUILD.sha256(BUILD.canonical_json(inventory)))
            initial = BUILD.tree_digest(root)
            (root / "empty").mkdir()
            os.utime(root / "z", (1, 1))
            self.assertEqual(BUILD.tree_digest(root), initial)
            (root / "z").write_bytes(b"changed")
            self.assertNotEqual(BUILD.tree_digest(root), initial)
            changed = BUILD.tree_digest(root)
            original_mode = stat.S_IMODE((root / "z").stat().st_mode)
            # Windows chmod supports the read-only flag, not POSIX execute bits.
            mode_bit = stat.S_IWRITE if os.name == "nt" else stat.S_IXUSR
            try:
                (root / "z").chmod(original_mode ^ mode_bit)
                self.assertNotEqual(stat.S_IMODE((root / "z").stat().st_mode), original_mode)
                self.assertNotEqual(BUILD.tree_digest(root), changed)
            finally:
                (root / "z").chmod(original_mode)

    def test_tree_digest_does_not_follow_linked_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "app"
            app.mkdir()
            external = root / "external"
            external.mkdir()
            (external / "unrelated").write_text("first")
            (app / "linked").symlink_to(external, target_is_directory=True)
            initial = BUILD.tree_digest(app)
            (external / "unrelated").write_text("second")
            self.assertEqual(BUILD.tree_digest(app), initial)
            with self.assertRaises(ValueError):
                BUILD.tree_inventory(app / "linked")

    def test_sources_envs_and_outputs_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            BUILD.validate_paths(root / "old", root / "new", root / "evidence", root / "envs")
            for old, new, evidence, envs in ((root / "old", root / "old", root / "evidence", root / "envs"),
                                               (root / "old", root / "new", root / "old/evidence", root / "envs"),
                                               (root / "old", root / "new", root / "evidence", root / "new/envs")):
                with self.assertRaises(ValueError):
                    BUILD.validate_paths(old, new, evidence, envs)

    def test_build_environment_is_offline_for_models_and_drops_user_source_paths(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/other/source", "PYTHONHOME": "/other/python", "VIRTUAL_ENV": "/other/env",
                                     "LEARNNOTE_DATA_DIR": "/user/data", "OPENAI_API_KEY": "synthetic", "LLM_API_KEY": "synthetic"}):
            env = BUILD.build_environment()
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LEARNNOTE_DATA_DIR", "OPENAI_API_KEY", "LLM_API_KEY"):
            self.assertNotIn(key, env)
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "PYTHONNOUSERSITE"):
            self.assertEqual(env[key], "1")

    def test_build_uses_source_requirements_separate_env_and_pinned_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, environment, evidence = root / "source", root / "env/old", root / "evidence"
            source.mkdir()
            evidence.mkdir()
            app = source / "dist/LearnNote.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            (app / "Contents/MacOS/LearnNote").write_bytes(b"synthetic executable")
            record = {"app_path": str(app), "app_tree_inventory": str(evidence / "app-tree.json"),
                      "build_source_tree_sha256": BUILD.sha256(BUILD.canonical_json([]))}
            toolchain = {"python": "3.12.0", "platform": "fixture", "pyinstaller": "6.22.2", "pyinstaller-hooks-contrib": "2026.7"}
            with patch.object(BUILD, "run_logged") as run, patch.object(BUILD.subprocess, "run") as freeze, \
                 patch.object(BUILD.subprocess, "check_output", return_value=json.dumps(toolchain)), \
                 patch.object(BUILD, "tracked_inventory", return_value=[]):
                BUILD.build_source(source, environment, evidence, record)
            commands = [call.args[0] for call in run.call_args_list]
            python = str(environment / "bin/python")
            self.assertEqual(commands, [
                [sys.executable, "-m", "venv", str(environment)],
                [python, "-m", "pip", "install", "-r", "backend/requirements.test.txt", "pyinstaller==6.22.2", "pyinstaller-hooks-contrib==2026.7"],
                [python, "-m", "pip", "check"],
                [python, "-m", "PyInstaller", "--noconfirm", "--clean", "LearnNote.macos.spec"],
            ])
            for call in run.call_args_list:
                self.assertEqual(call.args[1], source)
                self.assertEqual(call.args[3]["PYINSTALLER_CONFIG_DIR"], str(environment / "pyinstaller-cache"))
            self.assertEqual(freeze.call_args.args[0], [python, "-m", "pip", "freeze", "--all"])
            self.assertEqual(record["status"], "built")
            self.assertEqual(record["app_tree_sha256"], BUILD.tree_digest(app))
            self.assertEqual(json.loads((evidence / "app-tree.json").read_text()), BUILD.tree_inventory(app))
            self.assertEqual(json.loads((evidence / "toolchain.json").read_text()), toolchain)

    def test_build_rejects_reusing_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = root / "env"
            environment.mkdir()
            with self.assertRaisesRegex(ValueError, "must be new"):
                BUILD.build_source(root / "source", environment, root / "evidence", {})

    def test_command_failure_keeps_stdout_stderr_and_nonzero_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(subprocess.CalledProcessError):
                BUILD.run_logged([sys.executable, "-c", "import sys; print('fixture stdout'); print('fixture stderr', file=sys.stderr); sys.exit(3)"],
                                 root, root / "build.log", BUILD.build_environment())
            log = (root / "build.log").read_text()
            self.assertIn("fixture stdout", log)
            self.assertIn("fixture stderr", log)

    def test_failed_old_build_retains_provenance_and_still_attempts_new(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            calls = []
            def prepare(source, label, evidence):
                return {"status": "prepared", "source_commit": label}
            def build(source, environment, evidence, record):
                calls.append((source.name, environment))
                if source.name == "old":
                    raise RuntimeError("synthetic old build failure")
                record["status"] = "built"
            argv = ["build", "--old-source", str(root / "old"), "--new-source", str(root / "new"),
                    "--output", str(output), "--environments", str(root / "environments")]
            host_platform = sys.platform
            real_platform = BUILD.platform.platform
            def describe_host():
                # A shared sys.platform mock can poison platform's uname cache
                # on Windows and break later native SDK imports.
                self.assertEqual(sys.platform, host_platform)
                return real_platform()
            with patch("sys.argv", argv), patch.object(BUILD, "sys", SimpleNamespace(platform="darwin", executable=sys.executable)), \
                 patch.object(BUILD.platform, "platform", side_effect=describe_host) as describe, \
                 patch.object(BUILD, "prepare_source", side_effect=prepare), patch.object(BUILD, "build_source", side_effect=build):
                self.assertEqual(BUILD.main(), 1)
                with self.assertRaisesRegex(ValueError, "overwrite existing"):
                    BUILD.main()
                describe.assert_called_once()
            manifest = json.loads((output / "build-manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["builds"]["old"]["status"], "failed")
            self.assertEqual(manifest["builds"]["new"]["status"], "built")
            self.assertEqual([label for label, _ in calls], ["old", "new"])
            self.assertNotEqual(calls[0][1], calls[1][1])
            self.assertIn("synthetic old build failure", (output / "builds/old/failure.txt").read_text())


class RollbackWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github/workflows/native-version-rollback.yml").read_text()
        cls.workflow = yaml.safe_load(cls.text)
        cls.job = cls.workflow["jobs"]["version-rollback"]
        cls.steps = cls.job["steps"]

    def test_workflow_is_manual_no_inputs_read_only_unsigned_and_no_publish(self):
        self.assertEqual(self.workflow.get("on", self.workflow.get(True)), {"workflow_dispatch": None})
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.job["runs-on"], "macos-latest")
        for forbidden in ("secrets.", "gh release", "--clobber", "codesign", "notarytool", "continue-on-error", "curl ", "wget "):
            self.assertNotIn(forbidden, self.text)
        self.assertNotIn("permissions", self.job)
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            self.assertEqual(self.job["env"][key], "1")

    def test_immutable_refs_separate_paths_and_no_persisted_checkout_credentials(self):
        checkouts = [step for step in self.steps if "actions/checkout@" in step.get("uses", "")]
        self.assertEqual(len(checkouts), 3)
        sources = {step["with"].get("path"): step for step in checkouts}
        self.assertEqual(sources["sources/old"]["with"]["ref"], BUILD.OLD_COMMIT)
        self.assertEqual(sources["sources/new"]["with"]["ref"], BUILD.NEW_COMMIT)
        self.assertEqual(sources["sources/old"]["with"]["fetch-depth"], 0)
        for step in checkouts:
            self.assertIs(step["with"]["persist-credentials"], False)
        for step in self.steps:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[0-9a-f]{40}$")

    def test_build_and_harness_use_distinct_apps_and_recorded_manifest(self):
        commands = "\n".join(step.get("run", "") for step in self.steps)
        for expected in ("python scripts/native-version-rollback-build.py", "--old-source sources/old", "--new-source sources/new",
                         "--environments .rollback-build-envs", ".rollback-build-envs/new/bin/python scripts/native-version-rollback.py",
                         "--old-app sources/old/dist/LearnNote.app", "--new-app sources/new/dist/LearnNote.app",
                         "--output build/version-rollback", "--build-manifest build/version-rollback/build-manifest.json"):
            self.assertIn(expected, commands)
        build_code = (ROOT / "scripts/native-version-rollback-build.py").read_text()
        self.assertEqual(BUILD.PYINSTALLER_VERSION, "6.22.2")
        self.assertEqual(BUILD.HOOKS_VERSION, "2026.7")
        self.assertIn('f"pyinstaller=={PYINSTALLER_VERSION}"', build_code)
        self.assertIn('f"pyinstaller-hooks-contrib=={HOOKS_VERSION}"', build_code)
        self.assertNotIn('"-r", "backend/requirements.asr.txt"', build_code)

    def test_evidence_upload_always_preserves_hidden_snapshots_and_logs(self):
        uploads = [step for step in self.steps if "actions/upload-artifact@" in step.get("uses", "")]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["if"], "always()")
        self.assertEqual(uploads[0]["with"]["path"], "build/version-rollback/")
        self.assertIs(uploads[0]["with"]["include-hidden-files"], True)
        self.assertEqual(uploads[0]["with"]["retention-days"], 14)


if __name__ == "__main__":
    unittest.main()
