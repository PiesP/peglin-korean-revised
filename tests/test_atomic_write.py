from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from peglin_l10n import atomic_write


class AtomicWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "nested" / "output.bin"

    def assert_no_temporary_files(self) -> None:
        self.assertEqual([], list(self.path.parent.glob(f".{self.path.name}.*.tmp")))

    def test_writes_bytes_with_fixed_permissions_and_creates_parent(self) -> None:
        atomic_write.write_bytes_atomically(self.path, b"new\r\nbytes")
        self.assertEqual(b"new\r\nbytes", self.path.read_bytes())
        self.assertEqual(0o644, self.path.stat().st_mode & 0o777)
        self.assert_no_temporary_files()

    def test_partial_write_or_flush_failure_preserves_destination(self) -> None:
        self.path.parent.mkdir()
        self.path.write_bytes(b"previous")
        original_fdopen = os.fdopen

        for failure_at in ("write", "flush"):
            with self.subTest(failure_at=failure_at):

                class FailingStream:
                    def __init__(self, descriptor: int, mode: str) -> None:
                        self.stream = original_fdopen(descriptor, mode)

                    def __enter__(self) -> FailingStream:
                        return self

                    def __exit__(self, *args: object) -> None:
                        self.stream.close()

                    def write(self, contents: bytes) -> None:
                        self.stream.write(contents[:1])
                        if failure_at == "write":
                            raise OSError("injected write failure")

                    def flush(self) -> None:
                        if failure_at == "flush":
                            raise OSError("injected flush failure")
                        self.stream.flush()

                    def fileno(self) -> int:
                        return self.stream.fileno()

                with patch.object(atomic_write.os, "fdopen", side_effect=FailingStream):
                    with self.assertRaisesRegex(OSError, f"injected {failure_at} failure"):
                        atomic_write.write_bytes_atomically(self.path, b"replacement")
                self.assertEqual(b"previous", self.path.read_bytes())
                self.assert_no_temporary_files()

    def test_fsync_or_replace_failure_preserves_destination(self) -> None:
        self.path.parent.mkdir()
        self.path.write_bytes(b"previous")
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation):
                with patch.object(
                    atomic_write.os, operation, side_effect=OSError(f"injected {operation} failure")
                ):
                    with self.assertRaisesRegex(OSError, f"injected {operation} failure"):
                        atomic_write.write_bytes_atomically(self.path, b"replacement")
                self.assertEqual(b"previous", self.path.read_bytes())
                self.assert_no_temporary_files()
