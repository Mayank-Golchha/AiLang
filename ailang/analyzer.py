"""Semantic analysis pass for AILang AST trees.

Walks every AST node produced by the parser and collects semantic errors /
warnings into an ``ErrorCollector`` instance.  The public entry point is the
module-level :func:`analyze` helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from ailang import ast_nodes as ast
from ailang.errors import ErrorCode, ErrorCollector


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

RESERVED_KEYWORDS = {
    "use", "as", "exp", "cls", "enum",
    "if", "elif", "else",
    "loop", "for", "in", "match",
    "return", "break", "continue",
    "throw", "try", "catch",
    "async", "await",
    "true", "false",
    "self", "super",
    "Map", "Set", "Deque", "PQueue",
}

KNOWN_MODULES = {"std.io", "std.math", "std.string", "std.algo", "std.thread"}

# Symbols exported by known modules (used when 'as *' wildcard imports occur).
_MODULE_EXPORTS = {
    "std.io": ["print", "println", "input", "eprint", "eprintln"],
    "std.math": ["abs", "sqrt", "pow", "sin", "cos", "tan", "log", "ceil", "floor",
                 "min", "max", "PI", "E"],
    "std.string": ["to_string", "to_int", "to_float", "split", "join", "trim"],
    "std.algo": ["sort", "reverse", "find", "count", "filter", "map", "reduce"],
    "std.thread": ["spawn", "sleep"],
}

# Operators that yield a boolean result regardless of operand types.
_COMPARISON_OPS = {"==", "!=", "<", ">", "<=", ">=", "&&", "||"}
# Arithmetic / bitwise operators that propagate numeric types.
_ARITHMETIC_OPS = {"+", "-", "*", "/", "%", "**", "&", "|", "^", "<<", ">>"}


# ═══════════════════════════════════════════════════════════════════════════════
# SYMBOL TABLE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Symbol:
    """One entry in a scope's symbol table."""

    name: str
    type: Optional[ast.TypeNode]   # None when type is not yet inferred
    mutable: bool
    line: int
    col: int
    used: bool = False             # flipped on lookup – powers W002
    param_count: Optional[int] = None  # set for function symbols


