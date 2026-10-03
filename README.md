# Citerator

Compliance Q&A with citations you can verify. Every answer is traced back to its
source clause, scored for confidence, and escalated to a human when the evidence
is not strong enough.

> Status: scaffolding. Architecture diagram, setup guide, and eval results coming.

## Quick start

    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    copy .env.example .env
    docker compose -f docker\docker-compose.yml up -d

## Layout

    citerator/      core package (ingestion, retrieval, generation, observability, api)
    eval/           question set, eval runner, timestamped results
    dashboard/      Streamlit UI
    data/           raw documents and processed chunks (git-ignored)
    docker/         docker compose for Qdrant (later: API and dashboard)
    tests/          unit tests

*Decision-support tool, not legal advice.*