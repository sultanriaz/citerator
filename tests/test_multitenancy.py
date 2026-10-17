from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models

from citerator.api import documents_routes
from citerator.api.app import create_app
from citerator.api.deps import (
    TenantContext,
    clear_tenant_keys,
    register_tenant_key,
)
from citerator.cache import get_cache, reset_cache
from citerator.config import Settings, get_settings
from citerator.documents import ingest_service
from citerator.generation.citations import parse_citations
from citerator.retrieval.rerank import FakeReranker, rerank
from citerator.retrieval.search import (
    RetrievalFilters,
    RetrievedChunk,
    _build_filter,
    search,
)


@pytest.fixture
def multitenant_env(tmp_path: Path, monkeypatch) -> tuple[Settings, QdrantClient]:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "10000")
    get_settings.cache_clear()

    root = tmp_path / "docs"
    root.mkdir()
    db = tmp_path / "processed" / "documents.sqlite"

    s = Settings(
        documents_root=str(root),
        documents_db_path=str(db),
        embedder_kind="hash",
        sparse_kind="hash",
        embedding_model="hash",
        active_chunking_strategy="structure",
        qdrant_url=":memory:",
        max_concurrent_ingest_jobs=4,
        api_key="secret",
        cors_origins=["*"],
        max_upload_mb=1,
        rate_limit_requests_per_minute=10000,
    )

    shared_client = QdrantClient(location=":memory:")
    monkeypatch.setattr("citerator.config.get_settings", lambda: s)
    monkeypatch.setattr("citerator.api.app.get_settings", lambda: s)
    monkeypatch.setattr(ingest_service, "make_client", lambda url: shared_client)
    monkeypatch.setattr(documents_routes, "make_client", lambda url: shared_client)
    return s, shared_client


