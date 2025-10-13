<!-- Path: docs/tests/perf/latency_benchmark_plan.md -->

---
benchmark: "rosbag regression gate"
dataset: "sample_bag/pointcloud_latency.bag"
threshold_ms:
  p95: 250
sample_count: 1200
---

# Draco p95 왕복 지연 회귀 벤치마크 계획

본 계획은 `tests/perf/test_latency_gate.py`에서 재사용되며, rosbag 재생 기반
회귀 테스트를 통해 p95 지연이 250ms 미만임을 보장한다.

## 절차

1. `ros2 bag play sample_bag/pointcloud_latency.bag`으로 입력 데이터를 재생한다.
2. `stream_server`는 바이너리 프로토콜과 제어 채널을 활용해 프레임을 디코드하고 ACK을 전송한다.
3. `stream_client`는 동일한 bag을 스트리밍하며 텔레메트리와 로그를 수집한다.
4. 테스트 하니스는 캡처↔ACK 타임스탬프를 기반으로 p50/p95/p99, RTT, ACK 지연 분포를 계산한다.
5. 계산된 p95 값이 250ms 이상이면 테스트는 실패한다.

## 산출물

- `artifacts/perf/latest_latency.json`: 텔레메트리 JSON (스키마 준수).
- `artifacts/perf/summary.txt`: 핵심 통계 및 임계값 비교.

## 유지보수 지침

- 표본 수(`sample_count`)는 최소 1,000 프레임 이상을 유지한다.
- 새로운 데이터셋으로 교체할 경우 front-matter의 `dataset` 경로와 임계값을 동시에 갱신한다.
- CI 파이프라인(`scripts/ci/run_perf_gate.sh`) 변경 시에도 본 문서의 절차 섹션을 최신 상태로 유지한다.
