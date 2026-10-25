from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from peglin_l10n.candidate import _write_zip_atomically
from peglin_l10n.manager_package import create_manager_package

PREFIX = "BepInEx/plugins/PeglinKoreanRevised/"
DLL = PREFIX + "PeglinKoreanRevised.dll"
OVERLAY = PREFIX + "overlay.json"
INTEGRITY = PREFIX + "manifest.json"
SOURCE = {
    "steamAppId": "1296610",
    "steamBuildId": "22988052",
    "unityVersion": "2022.3.62f2",
    "assetSha256": "6625e7db90be3fbe28f207ee2b5ecebe95c3011e68a40002af10db98f23fbeb2",
}


def _json(value: dict[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ManagerPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "input.zip"
        self.output = self.root / "manager.zip"
        overlay = {
            "schemaVersion": 1,
            "kind": "peglin-korean-overlay",
            "game": "Peglin",
            "language": "ko",
            "status": "draft",
            "source": SOURCE,
            "terms": {f"fixture/{index}": "시험" for index in range(1899)},
        }
        self.members = {
            DLL: b"synthetic fixture DLL (never a public manager package)",
            OVERLAY: _json(overlay),
            "README.md": b"synthetic manual candidate README",
            "LICENSE": b"fixture license",
            "TRANSLATION-NOTICE.txt": b"fixture notice",
        }
        self.members[INTEGRITY] = _json(
            {
                "schemaVersion": 1,
                "kind": "peglin-korean-client-candidate",
                "game": "Peglin",
                "steamAppId": "1296610",
                "language": "ko",
                "status": "draft",
                "translationCount": 1899,
                "source": SOURCE,
                "runtime": {
                    "pluginGuid": "piesp.peglin.koreanrevised",
                    "pluginVersion": "0.1.2",
                    "assemblyCSharpSha256": "bf5af951bf16373f507c30af068ccc92aa867affbe6e855decf82486c2dc6244",
                    "recommendedPeglinPack": "BepInExPack_Peglin 5.4.2100",
                    "minimumBepInExVersion": "5.4.21",
                },
                "files": {DLL: _sha(self.members[DLL]), OVERLAY: _sha(self.members[OVERLAY])},
            }
        )
        self._write()

    def _write(self) -> str:
        _write_zip_atomically(self.input, self.members)
        return _sha(self.input.read_bytes())

    def _build(self) -> Path:
        return create_manager_package(self.input, _sha(self.input.read_bytes()), self.output)

    def test_preserves_qualified_payload_and_builds_manager_root(self) -> None:
        self._build()
        first = self.output.read_bytes()
        self._build()
        self.assertEqual(first, self.output.read_bytes())
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    DLL,
                    OVERLAY,
                    INTEGRITY,
                    "README.md",
                    "LICENSE",
                    "TRANSLATION-NOTICE.txt",
                    "manifest.json",
                    "icon.png",
                },
            )
            for name in (DLL, OVERLAY, INTEGRITY, "LICENSE", "TRANSLATION-NOTICE.txt"):
                self.assertEqual(archive.read(name), self.members[name])
            self.assertNotEqual(archive.read("manifest.json"), self.members[INTEGRITY])
            root = json.loads(archive.read("manifest.json"))
            self.assertEqual(root["name"], "PeglinKoreanRevised")
            self.assertEqual(root["version_number"], "0.1.2")
            self.assertEqual(root["dependencies"], ["BepInEx-BepInExPack_Peglin-5.4.2100"])
            self.assertEqual(struct.unpack(">II", archive.read("icon.png")[16:24]), (256, 256))
            self.assertIn(_sha(self.input.read_bytes()), archive.read("README.md").decode())
            self.assertNotIn("BepInEx.cfg", archive.namelist())

    def test_wrong_whole_zip_anchor_keeps_previous_output(self) -> None:
        self.output.write_bytes(b"previous output")
        with self.assertRaisesRegex(ValueError, "qualification anchor"):
            create_manager_package(self.input, "0" * 64, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous output")

    def test_rejects_extra_duplicate_traversal_and_large_member(self) -> None:
        for name, data in (
            ("BepInEx/config/BepInEx.cfg", b"unsafe"),
            (DLL, b"duplicate"),
            ("../escape", b"unsafe"),
            ("extra.bin", b"x" * (2 * 1024 * 1024)),
        ):
            with self.subTest(name=name):
                self._write()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(self.input, "a") as archive:
                        archive.writestr(name, data)
                self.output.write_bytes(b"previous output")
                with self.assertRaisesRegex(ValueError, "exactly the six|size limit"):
                    self._build()
                self.assertEqual(self.output.read_bytes(), b"previous output")

    def test_rejects_bad_crc(self) -> None:
        data = bytearray(self.input.read_bytes())
        offset = data.index(b"PK\x01\x02") + 16  # Central directory CRC for the first member.
        data[offset] ^= 1
        self.input.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "CRC|ZIP"):
            self._build()

    def test_rejects_unsupported_compression_without_writing(self) -> None:
        data = bytearray(self.input.read_bytes())
        data[data.index(b"PK\x03\x04") + 8 : data.index(b"PK\x03\x04") + 10] = b"\x63\x00"
        data[data.index(b"PK\x01\x02") + 10 : data.index(b"PK\x01\x02") + 12] = b"\x63\x00"
        self.input.write_bytes(data)
        self.output.write_bytes(b"previous output")
        with self.assertRaisesRegex(ValueError, "Invalid input ZIP"):
            self._build()
        self.assertEqual(self.output.read_bytes(), b"previous output")

    def test_rejects_status_source_and_self_manifest_tampering(self) -> None:
        original = self.members[INTEGRITY]
        for field in ("status", "source", "files"):
            with self.subTest(field=field):
                manifest = json.loads(original)
                if field == "status":
                    manifest[field] = "approved"
                elif field == "source":
                    manifest[field]["steamBuildId"] = "another-build"
                else:
                    manifest[field][DLL] = "0" * 64
                self.members[INTEGRITY] = _json(manifest)
                self._write()
                with self.assertRaises(ValueError):
                    self._build()
                self.members[INTEGRITY] = original

    def test_rejects_overlay_identity_tampering(self) -> None:
        overlay = json.loads(self.members[OVERLAY])
        overlay["status"] = "approved"
        self.members[OVERLAY] = _json(overlay)
        manifest = json.loads(self.members[INTEGRITY])
        manifest["files"][OVERLAY] = _sha(self.members[OVERLAY])
        self.members[INTEGRITY] = _json(manifest)
        self._write()
        with self.assertRaisesRegex(ValueError, "supported draft"):
            self._build()

    def test_rejects_oversized_expanded_overlay(self) -> None:
        self.members[OVERLAY] = b"x" * (1024 * 1024 + 1)
        self._write()
        with self.assertRaisesRegex(ValueError, "oversized"):
            self._build()
