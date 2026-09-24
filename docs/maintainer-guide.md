# 관리자 안내

이 문서는 번역 자료를 갱신하고 패치 후보를 검토하는 관리자를 위한 안내입니다.
일반 설치 방법은 [README](../README.md), 외부 번역 기여 절차는
[기여 안내](../CONTRIBUTING.ko.md)를 참고하세요.

## 로컬 환경

로컬 도구에는 Python 3.11 이상과 `uv`가 필요합니다. BepInEx 플러그인 후보를
컴파일하려면 .NET SDK와 합법적으로 설치된 Peglin이 필요합니다.

```bash
uv sync --locked
```

게임 설치 경로는 각 명령의 `--game-root` 옵션이나 `PEGLIN_GAME_ROOT` 환경
변수로 지정합니다. 사용 가능한 옵션은 저장소의 현재 명령 도움말을 기준으로
확인하세요.

```bash
uv run peglin-l10n --help
uv run peglin-l10n COMMAND --help
```

현재 도구는 다음 작업을 제공합니다.

| 명령 | 용도 |
| --- | --- |
| `extract` | 설치된 게임에서 검토용 번역 스냅샷을 추출합니다. |
| `validate` | 스냅샷과 번역 자료의 키, 토큰, 마크업과 원문 연결을 검사합니다. |
| `diff` | 두 게임 빌드의 스냅샷 차이를 비교합니다. |
| `fingerprint` | 한 용어 키의 원문 지문을 확인합니다. |
| `lint-overrides` | 저장소에 공개된 번역 파일과 잠금 메타데이터를 검사합니다. |
| `build-patch` | 로컬 게임 설치본에 결합된 JSON 오버레이를 만듭니다. |
| `build-candidate` | 로컬 게임 설치본에 결합된 BepInEx 설치 후보를 만듭니다. |

게임에서 추출한 스냅샷과 원문 표, 생성한 오버레이 및 후보 ZIP은 Git에
추가하지 않습니다. 공개 저장소에는 범주별 번역 CSV와 원문 전체를 포함하지 않는
`translation/source-lock.json`만 유지합니다.

## 번역 기여 검토

1. PR이 번역 CSV의 필요한 행만 수정했는지 확인합니다.
2. `Term`이 그대로이고 `Status`가 `draft`인지 확인합니다.
3. 자리표시자와 마크업이 원문 잠금 정보와 일치하는지 확인합니다.
4. 제안 문구를 게임 화면에서 확인하고, 확인한 빌드 ID와 검토 상태는 관리자가
   기록합니다.
5. 필수 자동 검사가 성공했는지 확인합니다.

`master` 보호 규칙에는 코드 소유자 검토와 관리자 승인을 필수로 설정해야 합니다.
자동 병합은 사용하지 않으며, 관리자가 PR을 승인한 뒤 GitHub에서 직접
병합합니다.

## 병합 후 릴리스

`.github/workflows/release-translation.yml`은 `master`에 병합된 PR인지 확인한
뒤 GitHub 제공 runner에서 번역 자료를 검증하고 설치용 패치를 빌드합니다. 릴리스
후보를 로컬에서 재현할 때는 잠금 파일의 소스 리비전을 명시합니다.

```bash
uv run peglin-l10n lint-overrides
uv run peglin-l10n build-release-candidate \
  --source-revision REV \
  --output-dir OUTPUT_DIR
```

workflow는 검증과 빌드에 성공한 병합 결과로 GitHub Release를 생성합니다. 생성된
오버레이 상태가 `draft`이면 prerelease로, `approved`이면 일반 Release로
게시됩니다. 릴리스 자동화는 관리자 승인과 수동 PR 병합을 대체하지 않습니다.
