"""Small synthetic ELF fixtures exercise both old and unified Dart snapshots."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from blutter_ci import detect_metadata, discover_targets, load_blutter

blutter = load_blutter(ROOT / "blutter")
from extract_dart_info import extract_snapshot_hash_flags, extract_libflutter_info
from dartvm_fetch_build import DartLibInfo


def elf_fixture(symbol_name, payload, virtual_base=0x10000, machine=183):
    # ELF64 little-endian with .dynstr, .dynsym and .rodata. st_value differs
    # deliberately from the file offset, as is allowed by the ELF specification.
    shstr = b"\0.shstrtab\0.dynstr\0.dynsym\0.rodata\0"
    dynstr = b"\0" + symbol_name.encode() + b"\0"
    blob = bytearray(64)
    def append(data):
        offset = len(blob)
        blob.extend(data)
        return offset
    shstr_offset = append(shstr)
    str_offset = append(dynstr)
    data_offset = append(payload)
    sym = struct.pack("<IBBHQQ", 1, 0x11, 0, 4, virtual_base, len(payload))
    sym_offset = append(bytes(24) + sym)
    while len(blob) % 8:
        blob.append(0)
    sh_offset = len(blob)
    headers = [bytes(64)]
    for name, kind, address, offset, size, link, align, entsize in (
        (b".shstrtab", 3, 0, shstr_offset, len(shstr), 0, 1, 0),
        (b".dynstr", 3, 0, str_offset, len(dynstr), 0, 1, 0),
        (b".dynsym", 11, 0, sym_offset, 48, 2, 8, 24),
        (b".rodata", 1, virtual_base, data_offset, len(payload), 0, 8, 0),
    ):
        headers.append(struct.pack("<IIQQQQIIQQ", shstr.index(name), kind, 0,
                                   address, offset, size, link, 0, align, entsize))
    blob.extend(b"".join(headers))
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(8)
    blob[:64] = struct.pack("<16sHHIQQQIHHHHHH", ident, 3, machine, 1, 0, 0,
                            sh_offset, 0, 64, 56, 0, 64, 5, 1)
    return blob


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name) / "fixture.so"

    def write_elf(self, symbol, payload, **kwargs):
        self.library.write_bytes(elf_fixture(symbol, payload, **kwargs))
        return str(self.library)

    def test_old_and_new_snapshot_symbols_with_virtual_address_mapping(self):
        flags = b"product arm64 android compressed-pointers"
        payload = struct.pack("<Iqq", 0xdcdcf5f5, 256, 2) + b"a" * 32 + flags + b"\0"
        for name in ("_kDartVmSnapshotData", "_kDartSnapshotData"):
            with self.subTest(symbol=name):
                digest, found = extract_snapshot_hash_flags(self.write_elf(name, payload))
                self.assertEqual(digest, "a" * 32)
                self.assertEqual(found, flags.decode().split())

    def test_missing_snapshot_symbol_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "Cannot find Dart snapshot"):
            extract_snapshot_hash_flags(self.write_elf("wrong_symbol", bytes(256)))

    def test_invalid_magic_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "magic"):
            extract_snapshot_hash_flags(self.write_elf("_kDartSnapshotData", bytes(256)))

    def test_unterminated_flags_are_rejected(self):
        payload = struct.pack("<Iqq", 0xdcdcf5f5, 256, 2) + b"a" * 32 + b"product"
        with self.assertRaisesRegex(ValueError, "Unterminated"):
            extract_snapshot_hash_flags(self.write_elf("_kDartSnapshotData", payload))

    def test_stable_version_does_not_require_exactly_two_engine_hashes(self):
        path = self.write_elf("unused", b'\0' + b'3.14.0 (stable) on "android_arm64"\0')
        engines, version, arch, os_name = extract_libflutter_info(path)
        self.assertEqual((engines, version, arch, os_name), ([], "3.14.0", "arm64", "android"))

    def test_beta_version_and_x64_machine(self):
        path = self.write_elf("unused", b'\0' + b'3.14.0-1.2.beta (beta)\0', machine=62)
        self.assertEqual(extract_libflutter_info(path)[1:3], ("3.14.0-1.2.beta", "x64"))

    def test_new_dart_disables_only_unsupported_advanced_analysis(self):
        info = DartLibInfo("3.14.0", "android", "arm64")
        item = blutter.BlutterInput("input.so", info, "out", False, False, False)
        self.assertTrue(item.no_analysis)
        self.assertTrue(item.blutter_name.endswith("_no-analysis"))
        older = blutter.BlutterInput("input.so", DartLibInfo("3.8.1", "android", "arm64"),
                                     "out", False, False, False)
        self.assertFalse(older.no_analysis)

    def test_checked_in_targets_have_consistent_metadata(self):
        for target in discover_targets():
            with self.subTest(target=target):
                metadata = detect_metadata(target, ROOT / "blutter")
                self.assertRegex(metadata["dart_version"], r"^\d+\.\d+\.\d+")
                self.assertRegex(metadata["snapshot_hash"], r"^[a-f0-9]{32}$")
                self.assertEqual(metadata["arch"], "arm64")
                self.assertIn("android", metadata["flags"])



if __name__ == "__main__":
    unittest.main()
