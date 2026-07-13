# Observed Claude Code transcript JSONL format

Notes from sampling real session files under `~/.claude/projects/*/*.jsonl`
(65 project dirs, ~16.7k files at time of writing). These pin the parser in
`housebroken/transcript.py`. The schema shifts between Claude Code versions, so
the adapter treats message-bearing records as the *minority* case and
skip-counts everything it doesn't recognize.

## One object per line

Each line is a single JSON object with a top-level `type`. Blank lines occur.
Truncated / malformed lines occur in the wild and MUST NOT be fatal — the
adapter counts them (`ParseStats.malformed_lines`) and continues.

## Distribution of `type` values (observed)

Most records are **not** conversational content:

- `last-prompt`, `mode`, `permission-mode` — session/mode metadata
- `attachment` — hook/attachment payloads (often the largest count)
- `ai-title` — generated session titles
- `queue-operation` — prompt-queue bookkeeping
- `file-history-snapshot` — editor snapshots
- `system` — system notices

Conversational content is only:

- `type: "user"` — a user turn
- `type: "assistant"` — an assistant turn

Everything else is counted into `ParseStats.skipped_types` and skipped.

## Message record shape

Top-level keys on a message record include: `type`, `sessionId`, `uuid`,
`parentUuid`, `isSidechain`, `timestamp` (ISO-8601, e.g.
`2026-06-24T19:06:29.760Z`), `cwd`, `gitBranch`, `version`, `userType`. User
records additionally carry `permissionMode`, `promptId`, `promptSource`,
`origin`, `imagePasteIds`.

The turn payload is under `message`:

- `message.role`: `"user"` | `"assistant"`
- `message.content`: either a **string** (plain user prose) or a **list of
  content blocks**.

### Content blocks

- `{"type": "text", "text": "..."}` — free text (both roles).
- `{"type": "tool_use", "id", "name", "input": {...}, "caller"}` — assistant
  invoking a tool. For `Bash`, `input` is `{"command", "description"}`. This is
  the primary signal the forbidden-action checker consumes.
- `{"type": "tool_result", "tool_use_id", "content", "is_error"}` — appears on
  a **user** record; it is the tool's *output*, not user intent, so the adapter
  does not surface it as a `UserMsg`.
- `{"type": "image", "source": ...}` — ignored.

`content` may also be a bare string on assistant records in some versions; the
adapter normalizes a string to a single text block.

## Normalized event vocabulary

The adapter emits only three frozen event types, each carrying receipt
coordinates (`file`, `line_no`, `timestamp`, `session_id`):

- `ToolCall{name, input, ...}` — one per `tool_use` block.
- `AssistantMsg{text}` — concatenated text blocks of one assistant record.
- `UserMsg{text}` — genuine user prose (never `tool_result`).

Robustness contract: unknown record types, non-object JSON, missing fields,
malformed and truncated lines are all counted and skipped, never raised.
