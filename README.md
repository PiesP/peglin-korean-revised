# 페글린 한국어 번역 개선 패치

Peglin의 한국어 문장을 더 정확하고 자연스럽게 다듬어 게임에 적용하는
비공식 번역 패치입니다. 패치는 BepInEx 플러그인으로 작동하며 Peglin의 원본
파일을 직접 수정하지 않습니다.

## 패치 받기

[릴리스 목록](https://github.com/PiesP/peglin-korean-revised/releases)에서 가장
최근의 설치용 ZIP 파일을 받으세요. Peglin이 업데이트되면 이전 패치가 적용되지
않을 수 있으므로, 현재 게임 버전에 맞는 최신 릴리스를 사용해야 합니다.

## 필요한 프로그램

- Windows용 Peglin
- [Peglin용 BepInEx 팩](https://thunderstore.io/c/peglin/p/BepInEx/BepInExPack_Peglin/)
  (Mono 버전)

## 설치

1. Peglin용 BepInEx 팩의 안내에 따라 BepInEx를 설치합니다.
2. Peglin을 한 번 실행했다가 종료하여 BepInEx 설정 파일을 만듭니다.
3. `BepInEx/config/BepInEx.cfg`를 열고 `[Preloader.Entrypoint]` 아래의 값을
   다음과 같이 확인합니다.

   ```ini
   Type = MonoBehaviour
   Assembly = UnityEngine.CoreModule.dll
   Method = .cctor
   ```

   나머지 설정은 그대로 둡니다.
4. 다운로드한 ZIP을 `Peglin.exe`가 있는 Peglin 설치 폴더에 풉니다.
5. 게임을 실행하고 언어 설정에서 한국어를 선택합니다.

게임 파일이 패치가 지원하는 버전과 다르면 안전을 위해 번역이 적용되지 않습니다.
이 경우 최신 릴리스가 있는지 확인해 주세요.

## 업데이트

1. Peglin을 종료합니다.
2. 기존 `BepInEx/plugins/PeglinKoreanRevised` 폴더를 삭제합니다.
3. [릴리스 목록](https://github.com/PiesP/peglin-korean-revised/releases)에서 가장
   최근의 설치용 ZIP을 받아 Peglin 설치 폴더에 풉니다.

## 제거

Peglin을 종료한 다음 `BepInEx/plugins/PeglinKoreanRevised` 폴더를 삭제합니다.
BepInEx 자체는 별도로 제거할 수 있습니다.

## 번역 오류 제보

어색하거나 잘못된 번역을 발견했다면
[번역 수정 제안](https://github.com/PiesP/peglin-korean-revised/issues/new?template=translation-suggestion.yml)을
작성해 주세요. 문제가 나타난 화면이나 상황, 현재 문구와 제안 문구를 함께 적으면
확인하는 데 도움이 됩니다.

설치나 실행에 문제가 있다면
[패치 문제 제보](https://github.com/PiesP/peglin-korean-revised/issues/new?template=patch-problem.yml)를
이용해 주세요. 번역 파일을 직접 수정하려면
[기여 안내](CONTRIBUTING.ko.md)를 참고하세요.

## 라이선스

저장소에서 직접 작성한 코드, 도구와 안내 문서는 [MIT License](LICENSE)로
제공합니다. `translation/`의 번역 및 게임 관련 자료는 이 라이선스의 범위에
포함되지 않습니다. Peglin과 게임 내 콘텐츠의 권리는 각 권리자에게 있으며,
이 저장소는 해당 콘텐츠에 대한 별도 이용 허락을 부여하지 않습니다.