class ScopeStack:
    """Nested lexical scopes backed by a list of dictionaries."""

    def __init__(self, errors: ErrorCollector):
        self._scopes: List[Dict[str, Symbol]] = [{}]  # global scope
        self._errors = errors

    # ------------------------------------------------------------------
    # scope manipulation
    # ------------------------------------------------------------------

    def push(self) -> None:
        """Enter a new (child) scope."""
        self._scopes.append({})

    def pop(self) -> None:
        """Exit the current scope, emitting W002 for unused variables."""
        scope = self._scopes.pop()
        for sym in scope.values():
            if not sym.used and sym.name != "_":
                self._errors.add(
                    ErrorCode.W002,
                    sym.line,
                    sym.col,
                    f"Variable '{sym.name}' is declared but never used",
                    span=len(sym.name),
                    hint="Remove the variable or prefix with '_' if intentional.",
                )

    # ------------------------------------------------------------------
    # declarations & lookups
    # ------------------------------------------------------------------

    def declare(
        self,
        name: str,
        type_: Optional[ast.TypeNode],
        mutable: bool,
        line: int,
        col: int,
        *,
        param_count: Optional[int] = None,
    ) -> None:
        """Declare *name* in the current (innermost) scope.

        Raises E013 if a symbol with the same name already exists in this
        exact scope level.
        """
        current = self._scopes[-1]
        if name in current:
            self._errors.add(
                ErrorCode.E013,
                line,
                col,
                f"Duplicate declaration of '{name}' in the same scope",
                span=len(name),
                hint=f"First declared at line {current[name].line}.",
            )
            return
        current[name] = Symbol(
            name=name,
            type=type_,
            mutable=mutable,
            line=line,
            col=col,
            param_count=param_count,
        )

    def lookup(self, name: str) -> Optional[Symbol]:
        """Resolve *name* from the innermost scope outward."""
        for scope in reversed(self._scopes):
            if name in scope:
                sym = scope[name]
                sym.used = True
                return sym
        return None

    def assign_check(self, name: str, line: int, col: int) -> None:
        """Verify the target of an assignment is mutable (E007)."""
        sym = self.lookup(name)
        if sym is not None and not sym.mutable:
            self._errors.add(
                ErrorCode.E007,
                line,
                col,
                f"Cannot reassign immutable variable '{name}'",
                span=len(name),
                hint="Declare with ':=' instead of '=' to make it mutable.",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYZER
# ═══════════════════════════════════════════════════════════════════════════════

class Analyzer:
    """Single-pass AST visitor that collects semantic diagnostics."""

    def __init__(self, errors: ErrorCollector):
        self.errors = errors
        self.scope = ScopeStack(errors)

        # Context flags
        self.in_loop: int = 0
        self.in_function: bool = False
        self.in_class: bool = False
        self.in_async: bool = False

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def analyze(self, program: ast.Program) -> None:
        """Walk the full AST rooted at *program*."""
        for imp in program.imports:
            self._analyze_import(imp)

        # E023: detect conflict between top-level executables and explicit main()
        self._check_main_conflict(program)

        self._analyze_body(program.statements)

    def _check_main_conflict(self, program: ast.Program) -> None:
        """Emit E023 if both top-level executable statements and an
        explicit main() function exist."""
        _GLOBAL_TYPES = (ast.VarDecl, ast.MultiVarDecl, ast.FuncDecl,
                         ast.ClassDecl, ast.EnumDecl, ast.ImportStmt)

        has_explicit_main = any(
            isinstance(s, ast.FuncDecl) and s.name == "main"
            for s in program.statements
        )

        if not has_explicit_main:
            return

        for stmt in program.statements:
            if not isinstance(stmt, _GLOBAL_TYPES):
                self.errors.add(
                    ErrorCode.E023,
                    stmt.line,
                    stmt.col,
                    "Top-level executable statements cannot coexist with "
                    "explicit main()",
                    hint="Move statements into main() or remove explicit main().",
                )
                break  # one error is enough

    # ------------------------------------------------------------------
    # import handling
    # ------------------------------------------------------------------

    def _analyze_import(self, node: ast.ImportStmt) -> None:
        mod_path = ".".join(node.module_path)
        if mod_path not in KNOWN_MODULES:
            self.errors.add(
                ErrorCode.W004,
                node.line,
                node.col,
                f"Unknown module '{mod_path}'",
                hint="No known C++ header mapping for this module.",
            )
        # Register alias in scope so that later references resolve.
        if node.alias == "*":
            # Wildcard import — register all known exports from this module.
            exports = _MODULE_EXPORTS.get(mod_path, [])
            for sym_name in exports:
                self.scope.declare(sym_name, None, False, node.line, node.col)
        elif node.alias is not None:
            self.scope.declare(node.alias, None, False, node.line, node.col)
        elif node.alias is None and node.module_path:
            # Default alias is the last component.
            last = node.module_path[-1]
            self.scope.declare(last, None, False, node.line, node.col)

    # ------------------------------------------------------------------
    # body / block helpers
    # ------------------------------------------------------------------

    def _analyze_body(self, stmts: List[ast.StmtNode]) -> None:
        """Analyze a list of statements, detecting unreachable code (W003)."""
        hit_terminator = False
        for stmt in stmts:
            if hit_terminator:
                self.errors.add(
                    ErrorCode.W003,
                    stmt.line,
                    stmt.col,
                    "Unreachable code",
                    hint="This statement follows a return, break, or continue.",
                )
            self._analyze_stmt(stmt)
            if isinstance(stmt, (ast.ReturnStmt, ast.BreakStmt, ast.ContinueStmt)):
                hit_terminator = True

    # ------------------------------------------------------------------
    # statement dispatch
    # ------------------------------------------------------------------

    def _analyze_stmt(self, stmt: ast.StmtNode) -> None:  # noqa: C901 – big dispatch
        if isinstance(stmt, ast.VarDecl):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, ast.MultiVarDecl):
            self._analyze_multi_var_decl(stmt)
        elif isinstance(stmt, ast.AssignmentStmt):
            self._analyze_assignment(stmt)
        elif isinstance(stmt, ast.FuncDecl):
            self._analyze_func_decl(stmt)
        elif isinstance(stmt, ast.ClassDecl):
            self._analyze_class_decl(stmt)
        elif isinstance(stmt, ast.EnumDecl):
            self._analyze_enum_decl(stmt)
        elif isinstance(stmt, ast.IfStmt):
            self._analyze_if(stmt)
        elif isinstance(stmt, ast.LoopStmt):
            self._analyze_loop(stmt)
        elif isinstance(stmt, ast.ForRangeStmt):
            self._analyze_for_range(stmt)
        elif isinstance(stmt, ast.ForEachStmt):
            self._analyze_for_each(stmt)
        elif isinstance(stmt, ast.ForMapStmt):
            self._analyze_for_map(stmt)
        elif isinstance(stmt, ast.MatchStmt):
            self._analyze_match(stmt)
        elif isinstance(stmt, ast.ReturnStmt):
            self._analyze_return(stmt)
        elif isinstance(stmt, ast.BreakStmt):
            self._analyze_break(stmt)
        elif isinstance(stmt, ast.ContinueStmt):
            self._analyze_continue(stmt)
        elif isinstance(stmt, ast.ThrowStmt):
            self._analyze_throw(stmt)
        elif isinstance(stmt, ast.TryStmt):
            self._analyze_try(stmt)
        elif isinstance(stmt, ast.ExprStmt):
            self._analyze_expr(stmt.expr)

    # ------------------------------------------------------------------
    # variable declarations
    # ------------------------------------------------------------------

    def _check_reserved(self, name: str, line: int, col: int) -> None:
        """Emit E004 if *name* is a reserved keyword."""
        if name in RESERVED_KEYWORDS:
            self.errors.add(
                ErrorCode.E004,
                line,
                col,
                f"'{name}' is a reserved keyword and cannot be used as an identifier",
                span=len(name),
            )

    def _analyze_var_decl(self, node: ast.VarDecl) -> None:
        self._check_reserved(node.name, node.line, node.col)

        # Evaluate RHS first so references inside can be resolved.
        inferred = self._analyze_expr(node.value)

        declared_type = node.type if node.type is not None else inferred

        # E006: type mismatch when both explicit and inferred types are known.
        if node.type is not None and inferred is not None:
            self._check_type_compat(node.type, inferred, node.line, node.col)

        self.scope.declare(node.name, declared_type, node.mutable, node.line, node.col)

    def _analyze_multi_var_decl(self, node: ast.MultiVarDecl) -> None:
        # E008: target count vs value count
        if len(node.targets) != len(node.values):
            self.errors.add(
                ErrorCode.E008,
                node.line,
                node.col,
                f"Expected {len(node.targets)} values but got {len(node.values)}",
                hint="Each target variable needs exactly one corresponding value.",
            )

        # Analyze values first.
        inferred_types: List[Optional[ast.TypeNode]] = []
        for val in node.values:
            inferred_types.append(self._analyze_expr(val))

        for i, target in enumerate(node.targets):
            if target.name == "_":
                continue
            self._check_reserved(target.name, target.line, target.col)
            ttype = target.type
            if ttype is None and i < len(inferred_types):
                ttype = inferred_types[i]
            if target.type is not None and i < len(inferred_types) and inferred_types[i] is not None:
                self._check_type_compat(target.type, inferred_types[i], target.line, target.col)
            self.scope.declare(target.name, ttype, node.mutable, target.line, target.col)

    # ------------------------------------------------------------------
    # assignment
    # ------------------------------------------------------------------

    def _analyze_assignment(self, node: ast.AssignmentStmt) -> None:
        # Determine the name being assigned (only simple ident targets).
        if isinstance(node.target, ast.IdentExpr):
            self.scope.assign_check(node.target.name, node.target.line, node.target.col)
        # Analyze both sides.
        target_type = self._analyze_expr(node.target)
        value_type = self._analyze_expr(node.value)
        if target_type is not None and value_type is not None:
            self._check_type_compat(target_type, value_type, node.line, node.col)

    # ------------------------------------------------------------------
    # function declarations
    # ------------------------------------------------------------------

    def _analyze_func_decl(self, node: ast.FuncDecl) -> None:
        self._check_reserved(node.name, node.line, node.col)

        # Register function in enclosing scope *before* body so recursion works.
        self.scope.declare(
            node.name,
            node.return_type,
            False,
            node.line,
            node.col,
            param_count=len(node.params),
        )

        # New scope for body.
        self.scope.push()

        # Declare params.
        for param in node.params:
            if param.name != "_":
                self._check_reserved(param.name, param.line, param.col)
                self.scope.declare(param.name, param.type, True, param.line, param.col)

        # Save / set context.
        prev_function = self.in_function
        prev_async = self.in_async
        self.in_function = True
        self.in_async = node.is_async

        self._analyze_body(node.body)

        # Restore context.
        self.in_function = prev_function
        self.in_async = prev_async

        self.scope.pop()

    # ------------------------------------------------------------------
    # class declarations
    # ------------------------------------------------------------------

    def _analyze_class_decl(self, node: ast.ClassDecl) -> None:
        self._check_reserved(node.name, node.line, node.col)
        self.scope.declare(node.name, ast.UserType(node.name, node.line, node.col), False, node.line, node.col)

        self.scope.push()

        prev_class = self.in_class
        self.in_class = True

        # Register generic type parameters so they don't trigger E005.
        for g in node.generics:
            self.scope.declare(g, None, False, node.line, node.col)

        for member in node.members:
            if isinstance(member, ast.VarDecl):
                self._analyze_var_decl(member)
            elif isinstance(member, ast.FuncDecl):
                self._analyze_func_decl(member)

        self.in_class = prev_class
        self.scope.pop()

    # ------------------------------------------------------------------
    # enum declarations
    # ------------------------------------------------------------------

    def _analyze_enum_decl(self, node: ast.EnumDecl) -> None:
        self._check_reserved(node.name, node.line, node.col)
        self.scope.declare(node.name, ast.UserType(node.name, node.line, node.col), False, node.line, node.col)

        for variant in node.variants:
            for field_type in variant.fields:
                self._analyze_type(field_type)

    # ------------------------------------------------------------------
    # control flow
    # ------------------------------------------------------------------

    def _analyze_if(self, node: ast.IfStmt) -> None:
        self._analyze_expr(node.condition)
        self.scope.push()
        self._analyze_body(node.body)
        self.scope.pop()

        for elif_clause in node.elifs:
            self._analyze_expr(elif_clause.condition)
            self.scope.push()
            self._analyze_body(elif_clause.body)
            self.scope.pop()

        if node.else_body is not None:
            self.scope.push()
            self._analyze_body(node.else_body)
            self.scope.pop()

    # -- loops ----------------------------------------------------------

    def _analyze_loop(self, node: ast.LoopStmt) -> None:
        if node.condition is not None:
            self._analyze_expr(node.condition)
        self.scope.push()
        self.in_loop += 1
        self._analyze_body(node.body)
        self.in_loop -= 1
        self.scope.pop()

    def _analyze_for_range(self, node: ast.ForRangeStmt) -> None:
        self._analyze_expr(node.start)
        self._analyze_expr(node.end)
        if node.step is not None:
            self._analyze_expr(node.step)

        self.scope.push()
        if node.var_name != "_":
            self._check_reserved(node.var_name, node.line, node.col)
            self.scope.declare(
                node.var_name,
                ast.PrimitiveType("int", node.line, node.col),
                True,
                node.line,
                node.col,
            )
        self.in_loop += 1
        self._analyze_body(node.body)
        self.in_loop -= 1
        self.scope.pop()

    def _analyze_for_each(self, node: ast.ForEachStmt) -> None:
        self._analyze_expr(node.iterable)

        self.scope.push()
        if node.var_name != "_":
            self._check_reserved(node.var_name, node.line, node.col)
            self.scope.declare(node.var_name, None, True, node.line, node.col)
        self.in_loop += 1
        self._analyze_body(node.body)
        self.in_loop -= 1
        self.scope.pop()

    def _analyze_for_map(self, node: ast.ForMapStmt) -> None:
        self._analyze_expr(node.iterable)

        self.scope.push()
        for name in (node.key_name, node.value_name):
            if name != "_":
                self._check_reserved(name, node.line, node.col)
                self.scope.declare(name, None, True, node.line, node.col)
        self.in_loop += 1
        self._analyze_body(node.body)
        self.in_loop -= 1
        self.scope.pop()

    # -- match ----------------------------------------------------------

    def _analyze_match(self, node: ast.MatchStmt) -> None:
        self._analyze_expr(node.expr)

        # E020: EOF arm must be last.  The parser stores `eof_arm` separately,
        # but if the source mixed EOF arms among regular arms, the parser may
        # still embed them.  We check that no MatchArm appears *after* the
        # logical position of the eof_arm by verifying line numbers.
        if node.eof_arm is not None and node.arms:
            last_arm = node.arms[-1]
            if node.eof_arm.line < last_arm.line:
                self.errors.add(
                    ErrorCode.E020,
                    node.eof_arm.line,
                    node.eof_arm.col,
                    "EOF (default) arm must be the last arm in a match block",
                )

        # W001: no EOF arm at all.
        if node.eof_arm is None:
            self.errors.add(
                ErrorCode.W001,
                node.line,
                node.col,
                "Match statement has no EOF (default) arm",
                hint="Consider adding a default arm to handle unexpected values.",
            )

        for arm in node.arms:
            self.scope.push()
            for pattern in arm.patterns:
                self._analyze_pattern(pattern)
            self._analyze_body(arm.body)
            self.scope.pop()

        if node.eof_arm is not None:
            self.scope.push()
            self._analyze_body(node.eof_arm.body)
            self.scope.pop()

    def _analyze_pattern(self, pattern: ast.PatternNode) -> None:
        if isinstance(pattern, ast.WildcardPattern):
            pass  # nothing to check
        elif isinstance(pattern, ast.LiteralPattern):
            self._analyze_expr(pattern.value)
        elif isinstance(pattern, ast.DestructurePattern):
            for fname in pattern.fields:
                if fname != "_":
                    self.scope.declare(fname, None, False, pattern.line, pattern.col)

    # -- return / break / continue --------------------------------------

    def _analyze_return(self, node: ast.ReturnStmt) -> None:
        if not self.in_function:
            self.errors.add(
                ErrorCode.E011,
                node.line,
                node.col,
                "'return' used outside of a function body",
            )
        if node.value is not None:
            self._analyze_expr(node.value)

    def _analyze_break(self, node: ast.BreakStmt) -> None:
        if self.in_loop == 0:
            self.errors.add(
                ErrorCode.E010,
                node.line,
                node.col,
                "'break' used outside of a loop",
            )

    def _analyze_continue(self, node: ast.ContinueStmt) -> None:
        if self.in_loop == 0:
            self.errors.add(
                ErrorCode.E010,
                node.line,
                node.col,
                "'continue' used outside of a loop",
            )

    # -- throw / try ----------------------------------------------------

    def _analyze_throw(self, node: ast.ThrowStmt) -> None:
        self._analyze_expr(node.value)

    def _analyze_try(self, node: ast.TryStmt) -> None:
        self.scope.push()
        self._analyze_body(node.body)
        self.scope.pop()

        for catch in node.catches:
            self.scope.push()
            if catch.name and catch.name != "_":
                self._check_reserved(catch.name, catch.line, catch.col)
                self.scope.declare(catch.name, catch.type, False, catch.line, catch.col)
            if catch.type is not None:
                self._analyze_type(catch.type)
            self._analyze_body(catch.body)
            self.scope.pop()

    # ------------------------------------------------------------------
    # expression dispatch  (returns inferred TypeNode or None)
    # ------------------------------------------------------------------

    def _analyze_expr(self, expr: ast.ExprNode) -> Optional[ast.TypeNode]:  # noqa: C901
        if expr is None:
            return None

        if isinstance(expr, ast.LiteralExpr):
            return self._analyze_literal(expr)
        if isinstance(expr, ast.IdentExpr):
            return self._analyze_ident(expr)
        if isinstance(expr, ast.BinaryExpr):
            return self._analyze_binary(expr)
        if isinstance(expr, ast.ChainedCompareExpr):
            return self._analyze_chained_compare(expr)
        if isinstance(expr, ast.UnaryExpr):
            return self._analyze_unary(expr)
        if isinstance(expr, ast.CallExpr):
            return self._analyze_call(expr)
        if isinstance(expr, ast.IndexExpr):
            return self._analyze_index(expr)
        if isinstance(expr, ast.DotExpr):
            return self._analyze_dot(expr)
        if isinstance(expr, ast.PropagateExpr):
            return self._analyze_propagate(expr)
        if isinstance(expr, ast.AwaitExpr):
            return self._analyze_await(expr)
        if isinstance(expr, ast.LambdaExpr):
            return self._analyze_lambda(expr)
        if isinstance(expr, ast.TupleLiteral):
            return self._analyze_tuple_literal(expr)
        if isinstance(expr, ast.ArrayLiteral):
            return self._analyze_array_literal(expr)
        if isinstance(expr, ast.MapLiteral):
            return self._analyze_map_literal(expr)
        if isinstance(expr, ast.SizedVectorLiteral):
            return self._analyze_sized_vector(expr)
        if isinstance(expr, ast.StringInterp):
            return self._analyze_string_interp(expr)
        if isinstance(expr, ast.GroupedExpr):
            return self._analyze_expr(expr.expr)
        return None

    # -- individual expression analysers --------------------------------

    def _analyze_literal(self, node: ast.LiteralExpr) -> Optional[ast.TypeNode]:
        type_map = {
            "int":    "int",
            "float":  "f64",
            "string": "str",
            "bool":   "bool",
        }
        prim_name = type_map.get(node.literal_type)
        if prim_name is not None:
            return ast.PrimitiveType(prim_name, node.line, node.col)
        return None

    def _analyze_ident(self, node: ast.IdentExpr) -> Optional[ast.TypeNode]:
        # E012: 'self' outside class
        if node.name == "self":
            if not self.in_class:
                self.errors.add(
                    ErrorCode.E012,
                    node.line,
                    node.col,
                    "'self' used outside of a class method",
                )
            return None

        # E005: undeclared identifier (skip "_" which is a discard placeholder)
        if node.name == "_":
            return None

        sym = self.scope.lookup(node.name)
        if sym is None:
            self.errors.add(
                ErrorCode.E005,
                node.line,
                node.col,
                f"Undeclared identifier '{node.name}'",
                span=len(node.name),
            )
            return None
        return sym.type

    def _analyze_binary(self, node: ast.BinaryExpr) -> Optional[ast.TypeNode]:
        left_t = self._analyze_expr(node.left)
        right_t = self._analyze_expr(node.right)

        if node.op in _COMPARISON_OPS:
            return ast.PrimitiveType("bool", node.line, node.col)

        # Best-effort numeric type propagation.
        if left_t is not None and right_t is not None:
            if isinstance(left_t, ast.PrimitiveType) and isinstance(right_t, ast.PrimitiveType):
                # Float wins over int.
                if left_t.name in ("float", "f64") or right_t.name in ("float", "f64"):
                    return ast.PrimitiveType("f64", node.line, node.col)
                if left_t.name == right_t.name:
                    return left_t
        # If we can infer at least one side, return that.
        return left_t or right_t

    def _analyze_chained_compare(self, node: ast.ChainedCompareExpr) -> Optional[ast.TypeNode]:
        for operand in node.operands:
            self._analyze_expr(operand)
        return ast.PrimitiveType("bool", node.line, node.col)

    def _analyze_unary(self, node: ast.UnaryExpr) -> Optional[ast.TypeNode]:
        inner = self._analyze_expr(node.operand)
        if node.op == "!":
            return ast.PrimitiveType("bool", node.line, node.col)
        return inner

    def _analyze_call(self, node: ast.CallExpr) -> Optional[ast.TypeNode]:
        # Analyze arguments first.
        for arg in node.args:
            self._analyze_expr(arg)

        # Resolve callee.
        callee_type: Optional[ast.TypeNode] = None

        if isinstance(node.callee, ast.IdentExpr):
            sym = self.scope.lookup(node.callee.name)
            if sym is None:
                # Don't double-report E005 – _analyze_expr on callee would do
                # that, but we've already resolved manually here.  Report once.
                self.errors.add(
                    ErrorCode.E005,
                    node.callee.line,
                    node.callee.col,
                    f"Undeclared identifier '{node.callee.name}'",
                    span=len(node.callee.name),
                )
            else:
                # E014: argument count
                if sym.param_count is not None and len(node.args) != sym.param_count:
                    self.errors.add(
                        ErrorCode.E014,
                        node.line,
                        node.col,
                        f"'{node.callee.name}' expects {sym.param_count} argument(s), "
                        f"got {len(node.args)}",
                    )
                callee_type = sym.type  # return type of the function
        else:
            # For non-ident callees (e.g. method calls), just analyze the expr.
            callee_type = self._analyze_expr(node.callee)

        return callee_type

    def _analyze_index(self, node: ast.IndexExpr) -> Optional[ast.TypeNode]:
        obj_t = self._analyze_expr(node.obj)
        self._analyze_expr(node.index)

        # Best effort: if obj is an array type, return element type.
        if isinstance(obj_t, ast.ArrayType):
            return obj_t.element_type
        if isinstance(obj_t, ast.MapType):
            return obj_t.value_type
        return None

    def _analyze_dot(self, node: ast.DotExpr) -> Optional[ast.TypeNode]:
        self._analyze_expr(node.obj)
        # We cannot resolve member types without a full class registry;
        # return None (unknown).
        return None

    def _analyze_propagate(self, node: ast.PropagateExpr) -> Optional[ast.TypeNode]:
        inner = self._analyze_expr(node.expr)
        # E016: ? on non-optional type
        if inner is not None and not isinstance(inner, ast.OptionalType):
            self.errors.add(
                ErrorCode.E016,
                node.line,
                node.col,
                "'?' (propagate) used on a non-optional type",
                hint="The expression must evaluate to an optional (T?) type.",
            )
        # Unwrap optional.
        if isinstance(inner, ast.OptionalType):
            return inner.inner_type
        return inner

    def _analyze_await(self, node: ast.AwaitExpr) -> Optional[ast.TypeNode]:
        # E017: await outside async function
        if not self.in_async:
            self.errors.add(
                ErrorCode.E017,
                node.line,
                node.col,
                "'await' used outside of an async function",
            )
        return self._analyze_expr(node.expr)

    def _analyze_lambda(self, node: ast.LambdaExpr) -> Optional[ast.TypeNode]:
        self.scope.push()
        for param_name in node.params:
            if param_name != "_":
                self._check_reserved(param_name, node.line, node.col)
                self.scope.declare(param_name, None, True, node.line, node.col)

        prev_fn = self.in_function
        self.in_function = True
        self._analyze_expr(node.body)
        self.in_function = prev_fn

        self.scope.pop()
        return None  # lambda return type is opaque

    def _analyze_tuple_literal(self, node: ast.TupleLiteral) -> Optional[ast.TypeNode]:
        elem_types: List[ast.TypeNode] = []
        for el in node.elements:
            t = self._analyze_expr(el)
            if t is not None:
                elem_types.append(t)
        if elem_types and len(elem_types) == len(node.elements):
            return ast.TupleType(elem_types, node.line, node.col)
        return None

    def _analyze_array_literal(self, node: ast.ArrayLiteral) -> Optional[ast.TypeNode]:
        elem_type: Optional[ast.TypeNode] = None
        for el in node.elements:
            t = self._analyze_expr(el)
            if t is not None and elem_type is None:
                elem_type = t
        if elem_type is not None:
            return ast.ArrayType(elem_type, None, node.line, node.col)
        return None

    def _analyze_map_literal(self, node: ast.MapLiteral) -> Optional[ast.TypeNode]:
        key_type: Optional[ast.TypeNode] = None
        val_type: Optional[ast.TypeNode] = None
        for key_expr, val_expr in node.entries:
            kt = self._analyze_expr(key_expr)
            vt = self._analyze_expr(val_expr)
            if kt is not None and key_type is None:
                key_type = kt
            if vt is not None and val_type is None:
                val_type = vt
        if key_type is not None and val_type is not None:
            return ast.MapType(key_type, val_type, node.line, node.col)
        return None

    def _analyze_sized_vector(self, node: ast.SizedVectorLiteral) -> Optional[ast.TypeNode]:
        self._analyze_expr(node.size_expr)
        fill_type: Optional[ast.TypeNode] = None
        if node.fill_value is not None:
            fill_type = self._analyze_expr(node.fill_value)
        if fill_type is not None:
            return ast.ArrayType(fill_type, None, node.line, node.col)
        return None

    def _analyze_string_interp(self, node: ast.StringInterp) -> Optional[ast.TypeNode]:
        for part in node.parts:
            if not isinstance(part, str):
                self._analyze_expr(part)
        return ast.PrimitiveType("str", node.line, node.col)

    # ------------------------------------------------------------------
    # type helpers
    # ------------------------------------------------------------------

    def _analyze_type(self, type_node: ast.TypeNode) -> None:
        """Walk a type node and validate sub-components (best effort)."""
        if type_node is None:
            return
        if isinstance(type_node, ast.PrimitiveType):
            pass
        elif isinstance(type_node, ast.ArrayType):
            self._analyze_type(type_node.element_type)
        elif isinstance(type_node, ast.MapType):
            self._analyze_type(type_node.key_type)
            self._analyze_type(type_node.value_type)
        elif isinstance(type_node, ast.TupleType):
            for et in type_node.element_types:
                self._analyze_type(et)
        elif isinstance(type_node, ast.GenericType):
            for ta in type_node.type_args:
                self._analyze_type(ta)
        elif isinstance(type_node, ast.UserType):
            pass
        elif isinstance(type_node, ast.OptionalType):
            self._analyze_type(type_node.inner_type)
        elif isinstance(type_node, ast.BuiltinCollectionType):
            for ta in type_node.type_args:
                self._analyze_type(ta)

    @staticmethod
    def _type_name(t: ast.TypeNode) -> Optional[str]:
        """Return a short printable name for a TypeNode, or None."""
        if isinstance(t, ast.PrimitiveType):
            return t.name
        if isinstance(t, ast.UserType):
            return t.name
        if isinstance(t, ast.ArrayType):
            inner = Analyzer._type_name(t.element_type)
            return f"[{inner}]" if inner else None
        if isinstance(t, ast.OptionalType):
            inner = Analyzer._type_name(t.inner_type)
            return f"{inner}?" if inner else None
        if isinstance(t, ast.MapType):
            k = Analyzer._type_name(t.key_type)
            v = Analyzer._type_name(t.value_type)
            return f"{{{k}: {v}}}" if k and v else None
        if isinstance(t, ast.TupleType):
            names = [Analyzer._type_name(et) for et in t.element_types]
            if all(names):
                return "(" + ", ".join(names) + ")"  # type: ignore[arg-type]
            return None
        return None

    def _check_type_compat(
        self,
        expected: ast.TypeNode,
        actual: ast.TypeNode,
        line: int,
        col: int,
    ) -> None:
        """Emit E006 when *expected* and *actual* are provably incompatible."""
        exp_name = self._type_name(expected)
        act_name = self._type_name(actual)
        if exp_name is None or act_name is None:
            return  # can't determine – skip
        if exp_name != act_name:
            self.errors.add(
                ErrorCode.E006,
                line,
                col,
                f"Type mismatch: expected '{exp_name}', got '{act_name}'",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def analyze(program: ast.Program, errors: ErrorCollector) -> None:
    """Run semantic analysis on *program*, appending diagnostics to *errors*."""
    analyzer = Analyzer(errors)
    analyzer.analyze(program)
