# 페글린 한국어 번역 개선 패치

Peglin의 한국어 문장을 더 자연스럽고 이해하기 쉽게 다듬어 게임에 적용하는
비공식 패치입니다. BepInEx 플러그인으로 작동하며 게임 파일을 직접 바꾸지 않습니다.
이 프로젝트는 개발 과정에서 AI 도구의 도움을 받았습니다.

현재 공개본은 번역 검수 상태가 `draft`인 시험판입니다. 일부 문구와 게임 상황은 실제
플레이로 확인되지 않았을 수 있습니다. 모든 화면의 번역을 검수했다고 주장하지 않으며,
이후 개선은 실제 플레이에서 발견한 사용자 제보를 바탕으로 진행합니다.

## 패치 받기

[릴리스 목록](https://github.com/PiesP/peglin-korean-revised/releases)에서 최신
`PeglinKoreanRevised-`로 시작하고 `.zip`으로 끝나는 설치 파일을 받으세요. JSON 파일은
일반 설치에 필요하지 않습니다. Peglin이 업데이트되면 이전 패치가 작동하지 않을 수
있으니 최신 릴리스를 확인해 주세요.

## 준비

- Windows용 Peglin
- [Peglin용 BepInEx 팩](https://thunderstore.io/c/peglin/p/BepInEx/BepInExPack_Peglin/)

지원 대상은 [`translation/source-lock.json`](translation/source-lock.json)에 기록된
Steam 빌드와 게임 파일 해시가 일치하는 Windows용 Peglin입니다. 플러그인은 대상 파일의
해시가 일치할 때만 번역을 적용합니다. 게임 업데이트 뒤 번역이 적용되지 않으면 새
패치가 나올 때까지 기다려 주세요.

아래 설치 순서는 BepInEx를 게임 폴더에 직접 설치하는 방법입니다. 게임 폴더는
`Peglin.exe`가 있는 곳입니다. Steam 라이브러리에서 Peglin을 선택하고 **관리 → 로컬
파일 찾아보기**를 누르면 열 수 있습니다.

Thunderstore Mod Manager나 r2modman을 사용한다면 BepInEx 팩을 매니저에서 설치하세요.
아래 2번의 수동 복사 단계는 건너뛰고, 나머지 단계에서 `게임 폴더`는 선택한 Peglin
프로필 폴더로 바꾸어 적용합니다. 설정 파일도 프로필 안의
`BepInEx/config/BepInEx.cfg`를 사용하고 게임은 매니저에서 실행하세요.

## 설치

1. Peglin을 종료합니다.
2. BepInEx 팩을 내려받아 다운로드 폴더 등에 압축을 풉니다. `BepInExPack_Peglin`
   폴더를 열고, **그 안의 파일과 폴더**를 `Peglin.exe`가 있는 게임 폴더로 옮깁니다.
   자세한 과정은 팩 페이지의 수동 설치 안내를 참고하세요. 설치 후 게임 폴더에
   `BepInEx` 폴더와 `winhttp.dll` 파일이 있는지 확인합니다.
3. 게임을 한 번 실행한 다음 종료합니다.
4. `BepInEx/config/BepInEx.cfg`를 메모장으로 엽니다. `[Preloader.Entrypoint]` 항목에서
   `Type` 값을 `MonoBehaviour`로 설정합니다. 이미 이 값이면 그대로 둡니다. 나머지
   설정은 바꾸지 마세요.

   ```ini
   Type = MonoBehaviour
   ```

5. 받은 패치 ZIP 파일을 마우스 오른쪽 버튼으로 클릭해 **모두 압축 풀기**를 선택하고,
   `Peglin.exe`가 있는 게임 폴더를 지정합니다. 설치 후
   `BepInEx/plugins/PeglinKoreanRevised` 폴더가 있어야 합니다.
6. 게임을 실행하고 언어 설정에서 한국어를 선택합니다.

## 수동 설치 후 폴더 구조

아래는 주요 경로만 표시한 예시입니다. 게임과 BepInEx 팩의 다른 파일 및 폴더는
생략했습니다. 패치 ZIP에 들어 있는 안내와 라이선스 파일은 게임 폴더 바로 아래에
함께 풀립니다.

```text
Peglin/                              (Peglin.exe가 있는 게임 폴더)
├── Peglin.exe
├── BepInEx/
│   ├── config/
│   │   └── BepInEx.cfg
│   └── plugins/
│       └── PeglinKoreanRevised/
│           ├── PeglinKoreanRevised.dll
│           ├── overlay.json
│           └── manifest.json
├── winhttp.dll                      (BepInEx 팩)
├── doorstop_config.ini              (BepInEx 팩)
├── doorstop_libs/                   (BepInEx 팩)
├── README.md                        (패치 설치 안내)
├── LICENSE
└── TRANSLATION-NOTICE.txt
```

지원하지 않는 게임 버전에서는 패치가 적용되지 않습니다. 게임 업데이트 후 번역이
나오지 않으면 릴리스 목록에서 더 최신 패치가 있는지 확인해 주세요.

## 적용 상태 확인과 문제 해결

게임 언어를 한국어로 선택한 뒤, 문제가 생기면 BepInEx의 `LogOutput.log`에서
`Peglin Korean Revised`가 남긴 아래 메시지를 확인하세요. 수동 설치에서는 게임 폴더의
`BepInEx/LogOutput.log`를, 모드 매니저에서는 **실행에 사용한 Peglin 프로필**의 같은
상대 경로를 확인합니다. 다른 프로필이나 이전 실행 로그와 혼동하지 마세요.

| 로그의 메시지 일부 | 의미와 다음 조치 |
| --- | --- |
| `Loaded … Korean terms` | 패치 파일을 읽었습니다. 아직 게임 원본 검증이나 번역 적용이 끝난 상태는 아닙니다. |
| `Starting Peglin source file verification` | 지원하는 게임인지 확인하고 있습니다. 파일 전체를 검사하며, `Verified`에 기록된 시간은 해시 검사 시간이지 전체 게임 시작 시간이 아닙니다. |
| `Verified resources.assets SHA-256` | 두 게임 파일의 해시가 일치합니다. 이어지는 적용 결과도 확인하세요. |
| `Waiting for the Korean I2 Localization source` | 게임의 번역 데이터를 기다리고 있습니다. 아직 적용 완료가 아닙니다. |
| `Applied … Korean translations to the in-memory I2 table` | 메모리의 번역 표에 반영했습니다. 실제 화면의 한국어 문구도 확인하세요. 이 메시지만으로 모든 화면의 표시를 보장하지는 않습니다. |
| `does not match this candidate` | 게임 원본과 패치의 지원 대상이 다릅니다. 최신 호환 패치를 확인하고, 없다면 새 패치를 기다리세요. 예상 해시를 고치거나 검사를 끄지 마세요. |
| `resources.assets was not found` / `Assembly-CSharp.dll was not found` | 필요한 게임 파일을 찾지 못했습니다. 올바른 게임과 프로필로 실행했는지 확인하고 Steam의 게임 파일 무결성 검사를 사용하세요. |
| `Korean overlay could not start` | 패치 파일이 없거나 손상됐거나 서로 다른 패키지가 섞였을 수 있습니다. 아래 업데이트 절차에 따라 패치 전용 폴더만 제거하고 같은 ZIP의 파일을 함께 다시 설치하세요. |
| `Could not verify` / `Korean source verification could not start` | 게임 파일 검사에 실패했습니다. 바로 뒤의 오류와 설치 방법을 확인해 패치 문제로 제보하세요. |
| `No overlay terms matched the Korean I2 source` | 대기 후에도 적용할 번역 데이터를 찾지 못했습니다. 게임 언어와 실행 프로필을 확인한 뒤 관련 메시지를 제보하세요. 해시 불일치와는 다른 상태입니다. |

패치 메시지가 전혀 없다면 BepInEx가 해당 실행에서 로드됐는지, 플러그인 폴더와
설치 4번의 설정이 맞는지부터 확인하세요. 원본 검증이 오래 걸리는 것처럼 느껴지면
`Hashing`과 `Verified` 메시지의 파일 크기·검사 시간을 함께 확인하세요. 검사는 현재
동기식이며, 느리다는 느낌만으로 원본 검증을 생략하지 않습니다.

[패치 문제 제보](https://github.com/PiesP/peglin-korean-revised/issues/new?template=patch-problem.yml)에는
패치 버전, 확인 가능한 게임 빌드, 설치 방법, 발생한 현상과 **관련 메시지 몇 줄**만
첨부하면 됩니다. 사용자 이름, 개인 경로, 계정·세이브 정보는 가리고 전체 로그나
게임 파일·DLL은 올리지 마세요. 번역 수정안을 제시할 필요는 없습니다.

## 업데이트

Peglin을 종료하고 `BepInEx/plugins/PeglinKoreanRevised` 폴더를 삭제한 뒤, 최신 설치용
ZIP을 처음 설치했던 위치에 풀어 주세요. BepInEx 자체와 설정 파일은 삭제하지 않아도 됩니다.

## 제거

Peglin을 종료한 다음 게임 폴더(또는 모드 매니저 프로필)에서
`BepInEx/plugins/PeglinKoreanRevised` 폴더를 삭제합니다. BepInEx는 다른 모드에서도
사용할 수 있으므로 별도로 제거하세요.

## 도움과 번역 제안

번역 문제는 [번역 수정 제안](https://github.com/PiesP/peglin-korean-revised/issues/new?template=translation-suggestion.yml),
설치나 실행 문제는 [패치 문제 제보](https://github.com/PiesP/peglin-korean-revised/issues/new?template=patch-problem.yml)로
알려 주세요. 수정안을 모르셔도 괜찮습니다. 표시된 문구와 화면 또는 상황을 알려 주면
제보할 수 있습니다. 번역 문구를 직접 수정하려는 분은 [기여 안내](CONTRIBUTING.ko.md)를
참고하세요.

## 라이선스

프로젝트가 작성한 코드, 도구와 안내 문서는 [MIT License](LICENSE)로 제공됩니다.
게임 관련 번역 자료에는 MIT가 적용되지 않으며, 자세한 내용은
[번역 자료 고지](TRANSLATION-NOTICE.txt)를 확인해 주세요.
