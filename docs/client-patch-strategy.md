# Peglin client patch strategy

This document records the patch method selected for the Korean translation
candidate and how to install or remove that candidate.

## Evaluation

Peglin does not expose a documented official localization mod API in the
sources reviewed for this project. The developer described native mod support
as a future goal while noting that the community had already modded the game.
The currently listed Peglin community loader is BepInExPack_Peglin, and its
instructions place plugins under BepInEx/plugins. BepInEx documents support
for Unity Mono plugins and runtime code loading.

The available choices are:

| Method | Benefits | Costs and risks | Result |
| --- | --- | --- | --- |
| Replace values in resources.assets | Uses the game's existing localization table without a plugin loader. | Rewrites a large serialized game asset, can be overwritten by game repair or update, and requires restoring the original file to uninstall. | Not selected. |
| BepInEx plugin that updates I2 data in memory | Keeps the installed game files unchanged, uses the established Peglin mod loader, and can be removed as one plugin directory. | Requires BepInEx and may need an update when Peglin changes its runtime or I2 table. | Selected. |
| Official or user-provided translation API | Could avoid runtime patching if the game exposes an appropriate supported interface. | No applicable official or user-data API was found in the sources reviewed. | Not available for this candidate. |

The installed copy inspected during implementation is a Unity Mono game and
contains I2 Localization. Its global source is registered as I2Languages and
includes Korean with language code ko. These facts make direct I2 table updates
possible without intercepting every text lookup. The current source manifest
and its asset hash are generated from the installed game; see the
build-candidate command for the current values.

The inspected Peglin BepInEx configuration uses `Application`'s static
initializer as its preloader entrypoint. This can load a plugin and run its
`Awake` method before Unity starts ticking `MonoBehaviour` components, leaving
`Start` and coroutines inactive. Set `Type = MonoBehaviour` under
`[Preloader.Entrypoint]` in `BepInEx/config/BepInEx.cfg`, while preserving its
`Assembly = UnityEngine.CoreModule.dll`, `Method = .cctor`, and other settings.
This lets Unity's lifecycle callbacks and the translation coroutine run.

## Candidate behavior

The plugin in plugin/Plugin.cs performs these steps:

1. Reads the adjacent overlay.json and manifest.json, checks their metadata,
   and verifies the plugin and overlay hashes recorded in the manifest.
2. In Unity's Start lifecycle method, hashes Peglin_Data/resources.assets and
   Peglin_Data/Managed/Assembly-CSharp.dll synchronously before initializing
   localization. It stops without applying translations if either file differs
   from the candidate's recorded hash.
3. Initializes I2 Localization, waits for its sources during startup and after
   scene loads, finds the Korean language slot by code, and updates matching
   terms in memory through TermData.SetTranslation.
4. Calls LocalizationManager.LocalizeAll(true) to refresh visible localized
   text and reapplies translations after an I2 Google source update.

It does not write to resources.assets or copy any loader files. The generated
ZIP contains only the plugin, overlay, package manifest, and README. The
manifest records the game build, resources.assets hash,
Assembly-CSharp.dll hash, plugin hash, overlay hash, and loader requirement. A
game update that changes either source file requires a new candidate; the old
candidate will refuse to apply.

The plugin DLL's ZIP timestamp is derived deterministically from its content;
other entries retain the fixed ZIP timestamp. This keeps identical candidates
reproducible and gives changed plugin binaries content-specific timestamps so
BepInEx can invalidate cached plugin metadata when that timestamp changes.

## Build and release

After an administrator approves and manually merges a contribution PR, the
release workflow verifies the merged commit and builds on GitHub-hosted Linux.
It uses the reviewed translation CSVs, `translation/source-lock.json`, and the
tracked plugin at `runtime/PeglinKoreanRevised.dll`; the hosted runner does not
need a Peglin installation or its game files. The workflow validates the
generated overlay, exact ZIP contents, manifests, and SHA-256 checksums before
creating a GitHub Release. Draft translations are published as prereleases.

To reproduce the hosted package locally:

    uv sync --locked
    uv run peglin-l10n lint-overrides
    uv run peglin-l10n build-release-candidate \
      --source-revision REV \
      --output-dir OUTPUT_DIR

This build validates the tracked plugin DLL against its source inputs and the
source lock. Updating the game build or plugin requires an administrator to
refresh those locked inputs and the runtime DLL using a trusted local game
installation before submitting the change for review. Do not include extracted
game tables or game binaries in the public repository.

## Install and remove

1. Install BepInEx Mono for Peglin. The Peglin community pack page on
   Thunderstore provides mod-manager and manual installation instructions.
2. Close Peglin. If `BepInEx/config/BepInEx.cfg` does not exist yet, run
   Peglin once with BepInEx installed to create it, then close the game.
3. In the config, set `Type = MonoBehaviour` in `[Preloader.Entrypoint]`.
   Keep `Assembly = UnityEngine.CoreModule.dll` and `Method = .cctor`; do not
   replace the complete config file.
4. Extract the candidate ZIP into the game's installation
   directory, the folder containing Peglin.exe.
5. Start Peglin with BepInEx enabled and select Korean in the game settings.
6. Check the BepInEx log for both verified source-file hashes and the number
   of translations applied.

To remove the candidate, close Peglin and delete
BepInEx/plugins/PeglinKoreanRevised. BepInEx itself is managed separately.

The current translation overlay is draft. Packaging it as a runnable candidate
does not mark the translations approved or establish in-game visual acceptance.

## Sources

- [Peglin developer response about mod support](https://itch.io/t/2065629/mod-support)
- [Peglin BepInEx pack and installation instructions](https://thunderstore.io/c/peglin/p/BepInEx/BepInExPack_Peglin/)
- [BepInEx basic plugin guide](https://docs.bepinex.dev/articles/dev_guide/plugin_tutorial/index.html)
- [BepInEx entrypoint troubleshooting for Unity 2017 and newer](https://docs.bepinex.dev/articles/user_guide/troubleshooting.html#unity-2017-and-newer)
- [BepInEx runtime patching guide](https://docs.bepinex.dev/articles/dev_guide/runtime_patching.html)
- [Peglin community modding guide](https://peglin.wiki.gg/wiki/Modding)
- [Related BepInEx Unity Mono report: plugins load from Application's initializer but callbacks and coroutines do not run](https://github.com/BepInEx/BepInEx/issues/1393)
