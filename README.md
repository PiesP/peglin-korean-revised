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
uv sync --locked
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

## Build the Korean overlay

Run the end-to-end local pipeline from the installed game through a deterministic
JSON overlay:

```bash
uv run peglin-l10n build-patch
```

The command reads the installation path above (or `PEGLIN_GAME_ROOT`), extracts
the current source table, reuses a snapshot only when it exactly matches the
installed data, validates the translations and source fingerprints, then writes
`patches/generated/peglin-ko-<build-id>-<asset-hash-prefix>.json`. Set
`--game-root`, `--extracted-dir`, `--output-dir`, `--glossary`, or `--overrides`
to select different paths. A patch contains the term keys, Korean text, review
status, source fingerprints, and source build/hash metadata. Draft entries keep
the overall artifact marked `draft`. The command never writes to the Steam
installation or changes `resources.assets`.

## Build a client candidate

Create an installable BepInEx ZIP for the currently installed game:

```bash
uv run peglin-l10n build-candidate
```

This command builds the JSON overlay, compiles the BepInEx Mono plugin against
the installed game's managed assemblies, and writes a versioned ZIP under
`patches/candidates/`. The .NET SDK is required. The ZIP contains the plugin,
the JSON overlay, an integrity manifest, and install instructions. The plugin
checks the packaged plugin and overlay hashes, then verifies both the installed
`resources.assets` and `Assembly-CSharp.dll` SHA-256 values before applying any
changes. It updates the I2 Korean table in memory; it does not install BepInEx
or modify game files.

See [Client patch strategy](docs/client-patch-strategy.md) for the method
evaluation, requirements, and installation instructions.

Run the installation-independent override structure check with:

```bash
uv run peglin-l10n lint-overrides
```

## GitHub automation

The `Validate translations` workflow runs on pull requests and pushes to
`master` using a GitHub-hosted runner. It compiles the Python package and checks
override metadata. It cannot verify source fingerprints or protected text
tokens without the local game snapshot; `build-patch` and `build-candidate`
perform those checks locally. The manual candidate workflow runs the latter.

The `Build Peglin Korean client candidate` workflow runs only when manually
dispatched from `master`, on a repository-scoped WSL self-hosted runner labeled
`peglin-game`. It builds the ignored JSON overlay and installable ZIP, then
uploads both as a 14-day Actions artifact. The runner can access this machine's
Steam install, so keep the repository private and do not add pull request or
other untrusted-code triggers to that runner workflow.

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

The project does not install a mod loader or patch `resources.assets`. Client
integration is packaged as an optional BepInEx candidate for manual review.
