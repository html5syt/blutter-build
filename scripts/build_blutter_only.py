#!/usr/bin/env python3
"""Compatibility entry point: build_blutter_only.py <dart_version> [os] [arch].

Run from the patched blutter checkout. Use blutter_ci.py build --target <name>
for automatic version detection. Build logic is shared with upstream blutter.py
instead of maintaining a divergent copy of compatibility macros.
"""
import argparse
from pathlib import Path

from blutter_ci import VERSION_PATTERN, build_only, load_blutter
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dart_version")
    parser.add_argument("os_name", nargs="?", default="android", choices=("android", "ios"))
    parser.add_argument("arch", nargs="?", default="arm64", choices=("arm64", "x64"))
    args = parser.parse_args()
    if re.fullmatch(VERSION_PATTERN, args.dart_version) is None:
        parser.error("Invalid Dart version; expected a version such as 3.14.0")
    directory = Path.cwd()
    load_blutter(directory)
    from dartvm_fetch_build import DartLibInfo
    build_only(DartLibInfo(args.dart_version, args.os_name, args.arch), directory)


if __name__ == "__main__":
    main()
