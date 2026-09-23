"""Tests for scripts.lib.gsc_trends: weekly bucketing and drop detection."""

from __future__ import annotations

from datetime import date

from scripts.lib import gsc_trends

W1, W2 = "2024-01-01", "2024-01-08"


def row(day: str, *, key: str = "q", clicks: int = 0, impressions: int = 0,
        position: float = 1.0) -> dict:
    return {"key": key, "date": day, "clicks": clicks,
            "impressions": impressions, "position": position}


def wk(start: str, pos: float, impressions: int = 100) -> dict:
    return {"week_start": start, "impressions": impressions, "clicks": 0,
            "avg_position": pos}


def test_rows_bucket_into_iso_weeks_chronologically():
    rows = [
        row("2024-01-08", clicks=3, impressions=40, position=7.0),
        row("2024-01-01", clicks=1, impressions=30, position=5.0),
        row("2024-01-02", clicks=2, impressions=20, position=5.0),
    ]
    series = gsc_trends.weekly_series(rows)
    weeks = series["q"]
    assert [w["week_start"] for w in weeks] == [W1, W2]
    assert weeks[0]["impressions"] == 50
    assert weeks[0]["clicks"] == 3
    assert weeks[1] == {"week_start": W2, "impressions": 40, "clicks": 3,
                        "avg_position": 7.0}


def test_avg_position_is_impression_weighted():
    rows = [
        row("2024-01-01", impressions=90, position=5.0),
        row("2024-01-02", impressions=10, position=10.0),
    ]
    series = gsc_trends.weekly_series(rows)
    assert series["q"][0]["avg_position"] == 5.5


def test_zero_impression_day_gets_weight_one():
    rows = [
        row("2024-01-01", impressions=0, position=100.0),
        row("2024-01-02", impressions=99, position=1.0),
    ]
    series = gsc_trends.weekly_series(rows)
    assert series["q"][0]["avg_position"] == 2.01
    assert series["q"][0]["impressions"] == 99


def test_window_end_trims_partial_trailing_week():
    rows = [
        row("2024-01-01", impressions=10, position=5.0),
        row("2024-01-08", impressions=10, position=9.0),
        row("2024-01-09", impressions=10, position=9.0),
    ]
    series = gsc_trends.weekly_series(rows, window_end=date(2024, 1, 9))
    weeks = series["q"]
    assert [w["week_start"] for w in weeks] == [W1]


def test_window_end_keeps_complete_trailing_week():
    rows = [
        row("2024-01-01", impressions=10, position=5.0),
        row("2024-01-08", impressions=10, position=9.0),
    ]
    series = gsc_trends.weekly_series(rows, window_end=date(2024, 1, 14))
    assert [w["week_start"] for w in series["q"]] == [W1, W2]


def test_key_empty_after_trim_is_omitted():
    rows = [
        row("2024-01-08", key="partial-only", impressions=10, position=5.0),
        row("2024-01-01", key="solid", impressions=10, position=5.0),
    ]
    series = gsc_trends.weekly_series(rows, window_end=date(2024, 1, 9))
    assert "partial-only" not in series
    assert "solid" in series


def test_drop_flagged_when_delta_beats_threshold_and_stdev():
    series = {"q": [wk(f"2024-01-{d:02d}", 5.0) for d in (1, 8, 15, 22)]
              + [wk("2024-01-29", 10.0)]}
    drops, improvements = gsc_trends.detect_drops(series)
    assert improvements == []
    (entry,) = drops
    assert entry["key"] == "q"
    assert entry["baseline_avg_position"] == 5.0
    assert entry["baseline_stdev"] == 0.0
    assert entry["position_delta"] == 5.0
    assert entry["latest_week_start"] == "2024-01-29"
    assert entry["latest_position"] == 10.0
    assert entry["baseline_weeks_used"] == 4


def test_wobble_within_stdev_not_flagged_even_if_over_threshold():
    series = {"q": [wk(W1, 2.0), wk(W2, 10.0), wk("2024-01-15", 2.0),
                    wk("2024-01-22", 10.0), wk("2024-01-29", 10.0)]}
    drops, improvements = gsc_trends.detect_drops(series)
    assert drops == [] and improvements == []


def test_improvement_lands_in_improvements():
    series = {"q": [wk(W1, 10.0), wk(W2, 10.0), wk("2024-01-15", 10.0),
                    wk("2024-01-22", 5.0)]}
    drops, improvements = gsc_trends.detect_drops(series)
    assert drops == []
    (entry,) = improvements
    assert entry["position_delta"] == -5.0
    assert entry["baseline_avg_position"] == 10.0


def test_min_impressions_floor_skips_low_volume_latest_week():
    series = {"q": [wk(W1, 5.0), wk(W2, 5.0),
                    wk("2024-01-15", 50.0, impressions=5)]}
    drops, improvements = gsc_trends.detect_drops(series, min_impressions=10)
    assert drops == [] and improvements == []


def test_fewer_than_two_weeks_skipped():
    series = {"q": [wk(W1, 5.0)]}
    assert gsc_trends.detect_drops(series) == ([], [])


def test_sort_orders_largest_drop_and_biggest_improvement_first():
    def key_series(latest: float) -> list[dict]:
        return [wk(W1, 10.0), wk(W2, 10.0), wk("2024-01-15", 10.0),
                wk("2024-01-22", latest)]

    series = {
        "small-drop": key_series(14.0),
        "big-drop": key_series(18.0),
        "small-gain": key_series(6.0),
        "big-gain": key_series(2.0),
    }
    drops, improvements = gsc_trends.detect_drops(series)
    assert [e["key"] for e in drops] == ["big-drop", "small-drop"]
    assert [e["key"] for e in improvements] == ["big-gain", "small-gain"]
