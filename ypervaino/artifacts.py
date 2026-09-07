from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


def _write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def _safe_plot_filename(plot_id: str) -> str:
    return re.sub(r"[^\w\-]", "_", plot_id or "plot") + ".png"


def _load_per_conversation_rows(output_dir: Path) -> list[dict[str, Any]]:
    pc_dir = output_dir / "per_conversation"
    if not pc_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in pc_dir.glob("*.json"):
        try:
            rows.append(json.loads(path.read_text()))
        except Exception:
            continue
    return rows


def _metric_values(rows: list[dict[str, Any]], metric_name: str) -> list[float]:
    vals: list[float] = []
    for row in rows:
        raw = (row.get("values") or {}).get(metric_name)
        if isinstance(raw, bool):
            vals.append(1.0 if raw else 0.0)
        elif isinstance(raw, (int, float)):
            vals.append(float(raw))
    return vals


def _grouped_metric_values(
    rows: list[dict[str, Any]], metric_name: str, group_by: str | None
) -> dict[str, list[float]]:
    if not group_by:
        return {"all": _metric_values(rows, metric_name)}
    grouped: dict[str, list[float]] = {}
    for row in rows:
        values = row.get("values") or {}
        group_key = str(values.get(group_by) or "unknown")
        raw = values.get(metric_name)
        if isinstance(raw, bool):
            grouped.setdefault(group_key, []).append(1.0 if raw else 0.0)
        elif isinstance(raw, (int, float)):
            grouped.setdefault(group_key, []).append(float(raw))
    return grouped


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
    aspect_by_id = {a.get("id"): a for a in aspects}
    hyp_by_id = {h.get("id"): h for h in hypotheses}
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    per_conv = _load_per_conversation_rows(output_dir)

    suggested = (plan.get("quantitative") or {}).get("suggested_plots") or []
    if not suggested and is_comparative and aspects:
        suggested = [
            {"id": "aspect_before_after_bar", "template": "aspect_before_after_bar", "bindings": {"aspect_ids": [a.get("id") for a in aspects if a.get("id")]}},
            {"id": "aspect_delta_lollipop", "template": "aspect_delta_lollipop", "bindings": {"aspect_ids": [a.get("id") for a in aspects if a.get("id")]}},
        ]
        if hypotheses:
            suggested.append({
                "id": "hypothesis_rate_comparison",
                "template": "hypothesis_rate_comparison",
                "bindings": {"hypothesis_ids": [h.get("id") for h in hypotheses if h.get("id")]},
            })

    for plot_spec in suggested:
        plot_id = plot_spec.get("id") or plot_spec.get("template") or "plot"
        template = plot_spec.get("template") or ""
        bindings = plot_spec.get("bindings") or {}
        title = plot_spec.get("title") or plot_id.replace("_", " ")
        filename = _safe_plot_filename(plot_id)
        rel_path = f"plots/{filename}"

        if template == "aspect_before_after_bar" and is_comparative:
            aspect_ids = bindings.get("aspect_ids") or [a.get("id") for a in aspects]
            selected = [aspect_by_id[aid] for aid in aspect_ids if aid in aspect_by_id and not aspect_by_id[aid].get("no_data")]
            if not selected:
                continue
            names = [a.get("name") or a.get("id") for a in selected]
            before = [a.get("before", 0) for a in selected]
            after = [a.get("after", 0) for a in selected]
            x = range(len(names))
            w = 0.35
            fig, ax = plt.subplots(figsize=(max(8, len(names) * 0.8), 5))
            ax.bar([i - w / 2 for i in x], before, width=w, label="before")
            ax.bar([i + w / 2 for i in x], after, width=w, label="after")
            ax.set_xticks(list(x))
            ax.set_xticklabels(names, rotation=30, ha="right")
            ax.set_title(title)
            ax.legend()
            fig.tight_layout()
            fig.savefig(plots_dir / filename)
            plt.close(fig)
            paths[plot_id] = rel_path
            continue

        if template == "aspect_delta_lollipop" and is_comparative:
            aspect_ids = bindings.get("aspect_ids") or [a.get("id") for a in aspects]
            selected = [aspect_by_id[aid] for aid in aspect_ids if aid in aspect_by_id and not aspect_by_id[aid].get("no_data")]
            if not selected:
                continue
            names = [a.get("name") or a.get("id") for a in selected]
            deltas = [a.get("delta_pct", 0) for a in selected]
            fig, ax = plt.subplots(figsize=(max(8, len(names) * 0.5), 4))
            ax.barh(names, deltas)
            ax.set_title(title)
            fig.tight_layout()
            fig.savefig(plots_dir / filename)
            plt.close(fig)
            paths[plot_id] = rel_path
            continue

        if template == "aspect_single_cohort_bar":
            aspect_ids = bindings.get("aspect_ids") or [a.get("id") for a in aspects]
            names: list[str] = []
            values: list[float] = []
            for aid in aspect_ids:
                a = aspect_by_id.get(aid)
                if not a or a.get("no_data"):
                    continue
                val = a.get("value")
                if val is None:
                    val = a.get("after")
                if val is None:
                    continue
                names.append(a.get("name") or aid)
                values.append(float(val))
            if not names:
                continue
            fig, ax = plt.subplots(figsize=(max(8, len(names) * 0.8), 5))
            ax.bar(range(len(names)), values, color="#f07400", alpha=0.85)
            ax.set_title(title)
            ax.set_xticks(range(len(names)))
            ax.set_xticklabels(names, rotation=30, ha="right")
            fig.tight_layout()
            fig.savefig(plots_dir / filename)
            plt.close(fig)
            paths[plot_id] = rel_path
            continue

        if template == "hypothesis_rate_comparison":
            hyp_ids = bindings.get("hypothesis_ids") or [h.get("id") for h in hypotheses]
            selected = [hyp_by_id[hid] for hid in hyp_ids if hid in hyp_by_id]
            if not selected:
                continue
            names = [h.get("title") or h.get("id") for h in selected]
            if is_comparative:
                b_rates = [(h.get("rates") or {}).get("before", {}).get("rate", 0) * 100 for h in selected]
                a_rates = [(h.get("rates") or {}).get("after", {}).get("rate", 0) * 100 for h in selected]
                x = range(len(names))
                w = 0.35
                fig, ax = plt.subplots(figsize=(max(10, len(names) * 0.55), 5))
                ax.bar([i - w / 2 for i in x], b_rates, width=w, label="before")
                ax.bar([i + w / 2 for i in x], a_rates, width=w, label="after")
                ax.set_xticks(list(x))
                ax.set_xticklabels(names, rotation=35, ha="right", fontsize=8)
                ax.set_ylabel("match rate %")
                ax.legend()
            else:
                rates = [(h.get("rates") or {}).get("all", {}).get("rate", 0) * 100 for h in selected]
                fig, ax = plt.subplots(figsize=(max(10, len(names) * 0.55), 5))
                ax.bar(range(len(names)), rates, color="#f07400", alpha=0.85)
                ax.set_xticks(range(len(names)))
                ax.set_xticklabels(names, rotation=35, ha="right", fontsize=8)
                ax.set_ylabel("match rate %")
            ax.set_title(title)
            fig.tight_layout()
            fig.savefig(plots_dir / filename)
            plt.close(fig)
            paths[plot_id] = rel_path
            continue

        if template == "distribution_histogram":
            metric_name = bindings.get("metric_name")
            if not metric_name:
                continue
            group_by = bindings.get("group_by")
            bins = int(bindings.get("bins") or 20)
            grouped = _grouped_metric_values(per_conv, metric_name, group_by)
            if not any(grouped.values()):
                continue
            fig, ax = plt.subplots(figsize=(8, 4))
            if len(grouped) == 1:
                ax.hist(next(iter(grouped.values())), bins=bins, color="#f07400", alpha=0.85)
            else:
                for label, vals in grouped.items():
                    if vals:
                        ax.hist(vals, bins=bins, alpha=0.55, label=str(label))
                ax.legend(fontsize=8)
            ax.set_title(title)
            ax.set_xlabel(metric_name)
            ax.set_ylabel("sessions")
            fig.tight_layout()
            fig.savefig(plots_dir / filename)
            plt.close(fig)
            paths[plot_id] = rel_path

    return paths
