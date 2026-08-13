from vaani.answer_extractive import answer
from vaani.retriever import Hit


def make_hit(pid, eng, tr=None, score=0.9):
    return Hit(passage_id=pid, eng_text=eng, tr_text=tr, score=score)


def test_picks_sentence_with_query_overlap():
    hits = [
        make_hit(
            "p1",
            "Goa has many beaches. Rachel Carson wrote Silent Spring in 1962. "
            "The book covered pesticides.",
        )
    ]
    result = answer(hits, "who wrote silent spring")
    assert "Rachel Carson" in result.text
    assert result.passage_ids == ["p1"]
    assert result.kind == "extractive"
    assert result.language == "en"


def test_devanagari_query_answers_from_translated_text():
    hits = [
        make_hit(
            "p2",
            "A corporation is a legal entity. It pays taxes.",
            tr="निगम एक कानूनी इकाई है। यह कर देता है।",
        )
    ]
    result = answer(hits, "निगम क्या है")
    assert result.language == "hi"
    assert "निगम" in result.text


def test_higher_ranked_passage_breaks_ties():
    hits = [
        make_hit("top", "Nothing relevant here at all today.", score=0.9),
        make_hit("low", "Also nothing relevant here at all.", score=0.2),
    ]
    result = answer(hits, "zzz unmatched query")
    assert result.passage_ids == ["top"]
