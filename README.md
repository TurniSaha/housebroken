# housebroken

**Grade your AI coding agent against your own `CLAUDE.md` — with receipts.**

`housebroken` replays your real Claude Code transcripts against your rules files
and tells you, rule by rule, which ones your agent violated (quoting the exact
transcript evidence), which fired and passed, and which have been asleep for
weeks — burning context tokens for nothing.

![housebroken report card](docs/demo.gif)

## Install

```bash
uvx housebroken          # zero-install, run it now
pipx install housebroken # keep it
```

Then just:

```bash
housebroken              # grade your real ~/.claude history
housebroken demo         # 30-second showcase, no history or setup needed
```

`housebroken demo` runs against a bundled synthetic transcript, so you get the
full report card even on a fresh machine with no Claude Code history.

### From source (before the PyPI release)

Until `housebroken` is published to PyPI, run it straight from a clone with
[uv](https://docs.astral.sh/uv/):

```bash
git clone <this-repo> && cd housebroken
uv run --with-editable . housebroken demo    # the showcase
uv run --with-editable . housebroken         # grade your real ~/.claude
```

Discovery is automatic (rules under `~/.claude/CLAUDE.md` and
`~/.claude/rules/`, transcripts under `~/.claude/projects/`). Point it elsewhere
with `--claude-dir DIR`, or override with `--rules PATH` / `--transcripts PATH`.

## The flip

`CLAUDE.md` is unfalsifiable prose. You edit it on a hunch and hope the agent
reads it. `housebroken` flips that: every rule becomes an assertion, checked
against what the agent actually did, and each rule gets a performance review.
You've been training a dog by leaving it notes — this tells you which notes it
ignored.

## What a run looks like

```
  HOUSEBROKEN REPORT ── score 40%

  ✗ VIOLATED       "Run the test suite before committing."           3×  [required-sequence]
      └ 2026-07-08T23:12:00Z session.jsonl:7
        commit with no prior test run in session: git commit -m 'stuff'
  ✗ VIOLATED       "Never use the --force flag when pushing ..."      1×  [forbidden-action]
      └ git push --force origin main
  ! SUSPECTED      "Write clean, readable code."             unverified  [judge 2/2]
      └ judge: claims cleanliness but shows no verifiable evidence
  ~ ASLEEP         "Never use --no-cache against staging."   ~14 tokens wasted
  ✓ PASSED         "Never use --hard with git reset."       (applicable 1×)
  ✓ PASSED-JUDGED  "Prefer small, surgical changes ..."     (judged 2/2 spans)
  ? UNENFORCEABLE  "Always be excellent."                   (prose — rewrite or delete)

  Verdicts: KEEP 6 · REWRITE 1 · DELETE 1
```

The beat that sells it is the receipt: your own rule, quoted back, next to
timestamped proof the agent ignored it.

## How it works

Each rule is sorted into a checkability class, shown next to its grade so you
always know whether a verdict is mechanical or judged:

- **forbidden-action** ("never use `--force`", "no emojis") — deterministic
  checks over tool calls and assistant text.
- **required-sequence** ("run tests before committing") — ordering checks over
  the events within a session.
- **output-format** ("use conventional commits") — pattern checks on the
  produced artifact (e.g. commit messages).
- **behavioral-prose** ("prefer small, surgical changes") — judged by your own
  `claude` CLI, and only when the judge can quote concrete evidence.
- **unenforceable** ("always be excellent") — surfaced as its own finding, with
  a suggestion to rewrite or delete.

**Receipts, or it didn't happen.** A `VIOLATED` verdict always quotes the exact
transcript span — session file, line, timestamp, and the offending command or
text. No receipt, no accusation.

**Applicability is tracked.** A git rule in a session with no git activity
didn't "pass" — it was irrelevant. `PASSED` means applicable and clean; `ASLEEP`
means it never came up in the window (with an estimate of the context tokens
it cost you anyway).

**The judge is conservative by design.** Behavioral-prose rules are judged
against windows of concrete activity, and the judge returns "no verdict" unless
it can cite evidence in the span. If it sampled spans and none cleared that bar,
the report says so plainly — housebroken never accuses without a receipt. That is
the point, not a limitation.

## Privacy

Local-first. No accounts, no telemetry, nothing leaves your machine. The only
network-shaped step is the optional Tier-2 judge, which rides *your* existing
`claude` CLI — your transcripts already live in that trust boundary, so
housebroken adds no new data flow. Every span is scrubbed for secrets (API keys,
tokens, bearer headers, emails) before it reaches a report or a judge prompt.
Pass `--no-judge` to skip Tier-2 entirely. Bundled demo fixtures are 100%
synthetic.

## What's next (v2)

A replayable scenario-fixture suite: rule edits go red/green like code, you can
bisect which rule change altered behavior, and a silent model upgrade that
changes your agent's behavior trips an alarm. The linter becomes a regression
suite for the newest config file in your repo.

## Authorship

Built by one person (Turni Saha, author and maintainer) together with a
frontier model (Claude) pushed hard. The commit history is what it looks like
when you treat a language model as a real collaborator on a real tool.

## Contributing

Issues and PRs welcome — the rule-compiler heuristics and the check classes are
where most of the interesting work is. See [LICENSE](LICENSE) (MIT).
