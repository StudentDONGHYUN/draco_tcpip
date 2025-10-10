# Draco 인코더 CLI 공용화 가이드

`draco_tools/core/encoder.py`는 스트리밍 노드와 배치 CLI에서 공용으로 사용하는
인코더 진입점을 제공합니다. 본 문서는 새 헬퍼의 사용법과 로그 포맷을 정리해
추가 도구 구현 시 참고할 수 있도록 합니다.

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

`add_encoder_arguments`는 등록한 설정을 `_encoder_cli_config` 네임스페이스에 자동
저장하므로, 별도의 전역 상태 없이 옵션을 재구성할 수 있습니다.

## 2. 옵션 해석 및 실행 파일 탐색

```python
from draco_tools.core.encoder import resolve_encoder_options, find_draco_encoder

encoder_hint, encoder_opts, skip_existing = resolve_encoder_options(args)
encoder_path = find_draco_encoder(encoder_hint)
```

`resolve_encoder_options`는 `EncoderOptions` 인스턴스를 돌려주며, 공용 helper가
생성한 `--cl/--qp/--qg` 인자를 자동으로 수집합니다.

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

스트리밍 노드(`stream_client.py`)와 배치 CLI(`encode_ply_to_draco.py`) 모두 위 포맷을
공유하며, prefix 값만 서로 다르게 지정합니다. 운영 로그/문서화 시 위 문자열을
바탕으로 일관된 파이프라인 메트릭을 수집할 수 있습니다.
