"""Generate the synthetic demo transcript. Run to regenerate synthetic_session.jsonl.

100% synthetic content — no real paths, secrets, names, or personal data.
Mirrors the observed real Claude Code JSONL shape (see docs/format-notes.md).
"""

import json
from pathlib import Path

SID = "0000fixture-0000-0000-0000-000000000001"
OUT = Path(__file__).with_name("synthetic_session.jsonl")


def user(text, ts, uuid, parent):
    return {
        "type": "user",
        "sessionId": SID,
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "timestamp": ts,
        "cwd": "/home/example/proj",
        "message": {"role": "user", "content": text},
    }


def assistant_text(text, ts, uuid, parent):
    return {
        "type": "assistant",
        "sessionId": SID,
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def assistant_tool(name, tool_input, ts, uuid, parent):
    return {
        "type": "assistant",
        "sessionId": SID,
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu_" + uuid[:8], "name": name, "input": tool_input}
            ],
        },
    }


def tool_result(text, ts, uuid, parent, tuid):
    return {
        "type": "user",
        "sessionId": SID,
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tuid, "content": text, "is_error": False}],
        },
    }


records = [
    # Non-message noise records (must be skip-counted, never fatal).
    {"type": "last-prompt", "content": "…"},
    {"type": "mode", "mode": "default"},
    {"type": "permission-mode", "permissionMode": "acceptEdits"},
    {"type": "ai-title", "title": "example session"},
    {"type": "file-history-snapshot", "messageId": "x", "snapshot": {}},

    user("Please commit the work.", "2026-07-08T14:30:00.000Z", "u1", None),
    # VIOLATION: forbidden --no-verify literally present in a Bash command.
    assistant_tool(
        "Bash",
        {"command": "git commit -m 'wip' --no-verify", "description": "commit"},
        "2026-07-08T14:32:11.000Z",
        "a1",
        "u1",
    ),
    tool_result("[main abc123] wip", "2026-07-08T14:32:12.000Z", "u2", "a1", "tu_a1"),

    # BENIGN: a normal commit, must NOT be flagged.
    user("Now commit properly.", "2026-07-08T14:40:00.000Z", "u3", "u2"),
    assistant_tool(
        "Bash",
        {"command": "git commit -m 'feat: add parser'", "description": "commit"},
        "2026-07-08T14:41:00.000Z",
        "a2",
        "u3",
    ),

    # VIOLATION: emoji in assistant output ("No emojis in assistant output").
    assistant_text("All done \U0001F680 shipping it now.", "2026-07-08T14:42:00.000Z", "a3", "a2"),

    # A substantive assistant span + an Edit anchor right after, so the Tier-2
    # judge has an evaluable WINDOW for behavioral-prose rules (concrete conduct,
    # not plan/status noise).
    assistant_text(
        "I decided to reuse the existing parser instead of rewriting it, because "
        "the change was small and rewriting would have added risk for no benefit. "
        "I kept the diff minimal and touched only the one function that needed it.",
        "2026-07-08T14:43:00.000Z",
        "a4",
        "a3",
    ),
    assistant_tool(
        "Edit",
        {"file_path": "src/parser.py", "old_string": "x", "new_string": "y"},
        "2026-07-08T14:43:30.000Z",
        "a5",
        "a4",
    ),

    # A malformed / truncated line is injected manually below (not JSON here).
]


def main():
    lines = [json.dumps(r) for r in records]
    # Inject a deliberately malformed line to exercise skip-and-count.
    lines.insert(6, '{"type": "assistant", "message": {"role": "assist')  # truncated
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
