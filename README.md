# Peglin Korean Revised

Local tools and source snapshots for reviewing Peglin's Korean localization.
The project reads the installed game files and writes extracted data under this
directory. It does not modify or launch the game.

## Game source

The accessible Steam installation is:

```text
/mnt/c/Program Files (x86)/Steam/steamapps/common/Peglin
```

The extractor reads I2 Localization data from
`Peglin_Data/resources.assets`. The source table contains official Korean text
and translator notes. Each generated `source.json` records the Steam build,
Unity version, and asset hash for that snapshot. Extracted rows are game-derived
data, so `/extracted/` is ignored by Git; extract again after cloning or when
the game updates.

## Setup

From this directory, install the pinned extractor dependency into a local
virtual environment:

```bash
uv sync
```

## Extract the current game table

```bash
uv run peglin-l10n extract \
  --game-root "/mnt/c/Program Files (x86)/Steam/steamapps/common/Peglin"
```

The command writes a versioned CSV and JSON source manifest under
`extracted/<steam-build-id>/`. Each CSV row contains:

```text
Term, Category, English, DevNotes, I2Description, OfficialKorean, RevisedKorean, Status, Comment
```

The extractor is read-only with respect to the Steam installation. It will stop
if it cannot identify and parse the I2 language table rather than emit a partial
CSV. If that output directory already exists, choose a new one with
`--output-dir` so prior review data is not overwritten.

## Validate and compare

Check a snapshot and the override file for duplicate terms, protected-token
changes, unbalanced markup, stale source fingerprints, approved-translation
build provenance, and glossary mismatches. `source.json` is read from the same
directory as the CSV; use `--source-manifest` when the manifest is elsewhere:

```bash
uv run peglin-l10n validate \
  --terms extracted/BUILD_ID/terms.csv
```

Replace `BUILD_ID` with the folder printed by `extract`.

Configured glossary and override files must exist. Stale fingerprints on draft
overrides are warnings; stale approved translations fail validation. Approved
entries also need a `reviewedBuildId` matching the snapshot's Steam build ID.

Compare two extracted builds and write changed terms and stale, removed, or
orphaned overrides to a JSON report:

```bash
uv run peglin-l10n diff \
  --old extracted/build-OLD/terms.csv \
  --new extracted/build-NEW/terms.csv \
  --output reports/generated/build-diff.json
```

Get the fingerprint to bind a reviewed override to its English and note context:

```bash
uv run peglin-l10n fingerprint \
  --terms extracted/BUILD_ID/terms.csv \
  --term 'Relics/damage_creates_lightning_name'
```

## Review workflow

1. Keep one extracted source snapshot per Steam build.
2. Review English, existing Korean, DevNotes, and I2 descriptions together.
   Re-translate an existing Korean value when it is inaccurate, unclear, or
   unnatural; do not preserve it solely because it is already present.
3. Store proposed Korean text in `translation/overrides.json`. It can contain
   selected edits or a complete retranslation, but should not mirror the
   official Korean column. Keep entries at status `draft` until wording,
   protected tokens, and in-game context have been reviewed. Approved entries
   also need a matching `reviewedBuildId` from the source manifest.
4. Run the validator and compare consecutive source snapshots before deciding
   which overrides need another review.

Glossary rows marked `established` follow existing official Korean usage; rows
marked `draft` are proposed terms that still need review.

An override entry has this shape:

```json
{
  "translation": "proposed Korean text",
  "status": "draft",
  "sourceFingerprint": "value from the fingerprint or diff command",
  "comment": "translation rationale or context"
}
```

This project does not install a mod loader or patch `resources.assets`; runtime
integration is a separate phase.
