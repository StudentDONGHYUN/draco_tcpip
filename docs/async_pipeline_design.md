# 비동기 프레임 파이프라인 설계

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
   - 비동기 작업 실행기(ThreadPool/Boost::asio strand)를 사용해 Draco 인코딩을 수행한다.
   - 인코딩 결과는 압축 바이트 배열과 타임스탬프, 프레임 ID를 포함한다.
   - 성공 시 `Encode → Network` 큐로 이동하고, 실패 시 오류 이벤트 채널로 전달한다.

3. **네트워크 전송 스테이지**
   - `Encode → Network` 큐는 최대 인플라이트 프레임 수(`max_inflight`)에 따라 크기를 조절한다.
   - TCP 소켓은 논블로킹 모드 + 이벤트 루프로 감시하며, 준비된 프레임을 바이너리 프로토콜로 전송한다.
   - 송신 완료 후 RTT 측정을 위해 인플라이트 테이블에 `frame_id → (sent_ts, size)`를 기록한다.

4. **응답 처리 스테이지**
   - 별도 I/O 루프가 서버 응답을 수신하고 인플라이트 테이블을 갱신한다.
   - 디코딩된 PLY/포인트 데이터를 ROS 2 퍼블리셔에 전달하며, 필요 시 렌더 스레드로 바로 전달할 수 있도록 zero-copy 버퍼를 사용한다.

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

