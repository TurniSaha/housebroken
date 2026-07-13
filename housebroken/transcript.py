"""JSONL transcript adapter: stream a Claude Code session into a tiny event vocabulary.

Observed real-shape schema (sampled from ~/.claude/projects/*/*.jsonl, see
docs/format-notes.md). Each line is one JSON object with a top-level ``type``.
The message-bearing records are the *minority*; most lines are metadata we skip.

  message records: type == "user" | "assistant"
    - top-level: sessionId, uuid, parentUuid, isSidechain, timestamp, cwd, ...
    - ``message`` object: {"role", "content"}
    - ``content`` is either a str (user prose) or a list of blocks:
        {"type": "text", "text": ...}
        {"type": "tool_use", "name", "input", "id"}      (assistant only)
        {"type": "tool_result", "tool_use_id", "content", "is_error"}  (user only)
        {"type": "image", "source": ...}                 (ignored)

  everything else (type in {last-prompt, mode, permission-mode, attachment,
  ai-title, queue-operation, file-history-snapshot, system, ...}) is counted
  and skipped, never fatal.

ROBUSTNESS CONTRACT: unknown record types, malformed JSON, and truncated lines
are counted and skipped. Parsing a corpus never raises on bad input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# Record types we recognize as carrying conversational content.
_MESSAGE_TYPES = frozenset({"user", "assistant"})


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A single tool invocation by the assistant."""

    name: str
    input: dict  # tool arguments as-provided (e.g. {"command": "..."} for Bash)
    timestamp: str | None
    session_id: str | None
    file: str  # absolute path of the source transcript
    line_no: int  # 1-based line number within the transcript

    def command(self) -> str:
        """Best-effort extraction of a shell command string, or '' if none."""
        val = self.input.get("command") if isinstance(self.input, dict) else None
        return val if isinstance(val, str) else ""


@dataclass(frozen=True, slots=True)
class AssistantMsg:
    """Assistant free-text (concatenated text blocks of one assistant record)."""

    text: str
    timestamp: str | None
    session_id: str | None
    file: str
    line_no: int


@dataclass(frozen=True, slots=True)
class UserMsg:
    """User free-text prompt (tool_result blocks are not surfaced as UserMsg)."""

    text: str
    timestamp: str | None
    session_id: str | None
    file: str
    line_no: int


Event = ToolCall | AssistantMsg | UserMsg


@dataclass(frozen=True, slots=True)
class ParseStats:
    """Skip/parse accounting for one transcript (or aggregate)."""

    events: int = 0
    tool_calls: int = 0
    assistant_msgs: int = 0
    user_msgs: int = 0
    skipped_types: dict = field(default_factory=dict)  # type -> count
    malformed_lines: int = 0
    total_lines: int = 0

    def merged(self, other: "ParseStats") -> "ParseStats":
        skipped = dict(self.skipped_types)
        for k, v in other.skipped_types.items():
            skipped[k] = skipped.get(k, 0) + v
        return ParseStats(
            events=self.events + other.events,
            tool_calls=self.tool_calls + other.tool_calls,
            assistant_msgs=self.assistant_msgs + other.assistant_msgs,
            user_msgs=self.user_msgs + other.user_msgs,
            skipped_types=skipped,
            malformed_lines=self.malformed_lines + other.malformed_lines,
            total_lines=self.total_lines + other.total_lines,
        )


class _Counter:
    """Mutable accumulator; converted to a frozen ParseStats at the end."""

    def __init__(self) -> None:
        self.events = 0
        self.tool_calls = 0
        self.assistant_msgs = 0
        self.user_msgs = 0
        self.skipped_types: dict[str, int] = {}
        self.malformed_lines = 0
        self.total_lines = 0

    def skip(self, rtype: str) -> None:
        self.skipped_types[rtype] = self.skipped_types.get(rtype, 0) + 1

    def freeze(self) -> ParseStats:
        return ParseStats(
            events=self.events,
            tool_calls=self.tool_calls,
            assistant_msgs=self.assistant_msgs,
            user_msgs=self.user_msgs,
            skipped_types=dict(self.skipped_types),
            malformed_lines=self.malformed_lines,
            total_lines=self.total_lines,
        )


def _iter_content_blocks(message: object) -> tuple[str, list]:
    """Return (role, content-blocks). Normalizes str content to a text block."""
    if not isinstance(message, dict):
        return "", []
    role = message.get("role") or ""
    content = message.get("content")
    if isinstance(content, str):
        return role, [{"type": "text", "text": content}]
    if isinstance(content, list):
        return role, content
    return role, []


def _text_of(blocks: list) -> str:
    parts = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            t = b.get("text")
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts).strip()


def stream_events(path: str | Path, counter: _Counter | None = None) -> Iterator[Event]:
    """Yield normalized events from one JSONL transcript.

    Streams line by line; never loads the whole file. Malformed/truncated lines
    and unknown record types are counted (on ``counter`` if given) and skipped.
    """
    p = Path(path)
    own = counter is None
    c = counter if counter is not None else _Counter()
    fpath = str(p)

    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            c.total_lines += 1
            try:
                rec = json.loads(line)
            except (ValueError, RecursionError):
                c.malformed_lines += 1
                continue
            if not isinstance(rec, dict):
                c.skip("<<non-object>>")
                continue

            rtype = rec.get("type")
            if rtype not in _MESSAGE_TYPES:
                c.skip(rtype if isinstance(rtype, str) else "<<notype>>")
                continue

            ts = rec.get("timestamp") if isinstance(rec.get("timestamp"), str) else None
            sid = rec.get("sessionId") if isinstance(rec.get("sessionId"), str) else None
            role, blocks = _iter_content_blocks(rec.get("message"))

            if rtype == "assistant":
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        name = b.get("name")
                        inp = b.get("input")
                        c.events += 1
                        c.tool_calls += 1
                        yield ToolCall(
                            name=name if isinstance(name, str) else "<unknown>",
                            input=inp if isinstance(inp, dict) else {},
                            timestamp=ts,
                            session_id=sid,
                            file=fpath,
                            line_no=line_no,
                        )
                text = _text_of(blocks)
                if text:
                    c.events += 1
                    c.assistant_msgs += 1
                    yield AssistantMsg(text=text, timestamp=ts, session_id=sid,
                                       file=fpath, line_no=line_no)
            elif rtype == "user":
                # tool_result blocks are agent-observed output, not user intent;
                # surface only genuine user prose as UserMsg.
                text = _text_of(blocks)
                if text:
                    c.events += 1
                    c.user_msgs += 1
                    yield UserMsg(text=text, timestamp=ts, session_id=sid,
                                  file=fpath, line_no=line_no)

    if own:
        # Caller passed no counter and cannot read it back; nothing to do.
        pass
