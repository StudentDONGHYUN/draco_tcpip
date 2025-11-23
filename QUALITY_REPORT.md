# Quality Report Format

품질 보고서는 성능·정확도 회귀를 동일한 스키마로 기록해 **추적성·재현성·자동화**를 확보하도록 설계되었습니다. `--quality-report-dir`를 켜면 클라이언트는 디코드된 각 프레임에 대해 JSONL 한 줄을 기록하며, 매 줄은 완전한 독립 객체입니다. 이 포맷은 변경 사항이 생기면 아래 `version`을 올리고, [`docs/reports/results_template.md`](docs/reports/results_template.md)에서 결과 요약과 함께 참조하도록 합니다.

## 스키마 (frame-level JSON object)
다음 JSON 구조가 한 줄로 기록됩니다. 필드는 **삭제 불가**이며, 새 필드가 추가될 때는 하위 호환을 유지해야 합니다.

```json
{
  "version": 1,
  "sequence": 12,
  "frame": "demo_run_001.decoded.ply",
  "timestamp_ns": 1683923432456,
  "server_metrics": { ... },
  "client_metrics": { ... },
  "original_metrics": { ... },
  "quality": {
    "point_count_abs": 0,
    "centroid_l2": 0.0001,
    "scale_diag_rel": 0.0003,
    "avg_nn_rel": 0.0012,
    "chamfer_est": 0.0021
  },
  "thresholds": { ... },
  "breaches": {
    "centroid_l2": false,
    "avg_nn_rel": true
  }
}
```

필드 설명과 품질 특성 매핑은 다음과 같습니다.

| 필드 | 내용 | 품질 특성 | 필수 검증 |
| --- | --- | --- | --- |
| `sequence` | 프레임 증가 ID(0부터). 로그/ROS 토픽과 교차 검증 가능해야 함. | **추적성, 재현성** | 단조 증가 확인, 누락/중복 없음 |
| `frame` | 파일 이름/식별자. `--prefix`와 시퀀스 기반으로 결정. | **검증 용이성** | 파일 존재 여부, 접두어 일치 |
| `timestamp_ns` | 로컬 모노토닉 시각. 서버/클라이언트 지연 계산에 사용. | **성능/관측 가능성** | 비음수, 단조 증가 |
| `server_metrics` | 서버가 보고한 디코드 지연·압축률·점수. | **성능, 신뢰성** | 스키마 키 존재 여부, 단위 확인 |
| `client_metrics` | 수신된 바이트 기반 로컬 측정치. | **무결성** | 필수 키(`rx_bytes`, `decode_ms` 등) 유효성 |
| `original_metrics` | 압축 전 포인트클라우드 측정치 캐시. | **정확도** | 포인트 수 > 0, 정상화 범위 확인 |
| `quality` | 절대·상대 오차, 선택적 Chamfer 추정치. | **정확도, 회귀 탐지** | 0 이상, NaN/inf 없음 |
| `thresholds` | `--quality-thresholds` 입력을 에코. | **명세 준수** | 입력과 byte-for-byte 일치 |
| `breaches` | 임계 초과 여부를 부울로 표시. | **품질 게이트** | `quality` 키와 동일 키 집합 |

### 스키마 버전 및 호환성 가이드
- `version`: 현재 `1`. 필드 추가 시 숫자를 올리고, 이전 파서가 최소한 `quality`/`breaches` 핵심 키를 읽을 수 있도록 유지합니다.
- **소수점 표현**: 모든 부동소수 필드는 소수점 6자리 이하로 제한하여 CSV/데이터베이스 삽입 시 정밀도 손실을 피합니다.
- **단위**: 지연은 ms, 거리/스케일은 미터/비율을 사용합니다. 단위를 변경할 경우 `version`을 증가시키고, `thresholds` 예제도 업데이트합니다.

보고서는 `<quality_report_dir>/<prefix>_quality.jsonl`에 저장됩니다. **테스트/운영 모두 동일한 포맷**을 사용하므로, 결과를 회귀 대시보드나 알림 파이프라인으로 바로 투입할 수 있습니다. `jq`로 임계 초과 프레임을 필터링하는 예시는 다음과 같습니다.

```bash
jq 'select(.breaches | to_entries | any(.value == true))' artifacts/quality/demo_run_quality.jsonl
```

### 수집·품질 게이트 절차
1. **수집**: 실행 스크립트 또는 런치에서 `--quality-report-dir`를 설정하고, 실행 메타데이터는 [`docs/reports/results_template.md`](docs/reports/results_template.md)의 매니페스트 섹션을 채웁니다.
2. **검증**: CI에서는 `jq`/`python -m json.tool`로 JSON 유효성을 확인하고, `breaches`가 존재하면 실패로 처리합니다.
3. **보관**: `artifacts/`, `metrics/`, `ros_logs/`와 함께 동일 run_id 디렉터리에 배치하여 추적성(요구사항→테스트→결과)을 유지합니다.
4. **분석**: 회귀 대시보드는 `version`과 `prefix`를 인덱스로 삼아 크로스런 비교를 수행하고, 단위 변경 시 버전으로 분기합니다.

### 품질 속성 대비 체크리스트
- **정확도**: `quality` 값의 허용 오차를 `thresholds`로 명시하고, 지표 이름과 단위를 문서화한다.
- **신뢰성**: `breaches` 플래그로 즉시 실패 여부를 결정하고, 누락/중복 시퀀스가 없는지 CI에서 검증한다.
- **관측 가능성**: `server_metrics`/`client_metrics`에 타임스탬프와 바이트 크기를 기록해 지연·손실 분석을 가능하게 한다.
- **이식성**: JSONL 포맷은 스트리밍/오프라인 파이프라인 모두에서 동일하게 소비할 수 있으며, 쉘 필터링과 데이터베이스 적재를 모두 지원한다.
- **보안성**: JSONL에 비밀 정보가 포함되지 않도록 하고, 외부 공유 시에는 경로·호스트를 비식별 처리한다.
- **테스트 가능성**: `version`별 스키마 유효성 테스트를 추가하고, `quality`/`breaches` 키 집합이 변경되면 회귀 테스트를 갱신한다.
- **유지보수성**: 새 필드를 추가할 때는 [`Quality_Attributes_Catalog`](docs/reference/Quality_Attributes_Catalog.md) 표에 증거와 영향을 기록하고, 파서/대시보드 업데이트 절차를 링크한다.
