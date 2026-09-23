# Peglin Korean Revised

Local tools and source snapshots for reviewing Peglin's Korean localization.
The project reads the installed game files and writes extracted data under this
directory. It does not modify or launch the game.

## Current source

The accessible Steam installation is:

```text
/mnt/c/Program Files (x86)/Steam/steamapps/common/Peglin
```

The initial local snapshot records Steam app `1296610`, build `22988052`, and
I2 Localization data from `Peglin_Data/resources.assets`. The source table
contains the official Korean column and translator notes. Extracted rows are
game-derived data, so `/extracted/` is ignored by Git.

The first extraction, made on 2026-09-23, found 1,912 unique terms across 18
language slots. English text exists without official Korean for 13 terms. The
Dev Notes slot has 101 nonempty values, of which 100 contain non-whitespace
text. These counts come from this installation snapshot, not the older
shared-chat snapshot.

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
changes, stale source fingerprints, approved-translation build provenance, and
glossary mismatches. `source.json` is read from the same directory as the CSV;
use `--source-manifest` when the manifest is elsewhere:

```bash
uv run peglin-l10n validate \
  --terms extracted/build-22988052/terms.csv
```

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
  --terms extracted/build-22988052/terms.csv \
  --term 'Relics/damage_creates_lightning_name'
```

## Review workflow

1. Keep one extracted source snapshot per Steam build.
2. Review missing Korean, changed source text, and existing Korean in context
   with the English and DevNotes columns.
3. Put accepted Korean changes in `translation/overrides.json`, recording the
   term's `sourceFingerprint`, `reviewedBuildId`, status, and review comment. Do
   not copy the full official table into an override file.
4. Run the validator and compare consecutive source snapshots before deciding
   which overrides need another review.

An override entry has this shape:

```json
{
  "translation": "reviewed Korean text",
  "status": "approved",
  "sourceFingerprint": "value from the fingerprint or diff command",
  "reviewedBuildId": "22988052",
  "comment": "translation rationale or context"
}
```

Runtime injection is a later phase. The installed game currently has no
BepInEx or other mod loader, and this project does not patch `resources.assets`.
