from __future__ import annotations

import re
from typing import Any

from ypervaino.config_loader import load_semantic_methods
from ypervaino.embeddings import nearest_prototype_label
from ypervaino.llm_client import LLMClient
from ypervaino.predicate import eval_predicate


class ConfigError(Exception):
    pass


def _ev(e: dict, key: str, default=None):
    val = e.get("event_value") or {}
    if isinstance(val, dict) and key in val:
        return val[key]
    return e.get(key, default)


def _is_boolean_value_type(sig: dict[str, Any]) -> bool:
    return str(sig.get("value_type") or "").lower() in ("boolean", "bool")


def _rule_based_score(text: str, spec: dict[str, Any]) -> int:
    text = (text or "").lower()
    score = 0
    for kw in spec.get("keywords") or []:
        if (kw or "").lower() in text:
            score += 1
    for pat in spec.get("regex") or []:
        if re.search(pat, text, re.I):
            score += 1
    for nk in spec.get("negative_keywords") or []:
        if (nk or "").lower() in text:
            score -= 1
    return score


def _dialog_searchable_text(fv: dict[str, Any], conversation: dict[str, Any] | None) -> str:
    cached = (fv.get("dialog_searchable_text") or "").strip()
    if cached:
        return cached.lower()
    transcript = (conversation or {}).get("transcript") or []
    if transcript:
        return "\n".join((line.get("text") or "").lower() for line in transcript if line.get("text"))
    return (fv.get("user_searchable_text") or "").lower()


def _opening_turn_text(fv: dict[str, Any]) -> str:
    opening = (fv.get("opening_text") or "").strip().lower()
    if opening:
        return opening
    turns = fv.get("user_turns") or []
    if turns:
        return str(turns[0]).lower()
    user_text = (fv.get("user_searchable_text") or "").strip()
    if user_text:
        return user_text.split("\n", 1)[0].lower()
    return ""


def _rule_based_corpus(
    fv: dict[str, Any],
    spec: dict[str, Any],
    conversation: dict[str, Any] | None,
) -> list[str]:
    scope = (spec.get("scope") or "session").lower()
    if scope == "opening_turns":
        return [_opening_turn_text(fv)]
    if scope == "turn":
        turns = [str(t).lower() for t in (fv.get("user_turns") or []) if str(t).strip()]
        if not turns:
            user_text = (fv.get("user_searchable_text") or "").strip()
            if user_text:
                turns = [line.lower() for line in user_text.split("\n") if line.strip()]
        return turns or [""]
    return [_dialog_searchable_text(fv, conversation)]


