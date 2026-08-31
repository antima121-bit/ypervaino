from __future__ import annotations

import re
from typing import Any


def normalize_hypothesis_predicate(predicate: Any, hyp: dict[str, Any] | None = None) -> Any:
    """Convert LLM SQL-style cohort predicates to per-session evaluable form."""
    if not isinstance(predicate, str):
        return predicate

    s = predicate.strip()
    lower = s.lower()
    title = ((hyp or {}).get("title") or "").lower()
    desc = ((hyp or {}).get("description") or "").lower()
    text = f"{title} {desc}"

    # Already a simple per-session predicate.
    if " when " not in lower and "mean(" not in lower and not lower.startswith("rate("):
        return s

    if "interruption" in text and "transfer" in text:
        return "interruption_count >= 2 and transfer_count > 0"
    if "guardrail" in text and "transfer" in text:
        return "guardrail_triggered > 0 and transfer_count > 0"
    if ("tool" in text or "llm error" in text or "error" in text) and "payment" in text:
        return "tool_error_count > 0 and payment_success_rate == 0"

    if " when " in lower:
        _left, right = re.split(r"\s+when\s+", s, maxsplit=1, flags=re.I)
        right = right.strip().lower()
        if "transfer" in right:
            cond = "transfer_count > 0"
        elif "payment" in right:
            cond = "payment_success_rate == 1"
        else:
            cond = "transfer_count > 0"
        if "interruption" in lower:
            return f"interruption_count >= 2 and {cond}"
        if "guardrail" in lower:
            return f"guardrail_triggered > 0 and {cond}"
        if "tool" in lower or "error" in lower:
            return f"tool_error_count > 0 and payment_success_rate == 0"

    return s
