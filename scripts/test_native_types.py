#!/usr/bin/env python3
"""Compile and run the native type regression against an already-built Dart VM."""
import argparse
import os
from pathlib import Path
import subprocess

from blutter_ci import ROOT, dart_info, detect_metadata, load_blutter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--blutter-dir", type=Path, default=ROOT / "blutter")
    args = parser.parse_args()
    metadata = detect_metadata(args.target, args.blutter_dir)
    blutter = load_blutter(args.blutter_dir)
    info = dart_info(metadata)
    item = blutter.BlutterInput("", info, "", False, False, False)
    macros = blutter.find_compat_macro(info.version, item.no_analysis)
    build = args.blutter_dir.resolve() / "build" / "native-type-test"
    build.mkdir(parents=True, exist_ok=True)
    source = args.blutter_dir.resolve() / "blutter" / "src"
    includes = [Path(blutter.PKG_INC_DIR) / ("dartvm" + info.version), source]
    files = [ROOT / "tests" / "native_type_metadata.cpp",
             source / "DartTypes.cpp", source / "DartLoader.cpp", source / "ElfHelper.cpp"]
    defines = ["NDEBUG", "PRODUCT", "DART_PRECOMPILED_RUNTIME",
               "TARGET_ARCH_ARM64", "DART_TARGET_OS_ANDROID"]
    if info.has_compressed_ptrs:
        defines.append("DART_COMPRESSED_POINTERS")
    executable = build / ("native_type_metadata.exe" if os.name == "nt" else "native_type_metadata")
    if os.name == "nt":
        command = ["cl", "/nologo", "/MD", "/EHsc", "/std:c++20", "/Zc:preprocessor", "/utf-8"]
        command += ["/D" + value for value in defines] + macros
        command += ["/I" + str(path) for path in includes] + [str(path) for path in files]
        command += ["/Fo" + str(build) + os.sep, "/Fe" + str(executable), "/link",
                    str(Path(blutter.PKG_LIB_DIR) / (info.lib_name + ".lib")),
                    str(args.blutter_dir.resolve() / "external" / "icu-windows" / "lib64" / "icuuc.lib"),
                    "ntdll.lib", "advapi32.lib"]
    else:
        command = ["c++", "-std=c++20", "-fno-rtti"] + ["-D" + value for value in defines] + macros
        command += ["-I" + str(path) for path in includes] + [str(path) for path in files]
        command += [str(Path(blutter.PKG_LIB_DIR) / ("lib" + info.lib_name + ".a")),
                    "-licuuc", "-ldl", "-pthread", "-o", str(executable)]
    subprocess.run(command, check=True)
    environment = {**os.environ, "PATH": str(Path(blutter.BIN_DIR)) + os.pathsep + os.environ.get("PATH", "")}
    library = ROOT / "targets" / args.target / "lib" / "arm64-v8a" / "libapp.so"
    subprocess.run([str(executable), str(library)], check=True, env=environment)


if __name__ == "__main__":
    main()
