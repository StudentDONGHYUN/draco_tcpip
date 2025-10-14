# DracoPy 전환 가이드

## 개요

이 프로젝트는 더 이상 외부 `draco_encoder`/`draco_decoder` 실행 파일을 사용하지 않고, 순수 Python 바인딩인 [`DracoPy`](https://pypi.org/project/DracoPy/)를 통해 모든 Draco 인코딩·디코딩을 메모리 상에서 수행합니다.

## 주요 변경 사항

- `draco_roundtrip.draco.encoder.encode_points()`가 `.drc` 임시 파일 없이 바로 `bytes` 를 반환합니다.
- 스트리밍 서버는 `DracoPy.decode()`를 사용해 수신된 프레임을 복원하며, `--legacy_downlink` 모드에서만 PLY 바이트를 생성합니다.
- `draco_tools`의 CLI 및 분석 스크립트는 더 이상 외부 바이너리 경로를 요구하지 않습니다.

## 마이그레이션 체크리스트

- Python 의존성에 `DracoPy`가 포함되었는지 확인합니다 (`pip install DracoPy`).
- 환경 변수 `DRACO_ENCODER`, `DRACO_DECODER` 는 더 이상 사용되지 않습니다.
- 기존 자동화 스크립트에서 `--draco` 또는 `--decoder` 옵션을 전달했다면 제거하거나, 새로운 경고 메시지를 무시해도 됩니다.

## 호환성

인코딩/디코딩 API 의 함수명은 유지되지만, 반환값은 더 이상 파일 경로가 아닌 바이트 버퍼입니다. 직접 파일이 필요할 경우 `open(..., 'wb')` 로 저장하면 됩니다.
