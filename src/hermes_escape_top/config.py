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
        for module, weight in weights.items():
            if not _number(weight) or float(weight) <= 0:
                raise ConfigError(f"{sym}.module_weights.{module} must be positive")
    if sum(float(spec["sleeve_cap"]) for spec in config["symbols"].values()) > 1.0 + 1e-9:
        raise ConfigError("symbols sleeve_cap total must not exceed 1")
    blind = config.get("missing", {}).get("blind_spot_threshold")
    if not isinstance(blind, (int, float)) or blind <= 0:
        raise ConfigError("missing.blind_spot_threshold must be positive")
    _validate_module_caps(config)
    _validate_status_thresholds(config)
    _validate_sell_fractions(config)
    _validate_routing(config)
    _validate_reentry(config)
    _validate_ibkr(config)
    _validate_state_retention(config)
    _validate_features(config)


def _validate_module_caps(config: Dict[str, Any]) -> None:
    caps = config.get("module_caps") or {}
    if set(caps) != {"A", "B", "C", "D"}:
        raise ConfigError("module_caps must contain A/B/C/D")
    for module, cap in caps.items():
        if not _number(cap) or float(cap) <= 0:
            raise ConfigError(f"module_caps.{module} must be positive")


def _validate_status_thresholds(config: Dict[str, Any]) -> None:
    thresholds = config.get("status_thresholds") or {}
    order = ("WATCH", "TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT")
    if any(key not in thresholds for key in order):
        raise ConfigError("status_thresholds must contain WATCH/TRIM/REDUCE/DEFENSIVE_EXIT/EXIT")
    values = [thresholds[key] for key in order]
    if any(not _number(value) or not 0 <= float(value) <= 100 for value in values):
        raise ConfigError("status_thresholds values must be numeric in [0,100]")
    if any(float(left) >= float(right) for left, right in zip(values, values[1:])):
        raise ConfigError("status_thresholds must be strictly increasing")


def _validate_sell_fractions(config: Dict[str, Any]) -> None:
    required = ("TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT")
    for name, fractions in (config.get("sell_fractions") or {}).items():
        if not isinstance(fractions, dict) or any(key not in fractions for key in required):
            raise ConfigError(f"sell_fractions.{name} must contain {'/'.join(required)}")
        values = [fractions[key] for key in required]
        if any(not _number(value) or not 0 <= float(value) <= 1 for value in values):
            raise ConfigError(f"sell_fractions.{name} values must be in [0,1]")
        if any(float(left) >= float(right) for left, right in zip(values, values[1:])):
            raise ConfigError(f"sell_fractions.{name} must be strictly increasing")


def _validate_routing(config: Dict[str, Any]) -> None:
    routing = config.get("routing") or {}
    defcon1 = routing.get("defcon1") or {}
    weights = [defcon1.get("BOXX"), defcon1.get("TREND")]
    extras = defcon1.get("extra_legs") or {}
    if not isinstance(extras, dict):
        raise ConfigError("routing.defcon1.extra_legs must be an object")
    weights.extend(extras.values())
    if any(not _number(value) or not 0 <= float(value) <= 1 for value in weights):
        raise ConfigError("routing.defcon1 weights must be in [0,1]")
    if abs(sum(float(value) for value in weights) - 1.0) > 1e-9:
        raise ConfigError("routing.defcon1 weights must sum to 1")
    if not str(defcon1.get("trend_symbol") or ""):
        raise ConfigError("routing.defcon1.trend_symbol is required")
    defcon2 = routing.get("defcon2") or {}
    threshold = defcon2.get("brkb_corr_threshold")
    window = defcon2.get("brkb_corr_window")
    if not _number(threshold) or not 0 <= float(threshold) <= 1:
        raise ConfigError("routing.defcon2.brkb_corr_threshold must be in [0,1]")
    if not _positive_int(window):
        raise ConfigError("routing.defcon2.brkb_corr_window must be a positive integer")


def _validate_reentry(config: Dict[str, Any]) -> None:
    reentry = config.get("reentry") or {}
    tranches = reentry.get("tranches")
    if not isinstance(tranches, list) or not tranches:
        raise ConfigError("reentry.tranches must be a non-empty list")
    if any(not _number(value) or float(value) <= 0 for value in tranches):
        raise ConfigError("reentry.tranches values must be positive")
    if abs(sum(float(value) for value in tranches) - 1.0) > 1e-9:
        raise ConfigError("reentry.tranches must sum to 1")
    if not _positive_int(reentry.get("time_lock_days")):
        raise ConfigError("reentry.time_lock_days must be a positive integer")
    for key in ("score_unlock", "c_module_unlock"):
        if not _number(reentry.get(key)) or float(reentry[key]) < 0:
            raise ConfigError(f"reentry.{key} must be non-negative")


def _validate_ibkr(config: Dict[str, Any]) -> None:
    ibkr = config.get("ibkr") or {}
    if not ibkr:
        raise ConfigError("ibkr section is required")
    if ibkr.get("readonly") is not True:
        raise ConfigError("ibkr.readonly must remain true")
    if str(ibkr.get("host") or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("ibkr.host must be loopback")
    ports = ibkr.get("ports")
    if not isinstance(ports, list) or not ports or any(not _positive_int(port) or int(port) > 65535 for port in ports):
        raise ConfigError("ibkr.ports must contain valid TCP ports")
    if not _positive_int(ibkr.get("client_id")):
        raise ConfigError("ibkr.client_id must be a positive integer")
    executions = ibkr.get("executions") or {}
    if executions.get("enabled") and not _positive_int(executions.get("client_id")):
        raise ConfigError("ibkr.executions.client_id must be a positive integer")
    if executions.get("enabled") and int(executions["client_id"]) == int(ibkr["client_id"]):
        raise ConfigError("ibkr.executions.client_id must differ from ibkr.client_id")


def _validate_state_retention(config: Dict[str, Any]) -> None:
    for key, value in (config.get("state_retention") or {}).items():
        if not _positive_int(value):
            raise ConfigError(f"state_retention.{key} must be a positive integer")


def _validate_features(config: Dict[str, Any]) -> None:
    for key, value in (config.get("features") or {}).items():
        if not isinstance(value, bool):
            raise ConfigError(f"features.{key} must be boolean")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _require_symbols(config: Dict[str, Any], symbols: Iterable[str]) -> None:
    missing = [sym for sym in symbols if sym not in config.get("symbols", {})]
    if missing:
        raise ConfigError("Missing symbols: " + ", ".join(missing))


def trade_symbols(config: Dict[str, Any]) -> List[str]:
    return list(config["symbols"].keys())
