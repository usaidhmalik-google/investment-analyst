"""Hybrid RAG & Complex Document Parsing for SEC EDGAR filings.

Implements:
1. HTML table-to-Markdown table preservation for complex SEC 10-K/10-Q financial tables.
2. Section-aware overlapping document chunking with character offset & citation lineage.
3. Embedding abstraction: deterministic L2-normalized feature-hashing (unigram + bigram)
   for zero-dependency/offline execution, plus optional Vertex AI ``text-embedding-005``.
4. Hybrid retrieval combining Okapi BM25 lexical scoring with dense vector cosine similarity
   via Reciprocal Rank Fusion (RRF), plus IR evaluation metrics (Precision@K, Recall@K, MRR, nDCG@K).
"""

from __future__ import annotations

import hashlib
import html
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.%$\-]*")
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "our",
        "their",
        "its",
        "not",
        "but",
        "can",
        "may",
        "will",
        "into",
        "such",
        "any",
        "all",
    }
)


# --------------------------------------------------------------------------- 1. HTML Table Parser


class _HTMLTableParser(HTMLParser):
    """Extracts HTML ``<table>`` structures as 2D string grids."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = 0
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "table":
            self._in_table += 1
            if self._in_table == 1:
                self._current_table = []
        elif self._in_table == 1 and t == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_table == 1 and self._in_row and t in ("td", "th"):
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("td", "th") and self._in_cell:
            cell_text = re.sub(r"\s+", " ", "".join(self._current_cell)).strip()
            self._current_row.append(cell_text)
            self._in_cell = False
        elif t == "tr" and self._in_row:
            if any(c for c in self._current_row):
                self._current_table.append(self._current_row)
            self._in_row = False
        elif t == "table" and self._in_table > 0:
            if self._in_table == 1 and self._current_table:
                self.tables.append(self._current_table)
            self._in_table -= 1

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def _grid_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    if width == 0:
        return ""
    padded = [r + [""] * (width - len(r)) for r in rows]
    header = padded[0]
    lines = [
        "| " + " | ".join(c.replace("|", "\\|") for c in header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in padded[1:]:
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |")
    return "\n".join(lines)


def extract_html_tables(html_document: str) -> list[dict[str, Any]]:
    """Parse all ``<table>`` blocks from an SEC HTML/iXBRL document into Markdown + row grids."""
    parser = _HTMLTableParser()
    parser.feed(html_document)
    parser.close()
    results: list[dict[str, Any]] = []
    for idx, grid in enumerate(parser.tables):
        md = _grid_to_markdown(grid)
        if md:
            results.append(
                {
                    "table_index": idx,
                    "row_count": len(grid),
                    "column_count": max(len(r) for r in grid),
                    "rows": grid,
                    "markdown": md,
                }
            )
    return results


def html_to_markdown_preserving_tables(html_document: str) -> str:
    """Convert SEC EDGAR HTML to clean text while preserving ``<table>`` blocks as Markdown tables."""
    table_re = re.compile(r"<table\b[^>]*>.*?</table>", re.I | re.S)

    def _replace_table(match: re.Match[str]) -> str:
        extracted = extract_html_tables(match.group(0))
        if not extracted:
            return " "
        return "\n\n" + extracted[0]["markdown"] + "\n\n"

    with_md_tables = table_re.sub(_replace_table, html_document)
    # Strip remaining HTML tags
    stripped = re.sub(r"<(script|style|ix:header)\b[^>]*>.*?</\1>", " ", with_md_tables, flags=re.I | re.S)
    stripped = re.sub(r"<(p|div|br|li|h[1-6]|section)\b[^>]*>", "\n", stripped, flags=re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    text = html.unescape(stripped).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    collapsed = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


# --------------------------------------------------------------------------- 2. Section-Aware Chunking


@dataclass(frozen=True)
class FilingChunk:
    chunk_id: str
    ticker: str
    form: str
    section: str
    accession_number: str
    chunk_index: int
    start_char: int
    end_char: int
    text: str
    token_count: int


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text) if tok.lower() not in _STOPWORDS]


def chunk_filing_section(
    text: str,
    *,
    ticker: str,
    form: str = "10-K",
    section: str = "risk_factors",
    accession_number: str = "latest",
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> list[FilingChunk]:
    """Split a filing section into overlapping semantic chunks aligned on paragraph/sentence boundaries."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    chunk_size = max(200, int(chunk_size))
    chunk_overlap = max(0, min(int(chunk_overlap), chunk_size // 2))

    chunks: list[FilingChunk] = []
    n = len(cleaned)
    cursor = 0
    idx = 0

    while cursor < n:
        target_end = min(n, cursor + chunk_size)
        if target_end < n:
            # Prefer paragraph boundary, then sentence boundary, then whitespace
            window = cleaned[cursor:target_end]
            para_break = window.rfind("\n\n")
            sent_break = max(window.rfind(". "), window.rfind(".\n"))
            space_break = window.rfind(" ")
            if para_break >= chunk_size // 2:
                target_end = cursor + para_break + 2
            elif sent_break >= chunk_size // 2:
                target_end = cursor + sent_break + 1
            elif space_break >= chunk_size // 2:
                target_end = cursor + space_break

        span_text = cleaned[cursor:target_end].strip()
        if span_text:
            tokens = tokenize(span_text)
            cid = f"SEC:{ticker.upper()}:{form.upper()}:{accession_number}#chunk-{idx}"
            chunks.append(
                FilingChunk(
                    chunk_id=cid,
                    ticker=ticker.upper(),
                    form=form.upper(),
                    section=section,
                    accession_number=accession_number,
                    chunk_index=idx,
                    start_char=cursor,
                    end_char=target_end,
                    text=span_text,
                    token_count=len(tokens),
                )
            )
            idx += 1

        if target_end >= n:
            break
        next_cursor = max(cursor + 1, target_end - chunk_overlap)
        cursor = next_cursor

    return chunks


# --------------------------------------------------------------------------- 3. Embeddings & Vector Index


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicEmbedder:
    """L2-normalized signed feature-hashing embedder over word unigrams and bigrams.

    Deterministic, fast, and dependency-free for CI / offline execution while still
    capturing multi-word domain phrases and normalized term weights.
    """

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = max(32, dimensions)

    def _embed_one(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features = list(tokens)
        features.extend(f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1))
        vec = [0.0] * self.dimensions
        if not features:
            return vec
        counts = Counter(features)
        for feat, count in counts.items():
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            h = int.from_bytes(digest, "little")
            bucket = h % self.dimensions
            sign = 1.0 if ((h >> 32) & 1) == 0 else -1.0
            weight = 1.0 + math.log(count)
            vec[bucket] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class VertexAIEmbedder:
    """Vertex AI ``text-embedding-005`` adapter with automatic fallback to ``DeterministicEmbedder``."""

    def __init__(self, model: str = "text-embedding-005", fallback_dim: int = 256) -> None:
        self.model = model
        self._fallback = DeterministicEmbedder(dimensions=fallback_dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            from google import genai

            client = genai.Client()
            resp = client.models.embed_content(model=self.model, contents=texts)
            embeddings = [list(e.values) for e in (resp.embeddings or [])]
            if len(embeddings) == len(texts):
                return embeddings
        except Exception as exc:  # noqa: BLE001 - graceful fallback when offline or unconfigured
            logger.debug("Vertex AI embeddings unavailable (%s); using deterministic embedder", exc)
        return self._fallback.embed(texts)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# --------------------------------------------------------------------------- 4. Hybrid BM25 + Dense Vector RRF


@dataclass(frozen=True)
class ScoredChunk:
    chunk: FilingChunk
    rrf_score: float
    bm25_score: float
    dense_score: float
    bm25_rank: int
    dense_rank: int


class HybridFilingRetriever:
    """Indexes ``FilingChunk`` items with both Okapi BM25 and dense vectors, fused with RRF."""

    def __init__(
        self,
        chunks: list[FilingChunk],
        *,
        embedder: Embedder | None = None,
        k1: float = 1.5,
        b: float = 0.75,
        rrf_k: int = 60,
    ) -> None:
        self.chunks = list(chunks)
        self.embedder = embedder or DeterministicEmbedder()
        self.k1 = k1
        self.b = b
        self.rrf_k = rrf_k

        self._doc_tokens: list[list[str]] = [tokenize(c.text) for c in self.chunks]
        self._doc_freqs: list[Counter[str]] = [Counter(toks) for toks in self._doc_tokens]
        self._doc_lens: list[int] = [len(toks) for toks in self._doc_tokens]
        self._avgdl: float = sum(self._doc_lens) / len(self._doc_lens) if self._doc_lens else 1.0

        df: Counter[str] = Counter()
        for freq in self._doc_freqs:
            for term in freq:
                df[term] += 1
        n_docs = len(self.chunks)
        self._idf: dict[str, float] = {
            term: math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }
        self._vectors: list[list[float]] = self.embedder.embed([c.text for c in self.chunks]) if self.chunks else []

    def _bm25_scores(self, query_tokens: list[str]) -> list[float]:
        scores: list[float] = []
        for idx, tf_map in enumerate(self._doc_freqs):
            dl = self._doc_lens[idx] or 1
            score = 0.0
            for q in query_tokens:
                tf = tf_map.get(q, 0)
                if tf == 0:
                    continue
                idf = self._idf.get(q, 0.0)
                denom = tf + self.k1 * (1.0 - self.b + self.b * (dl / max(1.0, self._avgdl)))
                score += idf * ((tf * (self.k1 + 1.0)) / denom)
            scores.append(score)
        return scores

    def _dense_scores(self, query: str) -> list[float]:
        if not self.chunks:
            return []
        q_vec = self.embedder.embed([query])[0]
        return [cosine_similarity(q_vec, d_vec) for d_vec in self._vectors]

    def search(
        self,
        query: str,
        *,
        top_k: int = 3,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
    ) -> list[ScoredChunk]:
        if not self.chunks:
            return []
        top_k = max(1, min(int(top_k), len(self.chunks)))
        q_tokens = tokenize(query)
        bm25 = self._bm25_scores(q_tokens)
        dense = self._dense_scores(query)

        # Rank 1..N (tie-broken by chunk index for determinism)
        bm25_order = sorted(range(len(self.chunks)), key=lambda i: (-bm25[i], i))
        dense_order = sorted(range(len(self.chunks)), key=lambda i: (-dense[i], i))

        bm25_ranks = {doc_idx: rank + 1 for rank, doc_idx in enumerate(bm25_order)}
        dense_ranks = {doc_idx: rank + 1 for rank, doc_idx in enumerate(dense_order)}

        scored: list[ScoredChunk] = []
        for idx, chunk in enumerate(self.chunks):
            b_rank = bm25_ranks[idx]
            d_rank = dense_ranks[idx]
            rrf = (bm25_weight / (self.rrf_k + b_rank)) + (dense_weight / (self.rrf_k + d_rank))
            scored.append(
                ScoredChunk(
                    chunk=chunk,
                    rrf_score=round(rrf, 6),
                    bm25_score=round(bm25[idx], 4),
                    dense_score=round(dense[idx], 4),
                    bm25_rank=b_rank,
                    dense_rank=d_rank,
                )
            )

        scored.sort(key=lambda s: (-s.rrf_score, -s.bm25_score, -s.dense_score, s.chunk.chunk_index))
        return scored[:top_k]


def evaluate_retrieval_quality(
    retrieved_ids: list[str],
    relevant_ids: set[str] | list[str],
    *,
    k: int | None = None,
) -> dict[str, float]:
    """Compute Precision@K, Recall@K, F1@K, Mean Reciprocal Rank (MRR), and nDCG@K."""
    rel = set(relevant_ids)
    cutoff = k if k is not None else max(1, len(retrieved_ids))
    top = retrieved_ids[:cutoff]
    if not rel:
        return {"precision_at_k": 1.0, "recall_at_k": 1.0, "f1_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0}
    if not top:
        return {"precision_at_k": 0.0, "recall_at_k": 0.0, "f1_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0}

    hits = sum(1 for cid in top if cid in rel)
    precision = hits / len(top)
    recall = hits / len(rel)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    mrr = 0.0
    for idx, cid in enumerate(top, start=1):
        if cid in rel:
            mrr = 1.0 / idx
            break

    dcg = sum((1.0 / math.log2(idx + 1)) for idx, cid in enumerate(top, start=1) if cid in rel)
    ideal_hits = min(len(rel), cutoff)
    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_hits + 1))
    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    return {
        "precision_at_k": round(precision, 4),
        "recall_at_k": round(recall, 4),
        "f1_at_k": round(f1, 4),
        "mrr": round(mrr, 4),
        "ndcg_at_k": round(ndcg, 4),
    }
