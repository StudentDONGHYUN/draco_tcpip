# Streaming Roundtrip Runbook

_Last updated: 2025-02-14_

## Purpose
이 문서는 Draco 기반 스트리밍 파이프라인을 로컬에서 실행하거나 회귀 테스트, 네트워크 실험을 수행할 때 참고하는 절차서입니다. 테스트 부트스트랩 개선 사항(경로 충돌 방지)과 타입 체킹 정책(Pyright strict)을 반영했습니다.

## Environment Preparation
1. Python 3.11 이상의 가상환경을 생성합니다.
2. 리포지토리 루트에서 `pip install -e .`를 실행해 `draco_roundtrip` 패키지를 편집 가능한 형태로 설치합니다.
3. VS Code/Pyright 설정에서 다음 경로를 `python.analysis.extraPaths`에 추가합니다.
   - `${workspaceFolder}`
   - `${workspaceFolder}/ros2_ws/src`
4. Strict 타입 체킹을 위해 `pyright --level strict`를 실행하고, 경고가 발생하면 우선 해결합니다.

## Test Execution
- **단위/통합 테스트**: `pytest` (루트 `pytest.ini`가 `testpaths = tests`로 구성되어 ROS 2 패키지 테스트와 경로 충돌을 방지합니다.)
- **성능 게이트**: `pytest tests/perf/test_latency_gate.py` — 최신 텔레메트리(`artifacts/perf/client_latest.json`)를 기반으로 p95 지연 임계치를 검증합니다.
- **CI 동등성**: `pytest -m "not slow"` 등을 추가 필터로 사용하여 로컬에서 CI와 동일한 커버리지를 확보합니다.

## Network Simulation
1. `scripts/netem_profile.sh <profile>`로 손실/지연/재정렬 시나리오를 활성화합니다. `configs/netem.profiles.yaml`에 기본 프로파일이 정의되어 있습니다.
2. 스트리밍 서버는 `ros2 run draco_roundtrip stream_server --config configs/server.profile.yaml`, 클라이언트는 `ros2 run draco_roundtrip stream_client --config configs/client.profile.yaml`으로 실행합니다.
3. 테스트 종료 후 `scripts/netem_profile.sh clear`로 네트워크 설정을 복원합니다.

## Observability & Shutdown
- 스트리밍 노드는 구조화된 JSON 로그를 출력하며, 각 로그에 `frame_id`, `seq`, `stage`, `latency_ms`, `queue_depth`가 포함됩니다.
- 종료 시점에는 `pending=0`, `p50/p95/p99` 지연, 전송한 총 프레임 수, 누락된 프레임 수가 요약됩니다.
- 로그 수집은 `artifacts/perf/` 디렉터리와 `tests/perf/utils.py`에서 읽어들이는 텔레메트리 파일을 통해 확인할 수 있습니다.

## Failure Handling
- `ModuleNotFoundError: tests.perf` 발생 시 `pytest.ini`와 루트 `conftest.py`가 최신인지 확인하고, `PYTHONPATH`에 `${workspaceFolder}`가 최우선으로 등록되었는지 검증합니다.
- ROS 패키지 테스트와 충돌하는 경우 `pytest.ini`의 `testpaths = tests` 구성이 유지되는지 확인하고, 필요하면 `pytest --testmon`으로 변경된 테스트만 재실행합니다.

## Useful Commands
- `ruff check .`
- `pyright`
- `bandit -r ros2_ws/src/draco_roundtrip/draco_roundtrip`
- `pytest --maxfail=1 --disable-warnings`

모든 변경 사항을 적용한 후 `docs/reports/audit_log.md`에 회귀 결과와 해결된 이슈를 기록해 추적성을 유지하십시오.
