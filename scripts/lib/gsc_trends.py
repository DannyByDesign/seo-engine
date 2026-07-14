"""Statistically honest trend analysis over GSC time-series rows.

Extracted from seo-rank-tracking so seo-maintain (and any other skill) can
reuse the same drop-detection methodology instead of inventing a naive
window-vs-window comparison: impression-weighted weekly buckets smooth
day-to-day noise, and a drop is flagged only when it exceeds BOTH an
absolute threshold and the baseline's own week-to-week standard deviation —
ordinary volatility on a low-volume query is not a finding.

Input rows: {"key", "date" (ISO), "clicks", "impressions", "position"}.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any, Optional


def weekly_series(
    rows: list[dict[str, Any]],
    *,
    window_end: Optional[date] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Group rows by key into chronological ISO-week buckets of
    {week_start, impressions, clicks, avg_position} where avg_position is
    impression-weighted (a high-impression day influences the weekly average
    more than a near-zero-impression day with a noisy position value).

    When `window_end` is given, a trailing bucket whose week is not yet
    complete at window_end is dropped — a 1-3-day "week" average is not
    comparable to full-week baselines.
    """
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(row["key"], []).append(row)

    series: dict[str, list[dict[str, Any]]] = {}
    for key, key_rows in by_key.items():
        buckets: dict[str, dict[str, Any]] = {}
        for row in key_rows:
            d = date.fromisoformat(row["date"])
            week_start = (d - timedelta(days=d.weekday())).isoformat()
            b = buckets.setdefault(week_start, {
                "week_start": week_start,
                "impressions": 0, "clicks": 0,
                "_weighted_position_sum": 0.0,
            })
            b["impressions"] += row["impressions"]
            b["clicks"] += row["clicks"]
            weight = max(row["impressions"], 1)
            b["_weighted_position_sum"] += row["position"] * weight

        weeks = []
        for b in buckets.values():
            weight_total = max(b["impressions"], 1)
            weeks.append({
                "week_start": b["week_start"],
                "impressions": b["impressions"],
                "clicks": b["clicks"],
                "avg_position": round(b["_weighted_position_sum"] / weight_total, 2),
            })
        weeks.sort(key=lambda w: w["week_start"])

        if window_end is not None and weeks:
            last_start = date.fromisoformat(weeks[-1]["week_start"])
            if last_start + timedelta(days=6) > window_end:
                weeks = weeks[:-1]

        if weeks:
            series[key] = weeks
    return series


def detect_drops(
    series: dict[str, list[dict[str, Any]]],
    *,
    baseline_weeks: int = 4,
    drop_threshold: float = 3.0,
    min_impressions: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare each key's latest complete week against the mean of the prior
    `baseline_weeks` weeks. Returns (drops, improvements), each entry carrying
    the baseline stats so a consumer can show *why* it was flagged.

    Flag condition: |delta| >= drop_threshold AND (baseline has no stdev, or
    |delta| > baseline stdev). Positive delta = position number got worse.
    """
    drops: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []

    for key, weeks in series.items():
        if len(weeks) < 2:
            continue
        latest_week = weeks[-1]
        baseline_pool = weeks[max(0, len(weeks) - 1 - baseline_weeks):-1]
        if not baseline_pool:
            continue
        if latest_week["impressions"] < min_impressions:
            continue

        baseline_positions = [w["avg_position"] for w in baseline_pool]
        baseline_avg = round(statistics.mean(baseline_positions), 2)
        baseline_stdev = (round(statistics.pstdev(baseline_positions), 2)
                          if len(baseline_positions) > 1 else 0.0)
        delta = round(latest_week["avg_position"] - baseline_avg, 2)

        entry = {
            "key": key,
            "latest_week_start": latest_week["week_start"],
            "latest_position": latest_week["avg_position"],
            "latest_week_impressions": latest_week["impressions"],
            "baseline_avg_position": baseline_avg,
            "baseline_stdev": baseline_stdev,
            "baseline_weeks_used": len(baseline_pool),
            "position_delta": delta,
        }

        meaningful = abs(delta) >= drop_threshold and (
            baseline_stdev == 0.0 or abs(delta) > baseline_stdev
        )
        if meaningful and delta > 0:
            drops.append(entry)
        elif meaningful and delta < 0:
            improvements.append(entry)

    drops.sort(key=lambda e: -e["position_delta"])
    improvements.sort(key=lambda e: e["position_delta"])
    return drops, improvements
