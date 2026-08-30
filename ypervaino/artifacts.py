from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def render_tables(output_dir: Path, result: dict[str, Any], is_comparative: bool) -> dict[str, str]:
    """Write CSV table artifacts; returns relative paths under output/."""
    paths: dict[str, str] = {}

    aspect_rows = []
    for a in result.get("aspects") or []:
        if is_comparative:
            aspect_rows.append([
                a.get("id") or a.get("name"),
                a.get("name"),
                a.get("before"),
                a.get("after"),
                a.get("delta_pct"),
                a.get("good_if"),
            ])
        else:
            aspect_rows.append([
                a.get("id") or a.get("name"),
                a.get("name"),
                a.get("value", a.get("before")),
            ])

    aspect_path = output_dir / "tables" / "aspect_summary.csv"
    if is_comparative:
        _write_csv(aspect_path, ["aspect_id", "name", "before", "after", "delta_pct", "good_if"], aspect_rows)
    else:
        _write_csv(aspect_path, ["aspect_id", "name", "value"], aspect_rows)
    paths["aspect_summary"] = "tables/aspect_summary.csv"

    hyp_rows = []
    for h in result.get("hypotheses") or []:
        rates = h.get("rates") or {}
        if is_comparative:
            b = rates.get("before") or {}
            a = rates.get("after") or {}
            hyp_rows.append([
                h.get("id"),
                h.get("title"),
                b.get("support"),
                round(b.get("rate") or 0, 4),
                a.get("support"),
                round(a.get("rate") or 0, 4),
                h.get("rejected"),
            ])
        else:
            all_rate = rates.get("all") or {}
            hyp_rows.append([
                h.get("id"),
                h.get("title"),
                all_rate.get("support"),
                round(all_rate.get("rate") or 0, 4),
                h.get("rejected"),
            ])

    hyp_path = output_dir / "tables" / "hypothesis_summary.csv"
    if is_comparative:
        _write_csv(
            hyp_path,
            ["hypothesis_id", "title", "before_support", "before_rate", "after_support", "after_rate", "rejected"],
            hyp_rows,
        )
    else:
        _write_csv(hyp_path, ["hypothesis_id", "title", "support", "rate", "rejected"], hyp_rows)
    paths["hypothesis_summary"] = "tables/hypothesis_summary.csv"

    return paths
