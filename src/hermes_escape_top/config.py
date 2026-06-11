from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List


PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_DIR / "config" / "config.json"

# Relative paths.* entries normally resolve under the package dir. Setting
# HERMES_DATA_DIR re-roots them so runtime data can live outside the git
# working tree (serve/backtest/test isolation). Absolute paths are unaffected.
DATA_DIR_ENV = "HERMES_DATA_DIR"


class ConfigError(ValueError):
    pass


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    payload = json.loads(path.read_text())
    validate_config(payload)
    return payload


def resolve_path(config: Dict[str, Any], key: str) -> Path:
    raw = config.get("paths", {}).get(key)
    if not raw:
        raise ConfigError(f"Missing paths.{key}")
    path = Path(str(raw)).expanduser()
    if path.is_absolute():
        return path
    override = os.environ.get(DATA_DIR_ENV)
    base = Path(override).expanduser() if override else PACKAGE_DIR
    return (base / path).resolve()


def validate_config(config: Dict[str, Any]) -> None:
    required = [
        "version",
        "runtime",
        "paths",
        "symbols",
        "module_caps",
        "missing",
        "portfolio",
        "features",
    ]
    missing = [key for key in required if key not in config]
    if missing:
        raise ConfigError("Missing config keys: " + ", ".join(missing))
    _require_symbols(config, ["MSTR", "FNGU", "SOXL"])
    for sym, spec in config["symbols"].items():
        cap = spec.get("sleeve_cap")
        if not isinstance(cap, (int, float)) or cap < 0 or cap > 1:
            raise ConfigError(f"{sym}.sleeve_cap must be in [0,1]")
        weights = spec.get("module_weights", {})
        if set(weights) != {"A", "B", "C", "D"}:
            raise ConfigError(f"{sym}.module_weights must contain A/B/C/D")
    blind = config.get("missing", {}).get("blind_spot_threshold")
    if not isinstance(blind, (int, float)) or blind <= 0:
        raise ConfigError("missing.blind_spot_threshold must be positive")


def _require_symbols(config: Dict[str, Any], symbols: Iterable[str]) -> None:
    missing = [sym for sym in symbols if sym not in config.get("symbols", {})]
    if missing:
        raise ConfigError("Missing symbols: " + ", ".join(missing))


def trade_symbols(config: Dict[str, Any]) -> List[str]:
    return list(config["symbols"].keys())
