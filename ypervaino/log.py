from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from ypervaino.settings import ROOT, STUDIES_ROOT

_configured = False
_file_handlers: dict[str, logging.Handler] = {}


def setup_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    lvl_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    lvl = getattr(logging, lvl_name, logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("ypervaino")
    root.setLevel(lvl)
    root.propagate = False

    if not root.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str = "ypervaino") -> logging.Logger:
    setup_logging()
    if name == "ypervaino" or name.startswith("ypervaino."):
        return logging.getLogger(name)
    return logging.getLogger(f"ypervaino.{name}")


def attach_study_log_file(slug: str) -> logging.Logger:
    """Logger for a study — stdout + studies/{slug}/intermediate/pipeline.log"""
    setup_logging()
    logger = logging.getLogger(f"ypervaino.study.{slug}")
    logger.setLevel(logging.getLogger("ypervaino").level)

    if slug not in _file_handlers:
        log_dir = STUDIES_ROOT / slug / "intermediate"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "pipeline.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            fmt="%(asctime)s %(levelname)-5s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)
        _file_handlers[slug] = fh

    return logger


def log_kv(logger: logging.Logger, msg: str, **fields: Any) -> None:
    if not fields:
        logger.info(msg)
        return
    parts = " ".join(f"{k}={v!r}" for k, v in fields.items() if v is not None)
    logger.info("%s %s", msg, parts)
