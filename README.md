# Zeus + Poseidon 한글화 패치

Steam판 **Zeus + Poseidon** (제우스 + 포세이돈) 비공식 한글화 패치입니다.

## 설치 방법

### 요구 사항
- Steam판 Zeus + Poseidon (정품 필수)
- Windows 10/11
- **Python 3.8 이상** ([다운로드](https://www.python.org/downloads/))
  - 설치 시 **"Add Python to PATH"** 옵션을 반드시 체크하세요

### 설치
1. 이 저장소를 다운로드하거나 `git clone` 합니다.
2. `install.bat`을 **관리자 권한으로** 실행합니다.
3. Steam에서 게임을 실행합니다.

> 설치 스크립트가 자동으로:
> 1. 원본 파일을 백업합니다 (최초 1회)
> 2. 원본 EXE를 한글 패치합니다
> 3. 번역 파일을 게임 폴더에 복사합니다

### 제거
`uninstall.bat`을 실행하면 원본 파일로 복원됩니다.
또는 Steam에서 '파일 무결성 검사'를 실행하세요.

## 패치 내용

- 게임 내 모든 UI 텍스트 한글화
- 멀티미디어 메시지(Zeus_MM) 한글화
- 이벤트 메시지(eventmsg) 한글화
- EXE 바이너리 패치를 통한 한글 폰트 렌더링 (KFONT 1bpp)
- 커스텀 어드벤처 영문 텍스트 정상 표시 지원

## 알려진 이슈

- 일부 UI 요소의 텍스트 센터링이 약간 어긋날 수 있음
- 오버레이 첫 표시 시 위치가 벗어날 수 있음 (스크롤 시 정상 복귀)

## 파일 구조

```
install.bat              # 설치 스크립트
uninstall.bat            # 제거 스크립트
patch/
  patch_korean.py        # EXE 패처 (설치 시 자동 실행)
  fonts/                 # 한글 폰트 데이터
Zeus_Text.eng            # 번역된 텍스트
Zeus_MM.eng              # 번역된 멀티미디어 메시지
Model/                   # 이벤트 메시지
Adventures/              # 커스텀 어드벤처 텍스트
```

## 면책 조항

이 프로젝트는 비공식 팬 번역이며, Impressions Games, Sierra Entertainment, Activision Blizzard, Microsoft와는 관련이 없습니다. 게임의 정품 사본을 소유한 사용자만 사용하십시오. 저작권자의 요청이 있을 경우 즉시 배포를 중단합니다.

이 패치는 원본 게임 파일을 포함하지 않습니다. 사용자의 정품 게임 파일을 현장에서 패치합니다.

Zeus + Poseidon™ is a trademark of its respective owners. This is an unofficial fan translation and is not affiliated with or endorsed by the original developers or publishers.

## 라이선스

번역 텍스트 및 패치 도구: MIT License
