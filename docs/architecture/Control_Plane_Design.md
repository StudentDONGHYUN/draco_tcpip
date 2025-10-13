# TCP Control Plane Design (Detailed)

새로운 v2 설계에서는 데이터와 제어 프레임이 모두 **단일 TCP 연결** 위에서
`FrameType`(DATA/ACK/HEARTBEAT/EOF/ERROR) 값으로 다중화된다. 기존의 제어용
보조 포트는 더 이상 열리지 않으며, 클라이언트와 서버는 동일한 소켓을 통해
순차적으로 프레임을 교환한다. 헤더는 `magic=b"DRC0"`, `version=2`를 사용하며
타임스탬프·콘텐츠 타입을 직접 포함한다.

## 핵심 변경 요약 (v1 → v2)
- **단일 헤더**: `FrameHeader`가 데이터 메타데이터(타임스탬프, 콘텐츠 타입)를
  직접 포함하여 `DataHeader`를 대체한다. 레거시 클라이언트를 위해 `--legacy-mode`
  가 활성화된 경우에만 `magic=b"DRTC"`, `version=1` 헤더를 수락한다.
- **소켓 하나로 제어/데이터 다중화**: `FrameType`과 `FLAG_FRAGMENTED`/`FLAG_MORE_FRAGMENTS`
  플래그가 동일한 바이트 스트림에서 논리적 역할을 구분한다. `--control-port`
  는 경고만 출력하고 실제 소켓을 개설하지 않는다.
- **프래그먼트 GC**: 서버는 `FragmentBuffer`를 사용해 조각 상태를 추적한다.
  항목은 300 초 동안 유휴 상태이면 제거되며 총 버퍼가 128 MiB를 초과하면 가장
  오래된 항목부터 축출된다. 정리 작업은 60 초마다 실행된다.
- **텍스트 프로토콜 보호**: `MAX_TEXT_NAME_LEN=4096`, `MAX_TEXT_PAYLOAD_LEN=104 857 600`
  을 초과하는 요청은 즉시 거절하고 연결을 닫는다. 로그에는 보안 경고와 드롭
  카운터가 기록된다.

## 헤더 레이아웃
- **바이너리(v2)**: `magic(4) | version(1) | flags(1) | sequence(4) | name_len(2)
  | payload_len(4) | timestamp_ns(8) | content_type(2)` → 총 26바이트.
- **프래그먼트 메타데이터**: `index(2) | total(2) | frame_payload_len(4)` → 8바이트.
- **레거시(v1)**: 타임스탬프와 콘텐츠 타입 없이 16바이트. 레거시 모드에서만 허용된다.

## 운영 시 주의 사항
- `FrameType.HEARTBEAT`는 2 초마다 전송하고 6 초 이내에 응답이 없으면
  `FrameType.ERROR`(`TIMEOUT`)로 세션을 종료한다.
- 클라이언트 연결이 닫히면 서버는 해당 세션의 프래그먼트 상태를 즉시 정리해
  메모리 누수를 방지한다.
- 텍스트 프로토콜을 사용할 때는 제한값을 넘는 입력을 사전에 필터링하고,
  가능하면 바이너리 프로토콜로 마이그레이션한다.

## 관련 구현 파일
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py`
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py`
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py`
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py`

<!-- AUTODOC:TCP_CONTROL_SEQUENCE_DETAILED -->
<!-- AUTODOC:TCP_CONTROL_SEQUENCE_DETAILED:BEGIN -->
```mermaid
sequenceDiagram
    title Draco TCP/IP 라운드트립 — TCP 제어 플레인
    participant CLI as StreamClient
    participant SRV as StreamServer

    %% FrameType: DATA(0), ACK(1), ERROR(2), HEARTBEAT(3), EOF(4)
    %% 모든 프레임이 동일한 소켓을 공유한다.

    rect rgb(245,245,245)
      CLI->>SRV: TCP 연결(단일 채널)
    end

    par 스트리밍
      CLI->>SRV: DATA 프레임(seq=1)
      SRV-->>CLI: ACK 프레임(seq=1)
      Note right of CLI: in_flight ≤ max_inflight<br/>ACK가 슬롯 해제

      CLI->>SRV: DATA 프레임(seq=2)
      SRV-->>CLI: ACK 프레임(seq=2)
      CLI->>SRV: DATA 프레임(seq=3)
      SRV-->>CLI: ACK 프레임(seq=3)
    and 하트비트
      loop 유휴
        SRV-->>CLI: HEARTBEAT 프레임
      end
    end

    opt 오류 경로
      CLI->>SRV: DATA 프레임(seq=4)
      SRV-->>CLI: ERROR 프레임(code=TIMEOUT,msg="ACK overdue")
      CLI-xSRV: 소켓 종료; state=FAILED
    end

    opt 정상 종료
      CLI-->>SRV: EOF 프레임
      SRV-->>CLI: EOF 프레임(pending=0 이후)
      CLI-xSRV: 소켓 종료; state=TERMINATED
    end
```
<!-- AUTODOC:TCP_CONTROL_SEQUENCE_DETAILED:END -->
