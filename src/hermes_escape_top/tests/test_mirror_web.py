from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from unittest import mock

from hermes_escape_top.web.mirror_render import render_mirror_dashboard
from hermes_escape_top.web.mirror_server import create_mirror_server


def sample_payload() -> dict:
    decisions = {
        "FNGU_QQQ": {
            "sleeve": "FNGU_QQQ",
            "risk_symbol": "FNGU",
            "base_symbol": "QQQ",
            "selected_symbol": "FNGU",
            "sleeve_cap": 0.20,
            "target_weight": 0.20,
            "cycle": "RISK_ON",
            "reason": "QQQ above EMA20 and MA200.",
        },
        "SOXL_SOXX": {
            "sleeve": "SOXL_SOXX",
            "risk_symbol": "SOXL",
            "base_symbol": "SOXX",
            "selected_symbol": "SOXL",
            "sleeve_cap": 0.30,
            "target_weight": 0.30,
            "cycle": "RISK_ON",
            "reason": "SOXX above EMA20 and MA200.",
        },
        "MSTR_QQQ": {
            "sleeve": "MSTR_QQQ",
            "risk_symbol": "MSTR",
            "base_symbol": "QQQ",
            "selected_symbol": "QQQ",
            "sleeve_cap": 0.15,
            "target_weight": 0.15,
            "cycle": "BASE_DEFENSE",
            "reason": "MSTR/BTC radar not risk-on; use QQQ base leg.",
        },
    }
    return {
        "schema_version": "test",
        "as_of": "2026-06-02",
        "data_quality": {"level": "HIGH", "overall_score": 95},
        "regime": {"current": "RISK_ON", "vix_percentile": 0.3, "inputs": {"QQQ.close": 746.16, "QQQ.ma200": 650}},
        "portfolio_risk": {"forecast_portfolio_vol": 0.22},
        "ibkr": {
            "source": "snapshot",
            "account_id": "DU123",
            "net_liq": 100000,
            "sync_time": "2026-06-02T22:00:00",
            "trade_symbols": [{"symbol": "FNGU", "actual_shares": 10, "actual_notional": 350, "actual_weight": 0.0035, "avg_cost": 30, "status": "UNDER"}],
            "route_legs": [{"symbol": "QQQ", "actual_shares": 5, "actual_notional": 3730, "actual_weight": 0.0373, "avg_cost": 700, "status": "UNDER"}],
            "extra_positions": [],
        },
        "mirror": {"decisions": decisions},
        "posterior_pnl": {
            "portfolio_value": 100000,
            "mirror": {
                "FNGU_QQQ": {"symbol": "FNGU", "target_weight": 0.20, "notional": 20000, "previous_close": 32, "current_close": 34, "shares": 625, "pnl": 1250, "return_pct": 0.0625},
                "SOXL_SOXX": {"symbol": "SOXL", "target_weight": 0.30, "notional": 30000, "previous_close": 220, "current_close": 224, "shares": 136.36, "pnl": 545.45, "return_pct": 0.0182},
                "MSTR_QQQ": {"symbol": "QQQ", "target_weight": 0.15, "notional": 15000, "previous_close": 742, "current_close": 746, "shares": 20.21, "pnl": 80.86, "return_pct": 0.0054},
            },
        },
        "snapshots": {
            symbol: {"fields": {"close": {"value": close}, "ema20": {"value": close * 0.98}, "ma200": {"value": close * 0.9}, "ma220": {"value": close * 0.88}, "drawdown_60d_high_pct": {"value": -0.05}}}
            for symbol, close in {"QQQ": 746, "FNGU": 34, "SOXX": 300, "SOXL": 224, "MSTR": 136, "BTC-USD": 110000}.items()
        },
        "flow": {
            "component_baskets": {
                "FNGU": {"severity": "NORMAL", "avg_cmf20": 0.1, "avg_mfi14": 55, "abnormal_components": 0, "component_count": 1, "components": [{"symbol": "NVDA", "severity": "NORMAL", "cmf20": 0.1, "mfi14": 60, "legacy_signed_5d": 1000000}]},
                "SOXL": {"severity": "WATCH", "avg_cmf20": -0.02, "avg_mfi14": 48, "abnormal_components": 1, "component_count": 1, "components": [{"symbol": "AVGO", "severity": "WATCH", "cmf20": -0.02, "mfi14": 48, "legacy_signed_5d": -2000000}]},
                "MSTR": {"severity": "NORMAL", "avg_cmf20": 0.05, "avg_mfi14": 52, "abnormal_components": 0, "component_count": 1, "components": [{"symbol": "MSTR", "severity": "NORMAL", "cmf20": 0.05, "mfi14": 52, "legacy_signed_5d": 500000}]},
            }
        },
    }


class MirrorWebTest(unittest.TestCase):
    def test_render_mirror_dashboard_contains_previous_layout_sections(self) -> None:
        html = render_mirror_dashboard(sample_payload())
        self.assertIn("Hermes 镜像参考", html)
        self.assertIn("切换逃顶 8766", html)
        self.assertIn("周期判断与推荐处置", html)
        self.assertIn("QQQ / FNGU", html)
        self.assertIn("SOXX / SOXL", html)
        self.assertIn("MSTR / QQQ", html)
        self.assertIn("IBKR 持仓", html)
        self.assertIn("理想化持仓配比", html)
        self.assertIn("模型校准 / 上一交易日理想 P/L", html)
        self.assertIn("主要持仓资金流入/流出", html)

    def test_mirror_server_health_and_refresh(self) -> None:
        server = create_mirror_server("127.0.0.1", 0, "2026-06-02")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(f"{base}/health", timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read().decode("utf-8"))["app"], "mirror")
            with mock.patch("hermes_escape_top.web.mirror_server.score_pipeline", return_value=sample_payload()):
                request = urllib.request.Request(f"{base}/api/refresh_score", data=b'{"as_of":"2026-06-02"}', headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("mirror", payload)
                self.assertEqual(payload["mirror"]["decisions"]["FNGU_QQQ"]["selected_symbol"], "FNGU")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

