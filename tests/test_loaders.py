from citerator.ingestion.loaders import (
    discover_files,
    doc_id_for,
    load_document,
    normalize_text,
)


def test_normalize_fixes_hyphenation_and_whitespace():
    assert normalize_text("the cus-\ntomer  must\u00a0verify") == "the customer must verify"
    # uppercase continuation is NOT dehyphenated (could be a real compound / acronym)
    assert normalize_text("cross-\nBorder") == "cross- Border"


def test_pdf_strips_running_header_footer_and_page_numbers(sample_pdf):
    doc = load_document(sample_pdf, sample_pdf.parent)
    text = " ".join(b.text for b in doc.blocks)
    assert "ACME Compliance Manual" not in text
    assert "Page 1 of 4" not in text and "Page 3 of 4" not in text


def test_pdf_dehyphenates_and_merges_paragraph_across_pages(sample_pdf):
    doc = load_document(sample_pdf, sample_pdf.parent)
    text = " ".join(b.text for b in doc.blocks)
    assert "customer's identity" in text and "cus-" not in text
    merged = next(b for b in doc.blocks if b.text.startswith("Financial institutions"))
    assert (merged.page, merged.last_page) == (1, 2)
    assert "applied again whenever" in merged.text


def test_pdf_detects_headings_levels_and_title(sample_pdf):
    doc = load_document(sample_pdf, sample_pdf.parent)
    heads = [(b.level, b.text) for b in doc.blocks if b.kind == "heading"]
    assert heads[0] == (1, "ACME AML Manual")
    assert (2, "1. Customer due diligence") in heads and (2, "3. Record keeping") in heads
    assert doc.title == "ACME AML Manual"
    assert doc.page_count == 4


def test_pdf_flags_page_without_text(sample_pdf):
    doc = load_document(sample_pdf, sample_pdf.parent)
    assert any("page 4" in w and "no extractable body text" in w for w in doc.warnings)


def test_markdown_front_matter_and_sidecar_metadata(docs_dir):
    doc = load_document(docs_dir / "policy.md", docs_dir)
    assert doc.title == "Internal KYC Policy"
    assert doc.doc_type == "internal_policy"
    assert doc.jurisdiction == "PK"  # from sidecar
    assert doc.effective_date == "2026-01-01"  # from front matter


def test_markdown_structure_and_code_block(docs_dir):
    doc = load_document(docs_dir / "policy.md", docs_dir)
    levels = [(b.level, b.text) for b in doc.blocks if b.kind == "heading"]
    assert (3, "Politically exposed persons") in levels
    code = next(b for b in doc.blocks if "code block that must stay intact" in b.text)
    assert "  with indentation" in code.text  # indentation preserved
    assert not any(b.text.startswith("---") for b in doc.blocks)  # front matter not in body


def test_html_strips_chrome_and_dedupes_nested_blocks(docs_dir):
    doc = load_document(docs_dir / "faq.html", docs_dir)
    text = "\n".join(b.text for b in doc.blocks)
    assert "Home | About" not in text and "Copyright" not in text and "var a=1" not in text
    assert text.count("nested paragraph") == 1
    assert "Transactions | 5" in text
    assert doc.title == "KYC FAQ"


def test_identity_is_stable_and_content_hash_changes(docs_dir):
    a = load_document(docs_dir / "policy.md", docs_dir)
    b = load_document(docs_dir / "policy.md", docs_dir)
    assert a.doc_id == b.doc_id == doc_id_for("policy.md") and a.doc_hash == b.doc_hash
    (docs_dir / "policy.md").write_text("# Changed\n\nNew text.", encoding="utf-8")
    c = load_document(docs_dir / "policy.md", docs_dir)
    assert c.doc_id == a.doc_id and c.doc_hash != a.doc_hash


def test_discover_files_ignores_unsupported(docs_dir):
    (docs_dir / "notes.txt").write_text("x")
    names = [p.name for p in discover_files(docs_dir)]
    assert names == sorted(["faq.html", "manual.pdf", "policy.md"])
