from pathlib import Path

from gpu_index import store
from gpu_index.validate import Report, check_drift, screen_source
from tests.conftest import make_obs


def test_write_day_is_idempotent_and_replaces_only_named_sources(tmp_path: Path) -> None:
    a1 = make_obs(source="a", provider="A", usd_per_gpu_hour=2.0)
    b1 = make_obs(source="b", provider="B", usd_per_gpu_hour=3.0)
    store.write_day("2026-09-28", [a1, b1], {"a", "b"}, base=tmp_path)
    store.write_day("2026-09-28", [a1, b1], {"a", "b"}, base=tmp_path)
    assert len(store.read_day("2026-09-28", base=tmp_path)) == 2

    a2 = make_obs(source="a", provider="A", usd_per_gpu_hour=2.5)
    store.write_day("2026-09-28", [a2], {"a"}, base=tmp_path)
    by_source = {o.source: o.usd_per_gpu_hour for o in store.read_day("2026-09-28", base=tmp_path)}
    assert by_source == {"a": 2.5, "b": 3.0}


def test_failed_source_keeps_earlier_same_day_rows(tmp_path: Path) -> None:
    store.write_day("2026-09-28", [make_obs(source="a")], {"a"}, base=tmp_path)
    store.write_day("2026-09-28", [], set(), base=tmp_path)  # source "a" failed this time
    assert len(store.read_day("2026-09-28", base=tmp_path)) == 1


def test_round_trip_preserves_values(tmp_path: Path) -> None:
    original = make_obs(gpu_count=8, usd_per_gpu_hour=12.29, sample_size=3)
    store.write_day(original.date, [original], {original.source}, base=tmp_path)
    assert store.read_day(original.date, base=tmp_path) == [original]
    assert store.dates(base=tmp_path) == ["2026-09-28"]


def test_screen_source_drops_bad_rows_and_rejects_thin_sources() -> None:
    report = Report()
    rows = [
        make_obs(usd_per_gpu_hour=2.0),
        make_obs(sku="x", usd_per_gpu_hour=500.0),  # out of bounds
        make_obs(sku="y", gpu_model="RTX 4090"),  # unknown model
    ]
    assert screen_source("test", rows, min_rows=1, report=report) == [rows[0]]
    assert any("outside" in e for e in report.errors)
    assert any("unknown gpu_model" in e for e in report.errors)

    thin = Report()
    assert screen_source("test", rows, min_rows=2, report=thin) is None
    assert any("keeping previous data" in e for e in thin.errors)


def test_check_drift_warns_on_big_moves_and_missing_providers() -> None:
    previous = [make_obs(usd_per_gpu_hour=2.0), make_obs(provider="Gone", usd_per_gpu_hour=3.0)]
    report = Report()
    check_drift(previous, [make_obs(usd_per_gpu_hour=3.5)], report)
    assert report.ok
    assert any("+75%" in w for w in report.warnings)
    assert any(w.startswith("Gone: listed yesterday") for w in report.warnings)


def test_clean_fixture_data_passes_every_gate(fixture_rows: list) -> None:
    report = Report()
    for source in {o.source for o in fixture_rows}:
        rows = [o for o in fixture_rows if o.source == source]
        assert screen_source(source, rows, min_rows=1, report=report) == rows
    check_drift(fixture_rows, fixture_rows, report)
    assert report.ok and not report.warnings
