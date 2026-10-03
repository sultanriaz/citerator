"""Chunking strategies: fixed-size with overlap, semantic, structure-aware.

All strategies work the same way: each one only decides WHERE to cut, returning character
spans over a document's `full_text`. A shared finalizer then turns spans into `Chunk`
objects with token counts, page ranges, section paths and deterministic IDs. That keeps
the strategies directly comparable and makes citations consistent across them.

Sizes are measured in tokens of the embedding model's tokenizer (see tokens.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from bisect import bisect_right
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .models import Block, Chunk, Document
from .tokens import Tokenizer

_CHUNK_NS = uuid.UUID("b9f1e5a2-3c1d-4e3a-9a77-5d1b2c3d4e5f")

# --------------------------------------------------------------------------- document text map

_SENT_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9(\["\u201c])')


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Cheap sentence segmentation (offsets into `text`). Good enough for regulatory prose."""
    spans, start = [], 0
    for m in _SENT_BOUNDARY.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


@dataclass
class DocText:
    """The document flattened to one string, with block boundaries and section paths."""

    blocks: list[Block]
    full_text: str
    block_spans: list[tuple[int, int]]
    block_paths: list[list[str]]  # section path for each block (a heading includes itself)

    def block_at(self, pos: int) -> int:
        starts = [s for s, _ in self.block_spans]
        return max(0, min(bisect_right(starts, pos) - 1, len(self.blocks) - 1))


def build_doc_text(doc: Document) -> DocText:
    texts = [b.text for b in doc.blocks]
    spans, pos = [], 0
    for t in texts:
        spans.append((pos, pos + len(t)))
        pos += len(t) + 2  # "\n\n" separator
    stack: list[tuple[int, str]] = []
    paths: list[list[str]] = []
    for b in doc.blocks:
        if b.kind == "heading":
            level = b.level or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, b.text))
        paths.append([t for _, t in stack])
    return DocText(doc.blocks, "\n\n".join(texts), spans, paths)


# --------------------------------------------------------------------------- helpers


def hard_split(text: str, base: int, max_tokens: int, tok: Tokenizer) -> list[tuple[int, int]]:
    """Last resort for a single run of text longer than the budget: cut on token windows."""
    offs = tok.offsets(text)
    if not offs:
        return []
    out = []
    for i in range(0, len(offs), max_tokens):
        j = min(i + max_tokens, len(offs))
        out.append((base + offs[i][0], base + offs[j - 1][1]))
    return out


class Chunker(Protocol):
    name: str
    use_breadcrumb: bool

    @property
    def params(self) -> dict: ...

    def spans(self, doc: Document, dt: DocText) -> list[tuple[int, int]]: ...


# --------------------------------------------------------------------------- 1. fixed-size baseline


class FixedChunker:
    """Sliding token window with overlap. Ignores structure on purpose: it is the baseline."""

    name = "fixed"
    use_breadcrumb = False

    def __init__(self, tokenizer: Tokenizer, max_tokens: int = 400, overlap_ratio: float = 0.12):
        if not 0 <= overlap_ratio < 1:
            raise ValueError("overlap_ratio must be in [0, 1)")
        self.tok = tokenizer
        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio

    @property
    def params(self) -> dict:
        return {"max_tokens": self.max_tokens, "overlap_ratio": self.overlap_ratio}

    def spans(self, doc: Document, dt: DocText) -> list[tuple[int, int]]:
        offs = self.tok.offsets(dt.full_text)
        n = len(offs)
        step = max(1, self.max_tokens - int(self.max_tokens * self.overlap_ratio))
        out, i = [], 0
        while i < n:
            j = min(i + self.max_tokens, n)
            out.append((offs[i][0], offs[j - 1][1]))
            if j == n:
                break
            i += step
        return out


# --------------------------------------------------------------------------- 2. structure-aware


