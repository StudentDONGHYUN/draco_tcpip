# 프로토콜 및 스키마 참조
Draco Roundtrip 스트리밍 세션을 제어하는 제어 플레인 메시지, 상태 기계, 텔레메트리 스키마를 정의합니다.
_마지막 업데이트: 2025-03-15_

**목차**
- [제어 플레인 메시지](#제어-플레인-메시지)
- [세션 상태 기계](#세션-상태-기계)
- [타이밍 및 조각화 규칙](#타이밍-및-조각화-규칙)
- [텔레메트리 스키마](#텔레메트리-스키마)
- [검증 체크리스트](#검증-체크리스트)

## 제어 플레인 메시지
| 코드(16진) | 심볼 | 목적 | 페이로드 |
|------------|--------|---------|---------|
| `0x01` | `ACK` | 수신자가 데이터 프레임을 수락했음을 확인 | 8바이트 부호 없는 시퀀스(빅엔디언) |
| `0x02` | `HEARTBEAT` | 유휴 구간 동안 송신자가 살아 있음을 알림 | 선택적 8바이트 단조 증가 타임스탬프 |
| `0x03` | `EOF` | 모든 프레임 전송이 완료되었음을 알림 | 없음 |
| `0x04` | `ERROR` | 비정상 종료를 보고 | 1바이트 오류 코드 + UTF-8 메시지 |

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
- `CONTROL_POLL_INTERVAL_S = 0.05`: 제어 소켓 폴링 주기.
- 조각화: `--tx-fragment-size` > 0이면 페이로드를 256–1400바이트 조각으로 나누고 `more_fragments` 플래그를 설정합니다. 수신 측은 ACK 전 조각을 재조립합니다.

## 텔레메트리 스키마
텔레메트리 JSON에는 다음 필드가 포함되어야 하며 스키마 버전은 `1.0.0`입니다.

| 필드 | 유형 | 비고 |
|-------|------|-------|
| `schema_version` | string | 항상 `1.0.0` |
| `schema_doc` | string | 본 문서 경로를 참조해야 함 |
| `session.id` | string | 고유 세션 식별자 |
| `session.role` | string | `"client"` 또는 `"server"` |
| `session.transport` | string | `--transport` 플래그와 동일 |
| `session.protocol` | string | `legacy` 또는 `binary` |
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

## 검증 체크리스트
- [ ] 바이너리 프로토콜 헤더가 위 메시지 표와 일치한다.
- [ ] 하트비트와 ACK 타이머가 [구성 참조](../reference/Configuration_Reference.md)의 타임아웃 상수 및 CLI 오버라이드를 준수한다.
- [ ] 텔레메트리 JSON이 필수 필드를 포함하고 스키마 검증을 통과한다.
- [ ] 종료 로그가 소켓을 닫기 전에 `pending` 카운트와 p50/p95/p99 지표를 기록한다.
- [ ] 조각화가 활성화되면 256–1400 B 범위를 지킨다.

## 자동 생성 와이어 참조
<!-- AUTODOC:PROTOCOL:BEGIN -->
#### 바이너리 프레임 헤더

| 프레임 헤더 필드 | 포맷 | 바이트 | 설명 |
| - | - | - | - |
| magic | 4s | 4 | 고정 ASCII 매직 b'DRTC' |
| version | B | 1 | 프로토콜 버전(기대값 1) |
| flags | B | 1 | 하위 4비트=FrameType, 상위 비트=조각화 플래그 |
| sequence | I | 4 | 단조 증가 프레임 시퀀스 번호 |
| name_len | H | 2 | 논리 이름/경로 메타데이터 길이 |
| payload_len | I | 4 | 페이로드 바이트 길이 |
| Total |  | 16 |  |

#### 조각 메타데이터

| 조각 정보 필드 | 포맷 | 바이트 | 설명 |
| - | - | - | - |
| index | H | 2 | 0부터 시작하는 조각 인덱스 |
| total | H | 2 | 전체 조각 수 |
| frame_payload_len | I | 4 | 재조립된 페이로드 길이 |
| Total |  | 8 |  |

#### 제어 플레인 데이터 헤더

| 데이터 헤더 필드 | 포맷 | 바이트 | 설명 |
| - | - | - | - |
| kind | B | 1 | 페이로드 종류(DATA_KIND_DRACO) |
| sequence | I | 4 | 프레임 시퀀스 번호 |
| timestamp_ns | Q | 8 | 나노초 단위 캡처 타임스탬프 |
| payload_len | I | 4 | 압축된 Draco 페이로드 크기 |
| content_type | B | 1 | 콘텐츠 유형 힌트(CONTENT_TYPE_DRACO) |
| Total |  | 18 |  |

| 응답 헤더 필드 | 포맷 | 바이트 | 설명 |
| - | - | - | - |
| kind | B | 1 | 응답 종류(RESPONSE_KIND_DECODED_AND_METRICS) |
| sequence | I | 4 | 프레임 시퀀스 번호 |
| timestamp_ns | Q | 8 | 캡처 타임스탬프 에코 |
| decoded_len | I | 4 | 디코드된 페이로드 길이 |
| metrics_len | I | 4 | JSON 메트릭 페이로드 길이 |
| decode_ms | H | 2 | 밀리초 단위 디코드 지연 |
| Total |  | 23 |  |

#### 열거형

| FrameType | 값 | 설명 |
| - | - | - |
| DATA | 0 | TCP 스트림에 다중화되는 프레임 종류 |
| ACK | 1 | TCP 스트림에 다중화되는 프레임 종류 |
| ERROR | 2 | TCP 스트림에 다중화되는 프레임 종류 |
| HEARTBEAT | 3 | TCP 스트림에 다중화되는 프레임 종류 |
| EOF | 4 | TCP 스트림에 다중화되는 프레임 종류 |
| CONTROL | 5 | TCP 스트림에 다중화되는 프레임 종류 |

| ControlCode | 값 | 설명 |
| - | - | - |
| ACK | 1 | 제어 메시지 코드 (SSOT 참조). |
| HEARTBEAT | 2 | 제어 메시지 코드 (SSOT 참조). |
| EOF | 3 | 제어 메시지 코드 (SSOT 참조). |
| ERROR | 4 | 제어 메시지 코드 (SSOT 참조). |

| ErrorCode | 값 | 설명 |
| - | - | - |
| NONE | 0 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| PROTOCOL_VIOLATION | 1 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| TIMEOUT | 2 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| INTERNAL_ERROR | 3 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |
| SHUTDOWN | 4 | 오류 코드 정의 (docs/contracts/control_plane_contract.md). |

#### 타이밍 및 조각 한계

| 상수 | 값 |
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
  INIT --> HANDSHAKING: on_connected() 호출
  HANDSHAKING --> STREAMING: on_first_data() / on_heartbeat()
  STREAMING --> DRAINING: on_eof_sent() / on_eof_received()
  DRAINING --> TERMINATED: on_ack() && pending 없음
  STREAMING --> FAILED: on_error() / 하트비트 타임아웃
  DRAINING --> FAILED: on_error()
  HANDSHAKING --> FAILED: on_error()
  TERMINATED --> [*]
  FAILED --> [*]
  STREAMING --> STREAMING: on_frame_sent() / ACK 대기
  DRAINING --> DRAINING: 남은 ACK 처리
```
<!-- AUTODOC:STATE_MACHINE:END -->

## Auto-Generated Telemetry 필드 Map
<!-- AUTODOC:TELEMETRY:BEGIN -->
| 필드 | 유형 / 제약 | 생성 위치 | 시점 | 비고 |
| - | - | - | - | - |
| metrics.ack_latency_ms.p50 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.ack_latency_ms.p95 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.ack_latency_ms.p99 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.frames.acked | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | ACK된 프레임 수 |
| metrics.frames.dropped | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 드롭된 프레임 수 |
| metrics.frames.sent | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 전송된 총 프레임 수 |
| metrics.frames.skipped | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 품질 필터로 건너뛴 프레임 수 |
| metrics.latency_ms.p50 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | PipelineStats에서 계산한 분위수 |
| metrics.latency_ms.p95 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.latency_ms.p99 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.queues.capture_max | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 최대 캡처 큐 깊이 |
| metrics.queues.decode_max | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 최대 디코드 큐 깊이 |
| metrics.queues.encode_max | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 최대 인코드 큐 깊이 |
| metrics.queues.pending | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 내보내기 시 대기 프레임 수(종료 시 0) |
| metrics.rtt_ms.p50 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.rtt_ms.p95 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.rtt_ms.p99 | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 |  |
| metrics.throughput_mbps.avg | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 총 전송 바이트와 경과 시간에서 집계 |
| metrics.throughput_mbps.peak | number (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:97 (Telemetry._normalize_metrics) | 메트릭 정규화 | 현재 익스포터에서 avg와 동일 |
| schema_doc | string (필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:171 (Telemetry.build) | 텔레메트리 출력 | 스키마 문서 경로 기준점 |
| schema_version | string (enum=1.0.0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:171 (Telemetry.build) | 텔레메트리 출력 | Telemetry.SCHEMA_VERSION 상수 |
| session.ended_at_ns | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | on_shutdown | 제어 플레인 완료 타임스탬프 |
| session.error_code | integer (min=0) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 실패 시 출력 | state == FAILED일 때 채움 |
| session.error_message | string | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 실패 시 출력 | 선택적 실패 컨텍스트 |
| session.fragment_size | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 세션 생성 | TX 조각 설정 |
| session.id | string (필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 세션 생성 | 역할/시간/PID에서 파생 |
| session.protocol | string (enum=legacy,binary; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 세션 생성 | 프레이밍 프로토콜 이름 |
| session.role | string (enum=client,server; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 세션 생성 | 텔레메트리에 전달된 CLI 역할 |
| session.socket_buffer_autotune | boolean | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 세션 생성 | CLI 소켓 버퍼 플래그 반영 |
| session.started_at_ns | integer (min=0; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | on_connected | 제어 플레인 타임스탬프 |
| session.state | string (enum=TERMINATED,FAILED; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | export | ControlPlane.state 값 |
| session.transport | string (enum=tcp,quic,udp_fec; 필수) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:71 (Telemetry._session_block) | 세션 생성 | 전송 인자 |
<!-- AUTODOC:TELEMETRY:END -->
