<!-- Path: docs/config/cli_flags_matrix.md -->

# CLI 플래그 매트릭스

`stream_client.py`와 `stream_server.py`에서 공통적으로 제공하는 주요 CLI 플래그와
기본값을 정리한다. 신규 플래그는 이 매트릭스를 선행적으로 업데이트한 뒤 코드에
반영해야 하며, 도움말(`--help`) 출력과 동일한 값을 유지해야 한다.

| 플래그 | 클라이언트 기본값 | 서버 기본값 | 설명 | 참조 |
|--------|---------------------|-------------|------|------|
| `--transport {tcp,quic,udp_fec}` | `tcp` | `tcp` | 데이터 채널 전송 계층 선택. Python 구현은 현재 `tcp`만 지원하고 나머지는 `NotImplementedError`로 명시한다. | docs/designs/hybrid_pipeline_v2.md |
| `--protocol {legacy,binary}` | `binary` | `binary` | 데이터 프레이밍 프로토콜. `legacy`는 텍스트 헤더, `binary`는 MTU 안전 바이너리 헤더를 사용한다. | docs/contracts/control_plane_contract.md |
| `--tx-fragment-size` | `0` (비활성) | `0` (비활성) | 지정 시 payload를 MTU 안전 조각(256~1400B)으로 분할. 0이면 단편화 사용 안 함. | docs/contracts/control_plane_contract.md |
| `--socket-buffer-autotune` | `False` | `False` | 커널 소켓 버퍼 자동 튜닝 요청. Linux에서 `SO_RCVBUF`/`SO_SNDBUF`를 0으로 설정해 커널이 동적으로 조정하도록 한다. | docs/plans/network_latency_reduction_plan.md |
| `--metrics-out` | `artifacts/perf/client_latest.json` | `artifacts/perf/server_latest.json` | 텔레메트리 JSON 출력 경로. 스키마를 만족해야 한다. | docs/specs/telemetry_schema.md |

> **참고:** 신규 CLI 옵션을 추가할 때는 `docs/references/config_reference.md`도 함께 갱신한다.
