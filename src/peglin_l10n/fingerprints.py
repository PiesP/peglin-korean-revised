"""Stable source fingerprints used to bind overrides to reviewed context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


SOURCE_FIELDS = ("Term", "English", "DevNotes", "I2Description")


def source_fingerprint(row: Mapping[str, str]) -> str:
    payload = {field: row.get(field, "") for field in SOURCE_FIELDS}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
