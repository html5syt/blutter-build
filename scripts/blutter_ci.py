#!/usr/bin/env python3
"""Discover targets, detect their Dart metadata, and run the patched upstream API."""
import argparse
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_REVISION = "4a60ac648bf448c5a7596437243bcd0b9376fdf0"
VERSION_PATTERN = r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?"


def target_directory(target, root=ROOT):
    # Targets are single directory names; never interpret dispatch inputs as paths.
    if not target or target in (".", "..") or re.fullmatch(r"[\w.-]+", target) is None:
        raise ValueError(f"Invalid target name: {target!r}")
    targets = (root / "targets").resolve()
    directory = (targets / target / "lib" / "arm64-v8a").resolve()
    if not directory.is_relative_to(targets):
        raise ValueError("Target resolves outside targets/")
    for name in ("libapp.so", "libflutter.so"):
        if not (directory / name).is_file():
            raise ValueError(f"Missing target library: {directory / name}")
    return directory


def discover_targets(root=ROOT):
    targets = []
    directory = root / "targets"
    if not directory.is_dir():
        raise ValueError("No targets/ directory; add targets/<name>/lib/arm64-v8a/*.so")
    for path in sorted(directory.iterdir()):
        if path.is_dir() and not path.name.startswith("."):
            target_directory(path.name, root)
            targets.append(path.name)
    if not targets:
        raise ValueError("No targets found; add targets/<name>/lib/arm64-v8a/*.so")
    return targets


def load_blutter(directory):
    directory = Path(directory).resolve()
    if not (directory / "blutter.py").is_file():
        raise ValueError(f"Not a blutter checkout: {directory}")
    sys.path.insert(0, str(directory))
    return importlib.import_module("blutter")


def detect_metadata(target, blutter_dir, root=ROOT):
    directory = target_directory(target, root)
    load_blutter(blutter_dir)
    from extract_dart_info import extract_dart_info
    version, snapshot_hash, flags, arch, os_name = extract_dart_info(
        str(directory / "libapp.so"), str(directory / "libflutter.so"))
    if not version or re.fullmatch(VERSION_PATTERN, version) is None:
        raise ValueError(f"Invalid detected Dart version: {version!r}")
    if arch != "arm64" or os_name != "android":
        raise ValueError(f"Only Android arm64 targets are supported, found {os_name} {arch}")
    if "arm64" not in flags or "android" not in flags:
        raise ValueError("libapp.so snapshot flags do not match libflutter.so (Android arm64)")
    return {
        "target": target, "dart_version": version, "snapshot_hash": snapshot_hash,
        "os_name": os_name, "arch": arch,
        "compressed_pointers": "compressed-pointers" in flags, "flags": flags,
    }


def dart_info(metadata):
    from dartvm_fetch_build import DartLibInfo
    return DartLibInfo(metadata["dart_version"], metadata["os_name"], metadata["arch"],
                       metadata["compressed_pointers"], metadata.get("snapshot_hash"))


def save_metadata(metadata, output_json=None):
    if output_json:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            for key in ("dart_version", "arch", "os_name", "snapshot_hash"):
                if key in metadata:
                    f.write(f"{key}={metadata[key]}\n")
    print(json.dumps(metadata, indent=2, ensure_ascii=False), flush=True)


def apply_patch(blutter_dir):
    patch = ROOT / "patches" / "blutter-dart314.patch"
    command = ["git", "-C", str(blutter_dir), "apply"]
    if subprocess.run(command + ["--reverse", "--check", str(patch)],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        print("Blutter compatibility patch already applied")
        return
    subprocess.run(command + ["--check", str(patch)], check=True)
    subprocess.run(command + [str(patch)], check=True)


def build_only(info, blutter_dir, no_analysis=False):
    blutter = load_blutter(blutter_dir)
    from dartvm_fetch_build import fetch_and_build
    build_input = blutter.BlutterInput("", info, "", True, False, no_analysis)
    suffix = ".lib" if os.name == "nt" else ".a"
    prefix = "" if os.name == "nt" else "lib"
    library = Path(blutter.PKG_LIB_DIR) / (prefix + info.lib_name + suffix)
    if not library.is_file():
        fetch_and_build(info)
    blutter.cmake_blutter(build_input)
    if not Path(build_input.blutter_file).is_file():
        raise RuntimeError(f"Build completed without binary: {build_input.blutter_file}")
    print(f"Built {build_input.blutter_file}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover", "patch", "detect", "analyze", "build"))
    parser.add_argument("--blutter-dir", type=Path, default=ROOT / "blutter")
    parser.add_argument("--target")
    parser.add_argument("--dart-version", default="auto")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "discover":
        print(json.dumps(discover_targets(), ensure_ascii=False))
        return
    if args.command == "patch":
        apply_patch(args.blutter_dir)
        return
    if args.command in ("detect", "analyze") or args.dart_version in ("", "auto"):
        if not args.target:
            parser.error("--target is required for automatic Dart version detection")
        metadata = detect_metadata(args.target, args.blutter_dir)
    else:
        if re.fullmatch(VERSION_PATTERN, args.dart_version) is None:
            parser.error("--dart-version must be a version such as 3.14.0 or auto")
        load_blutter(args.blutter_dir)
        metadata = {"dart_version": args.dart_version, "os_name": "android", "arch": "arm64",
                    "compressed_pointers": True}
    save_metadata(metadata, args.output_json)
    if args.command == "detect":
        return
    info = dart_info(metadata)
    if args.command == "build":
        build_only(info, args.blutter_dir)
    else:
        blutter = load_blutter(args.blutter_dir)
        directory = target_directory(args.target)
        outdir = (args.out_dir or ROOT / "out" / args.target).resolve()
        outdir.mkdir(parents=True, exist_ok=True)
        build_input = blutter.BlutterInput(str(directory / "libapp.so"), info,
                                          str(outdir), False, False, False)
        blutter.build_and_run(build_input)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
