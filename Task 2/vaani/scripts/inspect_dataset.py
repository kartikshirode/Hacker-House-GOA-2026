"""Probe MSMARCO-XI remote parquet without downloading full files.

Reads the schema and a couple of rows from the Hindi validation split
over HTTP range requests, then prints corpus-shape stats that drive
chunking and index design.
"""

import json

import duckdb

URL = "https://huggingface.co/datasets/ai4bharat/MSMARCO-XI/resolve/main/validation/hinval.parquet"

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")

print("=== schema ===")
for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{URL}')").fetchall():
    print(f"  {row[0]}: {row[1]}")

print("\n=== two sample rows (passages truncated) ===")
rows = con.execute(
    f"SELECT * FROM read_parquet('{URL}') LIMIT 2"
).fetchdf()
for _, r in rows.iterrows():
    rec = {}
    for col in rows.columns:
        val = r[col]
        rec[col] = val
    passages = rec.get("passages")
    print(json.dumps(
        {
            "query_id": int(rec.get("query_id", -1)),
            "source_lang": str(rec.get("source_lang")),
            "target_lang": str(rec.get("target_lang")),
            "query_type": str(rec.get("query_type")),
            "query": str(rec.get("query"))[:200],
            "Eng_Query": str(rec.get("Eng_Query"))[:200],
            "Answer": str(rec.get("Answer"))[:200],
            "Eng_Answer": str(rec.get("Eng_Answer"))[:200],
        },
        ensure_ascii=False,
        indent=2,
    ))
    if passages is not None:
        try:
            n_eng = len(passages["English_passages"])
            n_tr = len(passages["Translated_passages"])
            sel = list(passages["is_selected"])
            print(f"  passages: english={n_eng} translated={n_tr} is_selected={sel}")
            print(f"  first english passage: {str(passages['English_passages'][0])[:220]}")
            print(f"  first translated passage: {str(passages['Translated_passages'][0])[:220]}")
        except Exception as exc:  # structure may differ; show raw
            print(f"  passages raw (failed to unpack: {exc}): {str(passages)[:600]}")

print("\n=== split stats ===")
stats = con.execute(
    f"""
    SELECT
      count(*)                                   AS rows,
      count(DISTINCT query_id)                   AS unique_query_ids,
      count(DISTINCT query_type)                 AS query_types
    FROM read_parquet('{URL}')
    """
).fetchone()
print(f"  rows={stats[0]:,} unique_query_ids={stats[1]:,} query_types={stats[2]}")

print("\n=== query_type distribution ===")
for qt, n in con.execute(
    f"SELECT query_type, count(*) FROM read_parquet('{URL}') GROUP BY 1 ORDER BY 2 DESC"
).fetchall():
    print(f"  {qt}: {n:,}")
