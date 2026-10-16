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

    def _write_overlay(self, overlay: dict[str, object]) -> None:
        self.overlay.write_text(json.dumps(overlay, ensure_ascii=False) + "\n", encoding="utf-8")

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

    def _prebuilt(self, output: Path) -> Path:
        self.plugin.parent.mkdir(parents=True, exist_ok=True)
        self.plugin.write_bytes(b"fixture compiled plugin\x00")
        return candidate.create_prebuilt_client_candidate(
            self.overlay,
            output,
            self.plugin,
            hashlib.sha256(self.assembly.read_bytes()).hexdigest(),
            self.root,
        )

    def test_prebuilt_packages_the_validated_overlay_snapshot_after_path_replacement(self) -> None:
        original_bytes = self.overlay.read_bytes()
        original = json.loads(original_bytes)
        overlay_member = "BepInEx/plugins/PeglinKoreanRevised/overlay.json"
        manifest_member = "BepInEx/plugins/PeglinKoreanRevised/manifest.json"

        for label, replacement in (
            (
                "valid",
                {
                    **original,
                    "status": "approved",
                    "source": {**original["source"], "steamBuildId": "new-build"},
                    "terms": {"Other/Term": "다른 문구", "Extra/Term": "추가 문구"},
                },
            ),
            ("wrong language", {**original, "language": "en"}),
        ):
            with self.subTest(label=label):
                self.overlay.write_bytes(original_bytes)
                replacement_bytes = (json.dumps(replacement, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                )
                reads = 0
                original_open = Path.open
                overlay_path = self.overlay

                class InterleavingReader:
                    def __init__(self, stream: object) -> None:
                        self.stream = stream

                    def __enter__(self) -> InterleavingReader:
                        return self

                    def __exit__(self, *args: object) -> None:
                        self.stream.close()

                    def read(self, *args: object) -> object:
                        nonlocal reads
                        contents = self.stream.read(*args)
                        reads += 1
                        if reads == 1:
                            overlay_path.write_bytes(replacement_bytes)
                        return contents

                def interleaved_open(path: Path, *args: object, **kwargs: object) -> object:
                    stream = original_open(path, *args, **kwargs)
                    mode = kwargs.get("mode", args[0] if args else "r")
                    if path == overlay_path and mode in {"r", "rb"}:
                        return InterleavingReader(stream)
                    return stream

                with patch.object(Path, "open", interleaved_open):
                    archive_path = self._prebuilt(self.root / f"prebuilt-{label}")
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(sorted(archive.namelist()), archive.namelist())
                    self.assertEqual(6, len(archive.namelist()))
                    archived_bytes = archive.read(overlay_member)
                    manifest = json.loads(archive.read(manifest_member))
                    readme = archive.read("README.md").decode("utf-8")
                self.assertEqual(original_bytes, archived_bytes)
                self.assertEqual(1, reads)
                self.assertEqual(
                    hashlib.sha256(original_bytes).hexdigest(), manifest["files"][overlay_member]
                )
                self.assertEqual("fixture-build", manifest["source"]["steamBuildId"])
                self.assertEqual("draft", manifest["status"])
                self.assertEqual(1, manifest["translationCount"])
                self.assertIn("fixture-build", readme)
                self.assertIn("번역 상태: 초안입니다", readme)
                self.assertEqual(
                    f"PeglinKoreanRevised-fixture-build-{original['source']['assetSha256'][:8]}.zip",
                    archive_path.name,
                )

    def test_prebuilt_preserves_overlay_formatting_and_korean_bytes(self) -> None:
        original = json.loads(self.overlay.read_text(encoding="utf-8"))
        overlay_member = "BepInEx/plugins/PeglinKoreanRevised/overlay.json"
        manifest_member = "BepInEx/plugins/PeglinKoreanRevised/manifest.json"
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                formatted = (json.dumps(original, ensure_ascii=False, indent=2) + "\n").replace(
                    "\n", newline
                )
                expected_bytes = formatted.encode("utf-8")
                self.overlay.write_bytes(expected_bytes)
                archive_path = self._prebuilt(self.root / f"formatted-{len(newline)}")
                first_zip_bytes = archive_path.read_bytes()
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(expected_bytes, archive.read(overlay_member))
                    manifest = json.loads(archive.read(manifest_member))
                    self.assertEqual(
                        hashlib.sha256(expected_bytes).hexdigest(),
                        manifest["files"][overlay_member],
                    )
                    self.assertEqual(original["source"], manifest["source"])
                    self.assertEqual("draft", manifest["status"])
                    self.assertEqual(1, manifest["translationCount"])
                self.assertEqual(first_zip_bytes, self._prebuilt(archive_path.parent).read_bytes())

    def test_invalid_overlay_inputs_reject_both_routes_without_replacing_output(self) -> None:
        original = json.loads(self.overlay.read_text(encoding="utf-8"))
        wrong_language = {**original, "language": "en"}
        invalid_source = {**original, "source": {**original["source"], "steamBuildId": "bad id"}}
        cases = (
            (
                "missing",
                None,
                ValueError,
                "Overlay JSON does not exist|Could not read overlay JSON",
            ),
            ("unreadable", b"placeholder", ValueError, "Could not read overlay JSON"),
            ("invalid-utf8", b"\xff", UnicodeDecodeError, "utf-8"),
            ("bom", b"\xef\xbb\xbf{}", ValueError, "Could not read overlay JSON"),
            ("malformed", b"{bad", ValueError, "Could not read overlay JSON"),
            (
                "wrong-language",
                (json.dumps(wrong_language, ensure_ascii=False) + "\n").encode("utf-8"),
                ValueError,
                "Overlay must target Peglin and Korean",
            ),
            (
                "invalid-source",
                (json.dumps(invalid_source, ensure_ascii=False) + "\n").encode("utf-8"),
                ValueError,
                "Overlay source steamBuildId is invalid",
            ),
        )
        original_read_bytes = Path.read_bytes

        for route in ("build", "prebuilt"):
            for label, contents, error_type, error_message in cases:
                with self.subTest(route=route, label=label):
                    if contents is None:
                        self.overlay.unlink(missing_ok=True)
                    else:
                        self.overlay.write_bytes(contents)
                    output = self.root / f"reject-{route}-{label}"
                    output.mkdir()
                    existing = output / "existing.zip"
                    existing.write_bytes(b"existing candidate")
                    self.commands.clear()

                    def read_bytes(path: Path) -> bytes:
                        if label == "unreadable" and path == self.overlay:
                            raise OSError("injected overlay read error")
                        return original_read_bytes(path)

                    with patch.object(Path, "read_bytes", read_bytes):
                        with self.assertRaisesRegex(error_type, error_message):
                            if route == "build":
                                with patch.object(
                                    candidate,
                                    "_run_dotnet",
                                    side_effect=AssertionError("invalid overlay reached the build"),
                                ):
                                    candidate.create_client_candidate(
                                        self.overlay,
                                        self.game,
                                        output,
                                        self.project,
                                        project_root=self.root,
                                    )
                            else:
                                self._prebuilt(output)
                    self.assertEqual([], self.commands)
                    self.assertEqual([existing], list(output.iterdir()))
                    self.assertEqual(b"existing candidate", existing.read_bytes())

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

    def test_invalid_source_fields_reject_before_build_without_replacing_output(self) -> None:
        original = json.loads(self.overlay.read_text(encoding="utf-8"))
        output = self.root / "output"
        output.mkdir()
        existing = output / "existing.zip"
        existing.write_bytes(b"existing candidate")
        cases = (
            ("missing build ID", "steamBuildId", None, "steamBuildId is invalid"),
            ("wrong build ID type", "steamBuildId", 123, "steamBuildId is invalid"),
            ("malformed build ID", "steamBuildId", "bad id", "steamBuildId is invalid"),
            ("missing asset hash", "assetSha256", None, "assetSha256 is invalid"),
            ("wrong asset hash type", "assetSha256", 123, "assetSha256 is invalid"),
            ("short asset hash", "assetSha256", "a" * 63, "assetSha256 is invalid"),
            ("uppercase asset hash", "assetSha256", "A" * 64, "assetSha256 is invalid"),
        )
        for label, field, value, error in cases:
            with self.subTest(label=label):
                overlay = json.loads(json.dumps(original))
                if value is None:
                    del overlay["source"][field]
                else:
                    overlay["source"][field] = value
                self._write_overlay(overlay)
                self.commands.clear()
                with self.assertRaisesRegex(ValueError, f"Overlay source {error}"):
                    self._build()
                self.assertEqual([], self.commands)
                self.assertEqual([existing], list(output.iterdir()))
                self.assertEqual(b"existing candidate", existing.read_bytes())

    def test_prebuilt_accepts_supported_source_format_boundaries(self) -> None:
        original = json.loads(self.overlay.read_text(encoding="utf-8"))
        self.plugin.parent.mkdir(parents=True)
        self.plugin.write_bytes(b"fixture compiled plugin\x00")
        cases = (("a", "0" * 64), ("A._-9" * 12 + "A._-", "abcdef" * 10 + "abcd"))
        for build_id, asset_hash in cases:
            with self.subTest(build_id=build_id):
                overlay = json.loads(json.dumps(original))
                overlay["source"]["steamBuildId"] = build_id
                overlay["source"]["assetSha256"] = asset_hash
                self._write_overlay(overlay)
                archive = candidate.create_prebuilt_client_candidate(
                    self.overlay,
                    self.root / "prebuilt",
                    self.plugin,
                    hashlib.sha256(self.assembly.read_bytes()).hexdigest(),
                    self.root,
                )
                self.assertTrue(archive.is_file())
                self.assertIn(build_id, archive.name)

    def test_prebuilt_revalidates_overlay_before_replacing_output(self) -> None:
        original = json.loads(self.overlay.read_text(encoding="utf-8"))
        self.plugin.parent.mkdir(parents=True)
        self.plugin.write_bytes(b"fixture compiled plugin\x00")
        output = self.root / "prebuilt"
        output.mkdir()
        existing = output / "existing.zip"
        existing.write_bytes(b"existing candidate")
        for field, value, error in (
            ("steamBuildId", "bad id", "steamBuildId is invalid"),
            ("assetSha256", "A" * 64, "assetSha256 is invalid"),
        ):
            with self.subTest(field=field):
                overlay = json.loads(json.dumps(original))
                overlay["source"][field] = value
                self._write_overlay(overlay)
                with self.assertRaisesRegex(ValueError, f"Overlay source {error}"):
                    candidate.create_prebuilt_client_candidate(
                        self.overlay,
                        output,
                        self.plugin,
                        hashlib.sha256(self.assembly.read_bytes()).hexdigest(),
                        self.root,
                    )
                self.assertEqual([existing], list(output.iterdir()))
                self.assertEqual(b"existing candidate", existing.read_bytes())

    def test_prebuilt_keeps_source_terms_status_and_json_checks(self) -> None:
        original = json.loads(self.overlay.read_text(encoding="utf-8"))
        self.plugin.parent.mkdir(parents=True)
        self.plugin.write_bytes(b"fixture compiled plugin\x00")
        for field, value, error in (
            ("source", None, "source metadata and translation terms are required"),
            ("terms", {}, "source metadata and translation terms are required"),
            ("status", "unreviewed", "status must be draft or approved"),
        ):
            with self.subTest(field=field):
                overlay = json.loads(json.dumps(original))
                overlay[field] = value
                self._write_overlay(overlay)
                with self.assertRaisesRegex(ValueError, error):
                    candidate.create_prebuilt_client_candidate(
                        self.overlay,
                        self.root / "prebuilt",
                        self.plugin,
                        hashlib.sha256(self.assembly.read_bytes()).hexdigest(),
                        self.root,
                    )
                self.assertFalse((self.root / "prebuilt").exists())

        self.overlay.write_text("{invalid json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Could not read overlay JSON"):
            candidate.create_prebuilt_client_candidate(
                self.overlay,
                self.root / "prebuilt",
                self.plugin,
                hashlib.sha256(self.assembly.read_bytes()).hexdigest(),
                self.root,
            )
        self.assertFalse((self.root / "prebuilt").exists())

    def test_overlay_changed_during_build_is_revalidated_before_packaging(self) -> None:
        original = json.loads(self.overlay.read_text(encoding="utf-8"))

        def fake_dotnet(command: list[str], project_dir: Path) -> None:
            self.assertEqual(self.project.parent, project_dir)
            self.commands.append(command[1])
            if command[1] == "build":
                self.plugin.parent.mkdir(parents=True, exist_ok=True)
                self.plugin.write_bytes(b"fixture compiled plugin\x00")
                original["source"]["assetSha256"] = "A" * 64
                self._write_overlay(original)

        with patch.object(candidate, "_run_dotnet", side_effect=fake_dotnet):
            with self.assertRaisesRegex(ValueError, "Overlay source assetSha256 is invalid"):
                candidate.create_client_candidate(
                    self.overlay,
                    self.game,
                    self.root / "output",
                    self.project,
                    project_root=self.root,
                )
        self.assertEqual(["restore", "build"], self.commands)
        self.assertFalse((self.root / "output").exists())

    def test_valid_source_identity_drift_during_build_preserves_prior_candidate(self) -> None:
        original_bytes = self.overlay.read_bytes()
        original = json.loads(original_bytes)
        overlay_member = "BepInEx/plugins/PeglinKoreanRevised/overlay.json"
        manifest_member = "BepInEx/plugins/PeglinKoreanRevised/manifest.json"

        for fields in (("assetSha256",), ("steamBuildId",), ("assetSha256", "steamBuildId")):
            with self.subTest(fields=fields):
                self.overlay.write_bytes(original_bytes)
                prior_path = self._build()
                prior_bytes = prior_path.read_bytes()
                replacement = json.loads(original_bytes)
                if "assetSha256" in fields:
                    replacement["source"]["assetSha256"] = "b" * 64
                if "steamBuildId" in fields:
                    replacement["source"]["steamBuildId"] = "different-build"
                replacement["terms"]["General/Damage"] = "새 피해"
                replacement_bytes = (json.dumps(replacement, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                )
                self.commands.clear()

                def fake_dotnet(command: list[str], project_dir: Path) -> None:
                    self.assertEqual(self.project.parent, project_dir)
                    self.commands.append(command[1])
                    if command[1] == "build":
                        self.plugin.write_bytes(b"fixture compiled plugin\x00")
                        self.overlay.write_bytes(replacement_bytes)

                with patch.object(candidate, "_run_dotnet", side_effect=fake_dotnet):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Overlay source identity changed while building.*" + fields[0],
                    ):
                        candidate.create_client_candidate(
                            self.overlay,
                            self.game,
                            prior_path.parent,
                            self.project,
                            project_root=self.root,
                        )
                self.assertEqual(["restore", "build"], self.commands)
                self.assertEqual([prior_path], list(prior_path.parent.iterdir()))
                self.assertEqual(prior_bytes, prior_path.read_bytes())
                with zipfile.ZipFile(prior_path) as archive:
                    self.assertEqual(original_bytes, archive.read(overlay_member))
                    self.assertEqual(
                        original["source"], json.loads(archive.read(manifest_member))["source"]
                    )

    def test_same_source_build_edit_packages_final_validated_bytes(self) -> None:
        original = json.loads(self.overlay.read_bytes())
        overlay_member = "BepInEx/plugins/PeglinKoreanRevised/overlay.json"
        manifest_member = "BepInEx/plugins/PeglinKoreanRevised/manifest.json"
        for newline, edit_terms, escape_korean in (
            ("\n", False, False),
            ("\r\n", False, False),
            ("\n", True, False),
            ("\n", True, True),
        ):
            with self.subTest(
                newline=repr(newline), edit_terms=edit_terms, escape_korean=escape_korean
            ):
                changed = json.loads(json.dumps(original))
                if edit_terms:
                    changed["terms"]["General/Damage"] = "새 피해"
                    changed["terms"]["General/Other"] = "추가 문구"
                final_bytes = (
                    (json.dumps(changed, ensure_ascii=escape_korean, indent=2) + "\n")
                    .replace("\n", newline)
                    .encode("utf-8")
                )
                self._write_overlay(original)
                self.commands.clear()

                def fake_dotnet(command: list[str], project_dir: Path) -> None:
                    self.assertEqual(self.project.parent, project_dir)
                    self.commands.append(command[1])
                    if command[1] == "build":
                        self.plugin.parent.mkdir(parents=True, exist_ok=True)
                        self.plugin.write_bytes(b"fixture compiled plugin\x00")
                        self.overlay.write_bytes(final_bytes)

                with patch.object(candidate, "_run_dotnet", side_effect=fake_dotnet):
                    archive_path = candidate.create_client_candidate(
                        self.overlay,
                        self.game,
                        self.root / "output",
                        self.project,
                        project_root=self.root,
                    )
                self.assertEqual(["restore", "build"], self.commands)
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(final_bytes, archive.read(overlay_member))
                    manifest = json.loads(archive.read(manifest_member))
                self.assertEqual(changed["source"], manifest["source"])
                self.assertEqual(len(changed["terms"]), manifest["translationCount"])
                self.assertEqual(
                    hashlib.sha256(final_bytes).hexdigest(), manifest["files"][overlay_member]
                )

    def test_installed_route_packages_the_validated_snapshot_after_path_replacement(self) -> None:
        original_bytes = self.overlay.read_bytes()
        replacement = json.loads(original_bytes)
        replacement["source"]["assetSha256"] = "b" * 64
        replacement["source"]["steamBuildId"] = "different-build"
        replacement_bytes = (json.dumps(replacement, ensure_ascii=False) + "\n").encode("utf-8")
        original_read_overlay = candidate._read_overlay
        reads = 0

        def read_then_replace(path: Path) -> tuple[dict[str, object], bytes]:
            nonlocal reads
            snapshot = original_read_overlay(path)
            reads += 1
            if reads == 2:
                self.overlay.write_bytes(replacement_bytes)
            return snapshot

        with patch.object(candidate, "_read_overlay", side_effect=read_then_replace):
            archive_path = self._build()
        self.assertEqual(2, reads)
        self.assertEqual(replacement_bytes, self.overlay.read_bytes())
        with zipfile.ZipFile(archive_path) as archive:
            overlay_member = "BepInEx/plugins/PeglinKoreanRevised/overlay.json"
            manifest_member = "BepInEx/plugins/PeglinKoreanRevised/manifest.json"
            self.assertEqual(original_bytes, archive.read(overlay_member))
            manifest = json.loads(archive.read(manifest_member))
        self.assertEqual(json.loads(original_bytes)["source"], manifest["source"])
        self.assertEqual(
            hashlib.sha256(original_bytes).hexdigest(), manifest["files"][overlay_member]
        )

    def test_invalid_final_overlay_rejects_without_replacing_output(self) -> None:
        original_bytes = self.overlay.read_bytes()
        original = json.loads(original_bytes)
        cases = (
            ("malformed", b"{bad", "Could not read overlay JSON"),
            ("missing source", {**original, "source": None}, "source metadata.*required"),
            (
                "invalid source",
                {**original, "source": {**original["source"], "steamBuildId": "bad id"}},
                "steamBuildId is invalid",
            ),
            ("wrong game", {**original, "game": "Other"}, "must target Peglin and Korean"),
            ("wrong language", {**original, "language": "en"}, "must target Peglin and Korean"),
            (
                "wrong status",
                {**original, "status": "unreviewed"},
                "status must be draft or approved",
            ),
            ("empty terms", {**original, "terms": {}}, "translation terms are required"),
        )
        prior_path = self._build()
        prior_bytes = prior_path.read_bytes()
        for label, replacement, error in cases:
            with self.subTest(label=label):
                self.overlay.write_bytes(original_bytes)
                replacement_bytes = (
                    replacement
                    if isinstance(replacement, bytes)
                    else (json.dumps(replacement, ensure_ascii=False) + "\n").encode("utf-8")
                )
                self.commands.clear()

                def fake_dotnet(command: list[str], project_dir: Path) -> None:
                    self.assertEqual(self.project.parent, project_dir)
                    self.commands.append(command[1])
                    if command[1] == "build":
                        self.plugin.write_bytes(b"fixture compiled plugin\x00")
                        self.overlay.write_bytes(replacement_bytes)

                with patch.object(candidate, "_run_dotnet", side_effect=fake_dotnet):
                    with self.assertRaisesRegex(ValueError, error):
                        candidate.create_client_candidate(
                            self.overlay,
                            self.game,
                            prior_path.parent,
                            self.project,
                            project_root=self.root,
                        )
                self.assertEqual(["restore", "build"], self.commands)
                self.assertEqual([prior_path], list(prior_path.parent.iterdir()))
                self.assertEqual(prior_bytes, prior_path.read_bytes())

    def test_restore_build_and_zip_write_failures_preserve_prior_candidate(self) -> None:
        prior_path = self._build()
        prior_bytes = prior_path.read_bytes()
        for failure in ("restore", "build", "zip-write"):
            with self.subTest(failure=failure):
                self.commands.clear()

                def fake_dotnet(command: list[str], project_dir: Path) -> None:
                    self.assertEqual(self.project.parent, project_dir)
                    self.commands.append(command[1])
                    if command[1] == failure:
                        raise ValueError(f"injected {failure} failure")
                    if command[1] == "build":
                        self.plugin.write_bytes(b"fixture compiled plugin\x00")

                with patch.object(candidate, "_run_dotnet", side_effect=fake_dotnet):
                    if failure == "zip-write":
                        with patch.object(
                            candidate.os, "replace", side_effect=OSError("injected ZIP failure")
                        ):
                            with self.assertRaisesRegex(OSError, "injected ZIP failure"):
                                candidate.create_client_candidate(
                                    self.overlay,
                                    self.game,
                                    prior_path.parent,
                                    self.project,
                                    project_root=self.root,
                                )
                    else:
                        with self.assertRaisesRegex(ValueError, f"injected {failure} failure"):
                            candidate.create_client_candidate(
                                self.overlay,
                                self.game,
                                prior_path.parent,
                                self.project,
                                project_root=self.root,
                            )
                self.assertEqual([prior_path], list(prior_path.parent.iterdir()))
                self.assertEqual(prior_bytes, prior_path.read_bytes())

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
