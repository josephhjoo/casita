# What I changed and why

## What I chose and why

I looked for the part of Casita where the most interesting problems live with the least visibility: the two rankers. The deterministic `score()` and the Gemini ranker each hold an opinion about every listing, but there was no way to see where they disagree, how either aligns with recorded votes and funnel outcomes, or what actually moves when the ranking policy changes. The docs name this gap under "Ways This Could Go Further" on the Ranking page: make policy changes easier to evaluate, compare deterministic and LLM rank movement. This PR is an answer to that note.

## What's in it

`casita rank-diff`, a credentials-free, read-only report over data already persisted in the DB. It compares the pure `score()` ordering against the `llm_rank` ordering positionally (buckets, votes, and statuses are deliberately excluded from both orderings, since those encode human decisions rather than scoring policy). It reports the largest disagreements with the LLM's cached reasoning attached, checks both rankers against recorded human decisions, and via `--save-baseline` / `--baseline` shows exactly which listings moved between two points in time. Sentinel ranks (severity filtered, rank >= 9000) are verdicts, not rankings, so they're excluded and reported as a count. There are no LLM calls anywhere in the path. It works against the demo fixture with the same env-var redirection the test suite already uses.

## What building it surfaced

While tracing the ranking path I found that `score()`'s walk-time bonuses never ran in production; no `rank()` call site passed `walk_map`, and in `_render_site` the walk map was computed after ranking. The data existed and fed both the Gemini ranker and the detail pages; only the deterministic scorer was blind to it, so I fixed that with a regression test. I scoped the fix to non-Marin listings using the existing `walk.is_marin` mechanism, since walking time to SF anchors is the wrong travel mode for Marin; mirroring the LLM path's drive-time handling in `score()` is a natural follow-up but changes scoring semantics, so I left it out deliberately. A second smaller fix in passing: the neighborhood fallback bonus never matched slug-format neighborhood names, which is what scrapers store before geocoding resolves them.

## What the report shows on the fixture

Of 143 active listings, 108 have a comparable rank and 35 are LLM-filtered. The top disagreements split into two clean stories. The heuristic's top picks are Presidio listings the LLM buried for being around 1,000 sqft, "too small for two adults and two large dogs": square footage is a signal the heuristic doesn't score at all. The mirror image is a block of "small dogs only" listings the heuristic eliminates with its hard dog-policy gate, which the LLM ranks in its top 20 because it treats the policy as negotiable. One table, and you can see the two rankers' philosophies collide.

## An honest note on the agreement numbers

My first design compared the rankers head-to-head on agreement with human decisions. That's contaminated, as votes are fed to the LLM ranker as few-shot examples on every enrich, so its agreement is in-sample while the heuristic's is out-of-sample. The report annotates this and doesn't frame the counts as a contest. The directional numbers (heuristic 19/30, LLM 10/30 on 30 labeled listings) are also dominated by pass-behavior, as all 20 of the LLM's misses are passed-on listings it placed top-half, and passes often turn on things outside any ranker's inputs, like timing or an unresponsive landlord. The sharper standing check is "LLM contradicts a known vote," which is currently empty because the fixture's 16 votes are all upvotes and all sit in the LLM's top half; a fixture limitation, not a code gap.

## What I considered and didn't do

Splitting the CLI module (real debt, but mechanical), snapshot tests for the HTML renderer (a strong candidate, less connected to what makes this codebase interesting), and listing staleness handling (depends on market assumptions I couldn't verify). One coherent change felt better than three gestures.

## Verifying

uv sync && make check (35 tests, public validator, docs, package). Then the credentials-free report: CASITA_DB_PATH=fixtures/demo.sqlite CASITA_ROUTE_CACHE_DB=fixtures/demo.sqlite CASITA_ROUTES_OFFLINE=1 uv run `casita rank-diff` --local. Everything runs offline against the fixture.