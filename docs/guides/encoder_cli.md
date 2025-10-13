<!-- Path: docs/guides/encoder_cli.md -->

# Draco 인코더 CLI 공용화 가이드

`draco_tools/core/encoder.py`는 스트리밍 노드(`draco_roundtrip/nodes/stream_client.py`)와 배치 CLI(`draco_tools/encode_ply_to_draco.py`)가 동일한 옵션 파서를 공유하도록 설계된 호환 계층입니다.【F:ros2_ws/src/draco_tools/draco_tools/core/encoder.py†L1-L107】 전체 아키텍처는 `../references/codebase_overview.md`를 참고하세요.

## 1. 표준 인자 등록
```python
import argparse
from draco_tools.core.encoder import add_encoder_arguments

parser = argparse.ArgumentParser()
add_encoder_arguments(
    parser,
    hint_option="--encoder",        # 실행 파일 힌트 플래그 (생략 시 환경 변수/which 사용)
    hint_dest="encoder",
    extra_option="--encoder-extra",  # draco_encoder에 그대로 전달할 추가 인자
    extra_dest="encoder_extra",
    skip_options=("--skip-existing", "--no-skip-existing"),
)
args = parser.parse_args()
```
`add_encoder_arguments`는 등록한 설정을 `_encoder_cli_config` 네임스페이스에 자동 저장하므로, 별도의 전역 상태 없이 옵션을 재구성할 수 있습니다.

## 2. 옵션 해석 및 실행 파일 탐색
```python
from draco_tools.core.encoder import resolve_encoder_options, find_draco_encoder

encoder_hint, encoder_opts, skip_existing = resolve_encoder_options(args)
encoder_path = find_draco_encoder(encoder_hint)
```
- `resolve_encoder_options`는 `EncoderOptions` 인스턴스를 반환하며 `--cl/--qp/--qg` 값을 수집합니다.
- `find_draco_encoder`는 환경 변수(`DRACO_ENCODER`, `DRACO_HOME`)와 PATH를 순회해 실행 파일을 탐색합니다. 스트리밍 노드와 배치 도구가 동일한 검색 순서를 사용하도록 중앙에서 관리합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py†L1-L160】

## 3. 통합 로그 포맷
```python
from draco_tools.core.encoder import encode_frame, format_encode_log

result = encode_frame(src_ply, out_dir, encoder_opts, encoder_hint=encoder_path)
print(format_encode_log(result, source=src_ply, prefix="[CLIENT][ENCODER]"))
```
로그는 다음 패턴을 따릅니다.
```
[ENCODER] OK frame_0001.ply -> frame_0001.drc (0.432s)
[ENCODER] SKIP frame_0002.ply -> frame_0002.drc (cached)
```
- `encode_frame`은 `draco_roundtrip/draco/encoder.py`의 실제 인코더 래퍼를 호출합니다.
- `prefix`를 조정하면 스트리밍(`stream_client`)과 배치(`encode_ply_to_draco`) 로그를 구분할 수 있습니다.
- 로그는 `stream_collect_logs`가 수집하는 manifest와 함께 저장되며, 후속 분석 시 `../templates/results_template.md`에 붙여 넣기 쉽도록 포맷이 통일되어 있습니다.

## 4. 추가 팁
- 신규 도구에서 인자 구성이 필요하다면 `add_encoder_arguments` 호출 후 `set_defaults`로 패키지별 기본값을 지정할 수 있습니다.
- `skip_options`를 생략하면 항상 재인코딩하며, 스트리밍 모드에서는 `stream_client`가 인플라이트 큐를 기준으로 자체 중복 검사를 수행합니다.
- 인코딩 품질과 관련된 실험 로그는 `logging_guidelines.md`와 연동해 기록하세요.

### 관련 코드 살펴보기
- 공용 CLI 헬퍼: `ros2_ws/src/draco_tools/draco_tools/core/encoder.py`
- Draco 래퍼: `ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py`
- 스트리밍 클라이언트 사용 예시: `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py`
- 배치 파이프라인 사용 예시: `ros2_ws/src/draco_tools/draco_tools/encode_ply_to_draco.py`
