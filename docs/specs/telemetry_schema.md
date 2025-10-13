<!-- Path: docs/specs/telemetry_schema.md -->

# Draco 텔레메트리 스키마 (v1.0.0)

`docs/specs/telemetry_schema.json`은 스트리밍 세션이 종료될 때 기록해야 하는
표준 텔레메트리 구조를 JSON Schema 형태로 정의한다. 본 문서는 각 필드가
담아야 하는 의미와 단위를 설명한다.

## 공통 원칙

- 모든 시간 값은 나노초 단위의 모노토닉 시계(`time.monotonic_ns`)를 사용한다.
- 지연(latency)과 RTT/ACK 값은 밀리초 부동소수점으로 표준화하며, p50/p95/p99를 필수로 포함한다.
- 텔레메트리 파일은 UTF-8 JSON으로 직렬화하고, 파일 헤더에 BOM을 포함하지 않는다.

## 루트 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `schema_version` | string | 현재 스키마 버전. `1.0.0` 고정. |
| `schema_doc` | string | 본 문서 경로(`docs/specs/telemetry_schema.md`). 코드 주석에서 SSOT 경로를 그대로 참조한다. |
| `session` | object | 세션 메타데이터. 시작/종료 시각, 전송 프로토콜, 상태값 등을 포함한다. |
| `metrics` | object | 레이턴시, 큐 상태, 프레임 카운터 등 핵심 성능 지표. |

## `session` 세부 항목

- `id`: 세션 고유 식별자(예: ISO8601 타임스탬프 + PID).
- `role`: `"client"` 또는 `"server"`.
- `transport`: CLI `--transport` 값. 현재 Python 구현은 `tcp`만 지원하지만 스키마는 향후 확장을 대비해 `quic`, `udp_fec`를 포함한다.
- `protocol`: 데이터 프레이밍 방식(`legacy`/`binary`).
- `fragment_size`: `--tx-fragment-size` 값. 0이면 단편화를 사용하지 않는다.
- `socket_buffer_autotune`: `--socket-buffer-autotune` 플래그가 켜졌는지 여부.
- `started_at_ns`, `ended_at_ns`: 나노초 단위 모노토닉 타임스탬프.
- `state`: 제어 평면 상태기계 종료 결과(`TERMINATED` 또는 `FAILED`).
- `error_code`, `error_message`: `state="FAILED"`일 경우 필수. `error_code`는 `docs/contracts/control_plane_contract.md`의 오류 코드를 따른다.

## `metrics` 세부 항목

- `latency_ms`: 프레임 캡처 → 디코드 완료까지의 end-to-end 지연 분포.
- `rtt_ms`: 클라이언트가 프레임을 전송하고 서버 ACK을 받기까지의 왕복 지연.
- `ack_latency_ms`: 서버에서 프레임 수신 → ACK 송신까지의 지연.
- `throughput_mbps`: 평균(`avg`) 및 피크(`peak`) 송신 처리량. 메가비트/초.
- `queues`: 캡처(`capture_max`), 인코드(`encode_max`), 디코드(`decode_max`) 큐의 최대 깊이와 현재 `pending` 프레임 수.
- `frames`: 전송된(`sent`), ACK 완료된(`acked`), 드롭된(`dropped`), 스킵된(`skipped`) 프레임 수.

## 검증 흐름

1. 텔레메트리 클래스를 통해 Python 객체를 구성한다.
2. JSON으로 직렬화하기 전에 스키마를 로드하고 필수 필드를 모두 검증한다.
3. 검증에 실패하면 제어 평면 ERROR 코드 `INTERNAL_ERROR`로 종료하고 텔레메트리 파일을 쓰지 않는다.