@pytest.fixture
def app_client(multitenant_env: tuple[Settings, QdrantClient]) -> TestClient:
    settings, _ = multitenant_env
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _wait_for_job(client: TestClient, job_id: str, headers: dict, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/documents/jobs/{job_id}", headers=headers)
        assert r.status_code == 200
        body = r.json()
        if body["status"] in {"indexed", "failed"}:
            return body
        time.sleep(0.1)
    raise AssertionError(f"Job {job_id} did not finish within {timeout}s: body={body}")


def test_build_filter_multitenant_boundary() -> None:
    # 1. Analyst from tenant_acme
    filters = RetrievalFilters(
        tenant_id="tenant_acme",
        owner_id="user_alice",
        visibility="tenant",
    )
    qfilter = _build_filter(filters)
    assert qfilter is not None
    # Must have condition on tenant_id allowing tenant_acme + global
    must_clauses = qfilter.must
    assert any(
        isinstance(c, models.FieldCondition)
        and c.key == "tenant_id"
        and isinstance(c.match, models.MatchAny)
        and set(c.match.any) == {"tenant_acme", "global"}
        for c in must_clauses
    )

    # 2. Global tenant sees all or global docs
    filters_global = RetrievalFilters(tenant_id="global")
    qfilter_global = _build_filter(filters_global)
    assert qfilter_global is not None


def test_multitenant_upload_and_isolation(app_client: TestClient) -> None:
    # --- Tenant Acme headers ---
    alice_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "user_alice",
        "X-User-Role": "analyst",
    }
    charlie_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "user_charlie",
        "X-User-Role": "analyst",
    }
    acme_admin_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "admin_acme",
        "X-User-Role": "admin",
    }

    # --- Tenant FinTech headers ---
    bob_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_fintech",
        "X-User-Id": "user_bob",
        "X-User-Role": "analyst",
    }

    # --- Global admin headers ---
    global_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "global",
        "X-User-Id": "system_admin",
        "X-User-Role": "admin",
    }

    # 1. Alice (Acme) uploads a tenant-shared document
    r = app_client.post(
        "/documents/upload",
        files={"files": ("acme_policy.md", b"# Acme Policy\n\nConfidential AML.", "text/markdown")},
        data={"doc_type": "policy", "jurisdiction": "US", "visibility": "tenant"},
        headers=alice_headers,
    )
    assert r.status_code == 202
    job_acme = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], alice_headers)
    assert job_acme["status"] == "indexed"
    acme_doc_id = job_acme["doc_id"]

    # 2. Alice (Acme) uploads a private document
    r = app_client.post(
        "/documents/upload",
        files={"files": ("alice_draft.md", b"# Alice Private Notes\n\nSecret investigation.", "text/markdown")},
        data={"doc_type": "notes", "visibility": "private"},
        headers=alice_headers,
    )
    assert r.status_code == 202
    job_private = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], alice_headers)
    assert job_private["status"] == "indexed"
    private_doc_id = job_private["doc_id"]

    # 3. Bob (FinTech) uploads a tenant-shared document
    r = app_client.post(
        "/documents/upload",
        files={"files": ("fintech_guide.md", b"# FinTech Guidelines\n\nFinTech rules.", "text/markdown")},
        data={"doc_type": "guide", "visibility": "tenant"},
        headers=bob_headers,
    )
    assert r.status_code == 202
    job_fintech = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], bob_headers)
    assert job_fintech["status"] == "indexed"
    fintech_doc_id = job_fintech["doc_id"]

    # 4. Global admin uploads a public document
    r = app_client.post(
        "/documents/upload",
        files={"files": ("fatf_global.md", b"# FATF 40 Recommendations\n\nGlobal regulatory standard.", "text/markdown")},
        data={"doc_type": "standard", "visibility": "public"},
        headers=global_headers,
    )
    assert r.status_code == 202
    job_global = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], global_headers)
    assert job_global["status"] == "indexed"
    global_doc_id = job_global["doc_id"]

    # --- VERIFY LISTING ISOLATION ---

    # Alice should see: Acme policy + Alice's private draft + Global doc. NOT FinTech doc.
    r = app_client.get("/documents", headers=alice_headers)
    assert r.status_code == 200
    alice_doc_ids = {d["doc_id"] for d in r.json()["documents"]}
    assert acme_doc_id in alice_doc_ids
    assert private_doc_id in alice_doc_ids
    assert global_doc_id in alice_doc_ids
    assert fintech_doc_id not in alice_doc_ids

    # Charlie (Acme colleague) should see: Acme policy + Global doc. NOT Alice's private draft, NOT FinTech doc.
    r = app_client.get("/documents", headers=charlie_headers)
    assert r.status_code == 200
    charlie_doc_ids = {d["doc_id"] for d in r.json()["documents"]}
    assert acme_doc_id in charlie_doc_ids
    assert global_doc_id in charlie_doc_ids
    assert private_doc_id not in charlie_doc_ids
    assert fintech_doc_id not in charlie_doc_ids

    # Acme Admin should see: Acme policy + Alice's private draft + Global doc. NOT FinTech doc.
    r = app_client.get("/documents", headers=acme_admin_headers)
    assert r.status_code == 200
    admin_doc_ids = {d["doc_id"] for d in r.json()["documents"]}
    assert acme_doc_id in admin_doc_ids
    assert private_doc_id in admin_doc_ids
    assert global_doc_id in admin_doc_ids
    assert fintech_doc_id not in admin_doc_ids

    # Bob (FinTech) should see: FinTech guide + Global doc. NOT Acme policy, NOT Alice's draft.
    r = app_client.get("/documents", headers=bob_headers)
    assert r.status_code == 200
    bob_doc_ids = {d["doc_id"] for d in r.json()["documents"]}
    assert fintech_doc_id in bob_doc_ids
    assert global_doc_id in bob_doc_ids
    assert acme_doc_id not in bob_doc_ids
    assert private_doc_id not in bob_doc_ids

    # --- VERIFY DIRECT ACCESS / CHUNKS / 403 PERMISSIONS ---

    # Bob trying to view Acme doc -> 403 Forbidden
    r = app_client.get(f"/documents/{acme_doc_id}", headers=bob_headers)
    assert r.status_code == 403
    r = app_client.get(f"/documents/{acme_doc_id}/chunks", headers=bob_headers)
    assert r.status_code == 403

    # Charlie trying to view Alice's private doc -> 403 Forbidden
    r = app_client.get(f"/documents/{private_doc_id}", headers=charlie_headers)
    assert r.status_code == 403

    # Alice viewing her own private doc -> 200 OK
    r = app_client.get(f"/documents/{private_doc_id}", headers=alice_headers)
    assert r.status_code == 200

    # Acme admin viewing Alice's private doc -> 200 OK
    r = app_client.get(f"/documents/{private_doc_id}", headers=acme_admin_headers)
    assert r.status_code == 200

    # All users can view Global doc -> 200 OK
    r = app_client.get(f"/documents/{global_doc_id}", headers=alice_headers)
    assert r.status_code == 200
    r = app_client.get(f"/documents/{global_doc_id}", headers=bob_headers)
    assert r.status_code == 200

    # --- VERIFY DELETE PERMISSIONS ---

    # Bob trying to delete Acme doc -> 403 Forbidden
    r = app_client.delete(f"/documents/{acme_doc_id}", headers=bob_headers)
    assert r.status_code == 403

    # Charlie trying to delete Alice's private doc -> 403 Forbidden
    r = app_client.delete(f"/documents/{private_doc_id}", headers=charlie_headers)
    assert r.status_code == 403

    # Alice deletes her private doc -> 204 No Content
    r = app_client.delete(f"/documents/{private_doc_id}", headers=alice_headers)
    assert r.status_code == 204

    # Verify Alice's private doc is gone
    r = app_client.get(f"/documents/{private_doc_id}", headers=alice_headers)
    assert r.status_code == 404


