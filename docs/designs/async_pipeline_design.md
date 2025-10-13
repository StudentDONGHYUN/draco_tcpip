<!-- Path: docs/designs/async_pipeline_design.md -->

# 비동기 프레임 파이프라인 설계

_Last updated: 2025-02-14_

## Changelog
- 2025-02-14: 테스트 경로 부트스트랩 및 Pyright 연동 지침을 문서에 반영했습니다.

## Type-Checking, Packaging & IDE Integration
- 워크스페이스 루트의 `conftest.py`를 통해 로컬 테스트 헬퍼가 항상 우선적으로 로드되므로, 에디터의 `PYTHONPATH`에도 동일한 순서를 유지합니다.
- Pyright `strict` 모드를 사용할 때 `tests` 네임스페이스 충돌을 피하기 위해 `pytest.ini`의 `testpaths = tests` 구성을 그대로 적용하십시오.
- Editable install 이후에는 `ros2_ws/src`가 자동으로 경로에 포함되지 않을 수 있으므로, VS Code의 `python.analysis.extraPaths`에 명시적으로 추가합니다.

이 문서는 스트리밍 클라이언트/서버가 공유하는 비동기 파이프라인의 목표와 구성 요소를 설명합니다. 실제 구현은 `draco_roundtrip/nodes/stream_client.py`와 `stream_server.py`에서 확인할 수 있으며, 전체 아키텍처 개요는 `../references/codebase_overview.md`를 참고하세요.

## 목표
- 포인트클라우드 프레임 캡처, Draco 인코딩, 네트워크 전송, 서버 디코딩 단계를 동시에 진행해 프레임 왕복 지연을 최소화한다.
- 역압(backpressure)을 명시적으로 처리하여 과도한 프레임 버퍼링과 ROS 2 큐 오버플로를 방지한다.
- ROS 2(Python)와 향후 C++ 포팅 버전 모두에서 적용 가능한 공통 파이프라인 패턴을 정의한다.

## 구성 요소
1. **캡처 스테이지**
   - ROS 2 구독자가 대여 메시지(loaned message) 또는 zero-copy 공유 메모리를 이용해 프레임을 획득한다.
   - 캡처 스레드/코루틴은 `Capture → Encode` 큐에 프레임 핸들(메모리 참조 + 메타데이터)을 넣는다.
   - 큐 용량은 기본 4, 최대 16 프레임. 큐가 가득 차면 ROS 2 QoS 정책(Keep Last)과 연동해 가장 오래된 프레임을 폐기하거나 캡처를 일시 중단한다.
2. **인코딩 스테이지**
   - 비동기 작업 실행기(ThreadPool/Boost.Asio strand)를 사용해 Draco 인코딩을 수행한다.
   - 인코딩 결과는 압축 바이트 배열과 타임스탬프, 프레임 ID를 포함한다.
   - 성공 시 `Encode → Network` 큐로 이동하고, 실패 시 오류 이벤트 채널로 전달한다.
3. **네트워크 전송 스테이지**
   - `Encode → Network` 큐는 최대 인플라이트 프레임 수(`max_inflight`)에 따라 크기를 조절한다.
   - TCP 소켓은 논블로킹 모드 + 이벤트 루프로 감시하며, 준비된 프레임을 바이너리 프로토콜로 전송한다.
   - 송신 페이로드는 ``DataHeader``(kind=`0x10`, content_type=`DRACO`)와 순수 Draco 바이트로 구성된다. 헤더에는 프레임 시퀀스, 캡처 타임스탬프(ns), 압축 길이가 포함되어 서버가 디코더 메트릭을 계산할 수 있다.
   - 송신 완료 후 RTT 측정을 위해 인플라이트 테이블에 `frame_id → (sent_ts, size, encode_ms)`를 기록한다.
