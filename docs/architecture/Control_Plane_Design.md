# TCP Control Plane Design (Detailed)

<!-- AUTODOC:TCP_CONTROL_SEQUENCE_DETAILED -->
<!-- AUTODOC:TCP_CONTROL_SEQUENCE_DETAILED:BEGIN -->
```mermaid
sequenceDiagram
    title Draco TCP/IP 라운드트립 — TCP 제어 플레인
    participant CLI as StreamClient
    participant SRV as StreamServer

    %% 제어 플레인 종류: ACK(0x01), HEARTBEAT(0x02), EOF(0x03), ERROR(0x04)
    %% 계약에 따라 데이터와 제어 채널을 분리합니다.

    rect rgb(245,245,245)
      CLI->>SRV: TCP 연결(데이터)
      CLI-->>SRV: (선택) TCP 연결(제어)
    end

    par 스트리밍
      CLI->>SRV: DATA 프레임(seq=1)  %% 데이터 채널
      SRV-->>CLI: ACK(seq=1)          %% 제어 채널
      Note right of CLI: in_flight ≤ max_inflight<br/>ACK가 슬롯 해제

      CLI->>SRV: DATA 프레임(seq=2)
      SRV-->>CLI: ACK(seq=2)
      CLI->>SRV: DATA 프레임(seq=3)
      SRV-->>CLI: ACK(seq=3)
    and 하트비트
      loop 유휴
        SRV-->>CLI: HEARTBEAT
      end
    end

    opt 오류 경로
      CLI->>SRV: DATA 프레임(seq=4)
      SRV-->>CLI: ERROR{code=TIMEOUT,msg="ACK overdue"}
      CLI-xSRV: 소켓 종료; state=FAILED
    end

    opt 정상 종료
      CLI-->>SRV: EOF
      SRV-->>CLI: EOF(pending=0 이후)
      CLI-xSRV: 소켓 종료; state=TERMINATED
    end
```
<!-- AUTODOC:TCP_CONTROL_SEQUENCE_DETAILED:END -->
