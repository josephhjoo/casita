---
icon: lucide/list-ordered
---

# Ranking

Ranking has two layers.

`src/casita/rank.py` is the deterministic sorter. It handles explicit pipeline
state, votes, filtered listings, and heuristic score. Human engagement beats a
fresh LLM rank because an active conversation is real work.

`src/casita/llm.py` is the preference ranker. `rank_listings` builds a compact
brief for each listing, adds route summaries, attaches current feedback, and
asks Gemini to return every listing with:

- a rank
- a one-sentence reason
- a severity: `ok`, `concerns`, or `filtered`

The ranking policy keeps the personal assumptions: large dogs, SF walkability,
Marin drive context, trail or beach access, and practical livability.

## Ways This Could Go Further

Ranking is deliberately still prompt-centric and Vertex-only. `casita
rank-diff` now covers comparing deterministic and LLM rank movement. It
orders the active listings by `score()` and by `llm_rank` independently,
reports the largest positional disagreements alongside the LLM's own
reasoning, and checks both orderings against recorded votes and funnel
status. LLM agreement there is in-sample — votes are fed to the ranker as
few-shot examples on every enrich — while the heuristic's is out-of-sample,
so the two counts aren't head-to-head comparable; the report treats both as
directional, not statistical. `--save-baseline` / `--baseline` snapshot the
`llm_rank` ordering so a prompt edit's actual effect on rank movement is
visible instead of assumed. Credentials-free against the demo fixture:

```bash
CASITA_DB_PATH=fixtures/demo.sqlite CASITA_ROUTE_CACHE_DB=fixtures/demo.sqlite CASITA_ROUTES_OFFLINE=1 uv run casita rank-diff --local
```

What's still open: making policy changes easier to evaluate before they ship,
and supporting another model backend.
