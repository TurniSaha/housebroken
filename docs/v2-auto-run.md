# v2 design note — auto-run (watch / scheduled / gate modes)

**Status:** parked. Not in the launch build. This note sketches the design so it's
ready to pick up post-launch, and so the v1 architecture doesn't accidentally
block it.

## Why v1 is manual on purpose

v1 is a one-shot command: you run `housebroken`, it reads your transcripts, prints
the report card, exits. No daemon, no background process, no schedule. That's the
right launch shape — the "look what my agent actually did" moment is strongest as
a thing you *choose* to run and immediately get a receipt from. Automation is a
retention feature, not a first-impression feature, so it waits until people ask.

The whole point of writing this down now: **build v1 so none of these modes need a
rewrite later.** The core (`discover → transcript stream → classify → check →
score → report`) is already a pure pipeline over inputs. Every auto-run mode below
is just a different *trigger* and *output sink* wrapped around that same pipeline.
Keep it that way.

## The three auto-run modes (in build order)

### 1. Scheduled digest — "here's what your agent broke this week"

The lowest-effort, highest-delight mode. A recurring run (cron / launchd / systemd
timer, or GitHub Actions for repo-scoped configs) over the last N days, whose
output is a **diff against the previous run**, not the full card:

- new violations since last time (the only thing that needs your attention)
- rules that flipped PASSED → VIOLATED or vice versa
- rules that newly went ASLEEP (candidates to delete)
- score delta (`71% → 68%, three new commit-message violations`)

Delivered to a sink you pick: stdout (for `| mail`), a markdown file, or a
webhook/Slack message. Nobody wants a full 40-line report card every Monday; they
want the *delta*. That means v2 needs a tiny bit of state — the previous run's
grades — cached per config. The judge cache already establishes the "state lives
in `~/.cache/housebroken`" pattern; reuse it.

**Design seam this needs from v1:** the `--format json` output is already
snapshot-stable, so "diff this run's JSON against last run's JSON" is a pure
function. Build the digest as `housebroken digest` that reads two JSON snapshots.
No pipeline changes.

### 2. Commit gate — "check the session before this commit lands"

A `pre-commit` (or `pre-push`) git hook that runs housebroken over *just the current
session's* transcript and blocks the commit if a rule tagged **blocking** was
violated. This is the CI/enforcement face of the tool: not "grade my history" but
"stop me from breaking my own rule right now."

Critical scoping decisions (get these wrong and it's infuriating):

- **Only deterministic checks by default.** The judge is too slow and too
  conservative to sit in a commit path. Gate on forbidden-action / required-sequence
  / output-format only; judge stays opt-in and non-blocking.
- **Opt-in per rule, not all-or-nothing.** A rule becomes blocking only if the
  author marks it (e.g. a `[blocking]` tag in the rules file, or a config
  allowlist). Everything else is advisory. Most rules should never block.
- **Escapable.** `--no-verify` must work — the tool's own philosophy is that
  humans override; a gate you can't skip is a gate people rip out.
- **Fast.** Single-session, deterministic-only, must be sub-second or it dies.

**Design seam:** v1 already streams per-session and already has `--transcripts` to
point at one file. `housebroken gate --session <current>` is a thin wrapper.

### 3. Watch mode — live, while you work

`housebroken watch` tails the active transcript and prints a one-line nudge the
moment a violation happens ("⚠ just ran `git push --force` — violates 'no force
push to shared branches'"). The most technically fiddly (needs live tailing of the
JSONL as the assistant writes it, debouncing, and terminal real estate that
doesn't fight the assistant's own output) and the least clearly valuable, so it's
last. Ship digest and gate first; only build watch if users specifically ask to be
warned *during* a session rather than after.

## The retention logic (why this is the v2, not a v2)

v1's open question is the "run-two problem": does anyone run it a second time? The report *suggests* edits, but a one-shot tool has
no built-in reason to return. Auto-run is the answer: a scheduled digest gives a
standing reason to come back every week, and a commit gate makes it part of the
loop you can't skip. **If v1 lands but nobody re-runs it, this note stops being
"nice to have" and becomes the mandatory next build.**

## What stays parked even in v2

- Auto-editing your `CLAUDE.md` from verdicts (auto-PR). The tool *suggests*
  rewrites; a tool that silently rewrites your rules file is a different, scarier
  product. Keep the human in the loop.
- Hosted / dashboard / accounts. Auto-run stays local — cron on your machine, or
  Actions in your own repo. No service of ours in the path, ever. That's the
  privacy promise; automation must not break it.
