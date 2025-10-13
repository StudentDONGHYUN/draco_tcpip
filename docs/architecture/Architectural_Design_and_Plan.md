# 아키텍처 설계 및 지연 시간 계획
이 문서는 Draco Roundtrip의 비동기 스트리밍 파이프라인 구조, 하이브리드 제어 플레인 진화 방향, 그리고 네트워크 지연 시간 단축 로드맵을 정리합니다.
_마지막 업데이트: 2025-03-15_

**목차**
- [아키텍처 목표](#아키텍처-목표)
- [엔드투엔드 파이프라인 설계](#엔드투엔드-파이프라인-설계)
- [제어 플레인과 제한 큐](#제어-플레인과-제한-큐)
- [지연 시간 감소 전략](#지연-시간-감소-전략)
- [로드맵과 완료 정의](#로드맵과-완료-정의)
- [관측 가능성과 텔레메트리](#관측-가능성과-텔레메트리)

## 아키텍처 목표
- 캡처, 인코딩, 전송, 디코딩, 퍼블리시 단계를 비동기 워커에서 겹쳐 실행해 엔드투엔드 지연 시간을 최소화합니다.
- 손실 링크에서도 `MSG_EOF`, `MSG_ACK`, 하트비트 교환을 명시적으로 수행해 결정적 종료를 보장합니다.
- 모든 큐를 유한 크기로 유지(`maxsize`, 제한된 in-flight 윈도)하여 메모리 사용이 폭증하지 않도록 합니다.
- 현재 Python ROS 2 노드와의 호환성을 유지하면서 rclcpp/Boost.Asio로의 이행 경로를 준비합니다.

## 엔드투엔드 파이프라인 설계
```
[Capture Thread] --bounded--> [Encode Worker Pool] --bounded--> [TX Loop]
      │                                                         │
      │<--backpressure------------------------------------------│
      ▼                                                         ▼
[Network Transport] <== control/data ==> [RX Pump] --bounded--> [Decode Pool] --bounded--> [Publish Thread]
```
- **캡처 단계**: ROS 2 토픽 또는 파일 시스템 스풀러에서 구독한 프레임 핸들(메타데이터 + 페이로드 포인터)을 제한 큐(기본 4, 최대 16까지 설정 가능)에 적재합니다. 큐가 가득 차면 가장 오래된 프레임을 버리거나 공간이 생길 때까지 대기합니다.
- **인코드 단계**: 스레드 풀 혹은 `asyncio.to_thread` 워커가 Draco 인코더 래퍼를 호출하고, 결과에 시퀀스 ID·타임스탬프·인코딩 시간을 태깅합니다. 실패 시 구조화된 `ERROR` 메시지를 발생시킵니다.
- **전송 단계**: TX 루프는 논블로킹 소켓을 사용하며 시퀀스별 전송 시간을 기록하고 `max_inflight` 윈도를 준수합니다. 페이로드는 바이너리 프레이밍 헤더(kind `0x10`, Draco 콘텐츠)와 선택적 분할(`--tx-fragment-size`로 제어)을 사용합니다.
- **RX 펌프 및 디코드 단계**: 전용 리더가 제어/데이터 채널을 처리하고 ACK 시 in-flight 테이블을 갱신하며, 디코드된 페이로드를 제한된 디코드 큐로 전달합니다. `next_seq` 기반 재정렬 버퍼가 퍼블리시 순서를 보존합니다.
- **퍼블리시 단계**: 디코드된 포인트 클라우드를 ROS 토픽으로 발행하고, [구성 참조](../reference/Configuration_Reference.md)에 정의된 레이아웃 프로파일에 따라 아티팩트를 선택적으로 저장합니다.
- **공유 메모리**: 선택적 제로카피 캡처 경로는 전송 실패 시 공유 메모리 세그먼트를 정리하여 자원 사용을 제한합니다.

## 제어 플레인과 제한 큐
- **메시지 코드**(`0x01` ACK, `0x02` HEARTBEAT, `0x03` EOF, `0x04` ERROR)는 [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)의 계약을 따릅니다.
- **상태 기계**: `INIT → HANDSHAKING → STREAMING → DRAINING → TERMINATED` 흐름을 따르며, 실패 시 `FAILED`로 이탈합니다. EOF 전이는 `pending=0` 조건이 충족되어야 완료됩니다.
- **하트비트 정책**: 2 초마다 하트비트를 전송하고 6 초간 응답이 없으면 타임아웃으로 간주합니다. 누락된 하트비트는 `TIMEOUT` 코드를 동반한 `ERROR`를 발생시켜 큐를 비웁니다.
- **윈도 제어**: RTT EMA를 관측하는 적응형 윈도 컨트롤러가 값을 `--ack-timeout-min`과 `--ack-timeout-max` 사이로 조정합니다. 모든 경계에서 `asyncio.Queue(maxsize=n)`을 사용하여 명시적인 일시정지/재개 신호를 제공합니다.
- **프래그먼테이션**: `--tx-fragment-size`가 0보다 크면 TX 루프가 `more_fragments` 플래그를 포함한 MTU 안전 조각(256–1400 B)을 전송하며, 수신 측은 조각을 재조립한 뒤 ACK를 발송합니다.

## 지연 시간 감소 전략
1. **파이프라인 병렬화**: 비동기 큐와 백프레셔를 활용해 캡처/인코드/전송을 겹쳐 실행하고 Draco 인코딩으로 인해 캡처가 지연되지 않도록 합니다.
2. **제로카피 경로**: 파일 시스템 스풀 오버헤드를 피하기 위해 대여 메시지 또는 공유 메모리를 우선 사용하고, 전송 실패 시 자동으로 정리합니다.
3. **바이너리 프로토콜**: 헤더 크기와 시스템 콜을 최소화하기 위해 기본값을 `--protocol=binary`로 유지합니다. 제어/데이터 채널은 소켓을 공유하지만 주소 처리는 독립적으로 다룹니다.
4. **전송 튜닝**: 소켓 버퍼 자동 튜닝과 페이로드 분할 옵션을 활성화합니다. 향후 단계에서는 `--transport` 플래그 아래에서 QUIC/UDP-FEC 실험을 진행합니다.
5. **C++ 전환**: 핵심 노드를 rclcpp + Boost.Asio로 이전하여 Python GIL 병목을 제거하고, 얇은 래퍼를 통해 CLI 호환성을 유지합니다.
6. **벤치마크**: [성능 시험 계획](../development/Performance_Test_Plan.md)에 설명된 rosbag 기반 벤치마크로 개선 효과를 검증합니다.

## 로드맵과 완료 정의
| 단계 | 중점 | 완료 기준 |
|------|------|-----------|
| 0 – 안정화 | EOF/ACK/하트비트 핸드셰이크, 제한 큐, 결정적 종료 요약 | 로그에 `EOF sent/received`가 나타나고 텔레메트리에 `pending=0`이 보고되며 제한 큐 계측이 병합됨 |
| 1 – 성능 | 적응형 윈도, 바이너리 프로토콜, MTU 안전 분할, 네트워크 자동 튜닝 | `--adaptive-window`, `--tx-fragment-size`, `--socket-buffer-autotune` 플래그가 연결되고, p95 지연이 250 ms 미만인 벤치마크 통과 |
| 2 – 전송 실험 | QUIC/UDP-FEC 프로토타입, 우선순위 큐, 제로카피 개선 | 실험적 전송이 `--transport`로 보호되고 공유 메모리 정리가 검증됨 |
| 3 – 미래 개선 | rclcpp/Asio 포트, 인프로세스 Draco 통합, Python 호환 계층 | C++ 노드가 기능 동일성을 확보하고 Python 도구는 통합 프로토콜 어댑터를 통해 상호 작용 |

미해결 항목으로는 QUIC/UDP-FEC 평가, 적응형 비트레이트 제어기, 저지연 커널 튜닝의 자동 배포가 남아 있습니다. 각 작업은 [개발 프로세스](../development/Development_Process.md)에 기록합니다.

## 시퀀스 다이어그램
다음 다이어그램은 제한 큐, ACK 기반 흐름 제어, 제어/데이터 채널 분리를 포함한 최신 하이브리드 파이프라인을 설명합니다.

[비동기 파이프라인 설계](../designs/async_pipeline_design.md), [제어 플레인 계약](../contracts/control_plane_contract.md), [코드베이스 개요](../references/codebase_overview.md)도 참고하십시오.

### 자동 생성 시퀀스

<!-- AUTODOC:E2E_SEQUENCE -->
<!-- AUTODOC:E2E_SEQUENCE:BEGIN -->
```mermaid
sequenceDiagram
    title Draco TCP/IP 라운드트립 — 엔드투엔드 데이터 흐름
    participant U as 사용자/CLI
    participant BAG as ros2 bag play (프로세스)
    participant CLI as StreamClient (stream_client.py)
    participant ENC as Draco 인코더 (프로세스)
    participant SRV as StreamServer (stream_server.py)
    participant DEC as Draco 디코더 (프로세스)
    participant ROS as ROS 2 토픽(/stream_pair/decoded)

    %% 데이터 채널은 바이너리 프레이밍을 사용하며, 제어 채널은 ACK/HEARTBEAT/EOF를 운반합니다.
    %% 큐는 모두 제한되어 있고 TX 경로는 max_inflight를 준수합니다.

    U->>SRV: 서버 시작(리스닝)
    U->>CLI: 클라이언트 시작

    BAG-->>CLI: PointCloud2 게시(캡처)
    Note right of CLI: 캡처 큐(제한)

    CLI->>ENC: PLY → Draco(.drc) 인코딩
    Note right of ENC: 외부 프로세스 호출

    ENC-->>CLI: 인코딩된 바이트
    CLI->>SRV: TCP로 프레이밍된 DATA 전송(바이너리 프로토콜)
    Note right of CLI: 네트워크 큐(제한)
max_inflight를 갖는 TX 루프

    SRV-->>CLI: 제어 채널 ACK(seq)
    Note right of CLI: in_flight -= 1

    SRV->>DEC: Draco → PLY 디코딩
    Note right of DEC: 외부 프로세스 호출

    DEC-->>SRV: 디코드된 클라우드(PLY/PCD)
    SRV-->>ROS: 디코드된 클라우드 게시

    SRV-->>CLI: (선택) 프레임별 지표/요약

    %% 정상 종료
    CLI-->>SRV: EOF(제어 채널)
    SRV-->>CLI: EOF(pending=0 이후)
    SRV-xROS: 세션 종료
    CLI-xBAG: 캡처 종료 및 세션 종료
```
<!-- AUTODOC:E2E_SEQUENCE:END -->
