from pathlib import Path

from gpu_index import store
from gpu_index.validate import validate
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


def test_validate_flags_bad_rows_low_volume_and_drift() -> None:
    previous = [make_obs(usd_per_gpu_hour=2.0)]
    current = [
        make_obs(usd_per_gpu_hour=3.5),  # +75% vs yesterday -> warning
        make_obs(sku="x", usd_per_gpu_hour=500.0),  # out of bounds -> error
        make_obs(sku="y", gpu_model="RTX 4090"),  # unknown model -> error
    ]
    report = validate(current, previous, min_rows={"test": 3, "missing": 1})
    assert not report.ok
    assert any("outside" in e for e in report.errors)
    assert any("unknown gpu_model" in e for e in report.errors)
    assert any(e.startswith("missing: 0 rows") for e in report.errors)
    assert len(report.warnings) == 1 and "+" in report.warnings[0]


def test_validate_passes_clean_fixture_data(fixture_rows: list) -> None:
    report = validate(fixture_rows, fixture_rows, min_rows={"azure": 10})
    assert report.ok and not report.warnings
