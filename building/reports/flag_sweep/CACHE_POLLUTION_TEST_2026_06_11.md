# Flag-Sweep Cache Pollution Test — 2026-06-11

Scope: B-1 acceptance for T13 cache-key hardening.

## Code Change

`scripts/backtest_flag_sweep.py` cache schema was upgraded to `flag-sweep-cache-v2`.
The cache key now includes:

- git commit (`git rev-parse HEAD`)
- production code hash
- config content hash
- data manifest id
- variant
- backtest window
- enabled cost set

## Runtime Check

Command shape:

```bash
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python - <<'PY'
# import scripts/backtest_flag_sweep.py
# create a temp cache with the current baseline key
# verify same-key hit, config-polluted miss, commit-polluted miss
PY
```

Result:

```json
{
  "cache_schema": "flag-sweep-cache-v2",
  "config_parameter_change_hit": false,
  "config_parameter_change_key_changed": true,
  "current_key_prefix": "aa8734f61442d6d8",
  "git_commit_change_hit": false,
  "git_commit_change_key_changed": true,
  "real_cache_schema_before_v2": null,
  "real_cache_would_hit_current_v2": false,
  "same_key_hit": true,
  "variant": "baseline"
}
```

## Interpretation

- Same key hits the temp cache, proving the positive cache path still works.
- In-memory config pollution (`status_thresholds.WATCH += 1`) changes the key and returns cache miss.
- Commit pollution was exercised by changing the `_git_commit()` return value to a different SHA-shaped value; this changes the key and returns cache miss.
- Existing `baseline.json` predates the v2 schema (`real_cache_schema_before_v2 = null`), so the next real `--reuse-if-fresh` run will miss and recompute rather than reuse an under-specified v1/no-schema artifact.

No full-window backtest was launched for this pollution check; the test validates the exact cache-hit decision point before `run_full_backtest(...)` is called.
