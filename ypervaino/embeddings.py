from __future__ import annotations

import math
import threading
import time
from typing import Any

from openai import OpenAI

from ypervaino.log import get_logger
from ypervaino.parallel import run_parallel, worker_count
from ypervaino.settings import (
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_BATCH_SIZE,
    OPENAI_EMBEDDING_DIM,
    OPENAI_EMBEDDING_MODEL,
)

_log = get_logger("embeddings")

_warmed = False
_warmup_lock = threading.Lock()
_t0 = time.perf_counter()


def _step(msg: str, *, level: str = "info") -> None:
    elapsed = (time.perf_counter() - _t0) * 1000
    getattr(_log, level)(f"[+{elapsed:,.0f}ms] {msg}")


def embedding_dim() -> int:
    return OPENAI_EMBEDDING_DIM


def _zero_vec() -> list[float]:
    return [0.0] * OPENAI_EMBEDDING_DIM


def _client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY required for embeddings")
    return OpenAI(api_key=OPENAI_API_KEY)


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def _encode_batch(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    _step(f"OpenAI embed batch n={len(texts)} model={OPENAI_EMBEDDING_MODEL}")
    t0 = time.perf_counter()
    resp = _client().embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=texts,
        dimensions=OPENAI_EMBEDDING_DIM,
    )
    ordered = sorted(resp.data, key=lambda d: d.index)
    vecs = [_normalize(list(d.embedding)) for d in ordered]
    _step(f"OpenAI embed batch done in {(time.perf_counter() - t0) * 1000:.0f}ms tokens={resp.usage.total_tokens}")
    return vecs


def encode_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    batch_size = max(1, OPENAI_EMBEDDING_BATCH_SIZE)
    chunks = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    if len(chunks) == 1:
        return _encode_batch(chunks[0])
    _step(f"encode_texts: {len(texts)} texts in {len(chunks)} parallel batches (workers={worker_count()})")
    batch_results = run_parallel(
        chunks,
        _encode_batch,
        max_workers=worker_count(),
        label="openai-embeddings",
        log_every=max(1, len(chunks) // 5),
    )
    out: list[list[float]] = []
    for part in batch_results:
        out.extend(part)
    return out


def encode_text(text: str) -> list[float]:
    if not text.strip():
        return _zero_vec()
    return encode_texts([text])[0]


def warmup() -> None:
    """Verify OpenAI embeddings API is reachable (single cheap call)."""
    global _warmed
    if _warmed:
        return
    with _warmup_lock:
        if _warmed:
            return
        _step(f"warmup: OpenAI embeddings model={OPENAI_EMBEDDING_MODEL} dim={OPENAI_EMBEDDING_DIM}")
        encode_text("warmup")
        _warmed = True
        _step("warmup complete")


def apply_opening_embeddings(features: dict[str, dict[str, Any]]) -> int:
    """Batch-encode opening_text via parallel OpenAI API calls. Returns count updated."""
    pending: list[tuple[str, str]] = []
    zero = _zero_vec()
    for sid, fv in features.items():
        text = (fv.get("opening_text") or "").strip()
        if not text:
            fv["embedding_opening"] = zero
            continue
        emb = fv.get("embedding_opening")
        if emb and len(emb) == OPENAI_EMBEDDING_DIM and emb != zero:
            continue
        pending.append((sid, text))
    if not pending:
        return 0
    texts = [t for _, t in pending]
    _log.info("batch encoding %d opening texts via OpenAI (parallel batches)", len(texts))
    vecs = encode_texts(texts)
    for (sid, _), vec in zip(pending, vecs):
        features[sid]["embedding_opening"] = vec
    return len(pending)


def cosine_distance(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    return 1.0 - dot


def centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return _zero_vec()
    n = len(vectors)
    d = len(vectors[0])
    c = [0.0] * d
    for v in vectors:
        for i, x in enumerate(v):
            c[i] += x
    return [x / n for x in c]


def medoid_index(vectors: list[list[float]]) -> int:
    if not vectors:
        return 0
    if len(vectors) == 1:
        return 0
    best_i, best_score = 0, math.inf
    for i, vi in enumerate(vectors):
        dists = [cosine_distance(vi, vj) for j, vj in enumerate(vectors) if j != i]
        score = sum(dists) / max(len(dists), 1)
        if score < best_score:
            best_i, best_score = i, score
    return best_i


def farthest_point_indices(vectors: list[list[float]], k: int, seed: list[int] | None = None) -> list[int]:
    if not vectors or k <= 0:
        return []
    selected = list(seed or [])
    if not selected:
        selected = [medoid_index(vectors)]
    while len(selected) < min(k, len(vectors)):
        best_j, best_d = -1, -1.0
        for j, vj in enumerate(vectors):
            if j in selected:
                continue
            d = min(cosine_distance(vj, vectors[s]) for s in selected)
            if d > best_d:
                best_j, best_d = j, d
        if best_j < 0:
            break
        selected.append(best_j)
    return selected[:k]


def nearest_prototype_label(text: str, prototypes: list[dict[str, Any]], min_sim: float = 0.35) -> str:
    if not prototypes:
        return "other"
    vec = encode_text(text)
    best_label, best_sim = "other", -1.0
    for proto in prototypes:
        label = proto.get("id") or proto.get("label") or "match"
        phrases = proto.get("prototype_phrases") or proto.get("phrases") or []
        if not phrases:
            continue
        pvecs = encode_texts(phrases)
        sim = max(1.0 - cosine_distance(vec, pv) for pv in pvecs)
        if sim > best_sim:
            best_sim, best_label = sim, label
    return best_label if best_sim >= min_sim else (prototypes[-1].get("id") if prototypes else "other")


if __name__ == "__main__":
    from ypervaino.log import setup_logging

    setup_logging()
    warmup()
    v = encode_text("hello world")
    print(f"OK dim={len(v)} model={OPENAI_EMBEDDING_MODEL}")
