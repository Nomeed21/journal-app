# LiAInne — a gamified journal that turns reflection into a quest board

LiAInne is a personal journaling app wrapped in an RPG progression system:
journal entries, habits, skill trees, goals, and an AI coach all feed a
single XP economy, and a Quest Board auto-generates and chains tasks across
all of them. This doc is the "why," not the "what" — the code comments cover
implementation detail; this covers the decisions and the reasoning behind
them, for anyone evaluating the system design rather than clicking buttons.

Stack: FastAPI + Supabase (Postgres) on the backend, vanilla JS/HTML/CSS on
the frontend (no framework — deliberately, see below), Groq (Llama 3.3 70B)
for the AI coach and content generation, `sentence-transformers` for
semantic search over journal entries.

## Try it

Click **"Load Demo Data"** (or `POST /dev/seed-demo-data`) on a fresh
instance to populate ~3 weeks of realistic history — a mood-trend journal, a
12-day habit streak with an evolution pending, two skill nodes mid-progress,
a defeated boss battle, a few achievements, and a saved VP balance. That's
the fastest way to see the system doing something, rather than reading about
what it would do. `POST /dev/clear-demo-data` removes it again.

## The core design decision: one XP ledger

Early on, XP was computed by summing completed tasks per category on every
read — cheap to write, expensive and fragile to read, and it meant "how much
XP does this category have" had a different answer depending on which
endpoint you asked. `/skills` computed it one way, `/domains` another,
achievements a third.

The fix was an `xp_ledger` table: every XP-granting event (a completed task,
a mastered skill node, a defeated boss, an earned achievement, a habit
evolution) writes one row — `source_type + source_id → category, xp`. Reads
are just `SELECT SUM(xp) WHERE category = ...`. The upsert key is
`(source_type, source_id)`, which makes every write idempotent: completing
the same quest twice, or a retried request after a dropped connection,
can't double-award XP. This is the single design choice that made everything
downstream — levels, domain progress, the "why am I stuck" bottleneck
detector — trustworthy instead of "probably right."

Virtual Peso (the in-app currency for real-world rewards) follows the exact
same pattern in a separate `vp_ledger`, deliberately scarcer: 1 VP is only
minted on full quest completion, never on a task, a habit log, or a journal
entry. That scarcity is the point — it's meant to feel worth saving toward
an actual reward, not a number that goes up on every interaction.

## Habits don't log themselves

The original design had a `habits` table with manual "log today" button
presses. It got dropped. A habit's streak is now derived entirely from
`board_quests`: any completed quest sharing the habit's `skill_tree` or
`domain` counts as that habit being done for the day
(`_habit_quest_dates()` in `main.py`).

The reasoning: manual logging is a second, parallel source of truth that can
drift from what actually happened (you log the habit but didn't really do
the linked quest, or vice versa), and it's friction — one more button to
press for something the app can already infer. Deriving it from quest
completions means a single action (finishing a quest) correctly updates
streaks, skill mastery, and domain balance all at once, with no
reconciliation step. The tradeoff is that a habit with no quests in its
category can never show progress — which is intentional; it pushes every
habit toward being backed by something concrete on the board rather than
existing as an untracked promise.

## Skill mastery: 40% consistency + 60% completion

Each skill node's mastery percentage isn't just "tasks done." It's a blend:

- **40% habit consistency** — the success rate of quest-derived activity for
  habits linked to that node, with a slow decay (−2 points/day of
  inactivity, floored at 0) rather than an instant reset on a missed day.
  Life happens; one missed day shouldn't erase weeks of consistency.
- **60% quest completion** — the actual task-completion percentage of the
  board quest generated for that node.

The split favors doing-the-work over showing-up, but showing-up still counts
for something, which matches how skill acquisition actually feels — you can
grind tasks in a burst, but retention comes from consistency over time.

## Quest generation and chaining

The Quest Board (`/board/quests`) isn't manually curated — quests are
generated from four sources, each with its own generator function:

- **Skills** (`_gen_skill_chain`) — one quest per unlocked-but-incomplete
  skill node, with `parent_quest_id` pointing at the prerequisite node's
  quest if one exists. Completing a parent unlocks its children visually on
  the board (`children_unlocked` in the completion response), mirroring the
  skill tree's own prerequisite structure without duplicating that logic.
- **Goals** (`_gen_goal_quests`) — active goals and their unfinished
  milestones become quests, deduplicated by `source_id` so re-running
  generation never creates copies.
- **Habits** (`_gen_habit_recovery_quests`) — grouped by *category*, not by
  habit name. Since habit activity is derived from category-matched quest
  completions, three habits sharing a category are all resolved by
  completing *one* quest in it — generating three separate recovery cards in
  that situation would misrepresent the mechanic, so it's one card per
  at-risk category, listing which habits it covers.
- **Journal** (`_gen_journal_quests`) — an LLM call extracts 1–3 concrete
  quests from what you just wrote, fired async right after saving an entry.

All four write into the same `board_quests` table with a `source_type` /
`source_id` pair, which is also how deduplication and the later "what
generated this" display both work off one mechanism instead of four.

A lightweight **recommendation engine** (`_build_recommended_section`)
scores every open quest by due-date urgency, source priority (recovery and
boss quests outrank routine ones), difficulty, and section, and surfaces the
top 3 — so the board has an opinion about what to do next without hiding
everything else.

Generation is **throttled**, not run on every page load: `/board/quests`
only re-runs the generators if more than 5 minutes have passed
(`BOARD_GENERATION_THROTTLE_SECONDS`), because on a populated board most
calls find nothing new to create — full generation fans out into
O(skill nodes + habits + goals) database round-trips for a mostly-empty
result. The explicit "Generate Quests" button bypasses the throttle for
cases where you want it to run *now*.

## Resilience: `db_retry`

Supabase's connection pooler will silently close idle HTTP/2 keep-alive
connections server-side. The client doesn't always find out until it tries
to reuse one mid-request, which surfaces as an opaque `RemoteProtocolError`
and a 500 on whichever endpoint happened to chain several Supabase calls —
this was intermittently crashing `/ai-insight`, `/board/quests`, and
`/coaching/proactive` before it was diagnosed. httpcore's built-in retry
logic only covers failures *establishing* a new connection, not a pooled one
that died mid-reuse, so `db_retry()` wraps request-facing entrypoints with
an application-level retry that opens a fresh connection on failure. It's a
narrow, targeted fix rather than a blanket retry-everything approach,
applied specifically where multi-call chains made the failure window bigger.

## Monthly review caching

Monthly reviews are LLM-generated and cached per month
(`monthly_reviews`, keyed by `YYYY-MM`) rather than regenerated on every
visit to that month — reviewing March in June shouldn't re-run an LLM call
for data that hasn't changed. A `force=true` param and a visible "Regenerate"
button let you intentionally refresh it, e.g. after backfilling entries for
that month.
