# Quality Report Format

The streaming client writes a JSONL report for every decoded frame when `--quality-report-dir` is enabled.
Each line is an independent JSON object with the following schema:

```json
{
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

* `server_metrics` contains the metrics payload returned by `stream_server` (decoded cloud statistics, decode latency, compression ratio).
* `client_metrics` is computed locally on the decoded bytes received from the server.
* `original_metrics` caches the measurements of the captured cloud prior to compression.
* `quality` summarises absolute / relative error terms and the optional sampled Chamfer estimate computed by `draco_roundtrip.analysis.pointcloud_metrics`.
* `thresholds` mirrors the JSON passed via `--quality-thresholds`; `breaches` flags entries that exceeded the limit.

The report file lives under `<quality_report_dir>/<prefix>_quality.jsonl`. Tools such as `jq` can be used to filter frames with non-zero `breaches`:

```bash
jq 'select(.breaches | to_entries | any(.value == true))' artifacts/quality/demo_run_quality.jsonl
```

This format is stable across streaming runs and can be fed into regression dashboards or alerting pipelines.
