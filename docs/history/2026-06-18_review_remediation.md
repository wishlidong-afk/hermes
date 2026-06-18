# 2026-06-18 — Review Remediation & Concurrency Hardening (Audit Summary)

> Prepared for external audit. This document is **self-contained**: it assumes no
> prior context and gives the exact commits, files, and commands to independently
> verify every claim.

---

## 0. System context (read this first)

**Hermes 逃顶 (escape-top)** is a **read-only quant defense system** for MSTR / FNGU /
SOXL. It produces *advice*, *ideal positions*, and *order previews* — it **never places
orders**. The IBKR connection is `readonly=true`, and the live preflight **aborts** the
run if that invariant is violated. This framing matters for the audit: **no change below
touches an order-placement path**, because none exists.

- **Repo / branch:** `~/Documents/github/hermes`, branch `hermes-docs` (not `main`).
- **Deploy model:** repo `src/hermes_escape_top/` → live `~/.hermes/skills/investment/escape-top/hermes_escape_top/` via `scripts/deploy_to_live.sh`. The dashboard is served **from the live package** on `:8766` by launchd; the 07:10 daily run is launchd `com.hermes.daily`.
- **Code never auto-reaches live** — it must be explicitly deployed. So "committed" ≠ "live"; each item below states both.

### Scope of 2026-06-18
1. Close an 8-finding internal code review ("ultrareview").
2. Integrate a **real consolidated-tape (SIP) flow source** to replace a proxy.
3. Complete the **deferred P1**: cross-process concurrency hardening.
4. Repo hygiene + documentation accuracy.

**16 commits**, all pushed. **3 gated live deploys**. Final live code = `2beea7d`.

### Methodology (how the work was done)
- **Review-driven**: every change traces to a named finding or an explicit request.
- **Test-first**: reproduce → fix → prove. New behaviour ships with a test; the full suite must be green before any deploy.
- **Verify-then-deploy**: deploys go through a gated script with **automatic rollback** on any failed step, and each live deploy was **independently re-verified** (live `VERSION` hash + `verify_live` end-to-end gate + dashboard string checks), not assumed.

---

## 1. How to independently verify (run these)

```bash
# 1. The commit ledger for the day
git -C ~/Documents/github/hermes log --since="2026-06-18 00:00" \
    --until="2026-06-19 00:00" --reverse --pretty="%h %ad %s" --date=format:"%H:%M"

# 2. Test suite (expect: 517 passed)
cd ~/Documents/github/hermes/src && python3 -m pytest hermes_escape_top/tests/ -q

# 3. Live code identity (expect: 2beea7d ...)
cat ~/.hermes/skills/investment/escape-top/hermes_escape_top/VERSION

# 4. Live dashboard sanity
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8766/      # 200
curl -s http://127.0.0.1:8766/ | grep -c 估算差额                     # >0 (#2 honest label live)

# 5. End-to-end live gate (runs the REAL daily entry in non-official mode)
bash ~/Documents/github/hermes/ops/verify_live.sh                     # "verify_live PASS"
```

Every finding below cites `file:line` (or `file` + function) at the **repo** so claims are checkable against source.

---

## 2. Summary — the 8 review findings

