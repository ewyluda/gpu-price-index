"""Data-as-code storage: one CSV per day under ``data/observations/YYYY/``.

Plain CSV keeps every day's prices reviewable in a pull-request diff and gives the
dataset a public, auditable history in git. Re-running a source on the same day
replaces that source's rows, so collection is idempotent.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from pathlib import Path

from gpu_index.models import FIELDNAMES, Observation

ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.environ.get("GPU_INDEX_DATA_DIR", ROOT / "data" / "observations"))


def path_for(date: str, base: Path | None = None) -> Path:
    base = base or data_dir()
    return base / date[:4] / f"{date}.csv"


def read_day(date: str, base: Path | None = None) -> list[Observation]:
    path = path_for(date, base)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [Observation.from_row(row) for row in csv.DictReader(fh)]


def write_day(
    date: str,
    observations: Iterable[Observation],
    replace_sources: set[str],
    base: Path | None = None,
) -> Path:
    """Merge ``observations`` into the day file, replacing rows from ``replace_sources``."""
    kept = [o for o in read_day(date, base) if o.source not in replace_sources]
    merged = {o.key: o for o in [*kept, *observations]}
    rows = sorted(merged.values(), key=lambda o: o.key)

    path = path_for(date, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(o.to_row() for o in rows)
    return path


def dates(base: Path | None = None) -> list[str]:
    base = base or data_dir()
    return sorted(p.stem for p in base.glob("*/*.csv"))


def load_all(base: Path | None = None, since: str | None = None) -> list[Observation]:
    rows: list[Observation] = []
    for date in dates(base):
        if since is None or date >= since:
            rows.extend(read_day(date, base))
    return rows
