"""Document loaders: PDF, Markdown, HTML -> `Document` with typed blocks.

Every block keeps its page number (PDF) so chunks can later carry real citations.
PDF cleanup removes repeated running headers/footers and page numbers, fixes line-break
hyphenation, merges paragraphs that continue across pages, and flags pages that have no
text layer (scans) instead of silently indexing nothing.

Optional per-file metadata goes in a sidecar next to the document:
    fatf_recommendations.pdf  ->  fatf_recommendations.pdf.meta.json
    {"title": "...", "doc_type": "standard", "jurisdiction": "international",
     "effective_date": "2025-06-01"}
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
import uuid
from collections import Counter
from pathlib import Path

from .models import Block, Document

log = logging.getLogger("citerator.loaders")

SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".html", ".htm"}
_ID_NAMESPACE = uuid.UUID("6f1c2f0e-8f43-4a43-9d2b-3d5f0c9e7a11")

# --------------------------------------------------------------------------- identity


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_id_for(rel_path: str) -> str:
    """Stable identity from the relative path: survives content edits (so we can re-index)."""
    return str(uuid.uuid5(_ID_NAMESPACE, f"doc:{rel_path}"))


# --------------------------------------------------------------------------- normalization

_HYPHEN_BREAK = re.compile(r"([a-z])-[ \t]*\n[ \t]*([a-z])")
_INLINE_WS = re.compile(r"[ \t\u00a0\u2009\u200b]+")
_PAGE_NUMBER = re.compile(r"^\s*(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$", re.I)


def normalize_text(text: str, keep_newlines: bool = False) -> str:
    """Unicode-normalize, fix line-break hyphenation, collapse whitespace.

    Known trade-off: a genuine hyphenated compound split at a line end
    ("cross-\\nborder") becomes "crossborder". Dehyphenation only fires when the next
    line starts with a lowercase letter.
    """
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "").replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    lines = [_INLINE_WS.sub(" ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return ("\n" if keep_newlines else " ").join(lines)


# --------------------------------------------------------------------------- sidecar metadata


def read_sidecar(path: Path) -> dict:
    side = path.with_name(path.name + ".meta.json")
    if not side.exists():
        return {}
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("Ignoring unreadable sidecar %s: %s", side, exc)
        return {}


# --------------------------------------------------------------------------- PDF

_NUMBERED = re.compile(r"^(\d+(?:\.\d+)+)[.)]?\s+\S")


def _heading_level_from_number(text: str) -> int | None:
    m = _NUMBERED.match(text)
    return min(m.group(1).count(".") + 1, 6) if m else None


def _load_pdf(path: Path) -> tuple[list[Block], int, list[str], str | None]:
    import pymupdf

    warnings: list[str] = []
    raw: list[dict] = []
    pdf = pymupdf.open(path)
    page_count = pdf.page_count
    meta_title = (pdf.metadata or {}).get("title") or None

    for pno, page in enumerate(pdf, start=1):
        height = page.rect.height or 1.0
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            lines = []
            spans = []
            for ln in b.get("lines", []):
                ln_spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
                if ln_spans:
                    lines.append("".join(s["text"] for s in ln_spans))
                    spans.extend(ln_spans)
            if not spans:
                continue
            n_chars = sum(len(s["text"]) for s in spans)
            size = sum(s["size"] * len(s["text"]) for s in spans) / n_chars
            bold_chars = sum(len(s["text"]) for s in spans if (s["flags"] & 16) or "bold" in s["font"].lower())
            x0, y0, x1, y1 = b["bbox"]
            raw.append(
                {
                    "text": "\n".join(lines),
                    "size": size,
                    "bold": bold_chars / n_chars > 0.6,
                    "page": pno,
                    "n_chars": n_chars,
                    "in_margin": y0 < 0.09 * height or y1 > 0.91 * height,
                }
            )
    pdf.close()

    raw = _strip_running_text(raw, page_count)
    body_chars = Counter()
    for r in raw:
        body_chars[r["page"]] += r["n_chars"]
    for pno in range(1, page_count + 1):
        if body_chars[pno] < 20:
            warnings.append(
                f"page {pno}: no extractable body text (blank, image-only or scanned); OCR is not enabled"
            )
    if not raw:
        warnings.append("no extractable text in this PDF")
        return [], page_count, warnings, meta_title

    body_size = Counter()
    for r in raw:
        body_size[round(r["size"] * 2) / 2] += r["n_chars"]
    body = body_size.most_common(1)[0][0]

    # Pass 1: decide which blocks are headings.
    for r in raw:
        text = normalize_text(r["text"])
        r["norm"] = text
        short = len(text) <= 160 and not text.endswith((".", ";", ","))
        r["is_heading"] = bool(text) and short and (r["size"] >= body * 1.12 or (r["bold"] and len(text) <= 120))

    # Pass 2: heading levels by font-size rank, overridden by numbering depth like "2.1.3".
    sizes = sorted({round(r["size"] * 2) / 2 for r in raw if r["is_heading"] and r["size"] >= body * 1.12}, reverse=True)
    blocks: list[Block] = []
    for r in raw:
        if not r["norm"]:
            continue
        if r["is_heading"]:
            level = _heading_level_from_number(r["norm"])
            if level is None:
                s = round(r["size"] * 2) / 2
                level = sizes.index(s) + 1 if s in sizes else len(sizes) + 1
            blocks.append(Block(text=r["norm"], kind="heading", level=level, page=r["page"], page_end=r["page"]))
        else:
            blocks.append(Block(text=r["norm"], kind="paragraph", page=r["page"], page_end=r["page"]))

    blocks = _merge_cross_page(blocks)
    if not any(b.kind == "heading" for b in blocks):
        warnings.append("no headings detected; structure-aware chunking will fall back to size-based splits")
    return blocks, page_count, warnings, meta_title


def _strip_running_text(raw: list[dict], page_count: int) -> list[dict]:
    """Drop repeated headers/footers and bare page numbers found in the page margins."""
    keys_per_page: dict[int, set[str]] = {}
    for r in raw:
        if r["in_margin"]:
            key = re.sub(r"\d+", "#", re.sub(r"\s+", " ", r["text"]).strip().lower())
            keys_per_page.setdefault(r["page"], set()).add(key)
    page_hits = Counter(k for keys in keys_per_page.values() for k in keys)
    threshold = max(3, int(0.4 * page_count))
    repeated = {k for k, c in page_hits.items() if c >= threshold}

    kept = []
    for r in raw:
        if r["in_margin"]:
            key = re.sub(r"\d+", "#", re.sub(r"\s+", " ", r["text"]).strip().lower())
            if key in repeated or _PAGE_NUMBER.match(r["text"]):
                continue
        kept.append(r)
    return kept


def _merge_cross_page(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.kind == "paragraph"
            and b.kind == "paragraph"
            and prev.last_page is not None
            and b.page == prev.last_page + 1
            and not prev.text.rstrip().endswith((".", "!", "?", ":", ";"))
            and b.text[:1].islower()
        ):
            prev.text = f"{prev.text} {b.text}"
            prev.page_end = b.last_page
        else:
            out.append(b)
    return out


# --------------------------------------------------------------------------- Markdown

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta, text[m.end():]


def _load_markdown(text: str) -> tuple[list[Block], dict]:
    meta, body = _parse_front_matter(text.replace("\r\n", "\n"))
    blocks: list[Block] = []
    para: list[str] = []
    in_fence = False
    fence_lines: list[str] = []

    def flush():
        if para:
            t = normalize_text("\n".join(para), keep_newlines=True)
            if t:
                blocks.append(Block(text=t, kind="paragraph"))
            para.clear()

    for line in body.split("\n"):
        if _FENCE.match(line):
            if in_fence:
                fence_lines.append(line)
                blocks.append(Block(text="\n".join(fence_lines), kind="paragraph"))
                fence_lines = []
                in_fence = False
            else:
                flush()
                in_fence = True
                fence_lines = [line]
            continue
        if in_fence:
            fence_lines.append(line)
            continue
        m = _MD_HEADING.match(line)
        if m:
            flush()
            blocks.append(Block(text=normalize_text(m.group(2)), kind="heading", level=len(m.group(1))))
        elif not line.strip():
            flush()
        else:
            para.append(line)
    flush()
    if fence_lines:  # unterminated fence
        blocks.append(Block(text="\n".join(fence_lines), kind="paragraph"))
    return blocks, meta


# --------------------------------------------------------------------------- HTML

_HTML_BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "table"]
_HTML_SKIP_PARENTS = {"li", "blockquote", "pre", "table"}


def _load_html(raw: bytes | str) -> tuple[list[Block], str | None]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None
    root = soup.body or soup
    blocks: list[Block] = []
    for el in root.find_all(_HTML_BLOCK_TAGS):
        if any(p.name in _HTML_SKIP_PARENTS for p in el.parents if p is not root):
            continue
        if el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [normalize_text(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
                if any(cells):
                    rows.append(" | ".join(cells))
            text = "\n".join(rows)
        elif el.name == "pre":
            text = el.get_text().strip("\n")
        else:
            text = normalize_text(el.get_text(" "))
        if not text.strip():
            continue
        if el.name.startswith("h") and len(el.name) == 2 and el.name[1].isdigit():
            blocks.append(Block(text=text, kind="heading", level=int(el.name[1])))
        else:
            blocks.append(Block(text=text, kind="paragraph"))
    return blocks, title


# --------------------------------------------------------------------------- entry point


def load_document(path: Path, root: Path) -> Document:
    """Load one file into a `Document`. Raises on unsupported or unreadable files."""
    path = Path(path)
    root = Path(root)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported file type: {path.suffix}")

    rel = path.relative_to(root).as_posix()
    side = read_sidecar(path)
    warnings: list[str] = []
    page_count: int | None = None
    title: str | None = None

    if suffix == ".pdf":
        blocks, page_count, warnings, meta_title = _load_pdf(path)
        first_h = next((b.text for b in blocks if b.kind == "heading" and (b.page or 1) <= 1), None)
        title = first_h or meta_title
    elif suffix in {".md", ".markdown"}:
        blocks, fm = _load_markdown(path.read_text(encoding="utf-8", errors="replace"))
        side = {**fm, **side}
        title = next((b.text for b in blocks if b.kind == "heading"), None)
    else:
        blocks, html_title = _load_html(path.read_bytes())
        title = html_title or next((b.text for b in blocks if b.kind == "heading"), None)

    if not blocks and not any("no extractable text" in w for w in warnings):
        warnings.append("no extractable text")

    return Document(
        doc_id=doc_id_for(rel),
        doc_hash=file_sha256(path),
        source_file=rel,
        title=str(side.get("title") or title or path.stem),
        doc_type=str(side.get("doc_type") or "unknown"),
        jurisdiction=side.get("jurisdiction"),
        effective_date=str(side["effective_date"]) if side.get("effective_date") else None,
        page_count=page_count,
        blocks=blocks,
        warnings=warnings,
    )


def discover_files(root: Path) -> list[Path]:
    """All supported files under `root`, sorted for deterministic runs."""
    return sorted(p for p in Path(root).rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
