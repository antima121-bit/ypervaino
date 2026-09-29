"""Session discovery for analysis_tool from config.yaml scope."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from pymongo import MongoClient

logger = logging.getLogger(__name__)

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
from blueprint_fetch import write_va_blueprint_to_study  # noqa: E402
from deep_union import write_deep_union_over_parsed_traces  # noqa: E402
from pipeline_summary import build_pipeline_summary, log_pipeline_summary  # noqa: E402
from hypothesis_eval import run_hypothesis_evaluation  # noqa: E402
from hypothesis_gen import (  # noqa: E402
    default_inputs_for_study,
    generate_hypotheses,
    user_hypotheses_from_config_text,
    write_generated_hypotheses,
)
from llm_judge import run_llm_judge  # noqa: E402
from study_config import load_config, load_env  # noqa: E402
from trace_parser import write_parsed_traces  # noqa: E402

DEFAULT_CONFIG_PATH = TOOL_DIR / "config.yaml"
STUDIES_DIR = TOOL_DIR / "studies"
SAFETY_MAX_TIME_MS = 10_000
TRACE_REQUEST_TIMEOUT_S = 120
DEFAULT_TRACE_WORKERS = 10
TRACE_RETRY_COUNT = 3


def fetch_session_ids(
    mongo_uri: str,
    db_name: str,
    *,
    tenant_name: str,
    assistant_origin_id: str,
    date_range_start: datetime,
    date_range_end: datetime,
    channel: str = "voice",
    limit: int | None = None,
) -> list[str]:
    """Return voice_session_id UUIDs (or chat session _id) in the date range."""
    if date_range_start > date_range_end:
        raise ValueError("date_range_start must be on or before date_range_end")

    query: dict[str, Any] = {
        "tenant": tenant_name,
        "start_time": {"$gte": date_range_start, "$lte": date_range_end},
        "assistant_origin_id": assistant_origin_id,
    }
    if channel == "voice":
        query["voice_session_id"] = {"$ne": None}
    elif channel == "chat":
        query["voice_session_id"] = None
        query["$or"] = [
            {"external_chat_session": {"$ne": None}},
            {"chat_transport_provider": {"$ne": None}},
        ]
    else:
        raise ValueError(f"channel must be 'voice' or 'chat', got {channel!r}")

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=15_000)
    try:
        cursor = client[db_name].AssistantSession.find(
            query, {"_id": 1, "voice_session_id": 1}
        ).max_time_ms(SAFETY_MAX_TIME_MS)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [doc["voice_session_id"] or str(doc["_id"]) for doc in cursor]
    finally:
        client.close()


def study_output_dir(study_name: str, *, now: datetime | None = None) -> Path:
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    out = STUDIES_DIR / f"{study_name}_{ts}"
    out.mkdir(parents=True, exist_ok=False)
    return out


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _fetch_one_trace(
    session_id: str,
    *,
    trace_base_url: str,
    trace_env: str,
    log_traces_dir: Path,
    retry_count: int,
    request_timeout_s: float,
) -> dict[str, Any]:
    base = trace_base_url.rstrip("/")
    url = f"{base}/trace?session_id={session_id}&env={trace_env}"
    last_error: str | None = None
    for attempt in range(1, retry_count + 1):
        t0 = time.perf_counter()
        try:
            with urlopen(url, timeout=request_timeout_s) as resp:
                body = resp.read()
                http_status = resp.status
            payload = json.loads(body)
            out_path = log_traces_dir / f"{session_id}.json"
            write_json(out_path, payload)
            return {
                "session_id": session_id,
                "ok": True,
                "http_status": http_status,
                "attempt": attempt,
                "duration_sec": round(time.perf_counter() - t0, 3),
                "event_count": len(payload.get("events") or []),
                "path": str(out_path),
            }
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except URLError as exc:
            last_error = str(exc.reason)
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON: {exc}"
        except Exception as exc:
            last_error = str(exc)
        if attempt < retry_count:
            time.sleep(attempt)
    return {
        "session_id": session_id,
        "ok": False,
        "attempt": retry_count,
        "error": last_error,
    }


def fetch_traces_parallel(
    session_ids: list[str],
    study_dir: Path,
    *,
    trace_base_url: str,
    trace_env: str = "prod",
    max_workers: int = DEFAULT_TRACE_WORKERS,
    retry_count: int = TRACE_RETRY_COUNT,
    request_timeout_s: float = TRACE_REQUEST_TIMEOUT_S,
) -> dict[str, Any]:
    """Fetch BotProbe traces in parallel; write each under study_dir/log_traces/."""
    log_traces_dir = study_dir / "log_traces"
    log_traces_dir.mkdir(parents=True, exist_ok=True)

    if not session_ids:
        return {
            "total": 0,
            "ok": 0,
            "failed": 0,
            "results": [],
            "log_traces_dir": str(log_traces_dir),
        }

    workers = min(max_workers, len(session_ids))
    total = len(session_ids)
    results: list[dict[str, Any]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _fetch_one_trace,
                sid,
                trace_base_url=trace_base_url,
                trace_env=trace_env,
                log_traces_dir=log_traces_dir,
                retry_count=retry_count,
                request_timeout_s=request_timeout_s,
            ): sid
            for sid in session_ids
        }
        for future in as_completed(futures):
            results.append(future.result())
            done += 1
            ok_so_far = sum(1 for r in results if r.get("ok"))
            sys.stderr.write(f"\rTraces downloaded: {done}/{total} ({ok_so_far} ok)   ")
            sys.stderr.flush()
    if total:
        sys.stderr.write("\n")
        sys.stderr.flush()

    results.sort(key=lambda r: r["session_id"])
    ok = sum(1 for r in results if r.get("ok"))
    failed = len(results) - ok
    return {
        "total": len(session_ids),
        "ok": ok,
        "failed": failed,
        "retry_count": retry_count,
        "max_workers": workers,
        "trace_env": trace_env,
        "trace_base_url": trace_base_url,
        "log_traces_dir": str(log_traces_dir),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load analysis_tool config and list scoped session ids.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to config YAML (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap number of session ids returned.")
    parser.add_argument("--channel", choices=["voice", "chat"], default="voice")
    parser.add_argument(
        "--trace-workers",
        type=int,
        default=None,
        help="Override config concurrency for trace fetch (default: config concurrency).",
    )
    args = parser.parse_args(argv)
    from log_setup import configure_logging

    configure_logging(logging.INFO)

    cfg = load_config(args.config)
    study_dir = study_output_dir(cfg.study_name)
    logger.info("Study output directory: %s", study_dir)

    env = load_env()
    t_blueprint = time.perf_counter()
    blueprint_path = write_va_blueprint_to_study(
        study_dir,
        tenant_name=cfg.tenant_name,
        assistant_origin_id=cfg.assistant_origin_id,
        env=env,
        channel=args.channel,
    )
    blueprint_fetch_sec = round(time.perf_counter() - t_blueprint, 3)
    logger.debug(
        "VA blueprint fetch finished in %.3fs path=%s tenant=%s assistant_origin_id=%s",
        blueprint_fetch_sec,
        blueprint_path,
        cfg.tenant_name,
        cfg.assistant_origin_id,
    )

    t_mongo = time.perf_counter()
    session_ids = fetch_session_ids(
        env["MONGO_URI"],
        env["MONGO_DB_NAME"],
        tenant_name=cfg.tenant_name,
        assistant_origin_id=cfg.assistant_origin_id,
        date_range_start=cfg.date_range_start,
        date_range_end=cfg.date_range_end,
        channel=args.channel,
        limit=args.limit,
    )
    mongo_fetch_sec = round(time.perf_counter() - t_mongo, 3)
    logger.info("%s session ids fetched", len(session_ids))
    logger.info("Mongo session id fetch completed in %.3fs", mongo_fetch_sec)

    write_json(
        study_dir / "session_ids.json",
        {
            "study_name": cfg.study_name,
            "tenant_name": cfg.tenant_name,
            "assistant_origin_id": cfg.assistant_origin_id,
            "date_range_start": cfg.date_range_start.isoformat(),
            "date_range_end": cfg.date_range_end.isoformat(),
            "session_ids": session_ids,
        },
    )
    logger.info("Wrote %s", study_dir / "session_ids.json")

    trace_base = env.get("BOTPROBE_TRACE_BASE_URL") or env.get("BOTPROBE_BASE_URL")
    if not trace_base:
        raise RuntimeError(
            "BOTPROBE_TRACE_BASE_URL (or BOTPROBE_BASE_URL) not set in analysis_tool/.env"
        )
    trace_env = env.get("BOTPROBE_TRACE_ENV", "prod")

    trace_workers = args.trace_workers if args.trace_workers is not None else cfg.concurrency
    t_traces = time.perf_counter()
    trace_summary = fetch_traces_parallel(
        session_ids,
        study_dir,
        trace_base_url=trace_base,
        trace_env=trace_env,
        max_workers=trace_workers,
        retry_count=TRACE_RETRY_COUNT,
    )
    trace_fetch_sec = round(time.perf_counter() - t_traces, 3)
    logger.info(
        "Parallel trace fetch completed in %.3fs (%s ok, %s failed)",
        trace_fetch_sec,
        trace_summary["ok"],
        trace_summary["failed"],
    )

    write_json(
        study_dir / "trace_fetch_summary.json",
        {**trace_summary, "duration_sec": trace_fetch_sec},
    )
    log_traces_dir = study_dir / "log_traces"
    t_parse = time.perf_counter()
    parsed_written = write_parsed_traces(log_traces_dir, study_dir)
    parse_traces_sec = round(time.perf_counter() - t_parse, 3)
    parsed_traces_dir = study_dir / "parsed_traces"
    logger.info(
        "Trace parse completed in %.3fs — %s parsed file(s) saved to %s",
        parse_traces_sec,
        len(parsed_written),
        parsed_traces_dir,
    )

    write_json(
        study_dir / "parse_traces_summary.json",
        {
            "parsed_traces_dir": str(parsed_traces_dir),
            "parsed_session_count": len(parsed_written),
            "duration_sec": parse_traces_sec,
        },
    )
    t_union = time.perf_counter()
    deep_union_path = write_deep_union_over_parsed_traces(study_dir)
    deep_union_sec = round(time.perf_counter() - t_union, 3)
    logger.info("Deep union completed in %.3fs — saved to %s", deep_union_sec, deep_union_path)

    hypothesis_gen_sec: float | None = None
    generated_hypotheses_path: str | None = None
    if cfg.hypothesis:
        t_hypothesis = time.perf_counter()
        user_hyps = user_hypotheses_from_config_text(cfg.hypothesis)
        hyp_inputs = default_inputs_for_study(study_dir, user_hyps)
        hyp_payload = generate_hypotheses(hyp_inputs, model_name=cfg.model_name)
        hyp_out = write_generated_hypotheses(study_dir, hyp_payload)
        hypothesis_gen_sec = round(time.perf_counter() - t_hypothesis, 3)
        generated_hypotheses_path = str(hyp_out)
        logger.info(
            "Hypothesis generation completed in %.3fs — saved to %s",
            hypothesis_gen_sec,
            hyp_out,
        )
    else:
        logger.info("Skipping hypothesis generation (no hypothesis in config.yaml)")

    hypothesis_eval_sec: float | None = None
    hypothesis_eval_paths: dict[str, str] | None = None
    if generated_hypotheses_path:
        t_eval = time.perf_counter()
        eval_out = run_hypothesis_evaluation(study_dir)
        hypothesis_eval_sec = round(time.perf_counter() - t_eval, 3)
        hypothesis_eval_paths = {k: str(v) for k, v in eval_out.items()}
        logger.info("Hypothesis evaluation completed in %.3fs", hypothesis_eval_sec)

    llm_judge_sec: float | None = None
    llm_judge_path: str | None = None
    if generated_hypotheses_path and hypothesis_eval_paths:
        t_judge = time.perf_counter()
        judge_out = run_llm_judge(
            study_dir,
            model_name=cfg.model_name,
            concurrency=cfg.concurrency,
        )
        llm_judge_sec = round(time.perf_counter() - t_judge, 3)
        llm_judge_path = str(judge_out)
        logger.info("LLM judge completed in %.3fs — saved to %s", llm_judge_sec, judge_out)

    n_samples = len(parsed_written)
    pipeline_summary = build_pipeline_summary(study_dir, n_samples=n_samples)

    write_json(
        study_dir / "step_timings.json",
        {
            "blueprint_fetch_sec": blueprint_fetch_sec,
            "va_blueprint_path": str(blueprint_path),
            "mongo_session_ids_fetch_sec": mongo_fetch_sec,
            "parallel_trace_fetch_sec": trace_fetch_sec,
            "parse_traces_sec": parse_traces_sec,
            "deep_union_sec": deep_union_sec,
            "hypothesis_gen_sec": hypothesis_gen_sec,
            "generated_hypotheses_path": generated_hypotheses_path,
            "hypothesis_eval_sec": hypothesis_eval_sec,
            "hypothesis_eval_paths": hypothesis_eval_paths,
            "llm_judge_sec": llm_judge_sec,
            "llm_judge_path": llm_judge_path,
            "concurrency": cfg.concurrency,
            "model_name": cfg.model_name,
            "session_id_count": len(session_ids),
            "parsed_traces_dir": str(parsed_traces_dir),
            "parsed_session_count": n_samples,
            "deep_union_path": str(deep_union_path),
            "pipeline_summary": pipeline_summary,
        },
    )
    logger.info("Wrote raw traces under %s", log_traces_dir)
    log_pipeline_summary(study_dir, n_samples=n_samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
