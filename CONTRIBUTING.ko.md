# 번역 기여 안내

Peglin을 플레이하면서 발견한 번역 문제는 이슈나 Pull Request로 제안할 수
있습니다. 현재 번역 개선은 실제 플레이에서 확인한 사용자 제보를 바탕으로 진행합니다.
코드나 개발 도구를 몰라도 이슈로 편하게 알려 주세요. 번역 수정안을 몰라도 문제를
제보할 수 있습니다.

## 이슈로 제안하기

[번역 수정 제안 양식](https://github.com/PiesP/peglin-korean-revised/issues/new?template=translation-suggestion.yml)에
확인할 수 있는 정보를 적어 주세요. 모르는 버전은 `모름`이라고 적어도 됩니다.

- 설치한 패치 버전이나 릴리스 태그
- 게임 버전이나 Steam Build ID
- 게임에 표시된 문구
- 문구가 나온 화면이나 상황, 실제로 겪었거나 오해한 내용
- 해당 문구의 용어 키를 알고 있다면 정확한 키
- 더 나은 번역을 제안하고 싶을 때 제안 문구

수정안을 제안하지 않아도 이슈를 제출할 수 있습니다. 직접 작성한 번역 문구를
제안한다면 이슈 양식의 번역 문구 사용 허락 항목에 동의해 주세요. 권한 확인이 없는
제안 문구는 번역에 반영하지 않습니다. 관리자가 제보와 문맥을 검토하며, 이슈 내용이
자동으로 번역 파일에 복사되지는 않습니다.

스크린샷을 첨부하면 제보 내용을 더 쉽게 확인할 수 있습니다. 계정 이름, 개인 정보,
세이브 정보가 보이면 가린 뒤 올려 주세요.

## Pull Request로 수정하기

번역은 범주별 `translation/terms/<slug>.csv` 파일에서 관리합니다. 수정할 문구가
들어 있는 CSV를 찾아 필요한 행만 바꿔 주세요. 일반적인 번역 PR에서는 이 CSV
파일 외의 소스 잠금 파일, 용어집, 프로그램 코드와 GitHub Actions workflow를
수정하지 않습니다.

CSV는 UTF-8이며 열 순서와 이름을 그대로 유지합니다.

```csv
Term,Translation,Status,ReviewedBuildId,Comment
```

1. `Term` 값은 문구를 식별하는 키이므로 바꾸지 않습니다.
2. `Translation`에 제안하는 한국어 번역을 적습니다.
3. `Status`는 `draft`로 유지합니다. 관리자가 게임 화면과 빌드를 확인한 뒤 승인
   상태를 결정합니다.
4. `{0}`, `%s`, `<color>`, `[tag]`처럼 원문에 포함된 자리표시자와 마크업은
   삭제하거나 고치지 않습니다.
5. `ReviewedBuildId`는 비워 둡니다. 이 값은 관리자가 실제 게임 빌드를 검토한 뒤
   기록합니다.
6. `Comment`에는 문맥, 번역 의도나 확인이 필요한 내용을 간단히 적습니다.

값에 쉼표, 큰따옴표 또는 줄바꿈이 포함되면 표준 CSV 규칙에 따라 셀을
큰따옴표로 감싸고, 셀 안의 큰따옴표는 두 번 씁니다. `{0}`, `%s`, 태그와 기존
줄바꿈은 지우거나 바꾸지 않습니다.

PR 설명에는 수정한 `Term`과 파일 경로, 변경 전후 문구, 게임에서 확인한 위치를
적어 주세요. 여러 문구를 한 번에 수정할 때도 서로 관련된 변경만 한 PR에
포함하면 검토하기 쉽습니다.

## 저장소에 포함하면 안 되는 자료

Peglin에서 추출한 영어 원문 표, 개발자 메모, 게임 파일이나 그 밖의 비공개 원본
자료를 이슈나 PR에 올리지 마세요. 번역 제안에 필요한 짧은 문맥만 직접 설명하고,
전체 원문 데이터 대신 용어 키를 사용해 주세요.

저장소의 MIT 라이선스는 직접 작성한 코드, 도구와 안내 문서에 적용되며
`translation/`의 게임 관련 번역 자료에는 적용되지 않습니다. 기여할 문구를
공개하고 이 패치에서 사용할 권한이 있는지 확인한 뒤 이슈나 PR을 제출해 주세요.
번역 문구를 제안하는 이슈나 번역 문구를 포함한 PR을 제출하면, 제출자는 자신이
보유하거나 허락받은 권한 범위에서
프로젝트가 해당 문구를 저장소와 패치에 복제·수정·배포하고, 패치 사용자가 패치의
일부로 해당 문구를 사용할 수 있도록 비독점적이고 전 세계에서 유효한 무상 이용
허락을 부여합니다. 이 허락은 Peglin 또는 게임 내 콘텐츠의 권리까지
포함하지 않으며, 게임 권리자의 허락을 대신하지 않습니다. 필요한 권한을 보유하지
않았거나 확인할 수 없다면 해당 번역 문구를 제출하지 마세요. 이슈나 PR 양식의
권한 확인 항목에 동의해 주세요. 확인 항목이 없는 이슈나 PR은 번역 패치 릴리스
대상이 되지 않습니다.

MIT 라이선스는 Peglin이나 게임 내 콘텐츠에 대한 권리를 부여하지 않습니다.
자세한 내용은 저장소의 [번역 자료 고지](TRANSLATION-NOTICE.txt)를 참고하세요.

## 검토와 병합

모든 PR은 권한 확인 항목과 필수 `validate` 검사를 통과해야 합니다. 다른 기여자가
작성한 PR은 저장소 관리자가 최신 PR 헤드를 승인한 뒤 직접 병합합니다. 관리자가
작성한 PR은 자체 승인할 수 없으므로, 필수 `validate` 검사가 성공한 것을 확인한 뒤
관리자 권한으로 승인 요구를 우회해 수동 병합합니다. 자동 병합은 사용하지 않습니다.
수정 요청이 남으면 해당 PR에서 내용을 보완해 주세요.

관리자가 이슈 제안을 직접 반영할 때는 해당 이슈의 권한 확인과 번역 CSV 변경을
확인한 뒤 번역 CSV만 포함한 단일 커밋으로 기본 브랜치에 반영합니다. 커밋은 단일
부모를 가져야 하고, 메시지 마지막 줄에 `Issue: #번호`를 적어야 합니다. 이 커밋에도
필수 `validate` 검사가 성공해야 합니다.

병합이나 이슈 반영만으로 릴리스가 생성되지는 않습니다. 관리자가 공개를 결정하면
`master`의 최신 커밋에 새 주석 태그(annotated tag)를 만들고 푸시합니다. 태그 대상이
현재 `master` 최신 커밋이 아니거나 출처 검증을 통과하지 못하면 릴리스가 거부됩니다.
태그는 덮어쓰거나 삭제하지 마세요.

| 번역 상태 | 버전 태그 예시 | GitHub Release |
| --- | --- | --- |
| `draft` | `peglin-ko-v1.0.0-rc.1` | 시험판(prerelease) |
| `approved` | `peglin-ko-v1.0.0` | 정식 릴리스 |

`pyproject.toml`의 도구 버전이나 플러그인 버전과 별도로 번역 패치 버전을 정합니다.
`draft` 번역은 `-rc.N` 태그만, `approved` 번역은 안정 버전 태그만 사용할 수 있습니다.
태그를 푸시하기 전에 대상 커밋의 `validate` 검사가 성공했는지 확인하세요.

```sh
git fetch origin master
git tag -a peglin-ko-v1.0.0-rc.1 origin/master -m "Peglin Korean Revised v1.0.0-rc.1"
git push origin peglin-ko-v1.0.0-rc.1
```

태그 생성 규칙은 현재 관리자 계정 `PiesP`만 허용하고, 생성한 태그는 수정·삭제할 수
없게 설정되어 있습니다. 인증된 관리자 Git 계정으로 태그를 푸시해야 합니다. Actions의
`GITHUB_TOKEN`으로 태그를 만들면 태그 푸시 워크플로가 시작되지 않습니다. 릴리스
워크플로가 실패하면 Actions에서 실패한 실행을 다시 실행하세요.

## Automation command catalog

Python is the primary language for handwritten repository automation. The
`peglin-l10n` entry point is declared in `pyproject.toml`; `uv.lock` and
`[tool.maintenance]` select dependencies and runtimes. Use the locked Python
3.11 environment for local package commands. C# under `plugin/` is product
code; workflow YAML, lockfiles, and generated release files are not scripts.

| Public command | Purpose and implementation | Runtime and prerequisites | Inputs, outputs, side effects, tests |
| --- | --- | --- | --- |
| `peglin-l10n extract` | Read the installed I2 table; `cli.py`, `extract.py` | Python 3.11, locked UnityPy, supported local Peglin installation | `--game-root`, optional `--output-dir`; writes an immutable `terms.csv`/`source.json` snapshot; package tests |
| `peglin-l10n build-patch` | Validate translations against a local game snapshot; `cli.py`, `patching.py`, `validation.py` | Same local game and locked environment | Game, translations, glossary, snapshot/output paths; writes snapshot and overlay JSON; package tests |
| `peglin-l10n build-candidate` | Build the plugin and install ZIP from a local game; `cli.py`, `candidate.py` | Same local game, .NET SDK, locked NuGet inputs | Game, plugin, source and output paths; invokes `dotnet`, writes snapshot, overlay and ZIP; package tests |
| `peglin-l10n build-release-candidate` | Build source-locked public files without a local game; `cli.py`, `release.py`, `candidate.py` | Python 3.11, locked package environment on Linux, tracked plugin DLL and source lock | Full source revision, reserved tag, translations, lock and output directory; writes overlay, ZIP, notices, manifest, notes and checksums; `test_public_release.py` |
| `peglin-l10n lint-overrides` | Lint public translation CSVs; `cli.py`, `validation.py` | Locked package environment | Translation directory; JSON summary and diagnostics on stdout, no writes; package tests and `validate.yml` |
| `peglin-l10n validate` | Compare source snapshot and translations; `cli.py`, `validation.py` | Locked package environment and local snapshot | `--terms`, translations, glossary, optional source manifest; JSON summary and diagnostics, no writes; package tests |
| `peglin-l10n diff` | Compare two snapshots; `cli.py`, `diffing.py` | Locked package environment and two local snapshots | `--old`, `--new`, optional `--output`; JSON stdout or report file; package tests |
| `peglin-l10n fingerprint` | Compute one source row fingerprint; `cli.py`, `fingerprints.py` | Locked package environment and local `terms.csv` | `--terms`, `--term`; JSON stdout, no writes; package tests |

| Workflow helper | Runtime, inputs and effects | Tests |
| --- | --- | --- |
| `python3 .github/scripts/resolve_toolchains.py` | Bootstrap Python on Ubuntu before setup-python or `uv`; reads only `pyproject.toml` with standard-library `tomllib`, appends validated Python/uv versions to `GITHUB_OUTPUT`. It cannot import installed project dependencies or assume a newer bootstrap Python. | `test_toolchain_selection.py` |
| `python3 .github/scripts/verify_release_source.py` | Source-eligibility job after read-only checkout and Python setup; reads tag, actor, source and repository environment, invokes `gh api` with inherited `GH_TOKEN`, and writes eligibility/source/tag/tag-object outputs. It never publishes. | `test_release_source_policy.py` |
| `python3 .github/scripts/verify_release_artifacts.py` | Publication job, standard library only, from a reviewed immutable trusted checkout; reads downloaded current-run files and verified source/tag environment; appends release outputs only after every check passes. No candidate import/install or network call. | `test_release_artifact_verifier.py` |
| `python3 .github/scripts/publish_release.py` | Publication job after successful artifact verification; uses inherited `GH_TOKEN`, rechecks the annotated tag object through `gh api`, then passes the verified seven assets to `gh release create` as an argument vector. | `test_release_publisher.py` |

`validate.yml` and the build job in `release-translation.yml` use locked `uv`
for installation, compilation, test discovery and lint. The build job alone
runs `build-release-candidate`; `upload-artifact` stores its outputs for the same
workflow run. The eligibility job verifies the tag, latest `master` source,
permission-confirmed contribution and exact required check. The publication
job has `contents: write`; its downloaded candidate files are data, while the
verifier must come from a separately reviewed immutable full commit SHA with
`persist-credentials: false` and no candidate dependency install. Only then
may verifier outputs reach the tag-object recheck and release creation. During
the two-stage migration, the existing workflow-bound inline validator and
shell publication step remain active until that trusted SHA is landed and
pinned. `test_release_artifact_verifier.py` exercises the existing validator
as a baseline until the workflow switches to the extracted helper.

Remaining workflow `run:` blocks are bounded adapters: checkout/setup action
inputs are YAML; `python3` and `uv` commands start the named helpers or package
checks; the shell `set -euo pipefail` blocks guard step failure. The security
workflow retains Bash for pinned Docker OSV scanning, SARIF handling and
locked `dotnet` CodeQL reference-stub builds; changing those tool boundaries
or their failure handling calls for a separate security review. The release
workflow's inline validator and `gh` Bash block require removal when the
trusted verifier commit is pinned. Review the bootstrap constraint whenever
the runner Python, manifest parser or dependency order changes; review every
remaining inline block when its policy, permissions, source, outputs or
external command changes. `candidate.py` invokes `dotnet` through an argument
list; `verify_release_source.py` and the publisher likewise invoke `gh` without
shell interpolation. The contributor's manual `git fetch/tag/push` example
above is a human release action, not a CI script.