4. **응답 처리 스테이지**
   - 별도 I/O 루프가 서버 응답을 수신하고 인플라이트 테이블을 갱신한다.
   - 서버 응답은 ``ResponseHeader``(kind=`0x21`) + 디코딩된 포인트클라우드(Ply/PCD) + JSON 메트릭 블록(프레임 통계, 디코더 지연)을 단일 페이로드로 묶어 전송한다.
   - 클라이언트는 헤더를 해석해 디코딩된 바이트와 메트릭 JSON을 분리하고, `draco_roundtrip.analysis.pointcloud_metrics`를 통해 원본 클라우드에 대한 품질 지표를 계산한다.
   - per-frame 품질 요약은 JSONL(`quality_report_dir/…/quality.jsonl`)로 기록되며 임계치 초과 시 텔레메트리에 WARN 이벤트가 남는다.
5. **역압 및 흐름 제어**
   - 인플라이트 테이블이 임계치에 도달하면 캡처 스테이지에 `PAUSE_CAPTURE` 신호를 보낸다.
   - 서버에서 오류 또는 혼잡 신호를 보내면 `max_inflight`와 인코더 비트레이트를 조정하는 적응형 컨트롤러가 동작한다.

## 시퀀스 다이어그램(텍스트)
```
CaptureThread -> EncodePool : enqueue(frame_handle)
EncodeWorker -> NetworkLoop : enqueue(encoded_frame)
NetworkLoop -> Server : SEND frame_id,payload
Server -> NetworkLoop : ACK frame_id, decoded_bytes
NetworkLoop -> InflightTable : mark_complete(frame_id)
NetworkLoop -> ROSPublisher : publish(decoded_bytes)
NetworkLoop -> CaptureThread : (optional) resume_capture
```

## 장애 처리
- 인코딩 실패 시 캡처 스테이지가 프레임을 폐기하고 다음 프레임을 계속 처리한다.
- 네트워크 오류 또는 타임아웃 시 모든 큐를 플러시하고 서버 재연결 절차를 시작한다.
- 역압 신호는 타임아웃 기반으로 자동 해제되어 영구 정지가 발생하지 않도록 한다.

## 성능 측정 포인트
- 각 큐 투입/배출 시 타임스탬프를 기록하여 스테이지별 대기 시간을 계산한다.
- 인플라이트 테이블에서 프레임별 RTT, 평균 처리량(Mbps)을 계산해 로그 및 텔레메트리에 노출한다.
- 큐 길이, 역압 발생 횟수, 프레임 드랍 수를 Prometheus/ROS 2 통계 메시지로 내보낸다.

## 구현 가이드
- Python 버전: `asyncio` 기반 I/O 루프 + `asyncio.Queue`와 `asyncio.to_thread` 조합.
- C++ 버전: `rclcpp::executors::MultiThreadedExecutor`와 Boost.Asio `io_context`를 결합해 비동기 소켓과 작업 큐를 관리한다.
- 공유 메모리: `ros2_shm` 또는 CycloneDDS loaned message API를 활용해 복사 없는 전달을 구현한다.

## 현 구현과의 연결 고리
- `draco_roundtrip/nodes/stream_client.py`는 위 설계를 바탕으로 `FrameSender`, `WindowController`, `TelemetryRecorder` 클래스를 구성해 인플라이트 제어와 텔레메트리를 수집한다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py†L1-L222】
- `draco_roundtrip/nodes/stream_server.py`는 `DecodeJob`/`PipelineResult` 구조체와 `StageStats`를 사용해 디코딩 및 응답 단계를 계측한다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py†L1-L160】
- 설계에서 제안한 로그 포맷과 큐 구조는 `../guides/HOWTO.md`와 `../guides/logging_guidelines.md`에 반영되어 있으며, 적응형 윈도우 제어 정책은 `../plans/network_latency_reduction_plan.md`와 연동됩니다.

향후 C++ 포팅이나 전송 계층 실험 시 본 설계를 기준으로 변경 사항을 기록하고, 관련 체크리스트(`../checklists/hybrid_architecture_checklist.md`)를 함께 업데이트하세요.
