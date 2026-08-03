"""Compare the deterministic scorer against the LLM ranker.

Two independent ranking opinions exist on a listing: rank.score() (dog
policy, neighborhoods, beds/baths, laundry, parking, walk bonuses) and the
LLM's llm_rank (Gemini, persisted per listing during `casita enrich`). This
module holds the pure comparison logic behind the `rank-diff` CLI command —
DB access and rich-table rendering live in __init__.py.

Deliberately does not call rank.rank() and does not fold votes or funnel
status into either ordering: rank() already blends scoring with human
decisions on purpose, which is right for the site but wrong for this report.
Isolating scoring policy from that funnel is what lets both rankers be
checked against recorded human decisions independently.
"""
from dataclasses import dataclass

from .models import Listing
from .rank import score

# llm_rank values at or above this are verdicts (e.g. the 9999 fallback for
# listings the ranker didn't return), not real rankings.
SENTINEL_LLM_RANK = 9000

POSITIVE_STATUSES = frozenset(
    {"contacted", "shortlist", "viewing_scheduled", "viewing_done", "applied"}
)
NEGATIVE_STATUSES = frozenset({"passed_on", "declined_by_us"})
EXCLUDED_STATUSES = frozenset({"declined_by_landlord"})


def is_llm_sentinel(listing: Listing) -> bool:
    """True for LLM-rejected/unranked verdicts — not real rankings."""
    return listing.llm_severity == "filtered" or (listing.llm_rank or 0) >= SENTINEL_LLM_RANK


def comparison_universe(listings: list[Listing]) -> tuple[list[Listing], int]:
    """Active listings with a real llm_rank. Returns (kept, filtered_count)."""
    kept: list[Listing] = []
    filtered = 0
    for L in listings:
        if L.llm_rank is None or is_llm_sentinel(L):
            filtered += 1
        else:
            kept.append(L)
    return kept, filtered


def heuristic_order(listings: list[Listing], walk_map: dict | None) -> list[Listing]:
    """Listings sorted by score() descending — position 1 is the heuristic's favorite."""
    return sorted(listings, key=lambda L: -score(L, walk_map))


def llm_order(listings: list[Listing]) -> list[Listing]:
    """Listings sorted by llm_rank ascending — position 1 is the LLM's favorite."""
    return sorted(listings, key=lambda L: L.llm_rank)


def positions(ordered: list[Listing]) -> dict[str, int]:
    """1-based position of each listing.key within an ordering."""
    return {L.key: i + 1 for i, L in enumerate(ordered)}


def half(position: int, total: int) -> str:
    """"top" or "bottom" half of a 1-based position among `total` items."""
    return "top" if position <= (total + 1) // 2 else "bottom"


@dataclass(frozen=True)
class Disagreement:
    listing: Listing
    heuristic_pos: int
    llm_pos: int

    @property
    def delta(self) -> int:
        return self.heuristic_pos - self.llm_pos


def top_disagreements(listings: list[Listing], walk_map: dict | None, top: int) -> list[Disagreement]:
    """The `top` listings with the largest |heuristic position - LLM position|."""
    h_pos = positions(heuristic_order(listings, walk_map))
    l_pos = positions(llm_order(listings))
    rows = [Disagreement(L, h_pos[L.key], l_pos[L.key]) for L in listings]
    rows.sort(key=lambda d: -abs(d.delta))
    return rows[:top]


def human_label(status: str | None, net_vote: int) -> str | None:
    """'positive' / 'negative' / None (unlabeled, or landlord-declined and excluded).

    positive = net-upvoted OR an active-pipeline status; negative = passed on
    or declined by us; declined_by_landlord is excluded outright — that's the
    landlord's preference, not the user's, so it isn't a label on either
    ranker.
    """
    if status in EXCLUDED_STATUSES:
        return None
    if net_vote > 0 or status in POSITIVE_STATUSES:
        return "positive"
    if status in NEGATIVE_STATUSES:
        return "negative"
    return None


def _agrees(label: str, placement: str) -> bool:
    return (label == "positive" and placement == "top") or (label == "negative" and placement == "bottom")


@dataclass(frozen=True)
class LabeledRow:
    listing: Listing
    label: str  # "positive" | "negative"
    net_vote: int
    heuristic_half: str  # "top" | "bottom"
    llm_half: str
    heuristic_agrees: bool
    llm_agrees: bool


def labeled_rows(
    listings: list[Listing],
    status_map: dict[str, str],
    vote_scores: dict[str, int],
    walk_map: dict | None,
) -> list[LabeledRow]:
    """Listings with a recorded human decision, placed against both orderings."""
    total = len(listings)
    h_pos = positions(heuristic_order(listings, walk_map))
    l_pos = positions(llm_order(listings))
    rows: list[LabeledRow] = []
    for L in listings:
        net = vote_scores.get(L.key, 0)
        label = human_label(status_map.get(L.key), net)
        if label is None:
            continue
        h_half = half(h_pos[L.key], total)
        l_half = half(l_pos[L.key], total)
        rows.append(LabeledRow(
            listing=L, label=label, net_vote=net,
            heuristic_half=h_half, llm_half=l_half,
            heuristic_agrees=_agrees(label, h_half),
            llm_agrees=_agrees(label, l_half),
        ))
    return rows


@dataclass(frozen=True)
class AgreementSummary:
    total_labeled: int
    positive_count: int
    negative_count: int
    heuristic_agree_count: int
    llm_agree_count: int


def summarize_agreement(rows: list[LabeledRow]) -> AgreementSummary:
    return AgreementSummary(
        total_labeled=len(rows),
        positive_count=sum(1 for r in rows if r.label == "positive"),
        negative_count=sum(1 for r in rows if r.label == "negative"),
        heuristic_agree_count=sum(1 for r in rows if r.heuristic_agrees),
        llm_agree_count=sum(1 for r in rows if r.llm_agrees),
    )


def voted_listing_count(listings: list[Listing], vote_scores: dict[str, int]) -> int:
    """Listings in the comparison universe with a nonzero net vote (up or down)."""
    return sum(1 for L in listings if vote_scores.get(L.key, 0) != 0)


@dataclass(frozen=True)
class VoteContradiction:
    listing: Listing
    net_vote: int
    llm_half: str


def llm_vote_contradictions(
    listings: list[Listing], vote_scores: dict[str, int], walk_map: dict | None,
) -> list[VoteContradiction]:
    """Listings where the LLM's own placement runs against a recorded vote.

    Distinct from label agreement above: votes are fed to the LLM ranker as
    few-shot examples on every enrich (see docs/how-it-works/learning.md), so
    a listing the LLM buries despite an upvote — or promotes despite a
    downvote — is the strongest signal in this report: the ranker saw that
    exact vote and ranked against it anyway.
    """
    total = len(listings)
    l_pos = positions(llm_order(listings))
    out: list[VoteContradiction] = []
    for L in listings:
        net = vote_scores.get(L.key, 0)
        if net == 0:
            continue
        l_half = half(l_pos[L.key], total)
        if (net > 0 and l_half == "bottom") or (net < 0 and l_half == "top"):
            out.append(VoteContradiction(L, net, l_half))
    return out
