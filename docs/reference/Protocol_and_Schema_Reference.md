# 프로토콜 및 스키마 참조
Draco Roundtrip 스트리밍 세션을 제어하는 제어 플레인 메시지, 상태 기계, 텔레메트리 스키마를 정의합니다.
_마지막 업데이트: 2025-03-16_

**목차**
- [제어 플레인 메시지](#제어-플레인-메시지)
- [세션 상태 기계](#세션-상태-기계)
- [타이밍 및 조각화 규칙](#타이밍-및-조각화-규칙)
- [텔레메트리 스키마](#텔레메트리-스키마)
- [검증 체크리스트](#검증-체크리스트)

## 제어 플레인 메시지

### TCP 제어 시퀀스 개요

<!-- AUTODOC:TCP_CONTROL_SEQUENCE_SIMPLE -->
<!-- AUTODOC:TCP_CONTROL_SEQUENCE_SIMPLE:BEGIN -->
```mermaid
sequenceDiagram
  participant Sender as TCP Sender
  participant Receiver as TCP Receiver
  participant Control as Control Plane
  Sender->>Receiver: DATA frame
  Receiver-->>Sender: ACK (window update)
  Control-->>Sender: Heartbeat timer
  Sender-->>Control: EOF / Error signal
  Control-->>Receiver: Close stream on EOF
```
<!-- AUTODOC:TCP_CONTROL_SEQUENCE_SIMPLE:END -->

> v2 프로토콜부터는 **단일 TCP 연결**만 사용한다. DATA/ACK/HEARTBEAT/EOF/ERROR
> 프레임은 모두 동일한 스트림 위에서 순서대로 전송되며, `FrameType` 값으로
> 논리적 역할을 구분한다. 기존 제어 포트는 유지보수를 위해 파싱만 할 뿐,
> 새 연결에서는 개설되지 않는다.

| 코드(16진) | 심볼 | 목적 | 페이로드 |
|------------|--------|---------|---------|
| `0x01` | `ACK` | 수신자가 데이터 프레임을 수락했음을 확인 | 8바이트 부호 없는 시퀀스(빅엔디언) |
| `0x02` | `HEARTBEAT` | 유휴 구간 동안 송신자가 살아 있음을 알림 | 선택적 8바이트 단조 증가 타임스탬프 |
| `0x03` | `EOF` | 모든 프레임 전송이 완료되었음을 알림 | 없음 |
| `0x04` | `ERROR` | 비정상 종료를 보고 | 1바이트 오류 코드 + UTF-8 메시지 |

> **헤더 버전**
> - 기본 헤더는 `magic=b"DRC0"`, `version=2`이며, 타임스탬프(`timestamp_ns`)와 콘텐츠 타입(`content_type`)을 포함한다.
> - 레거시 모드(`--legacy-mode`)가 활성화된 경우에만 `magic=b"DRTC"`, `version=1` 프레임을 허용하며, 해당 프레임은 추가 메타데이터 없이 16바이트다.
> - 조각화가 활성화되면 `FLAG_FRAGMENTED`/`FLAG_MORE_FRAGMENTS` 플래그와 함께 8바이트 프래그먼트 메타데이터(인덱스/총합/프레임 길이)가 이어진다.

### 오류 코드
| 코드 | 식별자 | 설명 |
|------|------------|-------------|
| `0` | `NONE` | 예약됨 |
| `1` | `PROTOCOL_VIOLATION` | 잘못된 헤더 또는 상태 전이 |
| `2` | `TIMEOUT` | ACK/HEARTBEAT가 타임아웃 한도를 초과 |
| `3` | `INTERNAL_ERROR` | 인코더/디코더 실패 |
| `4` | `SHUTDOWN` | 운영자가 요청한 정상 종료 |

## 세션 상태 기계
상태는 `INIT → HANDSHAKING → STREAMING → DRAINING → TERMINATED`로 진행되며, 오류가 발생하면 어느 상태에서든 `FAILED`로 전이할 수 있습니다.

1. `INIT` → `HANDSHAKING`: TCP 연결이 성립되며 1초 이내에 첫 하트비트 또는 데이터 프레임이 도착해야 합니다.
2. `HANDSHAKING` → `STREAMING`: 첫 데이터 프레임 또는 ACK 수신.
3. `STREAMING` → `DRAINING`: 송신자가 `EOF`를 전송하고 남은 ACK를 기다립니다.
4. `DRAINING` → `TERMINATED`: 모든 프레임이 ACK되고 큐가 비어 있음(`pending=0`).
5. 모든 상태 → `FAILED`: 오류 메시지, 타임아웃, 내부 실패.

종료 시 양측은 대기 큐, RTT, 지연 분위수를 요약한 구조화 로그를 출력합니다. `FAILED` 상태에 진입한 세션은 추가 데이터 및 제어 메시지 전송을 중단해야 합니다.

## 타이밍 및 조각화 규칙
- `ACK_TIMEOUT_S = 0.5`: RTT EMA가 조정되기 전 초기 ACK 마감 시간.
- `HEARTBEAT_INTERVAL_S = 2.0`: 해당 간격 동안 데이터 프레임이 없으면 하트비트를 전송.
- `HEARTBEAT_LIVENESS_S = 6.0`: 임계값을 초과해 하트비트가 누락되면 `TIMEOUT` 코드의 `ERROR` 발생.
- `CONTROL_POLL_INTERVAL_S = 0.05`: 제어 워커 슬립 간격. 단일 소켓에서도 동일하게 사용됩니다.
- 조각화: `--tx-fragment-size` > 0이면 페이로드를 256–1400바이트 조각으로 나누고 `FLAG_FRAGMENTED`/`FLAG_MORE_FRAGMENTS` 플래그를 설정합니다. 수신 측은 ACK 전 조각을 재조립합니다.
- 프래그먼트 GC: 서버는 `FRAGMENT_TTL_SEC = 300`, `FRAGMENT_GC_INTERVAL = 60`을 사용해 유휴 조각을 삭제합니다. 누적 메모리가 `FRAGMENT_BUFFER_MAX_BYTES = 134217728`(128 MiB)을 넘으면 가장 오래된 항목부터 제거하고 경고를 기록합니다.

### 텍스트 프로토콜 제한

- `MAX_TEXT_NAME_LEN = 4096`: 텍스트 프로토콜에서 허용되는 메타 필드 최대 길이.
- `MAX_TEXT_PAYLOAD_LEN = 104857600`(100 MiB): 텍스트 페이로드 상한. 초과 시 세션을 즉시 종료.
- 제한을 위반하면 경고 로그와 함께 소켓을 닫고 `_text_limit_drops` 카운터를 증가시킨다. 전송자 측에서도 연결 종료를 감지해야 한다.
- 클라이언트와 서버 모두 v2 바이너리 프로토콜을 기본값으로 사용하며, 텍스트 모드는 레거시 호환성 전용이다.

## 텔레메트리 스키마
텔레메트리 JSON에는 다음 필드가 포함되어야 하며 스키마 버전은 `1.0.0`입니다.

| 필드 | 유형 | 비고 |
|-------|------|-------|
| `schema_version` | string | 항상 `1.0.0` |
| `schema_doc` | string | 본 문서 경로를 참조해야 함 |
| `session.id` | string | 고유 세션 식별자 |
| `session.role` | string | `"client"` 또는 `"server"` |
| `session.transport` | string | `--transport` 플래그와 동일 |
| `session.protocol` | string | `binary`, `text`, `legacy` 중 하나 |
| `session.fragment_size` | integer | `--tx-fragment-size` 값 |
| `session.socket_buffer_autotune` | boolean | CLI 플래그와 동일 |
| `session.started_at_ns` / `session.ended_at_ns` | integer | 단조 증가 타임스탬프(나노초) |
| `session.state` | string | `TERMINATED` 또는 `FAILED` |
| `session.error_code` / `session.error_message` | mixed | `state = FAILED`일 때 필수. 코드 값은 위 표와 일치 |
| `metrics.latency_ms` | object | `p50`, `p95`, `p99` 및 선택적 히스토그램 포함 |
| `metrics.rtt_ms` | object | 지연 필드와 동일 |
| `metrics.ack_latency_ms` | object | ACK 전 서버 처리 지연 |
| `metrics.throughput_mbps` | object | `avg`, `peak` 포함 |
| `metrics.queues` | object | `capture_max`, `encode_max`, `decode_max`, 현재 `pending` 포함 |
| `metrics.frames` | object | `sent`, `acked`, `dropped`, `skipped` |

텔레메트리 작성자는 파일을 저장하기 전에 `docs/specs/telemetry_schema.json`을 사용해 유효성을 검사해야 합니다. 유효하지 않은 텔레메트리는 `INTERNAL_ERROR` 코드의 `ERROR`로 처리하고 저장을 중단해야 합니다.

### 품질 특성 게이트
프로토콜/스키마 요소가 품질 특성별로 어떤 근거를 제공하는지 명확히 합니다. 스펙을 변경하면 표를 업데이트하고 [`Quality_Attributes_Catalog`](Quality_Attributes_Catalog.md)과 추적성 매트릭스에 반영합니다.

| 품질 특성 | 프로토콜/스키마 근거 | 검증/증거 |
| --- | --- | --- |
| 기능성·정확성 | FrameType 값, 단일 헤더 레이아웃, 필수 텔레메트리 필드 | 헤더/스키마 단위 테스트, `tests/unit/test_protocol_header.py`, 텔레메트리 스키마 검증 |
| 신뢰성 | 상태 기계(FAILED/TERMINATED), 하트비트 2 s/6 s, ACK 타임아웃 0.5 s | `tests/unit/test_single_channel_mux.py`, 실패 로그에 상태 전이 기록 |
| 보안성 | 텍스트 프로토콜 길이 제한, 단일 소켓 강제(보조 포트 비활성) | `tests/unit/test_text_protocol_limits.py`, 신규 플래그 추가 시 보안 리뷰 체크리스트 |
| 성능/효율성·확장성 | MTU 안전 조각화(256–1400 B), in-flight ACK 회로, CONTROL_POLL 50 ms | `tests/perf/test_latency_gate.py`, netem에서 조각화와 윈도 설정 조합 실험 |
| 운영 가능성·관측 | 종료 시 pending/p50/p95/p99 로그, 텔레메트리 필드(queues, throughput) | `docs/reports/results_template.md`의 게이트 테이블을 채우는 로그 샘플, rosbag 재현 명령 |
| 이식성 | `--legacy-mode` v1 호환성, 바이너리/텍스트 프로토콜 전환 | v1/v2 호환 회귀 테스트, CLI 도움말/문서가 일치하는지 확인 |
| 테스트 가능성·유지보수성 | 스키마 버전 필드, 단일 진입점 플래그, 명시적 상수 테이블 | 스키마 버전 변경 시 CI 실패 여부, 상수 값이 [`Configuration_Reference`](Configuration_Reference.md)와 일치 |

## 검증 체크리스트
- [ ] 바이너리 프로토콜 헤더가 위 메시지 표와 일치한다.
- [ ] 하트비트와 ACK 타이머가 [구성 참조](../reference/Configuration_Reference.md)의 타임아웃 상수 및 CLI 오버라이드를 준수한다.
- [ ] 텔레메트리 JSON이 필수 필드를 포함하고 스키마 검증을 통과한다.
- [ ] 종료 로그가 소켓을 닫기 전에 `pending` 카운트와 p50/p95/p99 지표를 기록한다.
- [ ] 조각화가 활성화되면 256–1400 B 범위를 지킨다.
- [ ] 텍스트 프로토콜 제한을 초과하면 즉시 연결을 종료하고 `_text_limit_drops` 카운터를 남긴다.
- [ ] `--legacy-mode`와 v2 기본 경로 모두에서 동일한 상태 전이/에러 코드 로그를 남긴다.
- [ ] 프로토콜/스키마 변경 시 `report_version`과 템플릿(품질 게이트 표)을 동기화한다.

## 자동 생성 와이어 참조
<!-- AUTODOC:PROTOCOL:BEGIN -->
#### Binary Frame Header (v2)

| 필드 | 포맷 | 바이트 | 설명 |
| - | - | - | - |
| `magic` | `4s` | 4 | 고정 ASCII 매직 `b"DRC0"` |
| `version` | `B` | 1 | 헤더 버전 (현재 `2`) |
| `flags` | `B` | 1 | 하위 4비트 = `FrameType`, 상위 비트 = 조각화 플래그 |
| `sequence` | `I` | 4 | 모노톤 uint32 프레임 시퀀스 |
| `name_len` | `H` | 2 | UTF-8 이름 길이 |
| `payload_len` | `I` | 4 | 페이로드 바이트 길이 |
| `timestamp_ns` | `Q` | 8 | 캡처 타임스탬프(나노초) |
| `content_type` | `H` | 2 | 콘텐츠 타입 힌트 (`CONTENT_TYPE_DRACO` 등) |
| **합계** |  | **26** |  |

#### Legacy Frame Header (v1)

| 필드 | 포맷 | 바이트 | 설명 |
| - | - | - | - |
| `magic` | `4s` | 4 | 레거시 매직 `b"DRTC"` |
| `version` | `B` | 1 | 버전 `1` (레거시 모드 전용) |
| `flags` | `B` | 1 | `FrameType` / 조각화 비트 |
| `sequence` | `I` | 4 | 프레임 시퀀스 |
| `name_len` | `H` | 2 | 이름 길이 |
| `payload_len` | `I` | 4 | 페이로드 길이 |
| **합계** |  | **16** |  |

> `--legacy-mode`가 활성화된 경우에만 v1 헤더를 허용한다. 새 클라이언트는
> 항상 v2 헤더를 전송해야 하며, 레거시 클라이언트에서 수신된 타임스탬프와
> 콘텐츠 타입은 프레임 페이로드 내부(텍스트 헤더)에서 파생된다.

#### Fragment Metadata

| 필드 | 포맷 | 바이트 | 설명 |
| - | - | - | - |
| `index` | `H` | 2 | 0 기반 조각 인덱스 |
| `total` | `H` | 2 | 전체 조각 수 |
| `frame_payload_len` | `I` | 4 | 재조립된 페이로드 길이 |
| **합계** |  | **8** |  |

> v2에서는 별도의 `DataHeader` 구조가 삭제되었다. 타임스탬프와 콘텐츠 타입
> 메타데이터는 프레임 헤더에 직접 포함되며, 응답(`compose_response_payload`)
> 역시 동일한 헤더 레이아웃을 사용한다.

#### Enumerations

| FrameType | Value | Description |
| - | - | - |
| DATA | 0 | Enumerate frame kinds multiplexed over the TCP stream. |
| ACK | 1 | Enumerate frame kinds multiplexed over the TCP stream. |
| ERROR | 2 | Enumerate frame kinds multiplexed over the TCP stream. |
| HEARTBEAT | 3 | Enumerate frame kinds multiplexed over the TCP stream. |
| EOF | 4 | Enumerate frame kinds multiplexed over the TCP stream. |
| CONTROL | 5 | Enumerate frame kinds multiplexed over the TCP stream. |

| ControlCode | Value | Description |
| - | - | - |
| ACK | 1 | 제어 메시지 코드 (SSOT 참조). |
| HEARTBEAT | 2 | 제어 메시지 코드 (SSOT 참조). |
| EOF | 3 | 제어 메시지 코드 (SSOT 참조). |
| ERROR | 4 | 제어 메시지 코드 (SSOT 참조). |

| ErrorCode | Value | Description |
| - | - | - |
| NONE | 0 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| PROTOCOL_VIOLATION | 1 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| TIMEOUT | 2 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| INTERNAL_ERROR | 3 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| SHUTDOWN | 4 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |

#### Timing and Fragment Limits

| Constant | Value |
| - | - |
| ACK_TIMEOUT_NS | 500000000 |
| HEARTBEAT_INTERVAL_NS | 2000000000 |
| HEARTBEAT_LIVENESS_NS | 6000000000 |
| CONTROL_POLL_INTERVAL | 0.05 |
| MIN_FRAGMENT_SIZE | 256 |
| MAX_FRAGMENT_SIZE | 1400 |
| DATA_CHANNEL | data |
| CONTROL_CHANNEL | control |
<!-- AUTODOC:PROTOCOL:END -->

## Auto-Generated State Machine
<!-- AUTODOC:STATE_MACHINE:BEGIN -->
```mermaid
stateDiagram-v2
  [*] --> INIT
  INIT --> HANDSHAKING: on_connected()
  HANDSHAKING --> STREAMING: on_first_data() / on_heartbeat()
  STREAMING --> DRAINING: on_eof_sent() / on_eof_received()
  DRAINING --> TERMINATED: on_ack() with no pending
  STREAMING --> FAILED: on_error() / heartbeat timeout
  DRAINING --> FAILED: on_error()
  HANDSHAKING --> FAILED: on_error()
  TERMINATED --> [*]
  FAILED --> [*]
  STREAMING --> STREAMING: on_frame_sent() / ACK pending
  DRAINING --> DRAINING: pending ACKs remain
```
<!-- AUTODOC:STATE_MACHINE:END -->

## Auto-Generated Telemetry 필드 Map
<!-- AUTODOC:TELEMETRY:BEGIN -->
| Field | Type / Constraints | Produced By | When | Notes |
| - | - | - | - | - |
| metrics.ack_latency_ms.p50 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.ack_latency_ms.p95 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.ack_latency_ms.p99 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.frames.acked | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Frames acknowledged |
| metrics.frames.dropped | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Frames dropped |
| metrics.frames.sent | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Total frames sent |
| metrics.frames.skipped | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Frames skipped due to quality filters |
| metrics.latency_ms.p50 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Percentiles computed from PipelineStats |
| metrics.latency_ms.p95 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.latency_ms.p99 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.queues.capture_max | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Max capture queue depth |
| metrics.queues.decode_max | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Max decode queue depth |
| metrics.queues.encode_max | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Max encode queue depth |
| metrics.queues.pending | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Pending frames at export (0 when terminated) |
| metrics.rtt_ms.p50 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.rtt_ms.p95 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.rtt_ms.p99 | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization |  |
| metrics.throughput_mbps.avg | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Aggregated from total bytes/elapsed |
| metrics.throughput_mbps.peak | number (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | Metrics normalization | Same as avg in current exporter |
| schema_doc | string (required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:171 (Telemetry.build) | Telemetry export | Anchors schema doc path |
| schema_version | string (enum=1.0.0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:171 (Telemetry.build) | Telemetry export | Constant from Telemetry.SCHEMA_VERSION |
| session.ended_at_ns | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | on_shutdown | ControlPlane completion timestamp |
| session.error_code | integer (min=0) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Failure export | Filled when state == FAILED |
| session.error_message | string | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Failure export | Optional failure context |
| session.fragment_size | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Session creation | Tx fragment configuration |
| session.id | string (required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Session creation | Derived from role/time/pid |
| session.protocol | string (enum=legacy,binary; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Session creation | Framing protocol name |
| session.role | string (enum=client,server; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Session creation | CLI role passed to Telemetry |
| session.socket_buffer_autotune | boolean | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Session creation | Reflects CLI socket buffer flag |
| session.started_at_ns | integer (min=0; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | on_connected | ControlPlane timestamp |
| session.state | string (enum=TERMINATED,FAILED; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | export | ControlPlane.state value |
| session.transport | string (enum=tcp,quic,udp_fec; required) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | Session creation | Transport argument |
<!-- AUTODOC:TELEMETRY:END -->
