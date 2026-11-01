"""Keep asset identity and change detection across path and descriptor stat APIs."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from peglin_l10n import extract


@dataclass(frozen=True)
class AssetStat:
    st_dev: int = 1
    st_ino: int = 2
    st_size: int = 5
    st_mtime_ns: int = 3
    st_ctime_ns: int = 4


class AssetSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.asset_path = Path(self.temporary.name) / "game/Peglin_Data/resources.assets"
        self.asset_path.parent.mkdir(parents=True)
        self.asset_path.write_bytes(b"asset")
        self.path_stat = AssetStat(st_ctime_ns=10)
        self.descriptor_stat = AssetStat(st_ctime_ns=20)

    def read_with_stats(
        self,
        path_after: AssetStat | None = None,
        descriptor_after: AssetStat | None = None,
        *,
        path_before: AssetStat | None = None,
        descriptor_before: AssetStat | None = None,
    ) -> tuple[bytes, str, tuple[int, int, int, int, int]]:
        path_before = path_before or self.path_stat
        descriptor_before = descriptor_before or self.descriptor_stat
        with (
            patch.object(Path, "stat", side_effect=[path_before, path_after or path_before]),
            patch.object(
                extract.os,
                "fstat",
                side_effect=[descriptor_before, descriptor_after or descriptor_before],
            ),
        ):
            return extract._read_asset_snapshot(self.asset_path)

    def test_stable_path_and_descriptor_ctimes_may_differ(self) -> None:
        data, digest, signature = self.read_with_stats()
        self.assertEqual(b"asset", data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
        self.assertEqual((1, 2, 5, 3, 10), signature)

    def test_replaced_path_before_open_is_rejected(self) -> None:
        replacement = replace(self.descriptor_stat, st_ino=99)
        with self.assertRaisesRegex(extract.ExtractionError, "replaced before"):
            self.read_with_stats(descriptor_before=replacement)

    def test_cross_api_size_or_mtime_mismatch_is_rejected(self) -> None:
        for field, value in (("st_size", 6), ("st_mtime_ns", 30)):
            with self.subTest(field=field):
                changed = replace(self.descriptor_stat, **{field: value})
                with self.assertRaisesRegex(extract.ExtractionError, "replaced before"):
                    self.read_with_stats(descriptor_before=changed)

    def test_descriptor_changes_during_read_are_rejected(self) -> None:
        for field, value in (("st_ctime_ns", 21), ("st_size", 6), ("st_mtime_ns", 30)):
            with self.subTest(field=field):
                changed = replace(self.descriptor_stat, **{field: value})
                with self.assertRaisesRegex(extract.ExtractionError, "changed while"):
                    self.read_with_stats(descriptor_after=changed)

    def test_path_changes_during_read_are_rejected(self) -> None:
        for field, value in (("st_ctime_ns", 11), ("st_ino", 99), ("st_mtime_ns", 30)):
            with self.subTest(field=field):
                changed = replace(self.path_stat, **{field: value})
                with self.assertRaisesRegex(extract.ExtractionError, "changed while"):
                    self.read_with_stats(path_after=changed)

    def test_truncated_read_is_rejected(self) -> None:
        larger = replace(self.path_stat, st_size=6)
        matching_descriptor = replace(self.descriptor_stat, st_size=6)
        with self.assertRaisesRegex(extract.ExtractionError, "truncated"):
            self.read_with_stats(path_before=larger, descriptor_before=matching_descriptor)

    def test_path_replacement_after_read_is_rejected_before_returning_installation(self) -> None:
        actual = self.asset_path.stat()
        initial_signature = extract._stat_signature(actual)
        changed = AssetStat(
            st_dev=actual.st_dev,
            st_ino=actual.st_ino + 1,
            st_size=actual.st_size,
            st_mtime_ns=actual.st_mtime_ns,
            st_ctime_ns=actual.st_ctime_ns,
        )
        script = SimpleNamespace(m_Namespace="I2.Loc", m_ClassName="LanguageSourceAsset")
        header = SimpleNamespace(
            m_Name=extract.TARGET_OBJECT_NAME,
            m_Script=SimpleNamespace(deref_parse_as_object=lambda: script),
        )
        asset_file = SimpleNamespace(header=SimpleNamespace(version=14), unity_version="fixture")
        obj = SimpleNamespace(
            type=SimpleNamespace(name="MonoBehaviour"),
            parse_monobehaviour_head=lambda: header,
            get_raw_data=lambda: b"raw",
            assets_file=asset_file,
        )
        unitypy = SimpleNamespace(
            load=lambda *args, **kwargs: SimpleNamespace(objects=[obj]), __version__="fixture"
        )
        original_stat = Path.stat
        read_done = False

        def read_snapshot(_asset_path: Path) -> tuple[bytes, str, tuple[int, int, int, int, int]]:
            nonlocal read_done
            read_done = True
            return b"asset", "digest", initial_signature

        def stat_after_read(path: Path, *args: object, **kwargs: object) -> object:
            if read_done and path == self.asset_path:
                return changed
            return original_stat(path, *args, **kwargs)

        with (
            patch.object(Path, "stat", autospec=True, side_effect=stat_after_read),
            patch.object(
                extract,
                "_read_asset_snapshot",
                side_effect=read_snapshot,
            ),
            patch.object(extract, "_steam_build_id", return_value=None),
            patch.object(extract, "_mono_header_size", return_value=0),
            patch.object(
                extract,
                "parse_i2_language_table",
                return_value=extract.ParsedTable((), (), 0, 0, 0),
            ),
            patch.dict(sys.modules, {"UnityPy": unitypy}),
        ):
            with self.assertRaisesRegex(extract.ExtractionError, "changed during extraction"):
                extract.load_installation(self.asset_path.parent.parent)


if __name__ == "__main__":
    unittest.main()
