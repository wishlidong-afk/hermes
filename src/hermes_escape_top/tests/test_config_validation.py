from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hermes_escape_top.config import CONFIG_PATH, ConfigError, validate_config


def _config() -> dict:
    return json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8"))


def test_current_config_satisfies_all_invariants():
    validate_config(_config())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda cfg: cfg["status_thresholds"].update({"TRIM": 55}), "status_thresholds"),
        (lambda cfg: cfg["routing"]["defcon1"].update({"BOXX": 0.7}), "routing.defcon1"),
        (lambda cfg: cfg["reentry"].update({"tranches": [0.3, 0.3, 0.3]}), "reentry.tranches"),
        (lambda cfg: cfg["ibkr"].update({"readonly": False}), "ibkr.readonly"),
        (lambda cfg: cfg["ibkr"].update({"host": "0.0.0.0"}), "ibkr.host"),
        (lambda cfg: cfg["state_retention"].update({"score_runs": 0}), "state_retention.score_runs"),
        (lambda cfg: cfg["features"].update({"use_no_advice_state": "true"}), "features.use_no_advice_state"),
    ],
)
def test_invalid_cross_field_configuration_is_rejected(mutate, message):
    config = copy.deepcopy(_config())
    mutate(config)

    with pytest.raises(ConfigError, match=message):
        validate_config(config)
