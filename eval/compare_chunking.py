
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from citerator.ingestion.embedding import get_embedder, get_sparse_embedder
from citerator.ingestion.pipeline import IngestConfig, run_ingestion
from citerator.ingestion.store import DENSE, make_client

log = logging.getLogger("eval.compare_chunking")


def load_labelled(path: Path) -> list[dict]:
    questions = json.loads(Path(path).read_text(encoding="utf-8"))
    labelled = []
    for q in questions:
        if q.get("expected_behavior", "answer") != "answer":
            continue
        if q.get("source_doc") and (q.get("source_page") or q.get("gold_section")):
            labelled.append(q)
    return labelled


def is_hit(payload: dict, q: dict) -> bool:
    if payload.get("source_file") != q["source_doc"]:
        return False
    ok = True
    if q.get("source_page"):
        sp = q["source_page"]
        lo, hi = (sp, sp) if isinstance(sp, int) else (sp[0], sp[1])
        ps, pe = payload.get("page_start"), payload.get("page_end")
        ok &= ps is not None and pe is not None and ps <= hi and pe >= lo  # page ranges overlap
    if q.get("gold_section"):
        ok &= q["gold_section"].lower() in " > ".join(payload.get("section_path") or []).lower()
    return ok


def evaluate(client, collection, embedder, questions, k) -> dict:
    hits, rr = [], []
    for q in questions:
        vec = embedder.embed_query(q["question"])
        res = client.query_points(collection, query=[float(x) for x in vec], using=DENSE, limit=k, with_payload=True)
        rank = next((i for i, p in enumerate(res.points, 1) if is_hit(p.payload, q)), None)
        hits.append(rank is not None)
        rr.append(1.0 / rank if rank else 0.0)
    return {f"hit@{k}": round(float(np.mean(hits)), 4), "mrr": round(float(np.mean(rr)), 4), "n_questions": len(questions)}


def plot(df: pd.DataFrame, k: int, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    labels = df["strategy"] + "\n" + df["embedder"]
    axes[0].bar(labels, df[f"hit@{k}"], color="#4f46e5")
    axes[0].set_title(f"Retrieval hit@{k} (higher is better)")
    axes[0].set_ylim(0, 1)
    axes[1].bar(labels, df["tokens_median"], color="#0d9488", label="median")
    axes[1].errorbar(labels, df["tokens_median"], yerr=[np.zeros(len(df)), df["tokens_p95"] - df["tokens_median"]],
                     fmt="none", ecolor="black", capsize=4, label="p95")
    axes[1].set_title("Chunk size in tokens (median, whisker to p95)")
    axes[1].legend()
    axes[2].bar(labels, df["n_chunks"], color="#d97706")
    axes[2].set_title("Number of chunks")
    for ax in axes:
        ax.tick_params(axis="x", labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--input", default="data/raw")
    p.add_argument("--questions", default="eval/questions.json")
    p.add_argument("--strategies", nargs="+", default=["fixed", "structure", "semantic"])
    p.add_argument("--embedders", nargs="+", default=["bge"], help="bge, openai, hash")
    p.add_argument("--sparse", default="none", help="sparse vectors are not needed for this comparison")
    p.add_argument("--qdrant-url", default=":memory:", help="':memory:' (default) keeps experiments out of your real DB")
    p.add_argument("--max-tokens", type=int, default=400)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--out-dir", default="eval/results")
    p.add_argument("--processed-dir", default="data/processed")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    questions = load_labelled(Path(args.questions))
    if not questions:
        print("error: no labelled questions found. Fill in `source_doc` and `source_page` (and/or "
              "`gold_section`) for questions with expected_behavior 'answer' in " + args.questions, file=sys.stderr)
        return 2
    print(f"Evaluating on {len(questions)} labelled questions")

    client = make_client(args.qdrant_url)
    rows = []
    for emb_kind in args.embedders:
        embedder = get_embedder(emb_kind)
        sparse = get_sparse_embedder(args.sparse)
        for strategy in args.strategies:
            cfg = IngestConfig(input_dir=Path(args.input), strategy=strategy, embedder=emb_kind, sparse=args.sparse,
                               qdrant_url=args.qdrant_url, max_tokens=args.max_tokens, force=True,
                               report_dir=Path(args.out_dir), processed_dir=Path(args.processed_dir))
            rep = run_ingestion(cfg, embedder=embedder, sparse=sparse, client=client)
            s = rep["stats"]
            metrics = evaluate(client, rep["config"]["collection"], embedder, questions, args.k)
            rows.append({"strategy": strategy, "embedder": embedder.name, **metrics,
                         "n_chunks": s["n_chunks"], "tokens_median": s["tokens_median"], "tokens_p95": s["tokens_p95"],
                         "overlap_ratio": s["overlap_ratio"], "pct_cross_page": s["pct_cross_page"],
                         "pct_over_model_limit": s["pct_over_model_limit"], "ingest_seconds": rep["seconds"],
                         "tokens_to_embed": s["embed_tokens_total"]})

    df = pd.DataFrame(rows)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path, png_path = out / f"chunking_comparison_{ts}.csv", out / f"chunking_comparison_{ts}.png"
    df.to_csv(csv_path, index=False)
    plot(df, args.k, png_path)
    print("\n" + df.to_string(index=False))
    print(f"\nSaved {csv_path} and {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
