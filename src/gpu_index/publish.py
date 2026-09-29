"""Build the static JSON/CSV artifacts the dashboard and MCP server read."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gpu_index import store
from gpu_index.index import SERIES, history, snapshot
from gpu_index.models import FIELDNAMES, Observation
from gpu_index.sources import ADAPTERS

SITE_DATA = store.ROOT / "site" / "data"
RUNS_LOG = store.ROOT / "data" / "runs.jsonl"
STATUS_HISTORY = 30


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def append_run(run: dict[str, Any], log_path: Path = RUNS_LOG) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(run, sort_keys=True) + "\n")


def read_runs(log_path: Path = RUNS_LOG) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


def build(rows: list[Observation] | None = None, out: Path = SITE_DATA) -> dict[str, Any]:
    rows = rows if rows is not None else store.load_all()
    snap = snapshot(rows)
    snap["generated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    snap["sources"] = [
        {"id": a.id, "name": a.name, "homepage": a.homepage, "terms": a.terms}
        for a in ADAPTERS.values()
    ]
    _write_json(out / "latest.json", snap)

    hist = history(rows)
    _write_json(out / "history.json", hist)

    with (out / "index-history.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["date", "gpu_model", "series", "usd_per_gpu_hour"])
        for gpu, series in hist["series"].items():
            for name in SERIES:
                for date, value in zip(hist["dates"], series[name], strict=True):
                    if value is not None:
                        writer.writerow([date, gpu, name, value])

    latest = [o for o in rows if o.date == snap["as_of"]]
    with (out / "observations-latest.csv").open("w", newline="", encoding="utf-8") as fh:
        dict_writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, lineterminator="\n")
        dict_writer.writeheader()
        dict_writer.writerows(o.to_row() for o in latest)

    runs = read_runs()
    _write_json(
        out / "status.json",
        {
            "latest": runs[-1] if runs else None,
            "recent": [
                {"date": r["date"], "ok": r["ok"], "observations": r["observations"]}
                for r in runs[-STATUS_HISTORY:]
            ],
        },
    )
    return snap
