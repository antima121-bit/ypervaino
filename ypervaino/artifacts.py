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
    paths: dict[str, str] = {}
    aspect_rows = []
    for a in result.get("aspects") or []:
        if is_comparative:
            aspect_rows.append([
                a.get("id"), a.get("name"), a.get("before"), a.get("after"), a.get("delta_pct"),
                (a.get("proof") or {}).get("p_value"), (a.get("proof") or {}).get("significant"),
            ])
        else:
            aspect_rows.append([a.get("id"), a.get("name"), a.get("value", a.get("before"))])
    aspect_path = output_dir / "tables" / "aspect_summary.csv"
    if is_comparative:
        _write_csv(aspect_path, ["aspect_id", "name", "before", "after", "delta_pct", "p_value", "significant"], aspect_rows)
    else:
        _write_csv(aspect_path, ["aspect_id", "name", "value"], aspect_rows)
    paths["aspect_summary"] = "tables/aspect_summary.csv"

    hyp_rows = []
    for h in result.get("hypotheses") or []:
        rates = h.get("rates") or {}
        if is_comparative:
            b, a = rates.get("before") or {}, rates.get("after") or {}
            hyp_rows.append([h.get("id"), h.get("title"), b.get("support"), round(b.get("rate") or 0, 4),
                             a.get("support"), round(a.get("rate") or 0, 4), h.get("rejected"),
                             (h.get("proof") or {}).get("p_value")])
        else:
            all_rate = rates.get("all") or {}
            hyp_rows.append([h.get("id"), h.get("title"), all_rate.get("support"), round(all_rate.get("rate") or 0, 4), h.get("rejected")])
    hyp_path = output_dir / "tables" / "hypothesis_summary.csv"
    if is_comparative:
        _write_csv(hyp_path, ["hypothesis_id", "title", "before_support", "before_rate", "after_support", "after_rate", "rejected", "p_value"], hyp_rows)
    else:
        _write_csv(hyp_path, ["hypothesis_id", "title", "support", "rate", "rejected"], hyp_rows)
    paths["hypothesis_summary"] = "tables/hypothesis_summary.csv"
    return paths


def render_plots(output_dir: Path, result: dict[str, Any], plan: dict[str, Any], is_comparative: bool) -> dict[str, str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {}

    paths: dict[str, str] = {}
    aspects = result.get("aspects") or []
    hypotheses = result.get("hypotheses") or []
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    if is_comparative and aspects:
        names = [a.get("name") or a.get("id") for a in aspects]
        before = [a.get("before", 0) for a in aspects]
        after = [a.get("after", 0) for a in aspects]
        x = range(len(names))
        w = 0.35
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar([i - w / 2 for i in x], before, width=w, label="before")
        ax.bar([i + w / 2 for i in x], after, width=w, label="after")
        ax.set_xticks(list(x))
        ax.set_xticklabels(names, rotation=30, ha="right")
        ax.legend()
        fig.tight_layout()
        p = plots_dir / "aspect_before_after_bar.png"
        fig.savefig(p)
        plt.close(fig)
        paths["aspect_before_after_bar"] = "plots/aspect_before_after_bar.png"

        fig, ax = plt.subplots(figsize=(8, 4))
        deltas = [a.get("delta_pct", 0) for a in aspects]
        ax.barh(names, deltas)
        fig.tight_layout()
        p = plots_dir / "aspect_delta_lollipop.png"
        fig.savefig(p)
        plt.close(fig)
        paths["aspect_delta_lollipop"] = "plots/aspect_delta_lollipop.png"

    if hypotheses and is_comparative:
        names = [h.get("title") or h.get("id") for h in hypotheses]
        b_rates = [(h.get("rates") or {}).get("before", {}).get("rate", 0) * 100 for h in hypotheses]
        a_rates = [(h.get("rates") or {}).get("after", {}).get("rate", 0) * 100 for h in hypotheses]
        x = range(len(names))
        w = 0.35
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar([i - w / 2 for i in x], b_rates, width=w, label="before")
        ax.bar([i + w / 2 for i in x], a_rates, width=w, label="after")
        ax.set_xticklabels(names, rotation=30, ha="right")
        ax.set_xticks(list(x))
        ax.set_ylabel("match rate %")
        ax.legend()
        fig.tight_layout()
        p = plots_dir / "hypothesis_rate_comparison.png"
        fig.savefig(p)
        plt.close(fig)
        paths["hypothesis_rate_comparison"] = "plots/hypothesis_rate_comparison.png"

    return paths
