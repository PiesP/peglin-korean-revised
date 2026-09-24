# 페글린 한국어 번역 개선 패치

Peglin의 한국어 문장을 더 자연스럽고 이해하기 쉽게 다듬어 게임에 적용하는
비공식 패치입니다. BepInEx 플러그인으로 작동하며 게임 파일을 직접 바꾸지 않습니다.
이 프로젝트는 개발 과정에서 AI 도구의 도움을 받았습니다.

## 패치 받기

[릴리스 목록](https://github.com/PiesP/peglin-korean-revised/releases)에서 최신
`PeglinKoreanRevised-`로 시작하고 `.zip`으로 끝나는 설치 파일을 받으세요. JSON 파일은
일반 설치에 필요하지 않습니다. Peglin이 업데이트되면 이전 패치가 작동하지 않을 수
있으니 최신 릴리스를 확인해 주세요.

## 준비

- Windows용 Peglin
- [Peglin용 BepInEx 팩](https://thunderstore.io/c/peglin/p/BepInEx/BepInExPack_Peglin/)

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
알려 주세요. 번역 문구를 직접 수정하려는 분은 [기여 안내](CONTRIBUTING.ko.md)를
참고하세요.

## 라이선스

프로젝트가 작성한 코드, 도구와 안내 문서는 [MIT License](LICENSE)로 제공됩니다.
게임 관련 번역 자료에는 MIT가 적용되지 않으며, 자세한 내용은
[번역 자료 고지](TRANSLATION-NOTICE.txt)를 확인해 주세요.