def test_multitenant_search_and_query_isolation(
    app_client: TestClient, multitenant_env: tuple[Settings, QdrantClient]
) -> None:
    settings, shared_client = multitenant_env

    alice_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "user_alice",
        "X-User-Role": "analyst",
    }
    bob_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_fintech",
        "X-User-Id": "user_bob",
        "X-User-Role": "analyst",
    }
    global_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "global",
        "X-User-Id": "system_admin",
        "X-User-Role": "admin",
    }

    # Upload Acme document
    r = app_client.post(
        "/documents/upload",
        files={"files": ("acme_rules.md", b"# Acme Rule\n\nAcme customer risk threshold.", "text/markdown")},
        data={"doc_type": "policy", "visibility": "tenant"},
        headers=alice_headers,
    )
    assert r.status_code == 202
    job_acme = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], alice_headers)
    assert job_acme["status"] == "indexed"

    # Upload FinTech document
    r = app_client.post(
        "/documents/upload",
        files={"files": ("fintech_rules.md", b"# FinTech Rule\n\nFintech transaction threshold.", "text/markdown")},
        data={"doc_type": "policy", "visibility": "tenant"},
        headers=bob_headers,
    )
    assert r.status_code == 202
    job_fintech = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], bob_headers)
    assert job_fintech["status"] == "indexed"

    # Upload Global document
    r = app_client.post(
        "/documents/upload",
        files={"files": ("global_fatf.md", b"# FATF Rule\n\nGlobal international standard threshold.", "text/markdown")},
        data={"doc_type": "standard", "visibility": "public"},
        headers=global_headers,
    )
    assert r.status_code == 202
    job_global = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], global_headers)
    assert job_global["status"] == "indexed"

    from citerator.retrieval.search import search

    # Search as Acme tenant
    acme_filters = RetrievalFilters(tenant_id="tenant_acme", owner_id="user_alice", visibility="tenant")
    acme_chunks = search(
        "threshold",
        settings,
        filters=acme_filters,
        client=shared_client,
    )
    acme_sources = {c.source_file for c in acme_chunks}
    assert any("acme_rules.md" in s for s in acme_sources)
    assert any("global_fatf.md" in s for s in acme_sources)
    assert not any("fintech_rules.md" in s for s in acme_sources), "Acme must NOT see FinTech chunks!"

    # Search as FinTech tenant
    fintech_filters = RetrievalFilters(tenant_id="tenant_fintech", owner_id="user_bob", visibility="tenant")
    fintech_chunks = search(
        "threshold",
        settings,
        filters=fintech_filters,
        client=shared_client,
    )
    fintech_sources = {c.source_file for c in fintech_chunks}
    assert any("fintech_rules.md" in s for s in fintech_sources)
    assert any("global_fatf.md" in s for s in fintech_sources)
    assert not any("acme_rules.md" in s for s in fintech_sources), "FinTech must NOT see Acme chunks!"


