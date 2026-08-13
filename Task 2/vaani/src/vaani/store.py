"""Passage store: row-offset addressable passage lookup.

Row offsets everywhere in vaani mean: position in the corpus passage
table sorted by passage_id. Index builders embed in that order and this
store loads in that order, so offsets line up by construction.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


class PassageStore:
    def __init__(self, passage_ids: list[str], eng: list[str], tr: list[str | None]):
        self.passage_ids = passage_ids
        self.eng = eng
        self.tr = tr

    @classmethod
    def load(cls, corpus_dir: Path | str) -> "PassageStore":
        path = (Path(corpus_dir) / "passages.parquet").as_posix()
        con = duckdb.connect()
        rows = con.execute(
            f"SELECT passage_id, eng_text, tr_text FROM '{path}' ORDER BY passage_id"
        ).fetchall()
        ids = [r[0] for r in rows]
        eng = [r[1] for r in rows]
        tr = [r[2] for r in rows]
        return cls(ids, eng, tr)

    def __len__(self) -> int:
        return len(self.passage_ids)

    def lookup(self, rows: list[int]) -> list[dict]:
        return [
            {
                "passage_id": self.passage_ids[r],
                "eng_text": self.eng[r],
                "tr_text": self.tr[r],
            }
            for r in rows
        ]
