"""Build the vaani retrieval corpus from one MSMARCO-XI language file.

Downloads a per-language parquet from the hub, explodes the 10 candidate
passages per query, dedups them into a passage corpus, and writes three
tables under data/corpus/<lang>_<split>/:

  passages.parquet  one row per unique passage (english + translated text,
                    appearance counts, selection counts, dominant query_type)
  queries.parquet   one row per query with answers and query_type
  qrels.parquet     (query_id, passage_id) pairs where is_selected = 1

Usage:
  uv run python scripts/build_corpus.py --lang hin --split val
  uv run python scripts/build_corpus.py --lang hin --split val --limit 20000
"""

import argparse
import time
from pathlib import Path

import duckdb
from huggingface_hub import hf_hub_download

REPO = "ai4bharat/MSMARCO-XI"

# hub file prefixes per language (see the repo file tree)
LANGS = {
    "asm": "Assamese", "ben": "Bengali", "guj": "Gujarati", "hin": "Hindi",
    "kan": "Kannada", "mal": "Malayalam", "mar": "Marathi", "nep": "Nepali",
    "ori": "Odia", "pan": "Punjabi", "san": "Sanskrit", "tam": "Tamil",
    "tel": "Telugu", "urd": "Urdu",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="hin", choices=sorted(LANGS))
    ap.add_argument("--split", default="val", choices=["val", "train"])
    ap.add_argument("--limit", type=int, default=0, help="cap on input rows, 0 = all")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    split_dir = "validation" if args.split == "val" else "train"
    filename = f"{split_dir}/{args.lang}{args.split}.parquet"
    print(f"downloading {REPO}/{filename} (cached after first run)")
    t0 = time.perf_counter()
    local = hf_hub_download(REPO, filename, repo_type="dataset")
    print(f"  file ready in {time.perf_counter() - t0:.1f}s -> {local}")

    out_dir = Path(args.data_dir) / "corpus" / f"{args.lang}_{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)

    limit_sql = f"LIMIT {args.limit}" if args.limit else ""
    con = duckdb.connect()
    local_sql = str(local).replace("\\", "/")

    t0 = time.perf_counter()
    con.execute(
        f"""
        CREATE TEMP TABLE src AS
        SELECT query_id, query_type, query, Eng_Query, Answer, Eng_Answer, passages
        FROM read_parquet('{local_sql}') {limit_sql}
        """
    )

    # one row per (query, passage slot); the three arrays zip positionally
    con.execute(
        """
        CREATE TEMP TABLE exploded AS
        SELECT
          query_id,
          query_type,
          unnest(passages.English_passages)    AS eng_text,
          unnest(passages.Translated_passages) AS tr_text,
          unnest(passages.is_selected)         AS is_selected
        FROM src
        """
    )

    # unique passages keyed by english text; md5 gives a stable cross-split id
    con.execute(
        """
        CREATE TEMP TABLE passages AS
        SELECT
          md5(eng_text)                       AS passage_id,
          arg_min(eng_text, eng_text)         AS eng_text,
          arg_min(tr_text, eng_text)          AS tr_text,
          count(*)                            AS n_appear,
          sum(is_selected)                    AS n_selected,
          mode(query_type)                    AS top_query_type,
          round(avg(length(eng_text)), 1)     AS eng_len
        FROM exploded
        WHERE eng_text IS NOT NULL AND length(trim(eng_text)) > 0
        GROUP BY md5(eng_text)
        """
    )

    con.execute(
        f"""
        COPY passages TO '{(out_dir / "passages.parquet").as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    con.execute(
        f"""
        COPY (
          SELECT query_id, query_type, query, Eng_Query AS eng_query,
                 Answer AS answer, Eng_Answer AS eng_answer
          FROM src
        ) TO '{(out_dir / "queries.parquet").as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    con.execute(
        f"""
        COPY (
          SELECT query_id, md5(eng_text) AS passage_id
          FROM exploded
          WHERE is_selected = 1
        ) TO '{(out_dir / "qrels.parquet").as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )

    n_q, n_p, n_rel, n_noans = con.execute(
        """
        SELECT
          (SELECT count(*) FROM src),
          (SELECT count(*) FROM passages),
          (SELECT count(*) FROM exploded WHERE is_selected = 1),
          (SELECT count(*) FROM src WHERE query_id NOT IN
             (SELECT DISTINCT query_id FROM exploded WHERE is_selected = 1))
        """
    ).fetchone()
    dt = time.perf_counter() - t0
    print(f"built in {dt:.1f}s -> {out_dir}")
    print(f"  queries={n_q:,}  unique_passages={n_p:,}  qrel_pairs={n_rel:,}")
    print(f"  queries with no selected passage (abstention gold): {n_noans:,}")

    stats = con.execute(
        """
        SELECT
          round(avg(length(eng_text)))                          AS avg_chars,
          round(quantile_cont(length(eng_text), 0.5))           AS p50_chars,
          round(quantile_cont(length(eng_text), 0.95))          AS p95_chars,
          max(length(eng_text))                                 AS max_chars
        FROM passages
        """
    ).fetchone()
    print(f"  passage length chars: avg={stats[0]} p50={stats[1]} p95={stats[2]} max={stats[3]}")


if __name__ == "__main__":
    main()
