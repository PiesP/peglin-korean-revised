from __future__ import annotations

import unittest

from peglin_l10n.release_tag import (
    is_prerelease_tag,
    is_release_tag,
    validate_release_tag_status,
)


class ReleaseTagTests(unittest.TestCase):
    def test_accepts_semver_stable_and_release_candidate_tags(self) -> None:
        for tag in (
            "peglin-ko-v0.1.0",
            "peglin-ko-v1.20.300",
            "peglin-ko-v1.0.0-rc.1",
            "peglin-ko-v1.0.0-rc.12",
        ):
            with self.subTest(tag=tag):
                self.assertTrue(is_release_tag(tag))

    def test_rejects_malformed_or_ambiguous_tags(self) -> None:
        for tag in (
            "peglin-ko-v01.0.0",
            "peglin-ko-v1.00.0",
            "peglin-ko-v1.0.0-rc.0",
            "peglin-ko-v1.0.0-rc.01",
            "peglin-ko-v1.0.0-beta.1",
            "peglin-ko-v1.0.0+build.1",
            "peglin-ko-v1.0.0/other",
        ):
            with self.subTest(tag=tag):
                self.assertFalse(is_release_tag(tag))

    def test_requires_rc_tags_for_draft_and_stable_tags_for_approved(self) -> None:
        self.assertTrue(validate_release_tag_status("peglin-ko-v1.0.0-rc.1", "draft"))
        self.assertFalse(validate_release_tag_status("peglin-ko-v1.0.0", "approved"))
        self.assertTrue(is_prerelease_tag("peglin-ko-v1.0.0-rc.1"))

    def test_rejects_tag_and_translation_status_mismatch(self) -> None:
        for tag, status in (
            ("peglin-ko-v1.0.0", "draft"),
            ("peglin-ko-v1.0.0-rc.1", "approved"),
        ):
            with self.subTest(tag=tag, status=status):
                with self.assertRaises(ValueError):
                    validate_release_tag_status(tag, status)


if __name__ == "__main__":
    unittest.main()
