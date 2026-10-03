"""Shared fixtures: small synthetic documents, built on the fly (no binary files in git)."""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

LOREM_CDD = (
    "Financial institutions must identify the customer and verify the customer's identity using reliable, "
    "independent source documents, data or information. Verification must take place before establishing "
    "the business relationship. Where the customer is a legal entity, the institution must understand its "
    "ownership and control structure."
)
LOREM_EDD = (
    "Enhanced due diligence is required for higher risk customers, including politically exposed persons and "
    "customers from high risk jurisdictions. Senior management approval must be obtained before establishing "
    "or continuing such relationships. The source of wealth and source of funds must be established."
)
LOREM_REC = (
    "Transaction records must be kept for at least five years after the transaction. Records must be sufficient "
    "to permit reconstruction of individual transactions so as to provide evidence for prosecution of criminal "
    "activity when necessary."
)


def _para(page, y, lines, size=10):
    for i, line in enumerate(lines):
        page.insert_text((72, y + i * 13), line, fontsize=size, fontname="helv")


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """4 pages: running header/footer, 2 heading levels, hyphenated line break, cross-page paragraph."""
    path = tmp_path / "manual.pdf"
    doc = pymupdf.open()
    for n in range(1, 5):
        page = doc.new_page()
        page.insert_text((72, 30), "ACME Compliance Manual", fontsize=9, fontname="helv")
        page.insert_text((72, 820), f"Page {n} of 4", fontsize=9, fontname="helv")
        if n == 1:
            page.insert_text((72, 110), "ACME AML Manual", fontsize=20, fontname="hebo")
            page.insert_text((72, 150), "1. Customer due diligence", fontsize=14, fontname="hebo")
            _para(page, 180, [
                "Financial institutions must identify the customer and verify the cus-",
                "tomer's identity using reliable, independent source documents. Verification",
                "must take place before establishing the business relationship and must also be",
            ])
        if n == 2:
            _para(page, 100, [
                "applied again whenever there are doubts about previously obtained data.",
            ])
            page.insert_text((72, 160), "2. Enhanced due diligence", fontsize=14, fontname="hebo")
            _para(page, 190, [
                "Enhanced due diligence is required for higher risk customers, including politically",
                "exposed persons and customers from high risk jurisdictions. Senior management",
                "approval must be obtained before establishing such relationships.",
            ])
        if n == 3:
            page.insert_text((72, 110), "3. Record keeping", fontsize=14, fontname="hebo")
            _para(page, 140, [
                "Transaction records must be kept for at least five years after the transaction.",
                "Records must permit reconstruction of individual transactions.",
            ])
        if n == 4:
            pass  # deliberately empty page: simulates a scan with no text layer
    doc.save(path)
    doc.close()
    return path


MARKDOWN_DOC = f"""---
title: Internal KYC Policy
doc_type: internal_policy
jurisdiction: PK
effective_date: 2026-01-01
---
# Internal KYC Policy

Intro paragraph about the purpose of this policy.

## Customer due diligence

{LOREM_CDD}

## Enhanced due diligence

{LOREM_EDD}

### Politically exposed persons

PEPs require senior management approval and ongoing monitoring.

## Record keeping

{LOREM_REC}

```
code block that must stay intact
  with indentation
```
"""

HTML_DOC = f"""<html><head><title>KYC FAQ</title><style>.x{{}}</style><script>var a=1;</script></head>
<body><nav>Home | About</nav>
<h1>KYC FAQ</h1>
<h2>Due diligence</h2><p>{LOREM_CDD}</p>
<ul><li>Verify identity</li><li>Understand ownership <p>nested paragraph</p></li></ul>
<h2>Records</h2><p>{LOREM_REC}</p>
<table><tr><th>Item</th><th>Years</th></tr><tr><td>Transactions</td><td>5</td></tr></table>
<footer>Copyright</footer></body></html>
"""


@pytest.fixture
def docs_dir(tmp_path, sample_pdf) -> Path:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "manual.pdf").write_bytes(sample_pdf.read_bytes())
    (root / "policy.md").write_text(MARKDOWN_DOC, encoding="utf-8")
    (root / "faq.html").write_text(HTML_DOC, encoding="utf-8")
    (root / "policy.md.meta.json").write_text('{"doc_type": "internal_policy", "jurisdiction": "PK"}', encoding="utf-8")
    return root