def test_forged_tenant_and_role_escalation_denied(app_client: TestClient) -> None:
    clear_tenant_keys()
    try:
        # Register server-side keys
        register_tenant_key("acme_key", "tenant_acme", is_admin=False, allowed_tenants=["tenant_acme"])
        register_tenant_key("fintech_key", "tenant_fintech", is_admin=False, allowed_tenants=["tenant_fintech"])
        register_tenant_key("admin_key", "tenant_acme", is_admin=True, allowed_tenants=["tenant_acme", "tenant_fintech", "global"])

        # 1. Normal authenticated request with valid tenant key
        r = app_client.get("/documents", headers={"X-API-Key": "acme_key", "X-Tenant-Id": "tenant_acme"})
        assert r.status_code == 200

        # 2. Tenant forgery: acme_key attempts to claim tenant_fintech
        r = app_client.get("/documents", headers={"X-API-Key": "acme_key", "X-Tenant-Id": "tenant_fintech"})
        assert r.status_code == 403
        assert "Tenant forgery detected" in r.json()["detail"]

        # 3. Horizontal privilege escalation / BOLA: fintech_key attempts to list tenant_acme docs
        r = app_client.get("/documents", headers={"X-API-Key": "fintech_key", "X-Tenant-Id": "tenant_acme"})
        assert r.status_code == 403
        assert "Tenant forgery detected" in r.json()["detail"]

        # 4. Role privilege escalation: acme_key self-promotes to admin
        r = app_client.get(
            "/documents",
            headers={"X-API-Key": "acme_key", "X-Tenant-Id": "tenant_acme", "X-User-Role": "admin"},
        )
        assert r.status_code == 403
        assert "Privilege escalation detected" in r.json()["detail"]

        # 5. Admin key with admin role claim succeeds
        r = app_client.get(
            "/documents",
            headers={"X-API-Key": "admin_key", "X-Tenant-Id": "tenant_acme", "X-User-Role": "admin"},
        )
        assert r.status_code == 200

        # 6. Completely invalid / rogue API key returns 401
        r = app_client.get("/documents", headers={"X-API-Key": "rogue_unregistered_key"})
        assert r.status_code == 401
    finally:
        clear_tenant_keys()


def test_cross_tenant_query_body_and_cache_isolation(
    app_client: TestClient, multitenant_env: tuple[Settings, QdrantClient]
) -> None:
    settings, _ = multitenant_env

    # 1. Cross-tenant query body validation
    # Acme user supplies request body with tenant_id="tenant_fintech"
    r = app_client.post(
        "/query",
        json={"question": "What is the threshold?", "tenant_id": "tenant_fintech"},
        headers={"X-API-Key": "secret", "X-Tenant-Id": "tenant_acme", "X-User-Role": "analyst"},
    )
    assert r.status_code == 403
    assert "Cross-tenant query forbidden" in r.text

    # 2. Cache isolation between tenants
    settings.cache_enabled = True
    reset_cache()
    try:
        cache = get_cache(settings)
        assert cache is not None

        test_question = "What is the suspicious activity threshold limit?"
        acme_cached_answer = {
            "state": "grounded",
            "answer": "Acme AML threshold is exactly $10,000.",
            "confidence": "high",
            "citations": [],
            "related_passages": [],
            "escalation_draft": None,
            "latency_ms": 15.0,
            "tokens": 42,
        }

        # Store in cache under tenant_acme
        cache.store(test_question, acme_cached_answer, tenant="tenant_acme")

        # FinTech tenant must get a cache miss (None)
        fintech_cached = cache.lookup(test_question, tenant="tenant_fintech")
        assert fintech_cached is None, "FinTech must not read Acme cached response!"

        # Unscoped / Global tenant must get a cache miss (None)
        global_cached = cache.lookup(test_question, tenant="global")
        assert global_cached is None, "Global lookup must not read tenant-scoped cached response!"

        # Default lookup without tenant must get a cache miss
        default_cached = cache.lookup(test_question)
        assert default_cached is None

        # Acme tenant lookup must succeed with exact cached result
        acme_lookup = cache.lookup(test_question, tenant="tenant_acme")
        assert acme_lookup is not None
        assert acme_lookup["answer"] == "Acme AML threshold is exactly $10,000."
    finally:
        reset_cache()


