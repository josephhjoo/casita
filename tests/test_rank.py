from casita.models import Listing
from casita.rank import rank, score
from casita.walk import BEACHES, PRESIDIO_GATES


def _sf_listing(source_id: str, *, laundry: str | None) -> Listing:
    return Listing(
        source="manual",
        source_id=source_id,
        url="",
        lat=37.78,
        lng=-122.45,
        dog_policy="large_ok",
        beds=3,
        baths=2,
        laundry=laundry,
        llm_rank=1,
        llm_severity="ok",
    )


def _marin_listing() -> Listing:
    return Listing(
        source="manual",
        source_id="marin-a",
        url="",
        lat=37.90,
        lng=-122.54,
        dog_policy="large_ok",
        beds=3,
        baths=2,
        llm_rank=1,
        llm_severity="ok",
    )


def test_rank_reorders_sf_listings_when_walk_map_supplied():
    # Tied on everything rank() checks except laundry — `far` starts ahead on
    # the baseline heuristic (in-unit laundry), `near` only wins once its
    # close Presidio time is scored.
    near = _sf_listing("sf-near", laundry=None)
    far = _sf_listing("sf-far", laundry="in-unit")
    walk_map = {
        (near.key, PRESIDIO_GATES[0].name): 5,
        (far.key, PRESIDIO_GATES[0].name): 100,
    }

    without_walk = rank([near, far], status_map={}, vote_scores={})
    assert [L.key for L in without_walk] == [far.key, near.key]

    with_walk = rank([near, far], walk_map=walk_map, status_map={}, vote_scores={})
    assert [L.key for L in with_walk] == [near.key, far.key]


def test_score_marin_listing_unchanged_with_walk_map():
    listing = _marin_listing()
    # Deliberately generous minutes — if the Marin guard were missing, this
    # would swing the score by a large margin.
    walk_map = {
        (listing.key, PRESIDIO_GATES[0].name): 1,
        (listing.key, BEACHES[0].name): 1,
    }

    assert score(listing, None) == score(listing, walk_map)
