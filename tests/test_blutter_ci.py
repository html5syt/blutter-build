import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import blutter_ci as ci


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "targets").mkdir()

    def add_target(self, name):
        directory = self.root / "targets" / name / "lib" / "arm64-v8a"
        directory.mkdir(parents=True)
        for filename in ("libapp.so", "libflutter.so"):
            (directory / filename).touch()
        return directory

    def test_discovery_does_not_require_version_in_name(self):
        self.add_target("my-app")
        self.add_target("second_1.2")
        self.assertEqual(ci.discover_targets(self.root), ["my-app", "second_1.2"])

    def test_discovery_fails_for_incomplete_target(self):
        directory = self.add_target("broken")
        (directory / "libflutter.so").unlink()
        with self.assertRaisesRegex(ValueError, "libflutter.so"):
            ci.discover_targets(self.root)

    def test_empty_targets_fail_early(self):
        with self.assertRaisesRegex(ValueError, "No targets"):
            ci.discover_targets(self.root)

    def test_dispatch_input_cannot_escape_or_inject_shell(self):
        for value in ("", "..", "../elsewhere", "a/b", "a\\b", '$(id)', 'a";exit 1', "a\nfoo", "a "):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ci.target_directory(value, self.root)

    def test_metadata_is_saved_as_json_and_github_outputs(self):
        output = self.root / "outputs"
        metadata = {"dart_version": "3.14.0", "snapshot_hash": "a" * 32,
                    "arch": "arm64", "os_name": "android", "flags": []}
        path = self.root / "nested" / "dart-info.json"
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            ci.save_metadata(metadata, path)
        self.assertEqual(json.loads(path.read_text()), metadata)
        self.assertIn("dart_version=3.14.0\n", output.read_text())

    def test_auto_build_requires_target_before_importing_blutter(self):
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as error:
                ci.main(["build"])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("--target is required", stderr.getvalue())

    def test_manual_build_rejects_invalid_version(self):
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as error:
                ci.main(["build", "--dart-version", '3.14.0\nmalicious=true'])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("--dart-version must be", stderr.getvalue())


class BuildTests(unittest.TestCase):
    def test_build_uses_upstream_input_and_preserves_snapshot_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "blutter_binary"
            build_input = SimpleNamespace(blutter_file=str(output))
            fake = SimpleNamespace(PKG_LIB_DIR=str(root), BlutterInput=Mock(return_value=build_input),
                                   cmake_blutter=Mock(side_effect=lambda item: output.touch()))
            fetch = Mock()
            module = SimpleNamespace(fetch_and_build=fetch)
            info = SimpleNamespace(lib_name="dartvm3.14.0_android_arm64",
                                   snapshot_hash="b" * 32, has_compressed_ptrs=False)
            with patch.object(ci, "load_blutter", return_value=fake), patch.dict(sys.modules, {"dartvm_fetch_build": module}):
                ci.build_only(info, root)
            fetch.assert_called_once_with(info)
            fake.BlutterInput.assert_called_once_with("", info, "", True, False, False)
            fake.cmake_blutter.assert_called_once_with(build_input)

    def test_build_fails_if_upstream_does_not_install_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake = SimpleNamespace(PKG_LIB_DIR=str(root),
                                   BlutterInput=Mock(return_value=SimpleNamespace(blutter_file=str(root / "missing"))),
                                   cmake_blutter=Mock())
            with patch.object(ci, "load_blutter", return_value=fake), patch.dict(sys.modules, {"dartvm_fetch_build": SimpleNamespace(fetch_and_build=Mock())}):
                with self.assertRaisesRegex(RuntimeError, "without binary"):
                    ci.build_only(SimpleNamespace(lib_name="test"), root)


class AnalysisOutputTests(unittest.TestCase):
    def test_metadata_alone_is_not_a_successful_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "dart-info.json").write_text("{}")
            with self.assertRaisesRegex(RuntimeError, "Incomplete.*pp.txt"):
                ci.validate_analysis_output(root)

    def test_empty_output_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("pp.txt", "objs.txt", "blutter_frida.js",
                         "ida_script/addNames.py", "ida_script/ida_dart_struct.h"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            (root / "asm").mkdir()
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                ci.validate_analysis_output(root)

    def test_complete_analysis_includes_ida_symbol_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("pp.txt", "objs.txt", "blutter_frida.js",
                         "ida_script/addNames.py", "ida_script/ida_dart_struct.h", "asm/app.dart"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("generated output")
            ci.validate_analysis_output(root)


class NoBuildTests(unittest.TestCase):
    def test_missing_binary_does_not_trigger_compilation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            item = SimpleNamespace(blutter_file=str(root / "missing"))
            blutter = SimpleNamespace(BlutterInput=Mock(return_value=item), build_and_run=Mock())
            with patch.object(ci, "detect_metadata", return_value={}), \
                 patch.object(ci, "dart_info", return_value=object()), \
                 patch.object(ci, "load_blutter", return_value=blutter), \
                 patch.object(ci, "target_directory", return_value=root):
                with self.assertRaisesRegex(RuntimeError, "No prebuilt binary"):
                    ci.main(["analyze", "--target", "test", "--no-build", "--out-dir", str(root)])
            blutter.build_and_run.assert_not_called()

    def test_existing_binary_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "existing"
            executable.touch()
            item = SimpleNamespace(blutter_file=str(executable))
            blutter = SimpleNamespace(BlutterInput=Mock(return_value=item), build_and_run=Mock())
            with patch.object(ci, "detect_metadata", return_value={}), \
                 patch.object(ci, "dart_info", return_value=object()), \
                 patch.object(ci, "load_blutter", return_value=blutter), \
                 patch.object(ci, "target_directory", return_value=root), \
                 patch.object(ci, "validate_analysis_output") as validate:
                ci.main(["analyze", "--target", "test", "--no-build", "--out-dir", str(root)])
            blutter.build_and_run.assert_called_once_with(item)
            validate.assert_called_once_with(root.resolve())


if __name__ == "__main__":
    unittest.main()
