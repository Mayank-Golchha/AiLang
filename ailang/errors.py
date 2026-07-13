"""Error types, codes, and formatting for the AILang transpiler."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List


class Severity(Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ErrorCode(Enum):
    """All error and warning codes for the transpiler."""

    # --- Lexer / Parser errors ---
    E001 = ("E001", Severity.ERROR, "Unknown token")
    E002 = ("E002", Severity.ERROR, "Unexpected token")
    E003 = ("E003", Severity.ERROR, "Mismatched indentation")

    # --- Semantic errors ---
    E004 = ("E004", Severity.ERROR, "Reserved keyword used as identifier")
    E005 = ("E005", Severity.ERROR, "Undeclared identifier")
    E006 = ("E006", Severity.ERROR, "Type mismatch")
    E007 = ("E007", Severity.ERROR, "Immutable variable assigned after declaration")
    E008 = ("E008", Severity.ERROR, "Multi-decl count mismatch")
    E010 = ("E010", Severity.ERROR, "Break/continue outside loop")
    E011 = ("E011", Severity.ERROR, "Return outside function")
    E012 = ("E012", Severity.ERROR, "self used outside class method")
    E013 = ("E013", Severity.ERROR, "Duplicate identifier in same scope")
    E014 = ("E014", Severity.ERROR, "Function called with wrong argument count")
    E015 = ("E015", Severity.ERROR, "Function called with wrong argument types")
    E016 = ("E016", Severity.ERROR, "? used on non-optional type")
    E017 = ("E017", Severity.ERROR, "await used outside async function")
    E018 = ("E018", Severity.ERROR, "sized_vector_literal has expression inside []")
    E019 = ("E019", Severity.ERROR, "Static array size must be integer literal")
    E020 = ("E020", Severity.ERROR, "EOF arm is not last in match block")
    E021 = ("E021", Severity.ERROR, "Unknown module in import")
    E022 = ("E022", Severity.ERROR, "Import conflict")
    E023 = ("E023", Severity.ERROR, "Top-level executable statements coexist with explicit main()")

    # --- Warnings ---
    W001 = ("W001", Severity.WARNING, "Missing EOF arm in match")
    W002 = ("W002", Severity.WARNING, "Unused variable")
    W003 = ("W003", Severity.WARNING, "Unreachable code after return/break/continue")
    W004 = ("W004", Severity.WARNING, "Unknown module — no known #include mapping")

    def __init__(self, code: str, severity: Severity, description: str):
        self.code_str = code
        self.severity = severity
        self.description = description


@dataclass
class TranspilerError:
    """A single error or warning with location and context."""

    code: ErrorCode
    line: int
    col: int
    message: str
    source_line: str = ""
    span: int = 1
    hint: Optional[str] = None

    @property
    def severity(self) -> Severity:
        return self.code.severity

    def format(self) -> str:
        severity = self.severity.value
        header = f"{severity} [{self.line}:{self.col}] {self.code.code_str} — {self.message}"
        lines = [header]
        if self.source_line:
            lines.append(f"  | {self.source_line}")
            pointer = " " * (self.col - 1) + "^" * max(1, self.span)
            lines.append(f"  | {pointer}")
        if self.hint:
            lines.append(f"  hint: {self.hint}")
        return "\n".join(lines)


class ErrorCollector:
    """Accumulates errors and warnings, then formats them for output."""

    def __init__(self, source_lines: Optional[List[str]] = None):
        self.errors: List[TranspilerError] = []
        self.source_lines: List[str] = source_lines or []

    def set_source(self, source: str) -> None:
        """Set source text for error context display."""
        self.source_lines = source.splitlines()

    def _get_source_line(self, line: int) -> str:
        if self.source_lines and 1 <= line <= len(self.source_lines):
            return self.source_lines[line - 1]
        return ""

    def add(
        self,
        code: ErrorCode,
        line: int,
        col: int,
        message: str,
        span: int = 1,
        hint: Optional[str] = None,
    ) -> None:
        source_line = self._get_source_line(line)
        self.errors.append(
            TranspilerError(
                code=code,
                line=line,
                col=col,
                message=message,
                source_line=source_line,
                span=span,
                hint=hint,
            )
        )

    def has_errors(self) -> bool:
        """True if any ERROR-severity issues exist."""
        return any(e.severity == Severity.ERROR for e in self.errors)

    def has_any(self) -> bool:
        """True if any errors or warnings exist."""
        return len(self.errors) > 0

    def format_all(self) -> str:
        """Format all errors/warnings sorted by location."""
        sorted_errors = sorted(self.errors, key=lambda e: (e.line, e.col))
        return "\n\n".join(e.format() for e in sorted_errors)

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.errors if e.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.errors if e.severity == Severity.WARNING)
