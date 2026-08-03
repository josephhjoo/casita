import pytest

from casita import rankdiff
from casita.models import Listing


def _listing(source_id: str, *, llm_rank: int | None, llm_severity: str | None = "ok", dog_policy=None) -> Listing:
    return Listing(
        source="manual", source_id=source_id, url="",
        dog_policy=dog_policy, llm_rank=llm_rank, llm_severity=llm_severity,
    )


# --- 1. label classification -------------------------------------------------


def test_human_label_returns_positive_for_each_positive_status():
    for status in rankdiff.POSITIVE_STATUSES:
        assert rankdiff.human_label(status, net_vote=0) == "positive"


def test_human_label_returns_negative_for_each_negative_status():
    for status in rankdiff.NEGATIVE_STATUSES:
        assert rankdiff.human_label(status, net_vote=0) == "negative"


def test_human_label_excludes_declined_by_landlord():
    # Landlord's preference, not the user's — not a label on either ranker,
    # even with an upvote on record.
    assert rankdiff.human_label("declined_by_landlord", net_vote=1) is None


def test_human_label_returns_positive_for_net_upvote_without_status():
    assert rankdiff.human_label(None, net_vote=1) == "positive"


def test_human_label_returns_none_for_unlabeled_listing():
    assert rankdiff.human_label(None, net_vote=0) is None


# --- 2. sentinel exclusion ----------------------------------------------------


def test_comparison_universe_excludes_filtered_severity():
    listing = _listing("filtered", llm_rank=5, llm_severity="filtered")
    universe, filtered_count = rankdiff.comparison_universe([listing])
    assert universe == []
    assert filtered_count == 1


def test_comparison_universe_excludes_sentinel_rank():
    listing = _listing("sentinel", llm_rank=9999, llm_severity="ok")
    universe, filtered_count = rankdiff.comparison_universe([listing])
    assert universe == []
    assert filtered_count == 1


def test_comparison_universe_includes_concerns_severity():
    listing = _listing("concerns", llm_rank=5, llm_severity="concerns")
    universe, filtered_count = rankdiff.comparison_universe([listing])
    assert universe == [listing]
    assert filtered_count == 0


# --- 3. positional comparison --------------------------------------------------


def test_top_disagreements_ranks_by_absolute_positional_delta():
    # dog_policy alone gives four strictly descending heuristic scores
    # (large_ok=12 > dogs_ok=6 > None=0 > small_only=-30) with everything
    # else left neutral, so heuristic order is exactly p, q, r, s.
    p = _listing("p", dog_policy="large_ok", llm_rank=4)  # heuristic #1, llm #4 -> delta -3
    q = _listing("q", dog_policy="dogs_ok", llm_rank=1)   # heuristic #2, llm #1 -> delta +1
    r = _listing("r", dog_policy=None, llm_rank=2)        # heuristic #3, llm #2 -> delta +1
    s = _listing("s", dog_policy="small_only", llm_rank=3)  # heuristic #4, llm #3 -> delta +1

    top = rankdiff.top_disagreements([p, q, r, s], walk_map=None, top=1)

    assert len(top) == 1
    assert top[0].listing.key == p.key
    assert top[0].heuristic_pos == 1
    assert top[0].llm_pos == 4
    assert top[0].delta == -3


# --- 4. baseline round-trip -----------------------------------------------------


def test_serialize_then_deserialize_baseline_round_trips_ranks():
    a = _listing("a", llm_rank=1)
    b = _listing("b", llm_rank=2)

    text = rankdiff.serialize_baseline([a, b], timestamp="2026-01-01T00:00:00+00:00")
    ranks = rankdiff.deserialize_baseline(text)

    assert ranks == {a.key: 1, b.key: 2}


def test_compute_movement_reports_moved_gone_and_new_listings():
    # Old snapshot: a=1, b=2, c=3. c drops out of the current universe (gone);
    # d is newly ranked (not in the old snapshot); a and b swap positions.
    old_ranks = {"manual:a": 1, "manual:b": 2, "manual:c": 3}
    a = _listing("a", llm_rank=3)  # was #1, now #3
    b = _listing("b", llm_rank=1)  # was #2, now #1
    d = _listing("d", llm_rank=2)  # new

    report = rankdiff.compute_movement([a, b, d], old_ranks, top=10)

    assert report.common_count == 2
    assert report.only_old_count == 1  # c
    assert report.only_new_count == 1  # d
    assert {m.listing.key: m.delta for m in report.movements} == {a.key: -2, b.key: 1}
    assert report.movements[0].listing.key == a.key  # larger |delta| first


def test_deserialize_baseline_raises_baseline_error_for_corrupt_input():
    with pytest.raises(rankdiff.BaselineError):
        rankdiff.deserialize_baseline("not json")


@pytest.mark.parametrize("text", [
    '{"ranks": [1, 2]}',       # ranks is a list, not a dict -> AttributeError
    '{"ranks": {"a": null}}',  # rank value isn't an int -> TypeError
    '{"ranks": {"a": "x"}}',   # rank value isn't numeric -> ValueError
    '{"no_ranks_key": {}}',    # missing "ranks" key -> KeyError
])
def test_deserialize_baseline_raises_baseline_error_for_wrong_shaped_json(text):
    with pytest.raises(rankdiff.BaselineError):
        rankdiff.deserialize_baseline(text)


# --- llm_vote_contradictions ----------------------------------------------------


def test_llm_vote_contradictions_flags_upvoted_listing_in_bottom_half():
    upvoted = _listing("upvoted", llm_rank=4)  # worst LLM rank -> bottom half despite the upvote
    a = _listing("a", llm_rank=1)
    b = _listing("b", llm_rank=2)
    c = _listing("c", llm_rank=3)
    vote_scores = {upvoted.key: 1}

    contradictions = rankdiff.llm_vote_contradictions([upvoted, a, b, c], vote_scores, walk_map=None)

    assert len(contradictions) == 1
    assert contradictions[0].listing.key == upvoted.key
    assert contradictions[0].net_vote == 1
    assert contradictions[0].llm_half == "bottom"
