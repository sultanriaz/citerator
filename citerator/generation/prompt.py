"""Prompt construction for grounded compliance Q&A."""

from __future__ import annotations

from citerator.retrieval.search import RetrievedChunk


SYSTEM_PROMPT = """You are a compliance analyst assistant.

Answer ONLY from the numbered source chunks provided below.
Cite every claim with [n] matching the chunk's position in the provided list.
Never cite a number that was not provided.
If the sources do not contain enough information, say that the available sources are insufficient."""


def _format_section(section_path: list[str]) -> str:
    return " > ".join(section_path) if section_path else "no section"


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> tuple[str, str]:
    """Return ``(system, user)`` messages for the LLM."""

    lines = [f"Question: {question}", "", "Sources:"]

    for index, chunk in enumerate(chunks, start=1):
        page_text = ""
        if chunk.page_start is not None or chunk.page_end is not None:
            page_text = f" | pages {chunk.page_start or '?'}-{chunk.page_end or '?'}"

        lines.append(
            f"[{index}] {chunk.doc_title} | "
            f"{_format_section(chunk.section_path)} | "
            f"{chunk.source_file}{page_text}"
        )
        lines.append(chunk.text)
        lines.append("")

    return SYSTEM_PROMPT, "\n".join(lines)