class StructureChunker:
    """Respects headings: one section -> one or more chunks, never crossing a section edge.

    - Sections with fewer than `min_tokens` are merged forward with following sibling sections
      (same parent), keeping the later headings inline so no text is lost.
    - Sections longer than `max_tokens` are packed paragraph by paragraph, then by sentence,
      and only as a last resort cut on token windows.
    - The section breadcrumb is prepended to the text that gets EMBEDDED (not to the stored
      text), which is where most of the retrieval gain comes from.
    """

    name = "structure"
    use_breadcrumb = True

    def __init__(self, tokenizer: Tokenizer, max_tokens: int = 400, min_tokens: int = 60):
        self.tok = tokenizer
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens

    @property
    def params(self) -> dict:
        return {"max_tokens": self.max_tokens, "min_tokens": self.min_tokens}

    def _pieces(self, dt: DocText, idx: int) -> list[tuple[int, int, int]]:
        """(start, end, tokens) pieces for one block, splitting oversize blocks by sentence."""
        start, end = dt.block_spans[idx]
        text = dt.blocks[idx].text
        n = self.tok.count(text)
        if n <= self.max_tokens:
            return [(start, end, n)]
        pieces = []
        for s, e in sentence_spans(text):
            sent = text[s:e]
            k = self.tok.count(sent)
            if k <= self.max_tokens:
                pieces.append((start + s, start + e, k))
            else:
                for hs, he in hard_split(sent, start + s, self.max_tokens, self.tok):
                    pieces.append((hs, he, self.tok.count(dt.full_text[hs:he])))
        return pieces

    def spans(self, doc: Document, dt: DocText) -> list[tuple[int, int]]:
        sections: list[dict] = []
        cur: dict | None = None
        for i, b in enumerate(doc.blocks):
            if b.kind == "heading":
                cur = {"path": tuple(dt.block_paths[i]), "head": i, "body": []}
                sections.append(cur)
            else:
                if cur is None:
                    cur = {"path": (), "head": None, "body": []}
                    sections.append(cur)
                cur["body"].append(i)
        sections = [s for s in sections if s["body"]]
        sec_tokens = [sum(self.tok.count(doc.blocks[i].text) for i in s["body"]) for s in sections]

        # Merge tiny sections forward within the same parent section.
        groups: list[list[int]] = []
        i = 0
        while i < len(sections):
            group, total = [i], sec_tokens[i]
            while (
                total < self.min_tokens
                and i + 1 < len(sections)
                and sections[i + 1]["path"][:-1] == sections[group[0]]["path"][:-1]
            ):
                i += 1
                group.append(i)
                total += sec_tokens[i]
            groups.append(group)
            i += 1

        out: list[tuple[int, int]] = []
        for group in groups:
            pieces: list[tuple[int, int, int]] = []
            for pos, si in enumerate(group):
                sec = sections[si]
                if pos > 0 and sec["head"] is not None:  # later headings stay inline
                    pieces += self._pieces(dt, sec["head"])
                for bi in sec["body"]:
                    pieces += self._pieces(dt, bi)
            cur_start, cur_end, cur_tok = None, None, 0
            for s, e, k in pieces:
                if cur_start is not None and cur_tok + k > self.max_tokens:
                    out.append((cur_start, cur_end))
                    cur_start, cur_end, cur_tok = None, None, 0
                if cur_start is None:
                    cur_start = s
                cur_end = e
                cur_tok += k
            if cur_start is not None:
                out.append((cur_start, cur_end))
        return out


# --------------------------------------------------------------------------- 3. semantic


class SemanticChunker:
    """Split where the topic shifts, detected from embedding similarity between sentences.

    For each gap between sentences we compare the mean embedding of the `window` sentences
    before it with the `window` after it. Gaps whose distance is at or above the
    `breakpoint_percentile` of the document's distances AND is a local peak are breaks, subject
    to min/max chunk size. Costs one extra embedding pass (cached by content hash).
    """

    name = "semantic"
    use_breadcrumb = False

    def __init__(
        self,
        tokenizer: Tokenizer,
        embedder,
        max_tokens: int = 400,
        min_tokens: int = 80,
        breakpoint_percentile: float = 90.0,
        window: int = 2,
    ):
        self.tok = tokenizer
        self.embedder = embedder
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.percentile = breakpoint_percentile
        self.window = window

    @property
    def params(self) -> dict:
        return {
            "max_tokens": self.max_tokens,
            "min_tokens": self.min_tokens,
            "breakpoint_percentile": self.percentile,
            "window": self.window,
            "embedder": getattr(self.embedder, "name", "unknown"),
        }

    def spans(self, doc: Document, dt: DocText) -> list[tuple[int, int]]:
        sents: list[tuple[int, int]] = []
        for (bs, _), b in zip(dt.block_spans, dt.blocks):
            sents += [(bs + s, bs + e) for s, e in sentence_spans(b.text)]
        if not sents:
            return []
        texts = [dt.full_text[s:e] for s, e in sents]
        tokens = [self.tok.count(t) for t in texts]
        n = len(sents)

        dist = np.zeros(max(n - 1, 0))
        if n > 1:
            vecs = np.asarray(self.embedder.embed_documents(texts), dtype=np.float32)
            for g in range(n - 1):
                a = vecs[max(0, g - self.window + 1): g + 1].mean(axis=0)
                b = vecs[g + 1: g + 1 + self.window].mean(axis=0)
                denom = float(np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
                dist[g] = 1.0 - float(a @ b) / denom
        threshold = float(np.percentile(dist, self.percentile)) if len(dist) else 0.0
        # Averaging over a window smears one topic shift across neighbouring gaps. Only the peak of
        # each plateau counts as a break; otherwise the first (early) gap fires and the minimum
        # chunk size then blocks the real boundary.
        is_peak = [
            bool(dist[g] >= threshold and dist[g] >= dist[max(0, g - self.window): g + self.window + 1].max() - 1e-12)
            for g in range(len(dist))
        ]

        groups: list[tuple[int, int, int]] = []  # (first sentence, last sentence, tokens)
        first, total = 0, 0
        for i in range(n):
            if i > first:
                over = total + tokens[i] > self.max_tokens
                topic_shift = is_peak[i - 1] and total >= self.min_tokens
                if over or topic_shift:
                    groups.append((first, i - 1, total))
                    first, total = i, 0
            total += tokens[i]
        groups.append((first, n - 1, total))

        # Fold a too-small tail into its predecessor when it fits.
        if len(groups) > 1 and groups[-1][2] < self.min_tokens and groups[-2][2] + groups[-1][2] <= self.max_tokens:
            a, b = groups[-2], groups[-1]
            groups = groups[:-2] + [(a[0], b[1], a[2] + b[2])]

        out: list[tuple[int, int]] = []
        for i0, i1, tk in groups:
            start, end = sents[i0][0], sents[i1][1]
            if tk > self.max_tokens and i0 == i1:  # a single huge sentence
                out += hard_split(dt.full_text[start:end], start, self.max_tokens, self.tok)
            else:
                out.append((start, end))
        return out


# --------------------------------------------------------------------------- finalizer


def _params_hash(params: dict) -> str:
    return hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:8]


