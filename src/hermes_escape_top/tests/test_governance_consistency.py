from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_governance_consistency.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_governance_consistency", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_registry_parser_reads_on_and_off_defaults():
    module = _module()
    markdown = """
| Flag | Default | Status | What it gates |
|---|---|---|---|
| `flag_on` | **ON** ✅ | live | unit |
| `flag_off` | OFF | candidate | unit |
"""

    assert module.parse_registry_defaults(markdown) == {"flag_on": True, "flag_off": False}


def test_repository_governance_evidence_matches_config_and_baseline():
    module = _module()

    report = module.check_repository(ROOT)

    assert report["ok"], report["errors"]
    assert report["checks"]["config_invariants"] == "OK"
    assert report["checks"]["flag_registry"] == "OK"
    assert report["checks"]["context_snapshot"] == "OK"
    assert report["checks"]["baseline_metadata"] == "OK"
    assert report["checks"].get("dollar_slo_alignment") == "OK"


def test_dollar_slo_alignment_rejects_cross_layer_drift():
    module = _module()
    assert hasattr(module, "dollar_slo_alignment")
    config = json.loads(
        (ROOT / "src" / "hermes_escape_top" / "config" / "config.json").read_text(encoding="utf-8")
    )
    config["soft_data_slo"]["max_age_days"]["dollar"] = 6

    values, errors = module.dollar_slo_alignment(config)

    assert values == {"config": 6, "external_profile": 14, "risk_source": 14}
    assert errors == ["dollar max-age mismatch: config=6, external_profile=14, risk_source=14"]


def test_dollar_slo_alignment_does_not_depend_on_feature_being_enabled():
    module = _module()
    config = json.loads(
        (ROOT / "src" / "hermes_escape_top" / "config" / "config.json").read_text(encoding="utf-8")
    )
    config["features"]["data_dollar"] = False

    values, errors = module.dollar_slo_alignment(config)

    assert values == {"config": 14, "external_profile": 14, "risk_source": 14}
    assert errors == []