class SignalExecutor:
    def __init__(self, plan: dict[str, Any], *, eval_session_count: int):
        self.plan = plan
        self.eval_session_count = eval_session_count
        self.methods = {m: cfg for m, cfg in (load_semantic_methods().get("methods") or {}).items()}
        self._zero_shot_usage: dict[str, int] = {}

    @staticmethod
    def _signal_has_spec(sig: dict[str, Any]) -> bool:
        method = sig.get("method")
        spec = sig.get("spec") or {}
        if method == "intent_classifier":
            return bool(spec.get("intent_id") or spec.get("labels"))
        if method == "embedding_nearest_neighbor":
            return bool(spec.get("labels") or spec.get("prototypes"))
        if method == "rule_based":
            return bool(spec.get("keywords") or spec.get("regex"))
        if method in ("zero_shot_llm", "llm_extract"):
            return bool(spec.get("prompt") or spec.get("labels"))
        return False

    def compute_values(
        self,
        fv: dict[str, Any],
        conversation: dict[str, Any] | None,
        *,
        hypothesis_id: str | None = None,
        counter_example_mode: bool = False,
    ) -> dict[str, Any]:
        values = dict(fv)
        for prim in self.plan.get("primitives_required") or []:
            name = prim.get("name") if isinstance(prim, dict) else prim
            if name and name not in values and name in fv:
                values[name] = fv[name]

        for sig in self.plan.get("signals_required") or []:
            name = sig.get("name") or sig.get("signal")
            if not name:
                continue
            # Plans often list primitives as rule_based signals with no spec — keep feature value.
            if not self._signal_has_spec(sig) and name in fv:
                continue
            result = self._run_signal(sig, fv, conversation, hypothesis_id, counter_example_mode)
            if result is None:
                continue
            # Never replace a numeric/bool primitive with a rule_based label fallback.
            if (
                name in fv
                and isinstance(fv[name], (int, float, bool))
                and isinstance(result, str)
                and sig.get("method") == "rule_based"
            ):
                continue
            values[name] = result

        for cs in self.plan.get("classical_signals_required") or []:
            name = cs.get("name")
            if name:
                values[name] = self._run_classical(cs, fv, conversation)
        return values

    def _run_classical(self, spec: dict, fv: dict, conversation: dict | None) -> Any:
        kind = spec.get("kind")
        events = (conversation or {}).get("events") or []
        transcript = (conversation or {}).get("transcript") or []
        if kind == "agent_path_label":
            return fv.get("agent_path")
        if kind == "regex_on_transcript":
            pattern = spec.get("pattern") or (spec.get("spec") or {}).get("pattern")
            if not pattern:
                return False
            text = fv.get("searchable_text") or ""
            return bool(re.search(pattern, text, re.I))
        if kind == "turn_index":
            needle = (spec.get("spec") or {}).get("contains") or spec.get("contains")
            if not needle:
                return -1
            for i, line in enumerate(transcript):
                if needle.lower() in (line.get("text") or "").lower():
                    return i
            return -1
        if kind == "conditional_metadata":
            et = spec.get("event_type")
            field = spec.get("field")
            for e in events:
                if e.get("event_type") == et:
                    val = _ev(e, field) if field else e.get("event_value")
                    if val is not None:
                        return val
            return None
        if kind == "duration_between":
            a, b = spec.get("event_type_a"), spec.get("event_type_b")
            ts_a = ts_b = None
            for e in events:
                if e.get("event_type") == a and ts_a is None:
                    ts_a = e.get("timestamp")
                if e.get("event_type") == b:
                    ts_b = e.get("timestamp")
            if ts_a and ts_b:
                from datetime import datetime
                try:
                    da = datetime.fromisoformat(str(ts_a).replace("Z", "+00:00"))
                    db = datetime.fromisoformat(str(ts_b).replace("Z", "+00:00"))
                    return int((db - da).total_seconds() * 1000)
                except Exception:
                    return None
            return None
        return None

    def _run_signal(
        self,
        sig: dict,
        fv: dict,
        conversation: dict | None,
        hypothesis_id: str | None,
        counter_example_mode: bool,
    ) -> Any:
        method = sig.get("method")
        spec = sig.get("spec") or {}
        cfg = self.methods.get(method) or {}

        if method == "intent_classifier":
            target = spec.get("intent_id")
            return fv.get("opening_intent_class") == target if target else fv.get("opening_intent_class")

        if method == "rule_based":
            spec = sig.get("spec") or {}
            min_hits = int(spec.get("min_hits") or 1)
            corpora = _rule_based_corpus(fv, spec, conversation)
            matched = any(_rule_based_score(text, spec) >= min_hits for text in corpora)
            labels = spec.get("labels") or ["match", "other"]
            if _is_boolean_value_type(sig):
                return 1 if matched else 0
            if matched:
                return labels[0]
            return labels[-1] if len(labels) > 1 else False

        if method == "embedding_nearest_neighbor":
            prototypes = spec.get("labels") or spec.get("prototypes") or []
            return nearest_prototype_label(
                fv.get("searchable_text") or "",
                prototypes,
                float(spec.get("min_similarity") or 0.35),
            )

        if method == "zero_shot_llm":
            cap = int(cfg.get("max_sessions_per_hypothesis") or 200)
            hid = hypothesis_id or sig.get("name") or "default"
            self._zero_shot_usage[hid] = self._zero_shot_usage.get(hid, 0) + 1
            if not counter_example_mode and self._zero_shot_usage[hid] > cap and cfg.get("error_if_full_deval"):
                raise ConfigError(f"zero_shot_llm cap exceeded for {hid}")
            prompt = spec.get("prompt") or "Classify this conversation."
            labels = spec.get("labels") or ["yes", "no"]
            snippet = (fv.get("searchable_text") or "")[:3000]
            out = LLMClient().json_completion(
                f"{prompt}\nLabels: {labels}\nTranscript excerpt:\n{snippet}\nReturn JSON {{\"label\": one of labels}}",
                schema_name="zero_shot_label",
            )
            return out.get("label") or labels[-1]

        if method == "llm_extract":
            if not counter_example_mode:
                return None
            prompt = spec.get("prompt") or "Extract field from transcript."
            snippet = (fv.get("searchable_text") or "")[:4000]
            out = LLMClient().json_completion(
                f"{prompt}\nReturn JSON {{\"value\": ...}}\nTranscript:\n{snippet}",
                schema_name="llm_extract_value",
            )
            return out.get("value")

        return None


def eval_hypothesis(predicate: Any, values: dict[str, Any]) -> bool:
    return eval_predicate(predicate, values)
