# 페글린 한국어 번역 개선 프로젝트

이 프로젝트는 Peglin의 한국어 번역을 검토하고 더 정확하고 이해하기 쉬운
표현으로 개선합니다. 설치된 게임에서 영어 원문, 기존 한국어, 개발자 메모와
I2 Localization 정보를 추출해 대조하고, 선택한 번역을 JSON 오버레이와
BepInEx 플러그인 후보로 만듭니다.

번역 오버레이를 빌드해도 게임 원본 파일은 수정하지 않습니다. 게임에 적용하려면
BepInEx를 설치하고 별도로 생성한 후보 ZIP을 추가해야 합니다.

## 플레이어용: 번역 후보 설치

이 절은 이미 만들어진 후보 ZIP을 받은 경우를 위한 안내입니다. ZIP은
`patches/candidates/`에서 만들거나 GitHub Actions에서
`Build Peglin Korean client candidate` 작업을 `master` 브랜치로 수동 실행해
받을 수 있습니다. 작업이 끝나면 해당 실행에서 ZIP 아티팩트를 다운로드하세요.

1. [Peglin용 BepInEx 팩](https://thunderstore.io/c/peglin/p/BepInEx/BepInExPack_Peglin/)
   안내에 따라 BepInEx Mono를 설치합니다.
2. Peglin을 종료합니다. `BepInEx/config/BepInEx.cfg`가 없다면 게임을 한 번
   실행해 설정 파일을 만든 뒤 종료합니다.
3. `BepInEx.cfg`의 `[Preloader.Entrypoint]`에서 `Type = MonoBehaviour`로
   설정합니다. `Assembly = UnityEngine.CoreModule.dll`과 `Method = .cctor`는
   그대로 두고 설정 파일 전체를 교체하지 마세요.
4. 후보 ZIP을 Peglin 설치 폴더, 즉 `Peglin.exe`가 있는 폴더에 풉니다.
5. 게임을 실행하고 설정에서 한국어를 선택합니다.
6. BepInEx 로그에서 원본 파일 해시 검증 완료와 한국어 용어 로드 건수를
   확인합니다.

게임 파일이 후보를 만들 때 사용한 버전과 다르면 플러그인은 번역을 적용하지
않습니다. 게임을 업데이트한 뒤에는 현재 설치본으로 후보를 다시 빌드해야 합니다.

번역이 아직 검수 중이면 로그에 초안 경고가 표시됩니다. 이 경고는 번역이
승인되지 않았다는 뜻입니다. 후보 ZIP을 만들었다고 해서 번역 승인이나 게임 화면
검수가 완료되는 것은 아닙니다.

후보를 제거하려면 게임을 종료한 다음
`BepInEx/plugins/PeglinKoreanRevised` 폴더를 삭제합니다. BepInEx 자체는
별도로 관리됩니다.

## 번역 및 패치 작업

### 준비

이 프로젝트의 기본 게임 경로는 WSL에서 접근 가능한 다음 Steam 설치 경로입니다.

```text
/mnt/c/Program Files (x86)/Steam/steamapps/common/Peglin
```

다른 위치에 설치했다면 명령에 `--game-root`를 지정하거나 `PEGLIN_GAME_ROOT`
환경 변수를 설정하세요. Python 3.11 이상과 `uv`가 필요합니다. BepInEx 후보를
빌드하려면 .NET SDK도 필요합니다.

저장소 루트에서 잠금 파일에 고정된 Python 도구를 설치합니다.

```bash
uv sync --locked
```

### 게임 번역 자료 추출

```bash
uv run peglin-l10n extract \
  --game-root "/mnt/c/Program Files (x86)/Steam/steamapps/common/Peglin"
```

추출 결과는 `extracted/BUILD_ID/`에 CSV와 `source.json`으로 저장됩니다. CSV 열은
`Term`, `Category`, `English`, `DevNotes`, `I2Description`, `OfficialKorean`,
`RevisedKorean`, `Status`, `Comment`입니다. 추출기는 게임 설치 파일을 읽기만
합니다. 기존 추출 결과를 덮어쓰지 않으므로 해당 빌드 폴더가 이미 있다면 다른
`--output-dir`을 지정하세요.

게임에서 추출한 자료는 Git에 포함하지 않으며 `extracted/`에서 관리합니다. 게임이
업데이트되면 새 자료를 추출해 현재 번역과 비교하세요.

### 번역 검증과 빌드 비교

특정 게임 빌드의 용어와 번역을 검증합니다.

```bash
uv run peglin-l10n validate \
  --terms extracted/BUILD_ID/terms.csv
```

`BUILD_ID`를 추출 명령이 출력한 폴더 이름으로 바꾸세요. `validate`는 중복 키,
보호 토큰과 마크업, 원문 지문, 용어집 일치를 검사합니다. 승인된 번역에는
검토한 게임 빌드 ID도 필요합니다.

게임 설치 자료 없이 번역 파일의 기본 구조와 상태를 확인할 때는 다음 명령을
사용합니다.

```bash
uv run peglin-l10n lint-overrides
```

두 게임 빌드 사이에서 바뀐 문구와 재검토가 필요한 번역을 비교하려면 다음처럼 실행합니다.

```bash
uv run peglin-l10n diff \
  --old extracted/OLD_BUILD_ID/terms.csv \
  --new extracted/NEW_BUILD_ID/terms.csv \
  --output reports/generated/build-diff.json
```

`OLD_BUILD_ID`와 `NEW_BUILD_ID`를 각각 이전 빌드와 새 빌드의 폴더 이름으로
바꾸세요.

특정 번역 키의 원문 지문을 확인하려면 다음 명령을 사용합니다.

```bash
uv run peglin-l10n fingerprint \
  --terms extracted/BUILD_ID/terms.csv \
  --term 'TERM_KEY'
```

`BUILD_ID`는 추출된 빌드 폴더 이름으로, `TERM_KEY`는 확인할 번역 키로
바꾸세요.

### JSON 오버레이와 BepInEx 후보 만들기

현재 게임 설치본의 자료를 추출하고 검증한 뒤 JSON 오버레이를 만듭니다.

```bash
uv run peglin-l10n build-patch
```

오버레이는 `patches/generated/`에 생성됩니다. 영어 원문 지문, 게임 빌드와
리소스 해시, 검수 상태가 함께 기록됩니다. 초안 번역이 있으면 오버레이도 초안
상태로 표시됩니다. 이 명령은 Steam 설치 파일이나 `resources.assets`를 변경하지
않습니다.

플레이어가 설치할 BepInEx ZIP 후보는 다음 명령으로 만듭니다.

```bash
uv run peglin-l10n build-candidate
```

후보는 `patches/candidates/`에 생성됩니다. 이 명령은 JSON 오버레이를 만들고,
현재 Peglin의 .NET 관리 어셈블리를 참조해 플러그인을 빌드한 뒤 ZIP으로 묶습니다.
.NET SDK가 필요합니다. 플러그인은 실행 시 manifest에 기록된 플러그인과
오버레이의 해시, 그리고 `resources.assets`와 `Assembly-CSharp.dll`의 해시를
확인한 뒤 한국어 번역을 메모리에서 갱신합니다. 빌드와 패키징은 게임 설치 폴더
밖에 결과물을 기록하며 게임 원본 파일을 수정하지 않습니다.

## 번역 파일

- `translation/overrides.json`: 개선하거나 새로 작성한 한국어 번역입니다. 각
  항목은 `draft` 또는 `approved` 상태를 가집니다. 문구, 보호 토큰과 게임 내
  문맥을 검토하기 전까지 초안 상태를 유지하세요. 승인 항목에는 검토한 게임
  빌드 ID도 연결해야 합니다.
- `translation/glossary.csv`: 게임 용어의 번역 기준입니다. `established`는 기존
  공식 한국어 사용례를 따르는 용어이고 `draft`는 추가 검토가 필요한 제안입니다.

번역을 검토할 때는 영어 원문과 기존 한국어뿐 아니라 `DevNotes`와 I2 설명도
함께 확인하세요. 기존 번역이 부정확하거나 불명확하거나 어색하면 그대로 유지하지
말고 다시 번역합니다. 용어와 보호 토큰을 확인한 뒤 검증 명령을 실행하세요.

## GitHub 자동화

`Validate translations` 작업은 `master` 브랜치로 향하는 Pull Request와 `master`
푸시에서 실행됩니다. Python 패키지를 컴파일하고 번역 파일의 메타데이터를
검사합니다. 이 GitHub 호스팅 작업에는 로컬 게임 설치본과 추출 자료가 없으므로
원문 지문이나 게임 텍스트 토큰까지 검사하지는 않습니다. 전체 검증은 로컬에서
`validate` 또는 `build-candidate`를 실행해 확인하세요.

`Build Peglin Korean client candidate` 작업은 `master`에서 수동으로 시작할 때만
실행됩니다. 이 작업은 Steam 설치본에 접근할 수 있는 비공개 WSL self-hosted
runner에서 오버레이와 ZIP을 만들고 Actions 아티팩트로 업로드합니다. 아티팩트는
14일간 보관됩니다. runner가 이 컴퓨터의 게임 파일에 접근하므로 저장소를
비공개로 유지하고, 신뢰할 수 없는 코드가 이 runner에서 실행되도록 작업 조건을
추가하지 마세요.

패치 방식과 플러그인 동작의 자세한 기술 검토는
[클라이언트 패치 방식 문서(영문)](docs/client-patch-strategy.md)에 있습니다.
