<!-- Path: docs/contracts/control_plane_contract.md -->

# Draco 스트리밍 제어 평면 계약서

본 문서는 `draco_roundtrip` 스트리밍 클라이언트와 서버가 공통으로 준수해야 하는
제어 채널(ACK/HEARTBEAT/EOF/ERROR) 프로토콜의 단일 진실 공급원(SSOT)이다.
모든 공개 함수와 로깅은 본 문서를 참조해야 하며, 규격을 변경할 경우 문서부터 갱신한다.

## 메시지 코드 정의

| 코드(hex) | 심볼 | 의미 | 페이로드 |
|-----------|------|------|-----------|
| `0x01` | `ACK` | 데이터 프레임 수신 확인 | 8바이트 unsigned sequence (big-endian) |
| `0x02` | `HEARTBEAT` | 연결의 liveness keep-alive | 옵션: 8바이트 monotonic timestamp(ns) |
| `0x03` | `EOF` | 송신 측에서 모든 프레임 전송 완료 | 없음 |
| `0x04` | `ERROR` | 비정상 종료 및 오류 보고 | 1바이트 오류 코드 + UTF-8 메시지 |

### 오류 코드 테이블

| 코드 | 식별자 | 설명 |
|------|--------|------|
| `0` | `NONE` | 오류 없음 (예약) |
| `1` | `PROTOCOL_VIOLATION` | 헤더 손상, 상태 위반 등 프로토콜 오류 |
| `2` | `TIMEOUT` | ACK/HEARTBEAT을 제시간에 받지 못함 |
| `3` | `INTERNAL_ERROR` | 디코더/인코더 등 내부 처리 실패 |
| `4` | `SHUTDOWN` | 운영자 혹은 애플리케이션에 의한 정상 중단 |

## 상태 머신

| 상태 | 설명 |
|------|------|
| `INIT` | TCP 연결 및 하위 프로토콜 협상 전 |
| `HANDSHAKING` | 프로토콜 매개변수 교환 및 첫 HEARTBEAT 교환 |
| `STREAMING` | 데이터 프레임 전송 및 ACK 수신 루프 |
| `DRAINING` | EOF 전송 후 잔여 ACK 및 대기 중 |
| `TERMINATED` | 정상 종료 (EOF ↔ ACK 교환 완료) |
| `FAILED` | ERROR 교환 또는 타임아웃으로 인한 종료 |

### 상태 전이 규칙

1. `INIT` → `HANDSHAKING`: 소켓 연결이 확인되면 전환. 첫 HEARTBEAT 또는 데이터 프레임 전까지 1초 제한.
2. `HANDSHAKING` → `STREAMING`: 첫 번째 데이터 프레임 또는 ACK 수신 시 전환.
3. `STREAMING` → `DRAINING`: 송신 측이 `EOF`를 보내면 즉시 전환, 수신 측은 EOF 로그 후 남은 ACK를 처리한다.
4. `DRAINING` → `TERMINATED`: 모든 pending frame에 대한 ACK가 수신되고 `pending=0` 상태가 되면 종료 로그와 함께 전환.
5. 어떤 상태든 `ERROR` 수신 또는 내부 오류 발생 시 `FAILED`로 전환하고 오류 코드를 로그 및 텔레메트리에 기록한다.
6. `FAILED` 상태에서는 더 이상의 메시지 송수신을 시도하지 않고 소켓을 정리한다.

## 타이밍 제약

- `ACK_TIMEOUT_S = 0.5`: 데이터 프레임 송신 후 500ms 내 ACK을 받지 못하면 재시도 또는 오류로 간주한다.
- `HEARTBEAT_INTERVAL_S = 2.0`: 정상 상태에서 2초마다 HEARTBEAT를 전송한다.
- `HEARTBEAT_LIVENESS_S = 6.0`: 이 간격 동안 HEARTBEAT를 받지 못하면 상대 노드가 죽은 것으로 판정하고 오류 코드 `TIMEOUT`을 전송한다.
- `CONTROL_POLL_INTERVAL_S = 0.05`: 제어 소켓 검사 주기. 클라이언트/서버 모두 동일 값 사용.

## 로깅 및 텔레메트리 요구 사항

1. 모든 `EOF` 송신/수신 이벤트는 `"EOF sent"` 또는 `"EOF received"` 로그를 포함해야 하며, 해당 시점의 `pending` 큐 상태를 함께 기록한다.
2. 세션 요약 텔레메트리는 `pending=0`을 강제하고, state가 `TERMINATED`인지 검증한다.
3. 오류 종료 시 텔레메트리에는 `state="FAILED"`와 오류 코드, 메시지를 포함하여 `telemetry_schema.json`을 통과해야 한다.
4. HEARTBEAT 지연이 `HEARTBEAT_LIVENESS_S`를 넘을 때는 즉시 오류로 승격하고 ERROR 메시지를 전송한다.

## 단편화(프래그먼트) 규칙

- `--tx-fragment-size`가 0보다 크면 송신자는 바이너리 프레임을 지정된 바이트 크기 이하로 조각낸다.
- 단편화된 각 조각은 동일한 시퀀스 번호를 공유하며, 이후 조각이 남아 있음을 나타내기 위해 헤더의 `more_fragments` 플래그를 1로 설정한다.
- MTU 안정성을 위해 조각 크기는 256 이상 1400 이하 범위로 제한한다. 범위를 벗어나면 초기 인수 검증 단계에서 오류를 보고한다.

## 호환성 원칙

- `--protocol legacy|binary` 플래그는 기존 동작을 유지하되, 바이너리 모드에서는 본 계약서의 헤더와 상태 머신을 **반드시** 따라야 한다.
- HEARTBEAT 주기와 오류 코드는 향후 확장을 위해 backwards compatible 해야 하므로, 새로운 메시지를 추가할 때는 코드 범위 `0x10` 이상을 사용한다.

