# Citerator — Citation-Verified Hybrid RAG Platform for Compliance

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-Vector_DB-DC2626?style=for-the-badge&logo=qdrant&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)
![Langfuse](https://img.shields.io/badge/Langfuse-Telemetry-000000?style=for-the-badge&logo=langfuse&logoColor=white)
![Ragas](https://img.shields.io/badge/Ragas-Evaluation-4F46E5?style=for-the-badge)

Citerator is an enterprise-grade retrieval-augmented generation (RAG) platform engineered for regulatory compliance and Anti-Money Laundering (AML) audit workflows. It implements dense-sparse hybrid retrieval, cross-encoder re-ranking, three-band confidence guardrails, Langfuse telemetry, and automated Ragas benchmark verification.

---

## 🏛️ Pipeline Architecture

```mermaid
flowchart TD
    UserQuery["User Regulatory Compliance Query"] --> HybridCtrl["Hybrid Retrieval Controller"]
    HybridCtrl --> DenseEmbed["BAAI/bge-small-en-v1.5 Dense Embeddings"]
    HybridCtrl --> SparseBM25["Sparse Lexical BM25 Search"]
    DenseEmbed --> Qdrant[("Qdrant Vector Engine")]
    SparseBM25 --> Qdrant
    Qdrant --> RRF["Reciprocal Rank Fusion (RRF)"]
    RRF --> CrossEncoder["Cross-Encoder Reranker (top-k=5)"]
    CrossEncoder --> SigmoidFilter["3-Band Sigmoid Confidence Guardrail"]
    
    SigmoidFilter -->|"Score < 0.60 (Insufficient)"| Refusal["Deterministic Rejection & Audit Log"]
    SigmoidFilter -->|"0.60 <= Score < 0.82 (Low)"| Hedged["Hedged Answer + Mandatory Audit Flag"]
    SigmoidFilter -->|"Score >= 0.82 (Confident)"| Generator["Grounding LLM Generation"]
    
    Generator --> CitationSpan["Exact Chunk & Paragraph Citation Mapping"]
    CitationSpan --> Tracing["Langfuse Telemetry & Cost Tracing"]
    Tracing --> FinalResponse["Verified Answer with Cryptographic Chunk Hashes"]
```

---

## 🔬 Core Engineering Highlights

1. **Hybrid Retrieval with Reciprocal Rank Fusion (RRF):** Dense semantic vectors (BGE) and sparse lexical scores (BM25) are fused directly within Qdrant, ensuring exact regulatory term recall and conceptual semantic coverage.
2. **Three-Band Sigmoid Guardrails:** Replaces brittle prompt instructions with mathematical confidence thresholding:
   - **`confident` ($\ge 0.82$):** Answer generated with exact paragraph citations.
   - **`low_confidence` ($0.60 \le s < 0.82$):** Hedged response requiring compliance officer review.
   - **`insufficient` ($< 0.60$):** Deterministic refusal to prevent hallucinations on missing regulatory clauses.
3. **Automated Ragas Evaluation:**
   - **Mean Faithfulness:** `0.97` across regulatory document validation splits.
   - **Refusal Accuracy:** `100%` on out-of-corpus adversarial queries.
4. **Langfuse Distributed Tracing:** End-to-end tracing of prompt tokens, generation latencies, and retrieval rank shifts.

---

## 📁 Repository Structure

```
citerator/
├── citerator/
│   ├── api/                   # FastAPI route definitions and dependencies
│   │   ├── app.py             # Application factory
│   │   ├── auth.py            # RBAC and JWT token management
│   │   ├── documents_routes.py# Regulatory PDF ingestion endpoints
│   │   ├── eval_routes.py     # Ragas test suite trigger routes
│   │   └── main.py            # Entrypoint
│   ├── core/                  # Configuration, logging, and security
│   ├── retrieval/             # BGE embeddings, BM25, and Qdrant client
│   └── eval/                  # Ragas benchmark execution harness
├── tests/                     # Unit and integration test suites
└── requirements.txt           # Dependency specification
```

---

## 🚀 Quickstart & Execution

```bash
git clone https://github.com/sultanriaz/citerator.git
cd citerator
python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn citerator.api.main:app --reload --port 8000
```
Open [http://localhost:8000/docs](http://localhost:8000/docs) to inspect the Swagger API interface.
