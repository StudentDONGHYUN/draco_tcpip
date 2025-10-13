# 성능 시험 계획
이 문서는 Draco Roundtrip의 p95 지연 목표를 강제하는 rosbag 기반 회귀 벤치마크를 정의합니다.
_마지막 업데이트: 2025-03-15_

**목차**
- [벤치마크 구성](#벤치마크-구성)
- [실행 절차](#실행-절차)
- [산출물](#산출물)
- [유지보수 지침](#유지보수-지침)

## 벤치마크 구성
| 항목 | 값 |
|------|----|
| 벤치마크 | `rosbag regression gate` |
| 데이터셋 | `sample_bag/pointcloud_latency.bag` |
| 임계값(p95) | 250 ms |
| 샘플 수 | 1 200 프레임 |

## 실행 절차
1. bag을 재생합니다.
   ```bash
   ros2 bag play sample_bag/pointcloud_latency.bag
   ```
2. 바이너리 프로토콜과 제한 큐를 활성화한 상태로 서버를 시작합니다.
3. 동일한 bag을 대상으로 클라이언트를 실행하고, 텔레메트리와 레이아웃 설정이 [구성 참조](../reference/Configuration_Reference.md)를 따른다고 확인합니다.
4. 다음 명령으로 지연 메트릭을 수집합니다.
   ```bash
   pytest tests/perf/test_latency_gate.py
   ```
5. 테스트 하네스는 캡처부터 ACK까지의 타임스탬프를 이용해 p50/p95/p99, RTT, ACK 지연을 계산하며, p95 ≥ 250 ms이면 실패로 간주합니다.

## 산출물
- `artifacts/perf/latest_latency.json`: [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)에 정의된 스키마와 일치하는 텔레메트리 JSON.
- `artifacts/perf/summary.txt`: 임계값 대비 분위수를 요약한 텍스트 보고서.

## 유지보수 지침
- 통계적으로 의미 있는 분위수를 위해 데이터셋당 최소 1 000 프레임을 유지합니다.
- 데이터셋 경로나 임계값을 변경할 경우 이 문서와 CI 스크립트(`scripts/ci/run_perf_gate.sh`)를 동시에 업데이트합니다.
- 전송 관련 플래그(`--transport`, `--tx-fragment-size`, `--socket-buffer-autotune`)가 변경되면 벤치마크를 다시 검증합니다.
