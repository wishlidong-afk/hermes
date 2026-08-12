from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import archive_soft_inputs, bootstrap, empty_score_pipeline, flow_snapshot, score_pipeline, soft_data_snapshot
from .ibkr.live_check import run_live_check
from .core.backtest.replay import available_replay_dates, run_score_replay, run_strategy_backtest
from .core.backtest.param_sweep import run_param_sweep
from .core.backtest.reports import write_full_backtest_markdown, write_json_report
from .core.backtest.run_full import run_full_backtest
from .core.data.manifest import freeze_manifest, verify_manifest, write_manifest
from .core.data.runtime_root import require_explicit_runtime_data_root
from .core.safe_io import pipeline_lock
from .scripts.backfill_history import all_backfill_symbols, backfill, default_store_dir, write_coverage_report
from .web.mirror_render import write_mirror_dashboard
from .web.mirror_server import create_mirror_server
from .web.render import write_dashboard
from .web.server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes Escape-Top greenfield CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Copy legacy local CSV history into greenfield data/history")
    p_backfill_history = sub.add_parser("backfill-history", help="Backfill daily OHLCV history into data/history")
    p_backfill_history.add_argument("--symbols", nargs="*", default=None)
    p_backfill_history.add_argument("--start", default="2018-01-01")
    p_backfill_history.add_argument("--end", default=None)
    p_backfill_history.add_argument("--store-dir", default=None)
    p_backfill_history.add_argument("--report", default="reports/N0_history_coverage.md")
    p_backfill_history.add_argument("--repair-overlap-days", type=int, default=0)
    p_backfill_history.add_argument(
        "--repair-history-head",
        action="store_true",
        help="explicitly fetch missing history before the first canonical row",
    )
    p_manifest = sub.add_parser("freeze-manifest", help="Freeze a sha256 data manifest for a directory")
    p_manifest.add_argument("--store-dir", default="data/history")
    p_manifest.add_argument("--output", default="data/archive/data_manifest_latest.json")
    p_verify_manifest = sub.add_parser("verify-manifest", help="Verify a directory against a frozen manifest")
    p_verify_manifest.add_argument("--store-dir", default="data/history")
    p_verify_manifest.add_argument("--manifest", required=True)
    p_empty = sub.add_parser("empty-score", help="Run Phase 0 empty score contract pipeline")
    p_empty.add_argument("--as-of", required=True)
    p_archive = sub.add_parser("archive-soft-inputs", help="Seed dated soft-data archives")
    p_archive.add_argument("--as-of", required=True)
    p_flow = sub.add_parser("flow", help="Compute Phase 1 flow v2 metrics")
    p_flow.add_argument("--as-of", required=True)
    p_score = sub.add_parser("score", help="Run Phase 3 scoring pipeline")
    p_score.add_argument("--as-of", required=True)
    p_ibkr_live = sub.add_parser("ibkr-live", help="Run read-only IBKR live verification")
    p_ibkr_live.add_argument("--as-of", required=True)
    p_ibkr_live.add_argument("--no-report", action="store_true")
    p_soft = sub.add_parser("soft-data", help="Collect Phase 10 soft adapter contract snapshot")
    p_soft.add_argument("--as-of", required=True)
    p_replay = sub.add_parser("replay", help="Run deterministic score replay over local history dates")
    p_replay.add_argument("--start", required=True)
    p_replay.add_argument("--end", required=True)
    p_replay.add_argument("--limit", type=int, default=None)
    p_backtest = sub.add_parser("backtest", help="Run transaction-level strategy backtest over local dates")
    p_backtest.add_argument("--start", required=True)
    p_backtest.add_argument("--end", required=True)
    p_backtest.add_argument("--limit", type=int, default=None)
    p_full = sub.add_parser("full-backtest", help="Run full routed backtest and write markdown/json reports")
    p_full.add_argument("--start", default="2018-01-01")
    p_full.add_argument("--end", default="2026-05-29")
    p_full.add_argument("--limit", type=int, default=None)
    p_full.add_argument("--json-output", default="reports/Backtest_FULL.json")
    p_full.add_argument("--markdown-output", default="reports/Backtest_FULL.md")
    p_sweep = sub.add_parser("param-sweep", help="Run local scaffold parameter sweep")
    p_sweep.add_argument("--start", required=True)
    p_sweep.add_argument("--end", required=True)
    p_sweep.add_argument("--limit", type=int, default=60)
    p_dash = sub.add_parser("dashboard", help="Render a read-only HTML dashboard snapshot")
    p_dash.add_argument("--as-of", required=True)
    p_dash.add_argument("--output", required=True)
    p_mirror_dash = sub.add_parser("mirror-dashboard", help="Render a read-only mirror reference HTML dashboard snapshot")
    p_mirror_dash.add_argument("--as-of", required=True)
    p_mirror_dash.add_argument("--output", required=True)
    p_serve = sub.add_parser("serve", help="Start read-only local dashboard server")
    p_serve.add_argument("--as-of", required=True)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8776)
    p_serve_mirror = sub.add_parser("serve-mirror", help="Start standalone mirror reference WebUI server")
    p_serve_mirror.add_argument("--as-of", required=True)
    p_serve_mirror.add_argument("--host", default="127.0.0.1")
    p_serve_mirror.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()

    if args.command in {
        "score",
        "dashboard",
        "mirror-dashboard",
        "serve",
        "serve-mirror",
    }:
        require_explicit_runtime_data_root(args.command)

    if args.command == "bootstrap":
        with pipeline_lock(blocking=True, timeout=600):
            payload = bootstrap()
    elif args.command == "backfill-history":
        with pipeline_lock(blocking=True, timeout=600):
            symbols = args.symbols or all_backfill_symbols()
            store_dir = Path(args.store_dir) if args.store_dir else default_store_dir()
            results = backfill(
                symbols,
                start=args.start,
                end=args.end,
                store_dir=store_dir,
                repair_overlap_days=args.repair_overlap_days,
                repair_history_head=args.repair_history_head,
            )
            report_path = write_coverage_report(results, args.report)
        payload = {"schema_version": "escape-top-greenfield-history-backfill-v1", "report": str(report_path), "results": {k: v.to_dict() for k, v in results.items()}}
    elif args.command == "freeze-manifest":
        with pipeline_lock(blocking=True, timeout=600):
            path = write_manifest(args.store_dir, args.output)
            manifest = freeze_manifest(args.store_dir)
        payload = {"schema_version": "escape-top-greenfield-manifest-freeze-v1", "output": str(path), "manifest_id": manifest.manifest_id, "entries": len(manifest.entries)}
    elif args.command == "verify-manifest":
        payload = {"schema_version": "escape-top-greenfield-manifest-verify-v1", "ok": verify_manifest(args.store_dir, args.manifest)}
    elif args.command == "empty-score":
        payload = empty_score_pipeline(args.as_of)
    elif args.command == "archive-soft-inputs":
        with pipeline_lock(blocking=True, timeout=600):
            payload = archive_soft_inputs(args.as_of)
    elif args.command == "flow":
        payload = flow_snapshot(args.as_of)
    elif args.command == "score":
        payload = score_pipeline(args.as_of)
    elif args.command == "ibkr-live":
        payload = run_live_check(args.as_of, write_report=not args.no_report)
    elif args.command == "soft-data":
        with pipeline_lock(blocking=True, timeout=600):
            payload = soft_data_snapshot(args.as_of)
    elif args.command == "replay":
        dates = available_replay_dates(args.start, args.end)
        payload = run_score_replay(dates, limit=args.limit)
    elif args.command == "backtest":
        payload = run_strategy_backtest(args.start, args.end, limit=args.limit)
    elif args.command == "full-backtest":
        report = run_full_backtest(args.start, args.end, limit=args.limit)
        full_payload = report.to_dict()
        json_path = write_json_report(full_payload, Path(args.json_output))
        md_path = write_full_backtest_markdown(full_payload, Path(args.markdown_output))
        payload = {
            "schema_version": full_payload["schema_version"],
            "data_manifest_id": full_payload["data_manifest_id"],
            "requested_start": full_payload["requested_start"],
            "requested_end": full_payload["requested_end"],
            "effective_start": full_payload["effective_start"],
            "effective_end": full_payload["effective_end"],
            "dates": len(full_payload["dates"]),
            "metrics": full_payload.get("simulation", {}).get("metrics", {}),
            "json_output": str(json_path),
            "markdown_output": str(md_path),
        }
    elif args.command == "param-sweep":
        payload = run_param_sweep(args.start, args.end, limit=args.limit)
    elif args.command == "dashboard":
        payload = score_pipeline(args.as_of)
        path = write_dashboard(payload, Path(args.output))
        payload = {"as_of": args.as_of, "output": str(path)}
    elif args.command == "mirror-dashboard":
        payload = score_pipeline(args.as_of)
        path = write_mirror_dashboard(payload, Path(args.output))
        payload = {"as_of": args.as_of, "output": str(path)}
    elif args.command == "serve":
        server = create_server(args.host, args.port, args.as_of)
        print(json.dumps({"url": f"http://{args.host}:{server.server_port}/", "as_of": args.as_of}, ensure_ascii=False))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    elif args.command == "serve-mirror":
        server = create_mirror_server(args.host, args.port, args.as_of)
        print(json.dumps({"url": f"http://{args.host}:{server.server_port}/", "as_of": args.as_of, "app": "mirror"}, ensure_ascii=False))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    else:
        raise SystemExit(f"Unknown command {args.command}")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
