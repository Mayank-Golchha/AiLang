"""
Indentation preprocessor for AILang.

Strips comments, normalises blank lines, and injects synthetic INDENT / DEDENT
tokens that lark can consume as regular terminals.

The output is a *modified source string* where special marker lines
``__INDENT__`` and ``__DEDENT__`` have been inserted.  The lark grammar
declares matching terminals so the parser sees them as block delimiters.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from ailang.errors import ErrorCode, ErrorCollector

# Marker strings that the lark grammar will match as terminals.
INDENT_MARKER = "__INDENT__"
DEDENT_MARKER = "__DEDENT__"

# Regex to detect a line that is purely blank / whitespace or a comment.
_BLANK_OR_COMMENT = re.compile(r"^\s*(#.*)?$")

# Characters we accept as indentation (spaces only — tabs are normalised).
_LEADING_WS = re.compile(r"^([ \t]*)")


def _strip_line_comments(line: str) -> str:
    """Remove trailing ``# …`` comment, preserving strings."""
    in_string = False
    string_char = None
    escape = False
    i = 0
    while i < len(line):
        ch = line[i]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if in_string:
            if ch == string_char:
                in_string = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            i += 1
            continue
        if ch == "#":
            return line[:i].rstrip()
        i += 1
    return line


def _measure_indent(line: str) -> int:
    """Return the number of leading spaces (tabs expanded to 4 spaces)."""
    count = 0
    for ch in line:
        if ch == " ":
            count += 1
        elif ch == "\t":
            count += 4
        else:
            break
    return count


def inject_indent_tokens(
    source: str,
    errors: ErrorCollector,
) -> str:
    """
    Pre-process *source* into a version with ``__INDENT__`` / ``__DEDENT__``
    marker lines injected so that lark can parse indentation-delimited blocks.

    Blank and comment-only lines are preserved as empty lines (they must not
    change the indent stack).

    Raises ``E003`` through *errors* when dedenting to a level that was never
    on the indent stack.
    """
    raw_lines = source.splitlines()
    indent_stack: List[int] = [0]
    output_lines: List[str] = []

    for lineno_0, raw in enumerate(raw_lines):
        lineno = lineno_0 + 1  # 1-indexed

        # Preserve blank / comment-only lines without touching indent.
        if _BLANK_OR_COMMENT.match(raw):
            output_lines.append("")
            continue

        cleaned = _strip_line_comments(raw)
        level = _measure_indent(cleaned)
        content = cleaned.lstrip()

        if level > indent_stack[-1]:
            # Deeper indentation → push & emit INDENT marker.
            indent_stack.append(level)
            output_lines.append(INDENT_MARKER)
        elif level < indent_stack[-1]:
            # Dedent — may pop multiple levels.
            while indent_stack and indent_stack[-1] > level:
                indent_stack.pop()
                output_lines.append(DEDENT_MARKER)
            if indent_stack[-1] != level:
                errors.add(
                    ErrorCode.E003,
                    lineno,
                    1,
                    f"indentation level {level} does not match any outer block",
                    span=level or 1,
                    hint="check that indentation is consistent (use spaces, not tabs)",
                )
                # Recovery: push the weird level so we can keep going.
                indent_stack.append(level)

        output_lines.append(content)

    # Close any remaining open indentation levels.
    while len(indent_stack) > 1:
        indent_stack.pop()
        output_lines.append(DEDENT_MARKER)

    return "\n".join(output_lines)
