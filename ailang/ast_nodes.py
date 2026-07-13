"""AST node dataclass definitions for every AILang grammar production."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Union


# ═══════════════════════════════════════════════════════════════════════════════
# TYPE NODES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PrimitiveType:
    """i8, i16, int, i64, u8, u16, u32, u64, float, f64, chr, str"""
    name: str
    line: int
    col: int


@dataclass
class ArrayType:
    """[T] → vector, [T, N] → array (N=literal) or vector(N) (N=ident)"""
    element_type: "TypeNode"
    size: Optional[Union["LiteralExpr", "IdentExpr"]]  # None=dynamic
    line: int
    col: int


@dataclass
class MapType:
    """{K: V} → unordered_map"""
    key_type: "TypeNode"
    value_type: "TypeNode"
    line: int
    col: int


@dataclass
class TupleType:
    """(T, U, ...) → std::tuple"""
    element_types: List["TypeNode"]
    line: int
    col: int


@dataclass
class GenericType:
    """UserType[T, U, ...]"""
    name: str
    type_args: List["TypeNode"]
    line: int
    col: int


@dataclass
class UserType:
    """A user-defined type name (also used for unresolved types)."""
    name: str
    line: int
    col: int


@dataclass
class OptionalType:
    """T? → std::optional<T>"""
    inner_type: "TypeNode"
    line: int
    col: int


@dataclass
class BuiltinCollectionType:
    """Map[K,V], Set[T], Deque[T], PQueue[T]"""
    collection: str  # "Map", "Set", "Deque", "PQueue"
    type_args: List["TypeNode"]
    line: int
    col: int


# Union of all type nodes
TypeNode = Union[
    PrimitiveType, ArrayType, MapType, TupleType,
    GenericType, UserType, OptionalType, BuiltinCollectionType,
]


# ═══════════════════════════════════════════════════════════════════════════════
# PATTERN NODES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WildcardPattern:
    """The _ pattern in match arms."""
    line: int
    col: int


@dataclass
class LiteralPattern:
    """A literal value pattern in match (200, "ok", true, etc.)."""
    value: "LiteralExpr"
    line: int
    col: int


@dataclass
class DestructurePattern:
    """EnumVariant(field1, field2, _) destructuring pattern."""
    name: str
    fields: List[str]  # field names or "_"
    line: int
    col: int


PatternNode = Union[WildcardPattern, LiteralPattern, DestructurePattern]


# ═══════════════════════════════════════════════════════════════════════════════
# EXPRESSION NODES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LiteralExpr:
    """Integer, float, string, or boolean literal."""
    value: Union[int, float, str, bool]
    literal_type: str  # "int", "float", "string", "bool"
    line: int
    col: int


@dataclass
class IdentExpr:
    """A variable or function name reference."""
    name: str
    line: int
    col: int


@dataclass
class BinaryExpr:
    """left op right — arithmetic, comparison, logical, bitwise."""
    op: str
    left: "ExprNode"
    right: "ExprNode"
    line: int
    col: int


@dataclass
class ChainedCompareExpr:
    """a < b < c → (a < b) && (b < c). Stores operands and operators."""
    operands: List["ExprNode"]
    operators: List[str]
    line: int
    col: int


@dataclass
class UnaryExpr:
    """Prefix unary: -, !, ~"""
    op: str
    operand: "ExprNode"
    line: int
    col: int


@dataclass
class CallExpr:
    """Function or method call: callee(args)"""
    callee: "ExprNode"
    args: List["ExprNode"]
    line: int
    col: int


@dataclass
class IndexExpr:
    """Array/map index access: obj[index]"""
    obj: "ExprNode"
    index: "ExprNode"
    line: int
    col: int


@dataclass
class DotExpr:
    """Member access: obj.attr"""
    obj: "ExprNode"
    attr: str
    line: int
    col: int


@dataclass
class PropagateExpr:
    """Error propagation: expr?"""
    expr: "ExprNode"
    line: int
    col: int


@dataclass
class AwaitExpr:
    """await expr"""
    expr: "ExprNode"
    line: int
    col: int


@dataclass
class LambdaExpr:
    """(params) => body_expr"""
    params: List[str]  # parameter names, "_" for discard
    body: "ExprNode"
    line: int
    col: int


@dataclass
class TupleLiteral:
    """(a, b, c) — tuple expression"""
    elements: List["ExprNode"]
    line: int
    col: int


@dataclass
class ArrayLiteral:
    """[a, b, c] — array/vector literal"""
    elements: List["ExprNode"]
    line: int
    col: int


@dataclass
class MapLiteral:
    """{k1: v1, k2: v2} — map literal expression"""
    entries: List[tuple]  # List of (key_expr, value_expr) tuples
    line: int
    col: int


@dataclass
class SizedVectorLiteral:
    """n*[0] or n*[] — vector initialized with n copies"""
    size_expr: "ExprNode"
    fill_value: Optional["ExprNode"]  # None for default-init
    line: int
    col: int


@dataclass
class StringInterp:
    """String with interpolation: "hello {name}, val={a+b}" """
    parts: List[Union[str, "ExprNode"]]  # alternating strings and expressions
    line: int
    col: int


@dataclass
class GroupedExpr:
    """Parenthesized expression: (expr)"""
    expr: "ExprNode"
    line: int
    col: int


ExprNode = Union[
    BinaryExpr, ChainedCompareExpr, UnaryExpr, CallExpr, IndexExpr,
    DotExpr, PropagateExpr, AwaitExpr, LambdaExpr, IdentExpr,
    LiteralExpr, TupleLiteral, ArrayLiteral, MapLiteral,
    SizedVectorLiteral, StringInterp, GroupedExpr,
]


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER NODES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Param:
    """Function parameter: name: type"""
    name: str  # "_" for discard
    type: "TypeNode"
    line: int
    col: int


@dataclass
class MultiVarTarget:
    """One target in a multi-variable declaration: name or _"""
    name: str  # "_" for discard
    type: Optional["TypeNode"]
    line: int
    col: int


# ═══════════════════════════════════════════════════════════════════════════════
# STATEMENT NODES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VarDecl:
    """Variable declaration: [exp] name [: type] (:= | =) value"""
    name: str
    type: Optional["TypeNode"]
    mutable: bool       # True for :=, False for =
    exported: bool      # True for exp
    value: "ExprNode"
    line: int
    col: int


@dataclass
class MultiVarDecl:
    """Multi-variable declaration: x, y, z := 1, 2, 3"""
    targets: List[MultiVarTarget]
    mutable: bool
    exported: bool
    values: List["ExprNode"]
    line: int
    col: int


@dataclass
class AssignmentStmt:
    """Assignment: postfix_expr assign_op expression"""
    target: "ExprNode"
    op: str  # "=", "+=", "-=", "*=", "/=", "%="
    value: "ExprNode"
    line: int
    col: int


@dataclass
class FuncDecl:
    """Function declaration with block or arrow body."""
    name: str
    params: List[Param]
    return_type: Optional["TypeNode"]
    body: List["StmtNode"]
    is_async: bool
    exported: bool
    is_arrow: bool  # True for => single-expression form
    line: int
    col: int


@dataclass
class ClassDecl:
    """Class declaration: [exp] cls Name[T]: members"""
    name: str
    generics: List[str]
    members: List[Union["VarDecl", "FuncDecl"]]
    exported: bool
    line: int
    col: int


@dataclass
class EnumVariant:
    """A single enum variant, optionally with payload types."""
    name: str
    fields: List["TypeNode"]  # empty for simple variants
    line: int
    col: int


@dataclass
class EnumDecl:
    """Enum declaration: [exp] enum Name: variants"""
    name: str
    variants: List[EnumVariant]
    exported: bool
    line: int
    col: int


@dataclass
class ElifClause:
    """An elif branch: elif condition: body"""
    condition: "ExprNode"
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class IfStmt:
    """if / elif / else statement."""
    condition: "ExprNode"
    body: List["StmtNode"]
    elifs: List[ElifClause]
    else_body: Optional[List["StmtNode"]]
    line: int
    col: int


@dataclass
class LoopStmt:
    """loop [condition]: body — infinite or while loop."""
    condition: Optional["ExprNode"]  # None for infinite
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class ForRangeStmt:
    """for i in start..end[, step]: body"""
    var_name: str  # "_" for discard
    start: "ExprNode"
    end: "ExprNode"
    step: Optional["ExprNode"]
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class ForEachStmt:
    """for item in iterable: body"""
    var_name: str
    iterable: "ExprNode"
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class ForMapStmt:
    """for key, value in map: body"""
    key_name: str
    value_name: str
    iterable: "ExprNode"
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class MatchArm:
    """A single arm in a match statement."""
    patterns: List[PatternNode]
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class EofArm:
    """The default/EOF arm in a match statement."""
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class MatchStmt:
    """match expression: arms + optional EOF arm."""
    expr: "ExprNode"
    arms: List[MatchArm]
    eof_arm: Optional[EofArm]
    line: int
    col: int


@dataclass
class ReturnStmt:
    """return [expression]"""
    value: Optional["ExprNode"]
    line: int
    col: int


@dataclass
class BreakStmt:
    """break"""
    line: int
    col: int


@dataclass
class ContinueStmt:
    """continue"""
    line: int
    col: int


@dataclass
class ThrowStmt:
    """throw expression"""
    value: "ExprNode"
    line: int
    col: int


@dataclass
class CatchClause:
    """catch [name: Type | Type]: body"""
    name: Optional[str]      # None for catch-all or type-only
    type: Optional["TypeNode"]  # None for catch-all
    body: List["StmtNode"]
    line: int
    col: int


@dataclass
class TryStmt:
    """try: body catch clauses"""
    body: List["StmtNode"]
    catches: List[CatchClause]
    line: int
    col: int


@dataclass
class ExprStmt:
    """An expression used as a statement."""
    expr: "ExprNode"
    line: int
    col: int


@dataclass
class ImportStmt:
    """use module.path [as alias | as *]"""
    module_path: List[str]  # e.g. ["std", "math"]
    alias: Optional[str]    # None=no alias, "*"=wildcard
    line: int
    col: int


StmtNode = Union[
    VarDecl, MultiVarDecl, AssignmentStmt, FuncDecl, ClassDecl,
    EnumDecl, IfStmt, LoopStmt, ForRangeStmt, ForEachStmt,
    ForMapStmt, MatchStmt, ReturnStmt, BreakStmt, ContinueStmt,
    ThrowStmt, TryStmt, ExprStmt,
]


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRAM (ROOT)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Program:
    """Root AST node representing a complete AILang program."""
    imports: List[ImportStmt]
    statements: List[StmtNode]
    line: int = 1
    col: int = 1