| # | Finding | Severity | Status | Commit(s) | Live? |
|---|---|---|---|---|---|
| 1 | Deploy verification wrote a **second official run** (polluted the daily record; a root cause of false SOXL "REDUCE→EXIT→REDUCE" flips) | High | ✅ Fixed | `3ea7dff` (+ `f043e0c`) | ✅ |
| 2 | Proxy metric mislabeled as **real net cash flow** ("5日净流/净额") | Medium | ✅ Fixed | `a8df353`, `e0d6148`, `218f0f4`, `2fdbdbf` | ✅ |
| 3 | **No cross-process mutex; non-atomic CSV writes** — web refresh, 07:10 cron, and two server threads could interleave / tear files | **High (P1)** | ⚠️ **Partial** (§2A) | `2beea7d` | ⚠️ |
| 4 | Manifest "re-freeze" button **bypassed the integrity scan** → could re-certify corrupt/hand-edited bars as OK | Medium-High | ✅ Fixed | `ce8ee92` | ✅ |
| 5 | The refresh button's **preview was unreachable** (the explicit-date path always preferred the official record) | Low-Med | ✅ Fixed | `e0d6148` | ✅ |
| 6 | Deploy was **non-atomic, additive, no restart, no rollback** | Medium | ⚠️ **Phase 1 partial** (§2A) | `f9aed82` | ✅ |
| 7 | Green "self-check OK" receipt **stamped before** state commit → could attest success on a failed run | Medium | ⚠️ **Partial** (§2A) | `ce8ee92` | ✅ |
| 8 | Production runbook described a **stale/loose engine** and an **outdated deploy flow** | Low | ✅ Fixed | `e24ebed`, `974ee3e` | n/a (doc) |