def test_missing_tenant_context_default_deny(
    app_client: TestClient,
    multitenant_env: tuple[Settings, QdrantClient],
) -> None:
    settings, shared_client = multitenant_env

    # 1. RetrievalFilters without tenant_id produces strict default-deny filter
    qf = _build_filter(RetrievalFilters())
    assert qf is not None
    must_conditions = {c.key: c.match.value for c in qf.must if hasattr(c.match, "value")}
    assert must_conditions.get("tenant_id") == "global"
    assert must_conditions.get("visibility") == "public"

    # 2. None filters also produce strict default-deny filter
    qf_none = _build_filter(None)
    assert qf_none is not None
    must_none = {c.key: c.match.value for c in qf_none.must if hasattr(c.match, "value")}
    assert must_none.get("tenant_id") == "global"
    assert must_none.get("visibility") == "public"

    # 3. Upload Acme doc (tenant_id="tenant_acme") and Global doc (tenant_id="global")
    alice_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "user_alice",
        "X-User-Role": "analyst",
    }
    global_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "global",
        "X-User-Id": "admin",
        "X-User-Role": "admin",
    }
    r = app_client.post(
        "/documents/upload",
        files={"files": ("acme_restricted.md", b"# Restricted\n\nConfidential Acme AML threshold.", "text/markdown")},
        data={"doc_type": "policy", "visibility": "tenant"},
        headers=alice_headers,
    )
    assert r.status_code == 202
    _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], alice_headers)

    r = app_client.post(
        "/documents/upload",
        files={"files": ("fatf_open.md", b"# FATF Open\n\nPublic international threshold standard.", "text/markdown")},
        data={"doc_type": "standard", "visibility": "public"},
        headers=global_headers,
    )
    assert r.status_code == 202
    _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], global_headers)

    # 4. Executing search with no tenant filters only returns global public points
    results = search("threshold", settings, filters=None, client=shared_client)
    assert len(results) > 0, "Expected to retrieve public global documents"
    for c in results:
        assert getattr(c, "tenant_id", "global") == "global"
        assert getattr(c, "visibility", "public") == "public"
        assert "acme_restricted.md" not in c.source_file, "Unauthenticated / missing tenant search leaked Acme doc!"


def test_rerank_and_citation_defense_in_depth(
    multitenant_env: tuple[Settings, QdrantClient],
) -> None:
    settings, _ = multitenant_env

    chunk_acme = RetrievedChunk(
        chunk_id="chunk_acme_1",
        doc_id="doc_acme",
        doc_hash="hash1",
        source_file="acme.md",
        doc_title="Acme Policy",
        doc_type="policy",
        tenant_id="tenant_acme",
        visibility="tenant",
        char_start=0,
        char_end=100,
        text="Acme customer threshold is 10k.",
        token_count=10,
        embed_token_count=10,
        chunk_index=0,
        chunker="structure",
    )

    chunk_fintech = RetrievedChunk(
        chunk_id="chunk_fintech_1",
        doc_id="doc_fintech",
        doc_hash="hash2",
        source_file="fintech.md",
        doc_title="FinTech Policy",
        doc_type="policy",
        tenant_id="tenant_fintech",
        visibility="tenant",
        char_start=0,
        char_end=100,
        text="FinTech transaction limit is 50k.",
        token_count=10,
        embed_token_count=10,
        chunk_index=0,
        chunker="structure",
    )

    chunk_global = RetrievedChunk(
        chunk_id="chunk_global_1",
        doc_id="doc_global",
        doc_hash="hash3",
        source_file="global.md",
        doc_title="FATF Recommendations",
        doc_type="standard",
        tenant_id="global",
        visibility="public",
        char_start=0,
        char_end=100,
        text="International FATF threshold guidelines.",
        token_count=10,
        embed_token_count=10,
        chunk_index=0,
        chunker="structure",
    )

    chunk_private_alice = RetrievedChunk(
        chunk_id="chunk_alice_priv_1",
        doc_id="doc_alice",
        doc_hash="hash4",
        source_file="alice_notes.md",
        doc_title="Alice Notes",
        doc_type="notes",
        tenant_id="tenant_acme",
        owner_id="user_alice",
        visibility="private",
        char_start=0,
        char_end=100,
        text="Confidential investigation notes by Alice.",
        token_count=10,
        embed_token_count=10,
        chunk_index=0,
        chunker="structure",
    )

    all_chunks = [chunk_acme, chunk_fintech, chunk_global, chunk_private_alice]
    fake_reranker = FakeReranker({"threshold": 0.9, "FATF": 0.8, "notes": 0.7, "FinTech": 0.95})

    # A. Charlie (Acme colleague, non-owner) reranking:
    # Must drop FinTech chunk (cross-tenant) AND Alice's private chunk (private visibility)
    charlie_tenant = TenantContext(
        tenant_id="tenant_acme",
        user_id="user_charlie",
        roles=["analyst"],
        is_admin=False,
    )
    reranked = rerank(
        "threshold",
        all_chunks,
        settings,
        reranker=fake_reranker,
        tenant=charlie_tenant,
    )
    reranked_ids = {c.chunk_id for c in reranked}
    assert "chunk_acme_1" in reranked_ids
    assert "chunk_global_1" in reranked_ids
    assert "chunk_fintech_1" not in reranked_ids, "Cross-tenant candidate was NOT dropped before reranker!"
    assert "chunk_alice_priv_1" not in reranked_ids, "Private candidate was NOT dropped before reranker!"

    # B. Citation resolution authorization:
    # Answer citing [1] (Acme), [2] (FinTech), [3] (Global)
    llm_answer = "Acme customer threshold is 10k [1]. Unauthorized reference [2]. International FATF threshold guidelines apply [3]."
    candidates_for_citations = [chunk_acme, chunk_fintech, chunk_global]

    acme_tenant = TenantContext(
        tenant_id="tenant_acme",
        user_id="user_alice",
        roles=["analyst"],
        is_admin=False,
    )
    citations = parse_citations(
        llm_answer,
        candidates_for_citations,
        tenant=acme_tenant,
    )
    cited_chunk_ids = {c.chunk_id for c in citations}
    assert "chunk_acme_1" in cited_chunk_ids
    assert "chunk_global_1" in cited_chunk_ids
    assert "chunk_fintech_1" not in cited_chunk_ids, "Cross-tenant citation was NOT dropped during citation resolution!"


