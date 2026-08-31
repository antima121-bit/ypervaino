from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

from ypervaino.log import get_logger
from ypervaino.settings import WORKER_THREADS

T = TypeVar("T")
R = TypeVar("R")

_log = get_logger("parallel")


def worker_count() -> int:
    return max(1, WORKER_THREADS)


def run_parallel(
    items: Iterable[T],
    fn: Callable[[T], R],
    *,
    max_workers: int | None = None,
    label: str = "parallel",
    log_every: int = 10,
) -> list[R]:
    items = list(items)
    if not items:
        return []
    workers = min(max_workers or worker_count(), len(items))
    if len(items) == 1:
        return [fn(items[0])]

    _log.info("%s: processing %d items with %d workers", label, len(items), workers)
    results: list[R | None] = [None] * len(items)
    done = 0
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_map = {ex.submit(fn, item): i for i, item in enumerate(items)}
        for fut in as_completed(future_map):
            results[future_map[fut]] = fut.result()
            with lock:
                done += 1
                if done == len(items) or done % log_every == 0:
                    _log.info("%s: progress %d/%d", label, done, len(items))

    _log.info("%s: finished %d items", label, len(items))
    return results
