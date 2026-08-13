"""Cut a reproducible local subset from a built corpus.

Samples queries stratified by query_type (keeping the natural share of
no-answer queries), pulls every passage their qrels reference, then
random-fills with unrelated passages up to the target corpus size.

Usage:
  uv run python scripts/make_subset.py --corpus data/corpus/hin_val \
      --out data/subset/hin_val_100k --queries 5000 --passages 100000
"""

import argparse
from pathlib import Path

import duckdb


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/corpus/hin_val")
    ap.add_argument("--out", default="data/subset/hin_val_100k")
    ap.add_argument("--queries", type=int, default=5000)
    ap.add_argument("--passages", type=int, default=100_000)
    args = ap.parse_args()

    src = Path(args.corpus)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SELECT setseed(0.42)")
    con.execute(f"CREATE VIEW q AS SELECT * FROM '{(src / 'queries.parquet').as_posix()}'")
    con.execute(f"CREATE VIEW p AS SELECT * FROM '{(src / 'passages.parquet').as_posix()}'")
    con.execute(f"CREATE VIEW r AS SELECT * FROM '{(src / 'qrels.parquet').as_posix()}'")

    # stratified query sample: proportional per query_type, random inside
    con.execute(
        f"""
        CREATE TEMP TABLE sq AS
        SELECT * FROM (
          SELECT *, row_number() OVER (PARTITION BY query_type ORDER BY random()) AS rn,
                 count(*) OVER (PARTITION BY query_type) AS n_type,
                 count(*) OVER () AS n_all
          FROM q
        )
        WHERE rn <= ceil({args.queries} * n_type / n_all)
        """
    )

    # all passages referenced by sampled queries' qrels
    con.execute(
        """
        CREATE TEMP TABLE gold_p AS
        SELECT DISTINCT p.* FROM p
        JOIN r ON p.passage_id = r.passage_id
        JOIN sq ON r.query_id = sq.query_id
        """
    )

    n_gold = con.execute("SELECT count(*) FROM gold_p").fetchone()[0]
    fill = max(0, args.passages - n_gold)
    con.execute(
        f"""
        CREATE TEMP TABLE sp AS
        SELECT * FROM gold_p
        UNION ALL
        SELECT * FROM (
          SELECT * FROM p
          WHERE passage_id NOT IN (SELECT passage_id FROM gold_p)
          ORDER BY random() LIMIT {fill}
        )
        """
    )

    con.execute(
        f"""
        COPY (SELECT * EXCLUDE (rn, n_type, n_all) FROM sq)
        TO '{(out / 'queries.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    con.execute(
        f"COPY sp TO '{(out / 'passages.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.execute(
        f"""
        COPY (
          SELECT r.* FROM r JOIN sq USING (query_id)
        ) TO '{(out / 'qrels.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )

    nq, np_, nr, cov = con.execute(
        f"""
        SELECT
          (SELECT count(*) FROM sq),
          (SELECT count(*) FROM sp),
          (SELECT count(*) FROM r JOIN sq USING (query_id)),
          (SELECT count(DISTINCT r.passage_id) FROM r JOIN sq USING (query_id)
           WHERE r.passage_id IN (SELECT passage_id FROM sp))
        """
    ).fetchone()
    print(f"subset -> {out}")
    print(f"  queries={nq:,} passages={np_:,} qrel_pairs={nr:,}")
    print(f"  qrel passages covered: {cov:,} (gold in subset: {n_gold:,})")
    noans = con.execute(
        "SELECT count(*) FROM sq WHERE query_id NOT IN (SELECT query_id FROM r)"
    ).fetchone()[0]
    print(f"  no-answer queries in sample: {noans:,}")


if __name__ == "__main__":
    main()
