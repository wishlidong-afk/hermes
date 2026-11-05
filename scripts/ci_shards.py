"""Deterministic pytest partitions and an independent all-tests completion gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption("--ci-shard-index", type=int)
    parser.addoption("--ci-shard-count", type=int)
    parser.addoption("--ci-shard-report", type=Path)


def pytest_configure(config):
    import pytest

    index = config.getoption("--ci-shard-index")
    count = config.getoption("--ci-shard-count")
    output = config.getoption("--ci-shard-report")
    if index is None or count is None or output is None or not 0 <= index < count:
        raise pytest.UsageError("CI shard requires report and 0 <= index < count")
    config.pluginmanager.register(Shard(config, index, count, output), "ci-shard-recorder")


class Shard:
    def __init__(self, config, index, count, output):
        self.output = output
        self.report = {
            "schema": "hermes-ci-shard-v1", "index": index, "count": count,
            "revision": os.environ.get("GITHUB_SHA", "local"),
            "run": os.environ.get("GITHUB_RUN_ID", "local"),
            "attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "collect_only": config.option.collectonly,
            "collected": [], "selected": [], "phases": [],
        }

    def pytest_collection_modifyitems(self, config, items):
        import pytest

        collected = sorted(item.nodeid for item in items)
        if not collected or len(set(collected)) != len(collected):
            raise pytest.UsageError("CI collection must be nonempty with unique node IDs")
        selected = collected[self.report["index"]::self.report["count"]]
        selected_set = set(selected)
        deselected = [item for item in items if item.nodeid not in selected_set]
        items[:] = [item for item in items if item.nodeid in selected_set]
        config.hook.pytest_deselected(items=deselected)
        self.report.update(collected=collected, selected=selected)

    def pytest_runtest_logreport(self, report):
        self.report["phases"].append({
            "nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
            "seconds": report.duration,
        })

    def pytest_sessionfinish(self, exitstatus):
        self.report["exit_code"] = int(exitstatus)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(self.report, sort_keys=True, indent=2) + "\n")


def verify(inventory_path: Path, directory: Path, count: int) -> dict:
    inventory = json.loads(inventory_path.read_text())
    expected = inventory["collected"]
    if (count < 1 or inventory["schema"] != "hermes-ci-shard-v1"
            or inventory["tool_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            or inventory["exit_code"] != 0 or inventory["collect_only"] is not True
            or not expected or expected != sorted(set(expected))):
        raise ValueError("invalid independent collection inventory")
    paths = sorted(directory.glob("shard-*.json"))
    if len(paths) != count:
        raise ValueError("missing or extra shard reports")
    seen: set[str] = set()
    indices: set[int] = set()
    skipped = 0
    for path in paths:
        row = json.loads(path.read_text())
        index = row["index"]
        if (type(index) is not int or not 0 <= index < count or index in indices
                or row["count"] != count or row["exit_code"] != 0
                or row["collect_only"] is not False
                or any(row[key] != inventory[key] for key in (
                    "schema", "revision", "run", "attempt", "tool_sha256", "collected"))
                or row["selected"] != expected[index::count]):
            raise ValueError(f"invalid shard binding or selection: {path.name}")
        selected = set(row["selected"])
        phases = row["phases"]
        by_node: dict[str, list[tuple[str, str]]] = {node: [] for node in selected}
        for phase in phases:
            if phase["nodeid"] not in by_node or phase["outcome"] not in {"passed", "skipped"}:
                raise ValueError(f"unexpected or failed test phase: {path.name}")
            by_node[phase["nodeid"]].append((phase["when"], phase["outcome"]))
        valid = ([("setup", "passed"), ("call", result), ("teardown", cleanup)]
                 for result in ("passed", "skipped") for cleanup in ("passed", "skipped"))
        allowed = list(valid) + [[("setup", "skipped"), ("teardown", cleanup)]
                                 for cleanup in ("passed", "skipped")]
        if seen & selected or any(sequence not in allowed for sequence in by_node.values()):
            raise ValueError(f"incomplete, repeated or failed tests: {path.name}")
        skipped += sum(p["outcome"] == "skipped" for p in phases)
        indices.add(index)
        seen.update(selected)
    if seen != set(expected):
        raise ValueError("shard union does not cover the independent inventory")
    return {"status": "PASS", "tests": len(expected), "shards": count, "skipped_phases": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.inventory, args.directory, args.count), sort_keys=True))
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f"CI completeness FAIL: {error}\n")


if __name__ == "__main__":
    main()
