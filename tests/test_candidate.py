from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from peglin_l10n import candidate
from peglin_l10n.source_lock import sha256_file


class FileHashTests(unittest.TestCase):
    def test_hashes_empty_binary_and_multi_chunk_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, contents in (
                ("empty", b""),
                ("한글 file.bin", b"\x00\xff\x80\x01"),
                ("large", bytes(range(256)) * 8193),
            ):
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(contents)
                    self.assertEqual(hashlib.sha256(contents).hexdigest(), sha256_file(path))

    def test_missing_file_and_read_error_propagate_and_close_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                sha256_file(Path(temporary) / "missing")

        class BrokenStream(io.BytesIO):
            def read(self, size: int = -1) -> bytes:
                raise OSError("injected read failure")

        stream = BrokenStream(b"contents")
        with patch.object(Path, "open", return_value=stream):
            with self.assertRaisesRegex(OSError, "injected read failure"):
                sha256_file(Path("injected"))
        self.assertTrue(stream.closed)


class ClientCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.game = self.root / "game"
        self.asset = self.game / "Peglin_Data" / "resources.assets"
        self.assembly = self.game / "Peglin_Data" / "Managed" / "Assembly-CSharp.dll"
        self.assembly.parent.mkdir(parents=True)
        self.asset.write_bytes(b"fixture resources\x00\xff")
        self.assembly.write_bytes(b"fixture managed assembly\x80")
        self.project = self.root / "plugin" / "PeglinKoreanRevised.csproj"
        self.project.parent.mkdir()
        self.project.write_text("<Project />\n", encoding="utf-8")
        (self.project.parent / "NuGet.Config").write_text("<configuration />\n", encoding="utf-8")
        (self.project.parent / "packages.lock.json").write_text("{}\n", encoding="utf-8")
        self.plugin = self.project.parent / "bin" / "Release" / "net46" / "PeglinKoreanRevised.dll"
        self.overlay = self.root / "overlay.json"
        self.overlay.write_text(
            json.dumps(
                {
                    "kind": "peglin-korean-overlay",
                    "game": "Peglin",
                    "language": "ko",
                    "status": "draft",
                    "source": {
                        "steamBuildId": "fixture-build",
                        "assetSha256": hashlib.sha256(self.asset.read_bytes()).hexdigest(),
                    },
                    "terms": {"General/Damage": "피해"},
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (self.root / "LICENSE").write_bytes(b"fixture MIT license\n")
        (self.root / "TRANSLATION-NOTICE.txt").write_bytes(b"fixture translation notice\n")
        self.commands: list[str] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build(self, changed_file: Path | None = None) -> Path:
        def fake_dotnet(command: list[str], project_dir: Path) -> None:
            self.assertEqual(self.project.parent, project_dir)
            self.commands.append(command[1])
            if command[1] == "build":
                self.plugin.parent.mkdir(parents=True, exist_ok=True)
                self.plugin.write_bytes(b"fixture compiled plugin\x00")
                if changed_file is not None:
                    changed_file.write_bytes(changed_file.read_bytes() + b"changed")

        with patch.object(candidate, "_run_dotnet", side_effect=fake_dotnet):
            return candidate.create_client_candidate(
                self.overlay,
                self.game,
                self.root / "output",
                self.project,
                project_root=self.root,
            )

    def test_matching_sources_package_deterministically(self) -> None:
        first = self._build()
        first_bytes = first.read_bytes()
        with zipfile.ZipFile(first) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertEqual(
                b"fixture compiled plugin\x00",
                archive.read("BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll"),
            )
            self.assertEqual(
                hashlib.sha256(self.assembly.read_bytes()).hexdigest(),
                json.loads(archive.read("BepInEx/plugins/PeglinKoreanRevised/manifest.json"))[
                    "runtime"
                ]["assemblyCSharpSha256"],
            )
        self.assertEqual(first_bytes, self._build().read_bytes())
        self.assertEqual(["restore", "build", "restore", "build"], self.commands)

    def test_initial_asset_mismatch_rejects_before_build(self) -> None:
        self.asset.write_bytes(b"different fixture resources")
        with self.assertRaisesRegex(ValueError, "Overlay source asset hash does not match"):
            self._build()
        self.assertEqual([], self.commands)

    def test_post_build_asset_change_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "resources.assets changed while building"):
            self._build(self.asset)
        self.assertEqual(["restore", "build"], self.commands)

    def test_post_build_assembly_change_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Assembly-CSharp.dll changed while building"):
            self._build(self.assembly)
        self.assertEqual(["restore", "build"], self.commands)


if __name__ == "__main__":
    unittest.main()
