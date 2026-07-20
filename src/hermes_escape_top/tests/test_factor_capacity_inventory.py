from __future__ import annotations

import json
from pathlib import Path

from hermes_escape_top.config import load_config
from hermes_escape_top.core.scoring.capacity import factor_capacity_inventory


ROOT = Path(__file__).resolve().parents[3]


def test_current_factor_capacity_inventory_matches_live_scoring_definitions():
    inventory = factor_capacity_inventory(load_config())
    summaries = {
        (row["symbol"], row["module"]): row
        for row in inventory["module_summaries"]
    }

    assert summaries[("MSTR", "A")]["defined_max"] == 50.0
    assert summaries[("MSTR", "A")]["post_cap_capacity"] == 20.0
    assert summaries[("MSTR", "B")]["defined_max"] == 26.0
    assert summaries[("MSTR", "B")]["configured_reachable_max"] == 21.0
    assert summaries[("MSTR", "B")]["post_cap_capacity"] == 21.0
    assert summaries[("FNGU", "B")]["configured_reachable_max"] == 26.0
    assert summaries[("FNGU", "B")]["post_cap_capacity"] == 25.0
    assert summaries[("SOXL", "C")]["defined_max"] == 36.0
    assert summaries[("SOXL", "C")]["post_cap_capacity"] == 35.0
    assert summaries[("MSTR", "D")]["post_cap_capacity"] == 20.0


def test_committed_factor_capacity_artifact_is_generated_from_current_config():
    expected = factor_capacity_inventory(load_config())
    artifact = json.loads(
        (ROOT / "building/reports/factor_capacity/FACTOR_CAPACITY_INVENTORY.json").read_text(
            encoding="utf-8"
        )
    )

    assert artifact == expected
