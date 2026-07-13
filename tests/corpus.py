"""Labeled classification corpus (H3 metric).

~50 synthetic, real-world-SHAPED rule sentences inspired by common public
CLAUDE.md idioms — NONE are taken from any private/local rules file. Each is
paired with its expected checkability class. The corpus is the measuring stick
for H3: the share of rules landing in a checkable (deterministic) class.

Classes: forbidden-action | required-sequence | output-format |
         behavioral-prose | unenforceable
"""

from housebroken.rules.classify import (
    BEHAVIORAL_PROSE,
    FORBIDDEN_ACTION,
    OUTPUT_FORMAT,
    REQUIRED_SEQUENCE,
    UNENFORCEABLE,
)

# (rule_text, expected_class)
CORPUS: tuple[tuple[str, str], ...] = (
    # ---- forbidden-action ----
    ("Never use the --force flag when pushing to a shared branch.", FORBIDDEN_ACTION),
    ("Do not commit directly to the main branch.", FORBIDDEN_ACTION),
    ("Never hardcode secrets in source code.", FORBIDDEN_ACTION),
    ("No emojis in commit messages or code comments.", FORBIDDEN_ACTION),
    ("Don't use `console.log` in production code.", FORBIDDEN_ACTION),
    ("Never disable TLS certificate verification.", FORBIDDEN_ACTION),
    ("Do NOT run `rm -rf` on paths built from user input.", FORBIDDEN_ACTION),
    ("Avoid `any` types in TypeScript application code.", FORBIDDEN_ACTION),
    ("Never store passwords in plaintext.", FORBIDDEN_ACTION),
    ("Do not use global mutable state.", FORBIDDEN_ACTION),
    ("Never leave debugging print statements in merged code.", FORBIDDEN_ACTION),
    ("No TODO comments without an associated issue number.", FORBIDDEN_ACTION),
    ("Don't catch exceptions without logging them.", FORBIDDEN_ACTION),

    # ---- required-sequence ----
    ("Run the test suite before committing.", REQUIRED_SEQUENCE),
    ("Always run the linter before you push.", REQUIRED_SEQUENCE),
    ("Type-check the project before committing changes.", REQUIRED_SEQUENCE),
    ("Build the project before running the tests.", REQUIRED_SEQUENCE),
    ("Run tests first, then commit.", REQUIRED_SEQUENCE),
    ("Verify the build passes before pushing to remote.", REQUIRED_SEQUENCE),
    ("Review the diff before committing.", REQUIRED_SEQUENCE),

    # ---- output-format ----
    ("Use conventional commit messages.", OUTPUT_FORMAT),
    ("Commit messages must follow the conventional commits format.", OUTPUT_FORMAT),
    ("Answer in bullet points.", OUTPUT_FORMAT),
    ("Wrap all code in fenced code blocks.", OUTPUT_FORMAT),
    ("Prefix every commit with a Jira ticket id.", OUTPUT_FORMAT),
    ("Use title case for all headings.", OUTPUT_FORMAT),
    ("Format responses as markdown.", OUTPUT_FORMAT),
    ("Return results as valid JSON.", OUTPUT_FORMAT),

    # ---- behavioral-prose ----
    ("Prefer simplicity over cleverness.", BEHAVIORAL_PROSE),
    ("Act like a senior engineer.", BEHAVIORAL_PROSE),
    ("Write clean, readable code.", BEHAVIORAL_PROSE),
    ("Prefer small, focused functions.", BEHAVIORAL_PROSE),
    ("Keep changes minimal and surgical.", BEHAVIORAL_PROSE),
    ("Handle errors explicitly and comprehensively.", BEHAVIORAL_PROSE),
    ("Find the root cause rather than patching symptoms.", BEHAVIORAL_PROSE),
    ("Write idiomatic, maintainable code.", BEHAVIORAL_PROSE),
    ("Be concise in explanations.", BEHAVIORAL_PROSE),
    ("Prefer composition over inheritance.", BEHAVIORAL_PROSE),
    ("Use descriptive, self-documenting variable names.", BEHAVIORAL_PROSE),

    # ---- unenforceable ----
    ("Think deeply.", UNENFORCEABLE),
    ("Be helpful.", UNENFORCEABLE),
    ("Care about quality.", UNENFORCEABLE),
    ("Have good taste.", UNENFORCEABLE),
    ("Stay curious.", UNENFORCEABLE),
    ("Take ownership.", UNENFORCEABLE),
    ("Move fast.", UNENFORCEABLE),
    ("Be a team player.", UNENFORCEABLE),
)