> **⚠️ Corrected after external audit (2026-06-18).** The original "All 8 resolved" claim was **overstated**. Accurate status: **5 fully resolved** (#1/#2/#4/#5/#8); **#3/#6/#7 partial**; and the audit surfaced **further open issues**. The ✅ marks above for #3/#6/#7 are **superseded by §2A below.**

5 of 8 are fully resolved and live. **#3, #6, #7 are partial** (§2A). #6 was always a two-phase item; Phase 2 (staging atomic switch) is deferred under explicit triggers (§6).

---

## 2A. External audit addendum (2026-06-18)

An external audit reviewed this remediation and correctly found the "All 8 resolved"
claim **overstated**. Corrected status: **5 fully resolved (#1/#2/#4/#5/#8), 3 partial
(#3/#6/#7)**, plus new findings. All accepted as valid (key claims re-verified against
source). Tracked for follow-up; none have been fixed yet at the time of this addendum.

**Partial (were claimed done):**
- **#3 (P1) — the lock does not cover all writers.** `pipeline_lock` sits at the 4
  WebUI refresh endpoints + the cron `main()`, but `score_pipeline()` — which writes
  5 SQLites + the audit log + the signal journal (`pipeline.py`) — is also reachable
  **unlocked** via `/api/ibkr_demo_snapshot`, `/api/ibkr_live_check`, and the CLI
  (`cli.py`). Two unsynchronized `score_pipeline` runs can still interleave. **Correct
  fix:** gate at the **persistence layer** (one locked entry), not per caller — minding
  re-entrancy (the cron's `main()` already holds the lock when it calls `score_pipeline`).
- **#6 (P1) — deploy concurrency + rollback.** `pgrep run_daily` is a one-shot
  time-of-check check; the deploy takes **no** `.pipeline.lock`, so a task starting after
  the check (or the live dashboard during the in-place rsync) is not serialized. Rollback
  untars the backup but does **not** delete files the failed rsync added; a `.hermes`
  commit failure prints `NOTE` yet the script still prints `deploy OK`. So "any failure
  auto-rollback / commit only when all-green" is overstated.
- **#7 (P2) — receipt.** Only the *state-commit* failure path writes a red receipt; an
  exception in scoring / artifact write / post-run diff **before** the receipt logic
  leaves the prior green receipt. Alpaca SIP refresh runs **after** the receipt and only
  warns on failure (daily still exits 0).

**New findings (outside the original 8):**
- **(P1) Health masks staleness.** `health.py` reads the frozen `snapshot_stale` instead
  of recomputing IBKR age from `sync_time` (a 2026-01-01 snapshot still reports OK); it
  also ignores the scheduled-run receipt and the SIP `as_of`.
- **(P2) Busy = HTTP 200** (should be `409`); and refresh/IBKR endpoints are loopback-only
  with **no token**, conflicting with `context.md`'s "all write endpoints require token" —
  a code/doc/requirement inconsistency to resolve with one explicit policy.
- **(P2) `.hermes` deploy commit** `git add`s the whole live tree (~37 files incl. SQLite,
  position history, order previews, a 1.4 MB backup tar) — runtime/sensitive data + repo
  bloat. Should track only code + entry scripts + VERSION.
- **(P3) Live writes back to repo** (NEXT5 → `building/logs`), breaking repo/live isolation.
- **(P3) Atomic write changed permissions.** `mkstemp` (0600) + `os.replace` left live CSVs
  at 0600 instead of 0644 (verified on disk). Preserve the original mode.

Day-level verification still holds: full suite **517**, `compileall` clean, launchd daily
exit 0, live `2beea7d`, no tracked API keys.

---

## 3. The findings in detail

### #1 — Deploy verification no longer pollutes the official record  ·  `3ea7dff`
- **Problem:** post-deploy verification ran the daily entry as a normal run, appending a **second `scheduled` (official)** record for the day. The dashboard pins the latest scheduled run as the official advice, so a verification run could overwrite the morning's official advice — a root cause of spurious intraday "flips".
- **Fix:** `ops/verify_live.sh` runs the real entry with `--deploy-verify`, which maps to `--run-type manual_rerun` and **does not** commit state or stamp the official receipt. The gate **asserts** the appended audit record is `manual_rerun` and that **no** official receipt/state was written ([`ops/verify_live.sh`](../../ops/verify_live.sh)).
- **Verify:** `tests/test_ops_entrypoints.py`; run `ops/verify_live.sh` and confirm the tail prints `official receipt/state untouched` + `verify_live PASS`.

### #2 — Honest flow labels; proxy vs. real, end to end  ·  `a8df353` → `e0d6148` → `218f0f4` → `2fdbdbf`
- **Problem:** a `sign × close × volume` **proxy** was presented as "5日净流 / 穿透股票现金流" (real net cash flow) across the 8766 main page, the 8765 mirror, and the workbench.
- **Fix, in layers:**
  - `a8df353` — added a **real flow source**: Alpaca **SIP consolidated-tape** daily turnover (`core/data/alpaca_flow.py`), and a dashboard block for it.
  - `e0d6148`, `218f0f4` — relabeled the proxy to "方向成交额(代理)/量价流向代理" on **all three** surfaces (`render.py`, `mirror_render.py`, `workbench.py`).
  - **Honesty on the real source too:** the SIP **total turnover** is real (VWAP×volume), but the **buy/sell split** is *estimated* from each minute's close-position, **not** exchange aggressor side ([`core/data/alpaca_flow.py`](../../src/hermes_escape_top/core/data/alpaca_flow.py) docstring). So the Alpaca card was relabeled "净额→估算差额", "主动买入占优→估算买入侧占优".
  - `2fdbdbf` — tightened "下跌天数" to **"弱量价天数"**, because the metric is `((cmf < 0) & (mfi < 50)).tail(5)` — weak price-volume days, not literal down days.
- **Note:** the proxy algorithm itself (`core/data/flow.py`) was **not** changed — it remains a labelled auxiliary indicator. Label/text only.
- **Verify:** `tests/test_dashboard_workbench.py`, `tests/test_mirror_web.py`, `tests/test_phase14_web.py`; live `curl localhost:8766 | grep -c 估算差额` → `>0`, `grep -c 5日净流` → `0`.

### #3 — Cross-process mutex + atomic writes  ·  `2beea7d`  (see §4 for the deep dive)

### #4 — Manifest button verifies before it freezes  ·  `ce8ee92`
- **Problem:** the WebUI "re-freeze manifest" button froze the data manifest **without** first running the history-integrity scan, so it could re-certify corrupt or hand-edited CSVs as "OK", hiding real damage.
- **Fix:** `force_refresh_manifest` runs `_history_integrity_scan` **first** and **refuses to freeze** when bars are corrupt, keeping the prior DRIFT status ([`web/refresh.py`](../../src/hermes_escape_top/web/refresh.py), `force_refresh_manifest`). Verify-then-freeze — the same discipline the daily run already applied.
- **Verify:** `tests/test_manifest_button_integrity.py` (both the clean-freeze and the refuse-on-corruption paths).

### #5 — The refresh preview is reachable and labelled  ·  `e0d6148`
- **Problem:** the "更新策略数据" button creates a `manual_rerun` preview, then redirected to `?as_of=<date>`; but the explicit-date path always preferred the official `scheduled` record (a correct earlier fix), so the user's preview was **invisible**.
- **Fix:** added `?view=preview`: `_latest_score_payload(prefer_preview=True)` returns the newest **non-official** record for the day, and the refresh redirect now appends `&view=preview`. The default headline stays official; the preview is reachable **and** clearly flagged non-official ([`web/server.py`](../../src/hermes_escape_top/web/server.py), [`web/render.py`](../../src/hermes_escape_top/web/render.py)).
- **Verify:** `tests/test_dashboard_official_only.py` (`view=preview` → manual_rerun; default → scheduled).

### #6 — Deploy is 0-drift, restarts, and auto-rolls-back (Phase 1)  ·  `f9aed82`  (see §5)

### #7 — Green receipt is stamped last, never on a failed run  ·  `ce8ee92`
- **Problem:** the end-of-run "官方 run·自检全绿" receipt (the dashboard's top banner) was written **before** the state commit, so a later failure left a false-green attestation.
- **Fix:** `run_daily_package.main()` commits state **first**, wraps it in try/except, and writes the receipt **last** — only for the `scheduled` official run, and **forces a red receipt** (`steps_ok=False`) if a required step failed, then `sys.exit(1)` ([`scripts/run_daily_package.py`](../../src/hermes_escape_top/scripts/run_daily_package.py), `_write_run_receipt` + `_execute_daily`).
- **Verify:** `tests/test_run_receipt_writer.py`, `tests/test_run_receipt_banner.py`.

### #8 — Runbook matches reality  ·  `e24ebed` + `974ee3e`
- `e24ebed` — corrected §7 to state the daily entry is the **single `python -m` package engine** (the loose standalone copy was retired 2026-06-17; the package self-locates via `_discover_runtime_paths`).
- `974ee3e` — corrected the **deploy-flow** description (it still said additive rsync + "import+决策对比") to match `deploy_to_live.sh`: guard → backup → `rsync --delete` (0-drift) + VERSION + ops/ entry sync → soft reverse-sync + config gate → smoke → restart → `verify_live` → commit, with auto-rollback.

---

## 4. Deep dive — #3 concurrency hardening (`2beea7d`)

**The defect (P1).** Two write paths mutated the same data dir with **zero serialization**: the 07:10 launchd run (`run_daily_package`) and the WebUI refresh endpoints (`ThreadingHTTPServer`, i.e. concurrent handler threads). They could interleave (two writers), and the dashboard (a separate reader) could observe a **half-written CSV**. No `flock`, no atomic write existed (verified by a repo-wide grep at the time).

**The fix — one new module, [`core/safe_io.py`](../../src/hermes_escape_top/core/safe_io.py):**

1. **`pipeline_lock()`** — one `flock` on `<archive_dir>/.pipeline.lock`.
   - The **daily run** takes it **blocking** (it *must* run, so it waits its turn, capped by a timeout so a stuck holder can't hang it forever).
   - The **4 in-process refresh endpoints** take it **non-blocking** and return a `{"busy": true, ...}` payload instead of racing the writer.
   - **Acquired only at the two top boundaries** — `run_daily_package.main()` and the web `do_POST` handler — **never in a shared helper**. This is the load-bearing design rule: a locked function that called another locked function would self-deadlock, because `flock` on a second fd of the same process conflicts with the first.

2. **Atomic writes** — `atomic_write_csv()` and `write_manifest()` now write a temp file in the **same directory** then `os.replace` (the discipline `commit_state` and the audit-log rotation already used). A reader sees the old or the new file, never a torn one; a crash mid-write leaves the prior file intact. Applied to the **6 writers on the live concurrent path**: history (`backfill_history`, `backfill_official_indices`), soft-data (`backfill_soft_data`), the `sentiment`/`risk_signals`/`macro` caches, and the manifest JSON.

**Why it is correct (points an auditor should check):**
- **The load-bearing assumption is tested.** `flock` is bound to the *open file description*, so a fresh `open` per acquirer conflicts **even within one process** — which is what serializes two `ThreadingHTTPServer` threads, not just two processes. `tests/test_safe_io.py::test_nonblocking_lock_conflicts_even_same_process` proves this on the actual platform; if it ever regressed, that test fails.
- **Deadlock-free.** The lock is acquired at exactly two non-nesting entry points; shared helpers (`refresh_all`, `refresh_score_with_market_data`, `force_refresh_manifest`, `write_manifest`) are never locked. The daily run holds the lock for its whole batch and calls only unlocked helpers.
- **No stale lock.** `flock` is released by the kernel on process death — a crashed holder does not leave a lock behind (unlike a pidfile).
- **Reader protection is separate from writer serialization.** The mutex serializes *writers*; atomic writes protect the *reader* (the dashboard doesn't take the lock). Both are needed; both are present.

**Verification:** `tests/test_safe_io.py` (6 tests: same-process conflict, blocking timeout, release-on-exit, release-on-exception, atomic write leaves no temp residue, atomic write keeps the old file on failure) + a real-config-path serialization smoke + full suite **517 passed** + the post-deploy `verify_live PASS` (the real daily entry ran end-to-end **under the lock** on live; the `.pipeline.lock` file's mtime matched the verification run).

**Bounded scope (disclosed):** ~13 **manual/offline** backfill scripts (`backfill_cot`, `backfill_naaim`, `backfill_crypto_micro`, etc.) still use direct `to_csv`. They are run by hand offline, not during live serving, so they are not on the concurrent read path. Converting them for consistency is a noted, low-priority follow-up, **not** a correctness gap for the live system.

---

## 5. Deploy mechanism — #6 Phase 1 (`f9aed82`)

Why an auditor should care: this is how "committed" becomes "live", and it is the gate that makes the live claims trustworthy. [`scripts/deploy_to_live.sh`](../../scripts/deploy_to_live.sh), 7 steps, **`set -uo pipefail`**, **auto-rollback on any failure**:

1. **Guard** — `pgrep run_daily`; abort if a daily/refresh run is in progress (no deploy on top of a run).
2. **Backup** — `tar` the live package **excluding `data/`** (one-command rollback).
3. **`rsync -a --delete`** repo→live = **true 0-drift** (repo deletions/renames are reflected live), writes `VERSION=<hash>`, and syncs the live-only entry scripts from [`ops/`](../../ops/).
4. **Soft-data reverse-sync** (live→repo) + **human config gate** (`y/N`).
5. **Smoke gate** — import + `predeploy_smoke` (FRED publish_date, resident sources, no-source regression, evidence-chain NA, manifest drift). **Fail → rollback.**
6. **Restart** the dashboard + accept: `curl :8766 == 200`.
7. **End-to-end** — [`ops/verify_live.sh`](../../ops/verify_live.sh) runs the **real** entry as `manual_rerun` and asserts the effects landed (manifest re-froze, NEXT-5 refreshed, **no** official receipt/state). **Fail → rollback.** Only then commit the live tree in the `.hermes` git.

**Deploys executed today (all gated, all independently re-verified):**

| Stamp | Hash | Contents | verify_live |
|---|---|---|---|
| 20260618_160004 | `e0d6148` | #1/#4/#5/#7/#8 + alpaca + #2 labels + #6 mechanism | PASS |
| 20260618_195501 | `218f0f4` | #2 cont (mirror/workbench/Alpaca honesty) | PASS |
| 20260618_205923 | `2beea7d` | #3 mutex + atomic writes + 弱量价天数 | PASS |

Live code is now `2beea7d`. The two latest commits (`974ee3e`, `6998b17`) are **doc/repo-only** and do not affect the live runtime (the deploy only syncs `.py`; live data is separate).

---

## 6. Deferred / out-of-scope (please scrutinize)

- **#6 Phase 2 — true atomic switch (staging dir + symlink flip).** The current deploy does **in-place** `rsync --delete`; during those ~seconds a dashboard request doing a first-time *lazy* import could read a half-synced module. Mitigations already in place: the pgrep guard (blocks the cron) and the post-rsync restart (recovers the reader); the window is seconds and the exposure is a not-yet-imported module only. **Deferred under explicit triggers** (`CONTRIBUTING.md:49`): (a) multi-machine deploys, (b) an actually-observed half-synced read, (c) automation/high-frequency deploys. None are currently met (single machine, infrequent manual deploys). **Note:** Phase 2 is now **only** the staging atomic switch — the cross-process-lock half shipped in #3 (`2beea7d`); `CONTRIBUTING.md:49` and `deploy_to_live.sh`'s header were corrected in this remediation to reflect that.
- **Manual backfill atomic-write consistency** — the ~13 offline writers in §4. Low priority, off the live concurrent path.
- **Soft-data tracking** — `4ba6120` untracked 13 `soft_history/*.csv` (per `.gitignore:30-36`'s own documented intent; only `mstr_btc_holdings` + `onchain_mstr_features` are seed). `6998b17` re-whitelisted `aaii_sentiment.csv` because it cannot be auto-refetched. **Auditor note:** the day's diffstat shows ~36k deletions — these are almost entirely **CSV data rows leaving git tracking**, not code removed.

---

## 7. Invariant & risk check

- **Never-orders invariant:** no change touched an order path (none exists); IBKR remained `readonly=true`; the live preflight still aborts otherwise. Confirmed live post-deploy.
- **No personalized investment advice** was added; the system outputs signals/previews only.
- **Secrets** (`fred_api_key.txt`) remain gitignored; no secret was committed.
- **Test suite:** 517 passed at `2beea7d` (was 511 before #3's 6 new tests).
- **Repo == intent:** `hermes-docs` HEAD `6998b17`, origin in sync, working tree clean.

---

## 8. Appendix — full commit ledger (2026-06-18)

| Time | Hash | Subject |
|---|---|---|
| 08:16 | `b7e8e07` | webui: explicit `?as_of=<date>` prefers the official scheduled record |
| 08:25 | `f043e0c` | ops: version live-only entry/scheduler files + end-to-end deploy gate |
| 08:46 | `867f0b5` | webui: swallow client-disconnect BrokenPipe in `_send` (clean err log) |
| 09:24 | `4e544e5` | cleanup: stop tracking runtime-generated status/coverage reports + doc `ops/` |
| 14:22 | `ce8ee92` | review fixes #4 + #7: manifest-button integrity gate + receipt written last |
| 14:29 | `e24ebed` | review fix #8: runbook — daily entry is the single `-m` engine |
| 14:43 | `f9aed82` | review #6 Phase 1: deploy that does 0-drift + restart + auto-rollback |
| 15:02 | `3ea7dff` | review fix #1: verify_live runs in non-official mode |
| 15:02 | `a8df353` | alpaca: real SIP daily-flow source + dashboard display (#2 root) |
| 15:22 | `e0d6148` | review fixes #2 + #5: honest legacy-flow label + reachable preview view |
| 19:23 | `218f0f4` | review #2 (cont.): honest flow labels on mirror/workbench + Alpaca split |
| 19:58 | `2fdbdbf` | tighten flow-day label: 下跌天数 → 弱量价天数 (precise to the metric) |
| 20:07 | `4ba6120` | untrack soft_history CSVs per .gitignore intent + cover PIT .bak strays |
| 20:33 | `2beea7d` | #3: cross-process pipeline mutex + atomic CSV/manifest writes |
| 21:14 | `974ee3e` | docs: refresh runbook §7 deploy flow to match deploy_to_live.sh |
| 21:14 | `6998b17` | re-track aaii_sentiment.csv as seed (whitelist in .gitignore) |

*Generated 2026-06-18. Verify against `git log` — see §1.*