def chunk_id_for(doc_id: str, chunker_name: str, params: dict, index: int) -> str:
    return str(uuid.uuid5(_CHUNK_NS, f"{doc_id}|{chunker_name}|{_params_hash(params)}|{index}"))


def _breadcrumb(doc_title: str, path: list[str]) -> str:
    parts = list(path) if path and path[0] == doc_title else [doc_title, *path]
    return " > ".join(p for p in parts if p)


def chunk_document(doc: Document, chunker: Chunker, tokenizer: Tokenizer) -> list[Chunk]:
    """Run `chunker` on `doc` and build fully annotated `Chunk` objects."""
    if not doc.blocks:
        return []
    dt = build_doc_text(doc)
    params = chunker.params
    chunks: list[Chunk] = []
    for start, end in chunker.spans(doc, dt):
        raw = dt.full_text[start:end]
        lead = len(raw) - len(raw.lstrip())
        text = raw.strip()
        if not text:
            continue
        start, end = start + lead, start + lead + len(text)
        b0, b1 = dt.block_at(start), dt.block_at(end - 1)
        path = dt.block_paths[b0]
        embed_text = f"{_breadcrumb(doc.title, path)}\n\n{text}" if chunker.use_breadcrumb else text
        idx = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=chunk_id_for(doc.doc_id, chunker.name, params, idx),
                doc_id=doc.doc_id,
                doc_hash=doc.doc_hash,
                source_file=doc.source_file,
                doc_title=doc.title,
                doc_type=doc.doc_type,
                jurisdiction=doc.jurisdiction,
                effective_date=doc.effective_date,
                section_path=list(path),
                page_start=doc.blocks[b0].page,
                page_end=doc.blocks[b1].last_page,
                char_start=start,
                char_end=end,
                text=text,
                embed_text=embed_text,
                token_count=tokenizer.count(text),
                embed_token_count=tokenizer.count(embed_text) if embed_text != text else tokenizer.count(text),
                chunk_index=idx,
                chunker=chunker.name,
                chunker_params=params,
            )
        )
    return chunks


def make_chunker(strategy: str, tokenizer: Tokenizer, embedder=None, **overrides) -> Chunker:
    """Factory used by the CLI. `overrides` are strategy parameters (unknown ones are ignored)."""
    pick = lambda *names: {k: overrides[k] for k in names if overrides.get(k) is not None}  # noqa: E731
    if strategy == "fixed":
        return FixedChunker(tokenizer, **pick("max_tokens", "overlap_ratio"))
    if strategy == "structure":
        return StructureChunker(tokenizer, **pick("max_tokens", "min_tokens"))
    if strategy == "semantic":
        if embedder is None:
            raise ValueError("semantic chunking needs an embedder")
        return SemanticChunker(tokenizer, embedder, **pick("max_tokens", "min_tokens", "breakpoint_percentile", "window"))
    raise ValueError(f"unknown chunking strategy: {strategy!r} (choose fixed, structure, semantic)")