def test_direct_document_idor_and_bola_all_endpoints(app_client: TestClient) -> None:
    alice_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "user_alice",
        "X-User-Role": "analyst",
    }
    charlie_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "user_charlie",
        "X-User-Role": "analyst",
    }
    bob_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_fintech",
        "X-User-Id": "user_bob",
        "X-User-Role": "analyst",
    }
    admin_headers = {
        "X-API-Key": "secret",
        "X-Tenant-Id": "tenant_acme",
        "X-User-Id": "admin_acme",
        "X-User-Role": "admin",
    }

    # Upload Acme document owned by Alice
    r = app_client.post(
        "/documents/upload",
        files={"files": ("acme_contracts.md", b"# Acme Contracts\n\nDirect access test.", "text/markdown")},
        data={"doc_type": "policy", "visibility": "tenant"},
        headers=alice_headers,
    )
    assert r.status_code == 202
    job = _wait_for_job(app_client, r.json()["accepted"][0]["job_id"], alice_headers)
    doc_id = job["doc_id"]

    # IDOR / BOLA Attempt 1: Bob (different tenant) tries GET /documents/{doc_id} -> 403
    r = app_client.get(f"/documents/{doc_id}", headers=bob_headers)
    assert r.status_code == 403

    # IDOR / BOLA Attempt 2: Bob tries GET /documents/{doc_id}/chunks -> 403
    r = app_client.get(f"/documents/{doc_id}/chunks", headers=bob_headers)
    assert r.status_code == 403

    # IDOR / BOLA Attempt 3: Bob tries POST /documents/{doc_id}/reindex -> 403
    r = app_client.post(f"/documents/{doc_id}/reindex", headers=bob_headers)
    assert r.status_code == 403

    # IDOR / BOLA Attempt 4: Bob tries DELETE /documents/{doc_id} -> 403
    r = app_client.delete(f"/documents/{doc_id}", headers=bob_headers)
    assert r.status_code == 403

    # Horizontal IDOR Attempt 5: Charlie (same tenant, but not owner or admin) tries reindex & delete -> 403
    r = app_client.post(f"/documents/{doc_id}/reindex", headers=charlie_headers)
    assert r.status_code == 403
    r = app_client.delete(f"/documents/{doc_id}", headers=charlie_headers)
    assert r.status_code == 403

    # Legitimate Owner Attempt: Alice can read and reindex -> 200 / 202
    r = app_client.get(f"/documents/{doc_id}", headers=alice_headers)
    assert r.status_code == 200
    r = app_client.post(f"/documents/{doc_id}/reindex", headers=alice_headers)
    assert r.status_code == 202

    # Legitimate Admin Attempt: Admin can reindex and delete -> 202 / 204
    r = app_client.post(f"/documents/{doc_id}/reindex", headers=admin_headers)
    assert r.status_code == 202
    r = app_client.delete(f"/documents/{doc_id}", headers=admin_headers)
    assert r.status_code == 204



