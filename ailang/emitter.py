"""C++20 code emitter for the AILang transpiler.

Walks the AST produced by the parser and produces a complete C++20 source
string, including #include directives, namespace aliases, and top-level
wrapping in ``int main()``.
"""

from __future__ import annotations

from typing import List, Optional

from . import ast_nodes as ast
from .includes import IncludeTracker


class _EmitterError(Exception):
    """Raised when the emitter encounters a fatal structural conflict (e.g. E023)."""
    pass

# ═══════════════════════════════════════════════════════════════════════════════
# PRIMITIVE TYPE MAP
# ═══════════════════════════════════════════════════════════════════════════════

_PRIM_TYPE_MAP = {
    "i8":  "int8_t",
    "i16": "int16_t",
    "int": "int32_t",
    "i64": "int64_t",
    "u8":  "uint8_t",
    "u16": "uint16_t",
    "u32": "uint32_t",
    "u64": "uint64_t",
    "float": "float",
    "f64": "double",
    "chr": "char",
    "str": "std::string",
    "bool": "bool",
    "void": "void",
}

_NEED_CSTDINT = {"i8", "i16", "int", "i64", "u8", "u16", "u32", "u64"}

# Built-in collection name → (C++ template, include feature)
_BUILTIN_COLLECTION_MAP = {
    "Map":    ("std::map",            "map"),
    "Set":    ("std::unordered_set",  "unordered_set"),
    "Deque":  ("std::deque",          "deque"),
    "PQueue": (None,                  "queue"),  # special-cased
}


# ═══════════════════════════════════════════════════════════════════════════════
# EMITTER
# ═══════════════════════════════════════════════════════════════════════════════

class Emitter:
    """Walk an AILang AST and produce C++20 source code."""

    def __init__(self, source_filename: str) -> None:
        self.includes = IncludeTracker()
        self.source_filename = source_filename
        self._indent = 0
        self._output: List[str] = []
        self._temp_counter = 0
        self._in_class = False  # Track whether we're inside a class body

    # ── helpers ────────────────────────────────────────────────────────────

    def _next_temp(self, prefix: str = "_tmp") -> str:
        self._temp_counter += 1
        return f"{prefix}{self._temp_counter}"

    def _line(self, text: str) -> None:
        """Emit an indented line."""
        self._output.append("    " * self._indent + text)

    def _blank(self) -> None:
        self._output.append("")

    def _indent_inc(self) -> None:
        self._indent += 1

    def _indent_dec(self) -> None:
        self._indent -= 1

    # ── public entry point ─────────────────────────────────────────────────

    # ── top-level classification ─────────────────────────────────────────

    # Node types that are always emitted at file scope (outside any function).
    _GLOBAL_NODES = (ast.VarDecl, ast.MultiVarDecl, ast.FuncDecl,
                     ast.ClassDecl, ast.EnumDecl, ast.ImportStmt)

    # Node types that represent executable code requiring an entry point.
    _EXECUTABLE_NODES = (ast.ExprStmt, ast.AssignmentStmt)

    @staticmethod
    def _classify_top_level(program: ast.Program):
        """Split top-level statements into globals and executables."""
        globals_: List[ast.StmtNode] = []
        executables: List[ast.StmtNode] = []
        for node in program.statements:
            if isinstance(node, Emitter._GLOBAL_NODES):
                globals_.append(node)
            elif isinstance(node, Emitter._EXECUTABLE_NODES):
                executables.append(node)
            else:
                # Anything else (if/loop/etc at top-level) treated as executable
                executables.append(node)
        return globals_, executables

    def emit(self, program: ast.Program) -> str:
        """Walk the AST and produce a complete C++20 source string."""
        globals_, executables = self._classify_top_level(program)

        has_explicit_main = any(
            isinstance(n, ast.FuncDecl) and n.name == "main"
            for n in globals_
        )

        # Phase 1: emit imports (also registers includes)
        import_lines: List[str] = []
        namespace_lines: List[str] = []
        for imp in program.imports:
            self._emit_import(imp, import_lines, namespace_lines)
        
        # Deduplicate namespace lines
        namespace_lines = list(dict.fromkeys(namespace_lines))

        # Phase 2: emit global declarations into a buffer
        #   Order: global vars → enums → classes → non-main functions → explicit main
        global_buf: List[str] = []
        main_buf: List[str] = []
        save = self._output

        self._output = global_buf
        for node in globals_:
            if isinstance(node, ast.FuncDecl) and node.name == "main":
                # Defer explicit main() — emit it last
                self._output = main_buf
                self._emit_main_func(node)
                self._blank()
                self._output = global_buf
            else:
                self._emit_stmt(node)
                self._blank()
        self._output = save

        # Phase 3: handle executables
        exec_buf: List[str] = []
        is_library_mode = False

        if executables and has_explicit_main:
            # E023: conflict — both top-level executables and explicit main()
            from .errors import ErrorCode, TranspilerError as _TE
            first_exec = executables[0]
            raise _EmitterError(
                f"E023: top-level executable statements cannot coexist "
                f"with explicit main() [line {first_exec.line}:{first_exec.col}]"
            )
        elif executables and not has_explicit_main:
            # Auto-generate main() wrapping executables
            self._output = exec_buf
            self._line("int main() {")
            self._indent_inc()
            for stmt in executables:
                self._emit_stmt(stmt)
            # Auto return 0 if last statement is not a return
            if not executables or not isinstance(executables[-1], ast.ReturnStmt):
                self._blank()
                self._line("return 0;")
            self._indent_dec()
            self._line("}")
            self._output = save
        elif not executables and not has_explicit_main:
            is_library_mode = True

        # Phase 4: assemble final output
        final: List[str] = []
        final.append(f"// Auto-generated by AILang transpiler")
        final.append(f"// Source: {self.source_filename}")

        if is_library_mode:
            final.append("// Note: no entry point — library mode")

        final.append("")

        inc_block = self.includes.emit()
        if inc_block:
            final.append(inc_block)
            final.append("")

        if namespace_lines:
            final.extend(namespace_lines)
            final.append("")

        if global_buf:
            final.extend(global_buf)

        if main_buf:
            final.extend(main_buf)

        if exec_buf:
            final.extend(exec_buf)
            final.append("")

        return "\n".join(final)

    # ═══════════════════════════════════════════════════════════════════════
    # TYPE EMISSION
    # ═══════════════════════════════════════════════════════════════════════

    def _emit_type(self, t: ast.TypeNode) -> str:
        """Convert an AILang TypeNode to a C++ type string and register includes."""
        if isinstance(t, ast.PrimitiveType):
            cpp = _PRIM_TYPE_MAP.get(t.name, t.name)
            if t.name in _NEED_CSTDINT:
                self.includes.need("cstdint")
            if t.name == "str":
                self.includes.need("string")
            return cpp

        if isinstance(t, ast.ArrayType):
            elem = self._emit_type(t.element_type)
            if t.size is not None:
                # [T, N] where N is literal → std::array
                if isinstance(t.size, ast.LiteralExpr):
                    self.includes.need("array")
                    return f"std::array<{elem}, {self._emit_expr(t.size)}>"
                else:
                    # N is an ident → std::vector (dynamically sized)
                    self.includes.need("vector")
                    return f"std::vector<{elem}>"
            else:
                self.includes.need("vector")
                return f"std::vector<{elem}>"

        if isinstance(t, ast.MapType):
            k = self._emit_type(t.key_type)
            v = self._emit_type(t.value_type)
            self.includes.need("unordered_map")
            return f"std::unordered_map<{k}, {v}>"

        if isinstance(t, ast.TupleType):
            self.includes.need("tuple")
            elems = ", ".join(self._emit_type(et) for et in t.element_types)
            return f"std::tuple<{elems}>"

        if isinstance(t, ast.OptionalType):
            self.includes.need("optional")
            inner = self._emit_type(t.inner_type)
            return f"std::optional<{inner}>"

        if isinstance(t, ast.BuiltinCollectionType):
            info = _BUILTIN_COLLECTION_MAP.get(t.collection)
            if info:
                cpp_tpl, feature = info
                self.includes.need(feature)
                if t.collection == "PQueue":
                    self.includes.need("vector")
                    self.includes.need("functional")
                    inner = self._emit_type(t.type_args[0])
                    return (f"std::priority_queue<{inner}, "
                            f"std::vector<{inner}>, std::greater<{inner}>>")
                args = ", ".join(self._emit_type(a) for a in t.type_args)
                return f"{cpp_tpl}<{args}>"
            # Unknown collection – fall through to user type style
            args = ", ".join(self._emit_type(a) for a in t.type_args)
            return f"{t.collection}<{args}>"

        if isinstance(t, ast.GenericType):
            args = ", ".join(self._emit_type(a) for a in t.type_args)
            return f"{t.name}<{args}>"

        if isinstance(t, ast.UserType):
            return t.name

        return "auto"  # fallback

    # ═══════════════════════════════════════════════════════════════════════
    # EXPRESSION EMISSION
    # ═══════════════════════════════════════════════════════════════════════

    def _emit_expr(self, e: ast.ExprNode) -> str:  # noqa: C901
        """Convert an expression node to a C++ expression string."""
        if isinstance(e, ast.LiteralExpr):
            return self._emit_literal(e)

        if isinstance(e, ast.IdentExpr):
            # self → *this  (though usually self.x is DotExpr)
            if e.name == "self":
                return "(*this)"
            return e.name

        if isinstance(e, ast.BinaryExpr):
            left = self._emit_expr(e.left)
            right = self._emit_expr(e.right)
            op = e.op
            # AILang uses 'and', 'or' keywords; map to C++ operators
            if op == "and":
                op = "&&"
            elif op == "or":
                op = "||"
            return f"{left} {op} {right}"

        if isinstance(e, ast.ChainedCompareExpr):
            parts: List[str] = []
            for i, op in enumerate(e.operators):
                left = self._emit_expr(e.operands[i])
                right = self._emit_expr(e.operands[i + 1])
                parts.append(f"{left} {op} {right}")
            return " && ".join(parts)

        if isinstance(e, ast.UnaryExpr):
            operand = self._emit_expr(e.operand)
            return f"{e.op}{operand}"

        if isinstance(e, ast.CallExpr):
            callee = self._emit_expr(e.callee)
            if callee in ("print", "println"):
                self.includes.need("iostream")
                if not e.args:
                    return "std::cout << std::endl"
                args = " << ".join(self._emit_expr(a) for a in e.args)
                return f"std::cout << {args} << std::endl"

            args = ", ".join(self._emit_expr(a) for a in e.args)
            return f"{callee}({args})"

        if isinstance(e, ast.IndexExpr):
            obj = self._emit_expr(e.obj)
            idx = self._emit_expr(e.index)
            return f"{obj}[{idx}]"

        if isinstance(e, ast.DotExpr):
            # self.field → this->field
            if isinstance(e.obj, ast.IdentExpr) and e.obj.name == "self":
                return f"this->{e.attr}"
            obj = self._emit_expr(e.obj)
            return f"{obj}.{e.attr}"

        if isinstance(e, ast.PropagateExpr):
            # This is typically handled at statement level; if used inline,
            # produce the temporary pattern inline (not ideal, but safe)
            inner = self._emit_expr(e.expr)
            return inner  # caller should use _emit_propagate for full pattern

        if isinstance(e, ast.AwaitExpr):
            inner = self._emit_expr(e.expr)
            return f"{inner}.get()"

        if isinstance(e, ast.LambdaExpr):
            return self._emit_lambda(e)

        if isinstance(e, ast.TupleLiteral):
            self.includes.need("tuple")
            elems = ", ".join(self._emit_expr(el) for el in e.elements)
            return f"std::make_tuple({elems})"

        if isinstance(e, ast.ArrayLiteral):
            self.includes.need("vector")
            elems = ", ".join(self._emit_expr(el) for el in e.elements)
            return "{" + elems + "}"

        if isinstance(e, ast.MapLiteral):
            self.includes.need("unordered_map")
            entries = ", ".join(
                f"{{{self._emit_expr(k)}, {self._emit_expr(v)}}}"
                for k, v in e.entries
            )
            return "{" + entries + "}"

        if isinstance(e, ast.SizedVectorLiteral):
            self.includes.need("vector")
            sz = self._emit_expr(e.size_expr)
            if e.fill_value is not None:
                fill = self._emit_expr(e.fill_value)
                return f"std::vector({sz}, {fill})"
            return f"std::vector<int32_t>({sz})"

        if isinstance(e, ast.StringInterp):
            return self._emit_string_interp(e)

        if isinstance(e, ast.GroupedExpr):
            inner = self._emit_expr(e.expr)
            return f"({inner})"

        return f"/* UNKNOWN_EXPR */"

    def _emit_literal(self, lit: ast.LiteralExpr) -> str:
        if lit.literal_type == "bool":
            return "true" if lit.value else "false"
        if lit.literal_type == "string":
            # Escape for C++ string literal
            escaped = (str(lit.value)
                       .replace("\\", "\\\\")
                       .replace('"', '\\"')
                       .replace("\n", "\\n")
                       .replace("\t", "\\t"))
            self.includes.need("string")
            return f'"{escaped}"'
        if lit.literal_type == "float":
            s = repr(lit.value)
            # Ensure it has a decimal point
            if "." not in s and "e" not in s and "E" not in s:
                s += ".0"
            return s
        # int
        return str(lit.value)

    def _emit_lambda(self, lam: ast.LambdaExpr) -> str:
        params = ", ".join(
            f"auto {p}" if p != "_" else "auto"
            for p in lam.params
        )
        body = self._emit_expr(lam.body)
        # Heuristic: use [&] if body references names not in params
        capture = self._lambda_capture(lam)
        return f"[{capture}]({params}){{ return {body}; }}"

    def _lambda_capture(self, lam: ast.LambdaExpr) -> str:
        """Determine capture clause for a lambda."""
        param_set = set(lam.params)
        refs = self._collect_idents(lam.body)
        if refs - param_set:
            return "&"
        return ""

    def _collect_idents(self, e: ast.ExprNode) -> set:
        """Recursively collect all IdentExpr names from an expression."""
        names: set = set()
        if isinstance(e, ast.IdentExpr):
            names.add(e.name)
        elif isinstance(e, ast.BinaryExpr):
            names |= self._collect_idents(e.left)
            names |= self._collect_idents(e.right)
        elif isinstance(e, ast.UnaryExpr):
            names |= self._collect_idents(e.operand)
        elif isinstance(e, ast.CallExpr):
            names |= self._collect_idents(e.callee)
            for a in e.args:
                names |= self._collect_idents(a)
        elif isinstance(e, ast.DotExpr):
            names |= self._collect_idents(e.obj)
        elif isinstance(e, ast.IndexExpr):
            names |= self._collect_idents(e.obj)
            names |= self._collect_idents(e.index)
        elif isinstance(e, ast.GroupedExpr):
            names |= self._collect_idents(e.expr)
        elif isinstance(e, ast.ChainedCompareExpr):
            for op in e.operands:
                names |= self._collect_idents(op)
        elif isinstance(e, ast.TupleLiteral):
            for el in e.elements:
                names |= self._collect_idents(el)
        elif isinstance(e, ast.ArrayLiteral):
            for el in e.elements:
                names |= self._collect_idents(el)
        elif isinstance(e, ast.PropagateExpr):
            names |= self._collect_idents(e.expr)
        elif isinstance(e, ast.AwaitExpr):
            names |= self._collect_idents(e.expr)
        elif isinstance(e, ast.SizedVectorLiteral):
            names |= self._collect_idents(e.size_expr)
            if e.fill_value:
                names |= self._collect_idents(e.fill_value)
        elif isinstance(e, ast.StringInterp):
            for p in e.parts:
                if not isinstance(p, str):
                    names |= self._collect_idents(p)
        elif isinstance(e, ast.MapLiteral):
            for k, v in e.entries:
                names |= self._collect_idents(k)
                names |= self._collect_idents(v)
        return names

    def _emit_string_interp(self, si: ast.StringInterp) -> str:
        self.includes.need("sstream")
        parts: List[str] = []
        for p in si.parts:
            if isinstance(p, str):
                escaped = (p.replace("\\", "\\\\")
                            .replace('"', '\\"')
                            .replace("\n", "\\n")
                            .replace("\t", "\\t"))
                parts.append(f'"{escaped}"')
            else:
                parts.append(f"({self._emit_expr(p)})")
        chain = " << ".join(parts)
        return f"([&](){{ std::ostringstream _ss; _ss << {chain}; return _ss.str(); }}())"

    # ═══════════════════════════════════════════════════════════════════════
    # STATEMENT EMISSION
    # ═══════════════════════════════════════════════════════════════════════

    def _emit_stmt(self, stmt: ast.StmtNode) -> None:  # noqa: C901
        """Emit a single statement."""
        if isinstance(stmt, ast.VarDecl):
            self._emit_var_decl(stmt)
        elif isinstance(stmt, ast.MultiVarDecl):
            self._emit_multi_var_decl(stmt)
        elif isinstance(stmt, ast.AssignmentStmt):
            self._emit_assignment(stmt)
        elif isinstance(stmt, ast.FuncDecl):
            self._emit_func_decl(stmt)
        elif isinstance(stmt, ast.ClassDecl):
            self._emit_class_decl(stmt)
        elif isinstance(stmt, ast.EnumDecl):
            self._emit_enum_decl(stmt)
        elif isinstance(stmt, ast.IfStmt):
            self._emit_if_stmt(stmt)
        elif isinstance(stmt, ast.LoopStmt):
            self._emit_loop_stmt(stmt)
        elif isinstance(stmt, ast.ForRangeStmt):
            self._emit_for_range(stmt)
        elif isinstance(stmt, ast.ForEachStmt):
            self._emit_for_each(stmt)
        elif isinstance(stmt, ast.ForMapStmt):
            self._emit_for_map(stmt)
        elif isinstance(stmt, ast.MatchStmt):
            self._emit_match(stmt)
        elif isinstance(stmt, ast.ReturnStmt):
            self._emit_return(stmt)
        elif isinstance(stmt, ast.BreakStmt):
            self._line("break;")
        elif isinstance(stmt, ast.ContinueStmt):
            self._line("continue;")
        elif isinstance(stmt, ast.ThrowStmt):
            val = self._emit_expr(stmt.value)
            self._line(f"throw {val};")
        elif isinstance(stmt, ast.TryStmt):
            self._emit_try(stmt)
        elif isinstance(stmt, ast.ExprStmt):
            self._emit_expr_stmt(stmt)
        else:
            self._line(f"/* UNHANDLED STMT: {type(stmt).__name__} */")

    # ── imports ────────────────────────────────────────────────────────────

    def _emit_import(self, imp: ast.ImportStmt, import_lines: List[str],
                     ns_lines: List[str]) -> None:
        mod_path = ".".join(imp.module_path)
        headers = self.includes.need_module(mod_path)
        if headers is None:
            # Unknown module → emit TODO comment
            import_lines.append(f"// TODO: #include <{'/'.join(imp.module_path)}>")

        if imp.alias == "*":
            # use std.math as * → using namespace std;
            ns_lines.append("using namespace std;")
        elif imp.alias is not None:
            # use std.math as m → namespace m = std;
            ns_lines.append(f"namespace {imp.alias} = std;")

    # ── variable declarations ──────────────────────────────────────────────

    def _emit_var_decl(self, v: ast.VarDecl) -> None:
        val = self._emit_expr(v.value)
        is_file_scope = self._indent == 0 and not self._in_class

        if v.type is not None:
            cpp_type = self._emit_type(v.type)
            if v.mutable:
                if v.exported and is_file_scope:
                    self._line(f"inline {cpp_type} {v.name} = {val};")
                else:
                    self._line(f"{cpp_type} {v.name} = {val};")
            else:
                if v.exported and is_file_scope:
                    self._line(f"inline const {cpp_type} {v.name} = {val};")
                else:
                    self._line(f"const {cpp_type} {v.name} = {val};")
        else:
            if v.mutable:
                if v.exported and is_file_scope:
                    self._line(f"inline auto {v.name} = {val};")
                else:
                    self._line(f"auto {v.name} = {val};")
            else:
                if v.exported and is_file_scope:
                    self._line(f"inline const auto {v.name} = {val};")
                else:
                    self._line(f"const auto {v.name} = {val};")

    def _emit_multi_var_decl(self, mv: ast.MultiVarDecl) -> None:
        # Check if single-value RHS (tuple destructuring)
        if len(mv.values) == 1 and len(mv.targets) > 1:
            # Tuple destructuring: first, _, last = tup
            tup_expr = self._emit_expr(mv.values[0])
            self.includes.need("tuple")
            for i, tgt in enumerate(mv.targets):
                if tgt.name == "_":
                    continue
                cpp_type = self._emit_type(tgt.type) if tgt.type else "auto"
                const = "" if mv.mutable else "const "
                self._line(f"{const}{cpp_type} {tgt.name} = std::get<{i}>({tup_expr});")
        else:
            # Parallel assignment: x, y, z := 1, 2, 3
            for tgt, val_node in zip(mv.targets, mv.values):
                if tgt.name == "_":
                    continue
                val = self._emit_expr(val_node)
                if tgt.type is not None:
                    cpp_type = self._emit_type(tgt.type)
                    const = "" if mv.mutable else "const "
                    self._line(f"{const}{cpp_type} {tgt.name} = {val};")
                else:
                    const = "" if mv.mutable else "const "
                    self._line(f"{const}auto {tgt.name} = {val};")

    # ── assignment ─────────────────────────────────────────────────────────

    def _emit_assignment(self, a: ast.AssignmentStmt) -> None:
        target = self._emit_expr(a.target)
        val = self._emit_expr(a.value)
        self._line(f"{target} {a.op} {val};")

    # ── functions ──────────────────────────────────────────────────────────

    def _emit_func_decl(self, f: ast.FuncDecl) -> None:
        # Return type
        if f.return_type is not None:
            ret = self._emit_type(f.return_type)
        else:
            ret = "void"

        # Async wrapping
        if f.is_async:
            self.includes.need("future")
            ret = f"std::future<{ret}>"

        # Parameters
        params = ", ".join(
            f"{self._emit_type(p.type)} {p.name}" for p in f.params
        )

        if f.is_arrow:
            # Single-expression body: square(x:int) -> int => x*x
            assert len(f.body) == 1
            body_stmt = f.body[0]
            body_expr = self._extract_expr(body_stmt)
            expr_str = self._emit_expr(body_expr)
            if f.is_async:
                self._line(f"{ret} {f.name}({params}) {{")
                self._indent_inc()
                self._line(f"return std::async(std::launch::async, [&]() {{")
                self._indent_inc()
                self._line(f"return {expr_str};")
                self._indent_dec()
                self._line("});")
                self._indent_dec()
                self._line("}")
            else:
                self._line(f"{ret} {f.name}({params}) {{ return {expr_str}; }}")
        else:
            # Block body
            self._line(f"{ret} {f.name}({params}) {{")
            self._indent_inc()
            if f.is_async:
                self._line("return std::async(std::launch::async, [&]() {")
                self._indent_inc()
                self._emit_func_body(f.body, has_return_type=(f.return_type is not None))
                self._indent_dec()
                self._line("});")
            else:
                self._emit_func_body(f.body, has_return_type=(f.return_type is not None))
            self._indent_dec()
            self._line("}")

    def _emit_func_body(self, body: List[ast.StmtNode], has_return_type: bool) -> None:
        """Emit function body statements with implicit return on the last expression."""
        if not body:
            return
        for stmt in body[:-1]:
            self._emit_stmt(stmt)
        # Last statement: implicit return if it's an ExprStmt and function has return type
        last = body[-1]
        if has_return_type and isinstance(last, ast.ExprStmt):
            val = self._emit_expr(last.expr)
            self._line(f"return {val};")
        else:
            self._emit_stmt(last)

    @staticmethod
    def _extract_expr(stmt: ast.StmtNode) -> ast.ExprNode:
        """Extract the expression from an ExprStmt or return the node itself."""
        if isinstance(stmt, ast.ExprStmt):
            return stmt.expr
        if isinstance(stmt, ast.ReturnStmt) and stmt.value is not None:
            return stmt.value
        # Shouldn't happen for well-formed arrow functions
        return stmt  # type: ignore[return-value]

    # ── explicit main() ────────────────────────────────────────────────────

    def _emit_main_func(self, f: ast.FuncDecl) -> None:
        """Emit an explicit main() function with proper C++ signatures.

        Handles these AILang signatures:
          main()              → int main()
          main() -> int       → int main()
          main(args:[str])    → int main(int argc, char* argv[])
                                  + std::vector<std::string> args(argv, argv + argc);
          main(args:[str]) -> int  → same as above
        """
        has_args = len(f.params) > 0

        if has_args:
            self.includes.need("vector")
            self.includes.need("string")
            self._line("int main(int argc, char* argv[]) {")
            self._indent_inc()
            # Build the vector<string> from argv
            arg_name = f.params[0].name if f.params[0].name != "_" else "args"
            self._line(f"std::vector<std::string> {arg_name}(argv, argv + argc);")
        else:
            self._line("int main() {")
            self._indent_inc()

        # Emit body with implicit return on last ExprStmt
        self._emit_func_body(f.body, has_return_type=True)

        # Auto append return 0 if the last statement is not a return
        if not f.body or not isinstance(f.body[-1], (ast.ReturnStmt, ast.ExprStmt)):
            self._line("return 0;")

        self._indent_dec()
        self._line("}")

    # ── classes ────────────────────────────────────────────────────────────

    def _emit_class_decl(self, cls: ast.ClassDecl) -> None:
        # Template parameters
        if cls.generics:
            tparams = ", ".join(f"typename {g}" for g in cls.generics)
            self._line(f"template<{tparams}>")

        self._line(f"class {cls.name} {{")

        # Separate public / private members
        public_members: List[ast.VarDecl | ast.FuncDecl] = []
        private_members: List[ast.VarDecl | ast.FuncDecl] = []

        for m in cls.members:
            if isinstance(m, ast.VarDecl) and m.exported:
                public_members.append(m)
            elif isinstance(m, ast.FuncDecl) and m.exported:
                public_members.append(m)
            elif isinstance(m, ast.FuncDecl):
                # Methods default to public in AILang
                public_members.append(m)
            elif isinstance(m, ast.VarDecl) and not m.exported:
                # Fields default to public unless explicitly private
                public_members.append(m)
            else:
                private_members.append(m)

        prev_in_class = self._in_class
        self._in_class = True

        if public_members:
            self._line("public:")
            self._indent_inc()
            for m in public_members:
                if isinstance(m, ast.VarDecl):
                    self._emit_class_field(m)
                elif isinstance(m, ast.FuncDecl):
                    self._emit_func_decl(m)
                    self._blank()
            self._indent_dec()

        if private_members:
            self._line("private:")
            self._indent_inc()
            for m in private_members:
                if isinstance(m, ast.VarDecl):
                    self._emit_class_field(m)
                elif isinstance(m, ast.FuncDecl):
                    self._emit_func_decl(m)
                    self._blank()
            self._indent_dec()

        self._in_class = prev_in_class
        self._line("};")

    def _emit_class_field(self, v: ast.VarDecl) -> None:
        val = self._emit_expr(v.value)
        if v.type is not None:
            cpp_type = self._emit_type(v.type)
            self._line(f"{cpp_type} {v.name} = {val};")
        else:
            self._line(f"auto {v.name} = {val};")

    # ── enums ──────────────────────────────────────────────────────────────

    def _emit_enum_decl(self, en: ast.EnumDecl) -> None:
        has_payloads = any(v.fields for v in en.variants)
        if not has_payloads:
            # Simple enum → enum class
            variants = ", ".join(v.name for v in en.variants)
            self._line(f"enum class {en.name} {{ {variants} }};")
        else:
            # Payload enum → structs + variant
            self.includes.need("variant")
            for v in en.variants:
                if v.fields:
                    field_decls = "; ".join(
                        f"{self._emit_type(ft)} {self._gen_field_name(i)}"
                        for i, ft in enumerate(v.fields)
                    )
                    self._line(f"struct {v.name} {{ {field_decls}; }};")
                else:
                    self._line(f"struct {v.name} {{}};")
            variant_types = ", ".join(v.name for v in en.variants)
            self._line(f"using {en.name} = std::variant<{variant_types}>;")

    @staticmethod
    def _gen_field_name(index: int) -> str:
        """Generate struct field names for enum payloads: r, w, h, f0, f1, ..."""
        if index < 26:
            return chr(ord('a') + index)
        return f"f{index}"

    # ── if/elif/else ───────────────────────────────────────────────────────

    def _emit_if_stmt(self, s: ast.IfStmt) -> None:
        cond = self._emit_expr(s.condition)
        self._line(f"if ({cond}) {{")
        self._indent_inc()
        for stmt in s.body:
            self._emit_stmt(stmt)
        self._indent_dec()
        self._line("}")

        for elif_clause in s.elifs:
            econd = self._emit_expr(elif_clause.condition)
            self._line(f"else if ({econd}) {{")
            self._indent_inc()
            for stmt in elif_clause.body:
                self._emit_stmt(stmt)
            self._indent_dec()
            self._line("}")

        if s.else_body is not None:
            self._line("else {")
            self._indent_inc()
            for stmt in s.else_body:
                self._emit_stmt(stmt)
            self._indent_dec()
            self._line("}")

    # ── loops ──────────────────────────────────────────────────────────────

    def _emit_loop_stmt(self, s: ast.LoopStmt) -> None:
        if s.condition is not None:
            cond = self._emit_expr(s.condition)
            self._line(f"while ({cond}) {{")
        else:
            self._line("while (true) {")
        self._indent_inc()
        for stmt in s.body:
            self._emit_stmt(stmt)
        self._indent_dec()
        self._line("}")

    def _emit_for_range(self, s: ast.ForRangeStmt) -> None:
        self.includes.need("cstdint")
        start = self._emit_expr(s.start)
        end = self._emit_expr(s.end)
        var = s.var_name if s.var_name != "_" else "_"
        if s.step is not None:
            step = self._emit_expr(s.step)
            self._line(f"for (int32_t {var} = {start}; {var} < {end}; {var} += {step}) {{")
        else:
            self._line(f"for (int32_t {var} = {start}; {var} < {end}; {var}++) {{")
        self._indent_inc()
        for stmt in s.body:
            self._emit_stmt(stmt)
        self._indent_dec()
        self._line("}")

    def _emit_for_each(self, s: ast.ForEachStmt) -> None:
        iterable = self._emit_expr(s.iterable)
        self._line(f"for (auto& {s.var_name} : {iterable}) {{")
        self._indent_inc()
        for stmt in s.body:
            self._emit_stmt(stmt)
        self._indent_dec()
        self._line("}")

    def _emit_for_map(self, s: ast.ForMapStmt) -> None:
        iterable = self._emit_expr(s.iterable)
        self._line(f"for (auto& [{s.key_name}, {s.value_name}] : {iterable}) {{")
        self._indent_inc()
        for stmt in s.body:
            self._emit_stmt(stmt)
        self._indent_dec()
        self._line("}")

    # ── match ──────────────────────────────────────────────────────────────

    def _emit_match(self, m: ast.MatchStmt) -> None:
        # Determine if this is an enum-destructuring match or a literal/switch match
        has_destructure = any(
            isinstance(p, ast.DestructurePattern)
            for arm in m.arms for p in arm.patterns
        )

        if has_destructure:
            self._emit_match_variant(m)
        else:
            self._emit_match_switch(m)

    def _emit_match_switch(self, m: ast.MatchStmt) -> None:
        expr = self._emit_expr(m.expr)
        self._line(f"switch ({expr}) {{")
        self._indent_inc()
        for arm in m.arms:
            for pat in arm.patterns:
                if isinstance(pat, ast.WildcardPattern):
                    self._line("default:")
                elif isinstance(pat, ast.LiteralPattern):
                    val = self._emit_expr(pat.value)
                    self._line(f"case {val}:")
            self._line("{")
            self._indent_inc()
            for stmt in arm.body:
                self._emit_stmt(stmt)
            self._indent_dec()
            self._line("} break;")
        if m.eof_arm is not None:
            self._line("default:")
            self._line("{")
            self._indent_inc()
            for stmt in m.eof_arm.body:
                self._emit_stmt(stmt)
            self._indent_dec()
            self._line("} break;")
        self._indent_dec()
        self._line("}")

    def _emit_match_variant(self, m: ast.MatchStmt) -> None:
        self.includes.need("variant")
        expr = self._emit_expr(m.expr)
        self._line(f"std::visit([&](auto&& _arg) {{")
        self._indent_inc()
        self._line("using T = std::decay_t<decltype(_arg)>;")
        first = True
        for arm in m.arms:
            for pat in arm.patterns:
                if isinstance(pat, ast.DestructurePattern):
                    keyword = "if constexpr" if first else "else if constexpr"
                    self._line(f"{keyword} (std::is_same_v<T, {pat.name}>) {{")
                    self._indent_inc()
                    # Bind fields
                    for i, fname in enumerate(pat.fields):
                        if fname != "_":
                            field_accessor = self._gen_field_name(i)
                            self._line(f"auto {fname} = _arg.{field_accessor};")
                    for stmt in arm.body:
                        self._emit_stmt(stmt)
                    self._indent_dec()
                    self._line("}")
                    first = False
                elif isinstance(pat, ast.WildcardPattern):
                    # Default case for variant — use else
                    if not first:
                        self._line("else {")
                    else:
                        self._line("{")
                    self._indent_inc()
                    for stmt in arm.body:
                        self._emit_stmt(stmt)
                    self._indent_dec()
                    self._line("}")
                    first = False
        if m.eof_arm is not None:
            if not first:
                self._line("else {")
            else:
                self._line("{")
            self._indent_inc()
            for stmt in m.eof_arm.body:
                self._emit_stmt(stmt)
            self._indent_dec()
            self._line("}")
        self._indent_dec()
        self._line(f"}}, {expr});")

    # ── return ─────────────────────────────────────────────────────────────

    def _emit_return(self, r: ast.ReturnStmt) -> None:
        if r.value is not None:
            val = self._emit_expr(r.value)
            self._line(f"return {val};")
        else:
            self._line("return;")

    # ── try/catch ──────────────────────────────────────────────────────────

    def _emit_try(self, t: ast.TryStmt) -> None:
        self._line("try {")
        self._indent_inc()
        for stmt in t.body:
            self._emit_stmt(stmt)
        self._indent_dec()
        self._line("}")
        for c in t.catches:
            self._emit_catch(c)

    def _emit_catch(self, c: ast.CatchClause) -> None:
        if c.type is None and c.name is None:
            # catch-all
            self._line("catch (...) {")
        elif c.type is not None and c.name is not None:
            ctype = self._emit_type(c.type)
            self._line(f"catch (const {ctype}& {c.name}) {{")
        elif c.type is not None:
            ctype = self._emit_type(c.type)
            self._line(f"catch (const {ctype}&) {{")
        else:
            self._line("catch (...) {")
        self._indent_inc()
        for stmt in c.body:
            self._emit_stmt(stmt)
        self._indent_dec()
        self._line("}")

    # ── expression statement ───────────────────────────────────────────────

    def _emit_expr_stmt(self, es: ast.ExprStmt) -> None:
        # Check for error propagation at statement level
        if isinstance(es.expr, ast.PropagateExpr):
            self._emit_propagate(es.expr)
            return

        val = self._emit_expr(es.expr)
        self._line(f"{val};")

    def _emit_propagate(self, prop: ast.PropagateExpr) -> None:
        """Error propagation: expr? → temp + check + unwrap."""
        self.includes.need("expected")
        inner = self._emit_expr(prop.expr)
        tmp = self._next_temp("_res_")
        self._line(f"auto {tmp} = {inner};")
        self._line(f"if (!{tmp}) return std::unexpected({tmp}.error());")
        self._line(f"auto _val = *{tmp};")


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL API
# ═══════════════════════════════════════════════════════════════════════════════

def emit(program: ast.Program, source_filename: str = "input.ail") -> str:
    """Walk the AST and produce a complete C++20 source string with includes.

    This is the main entry point for the emitter module.

    Args:
        program: The parsed AST ``Program`` node.
        source_filename: The original source file name (used in a header comment).

    Returns:
        A complete C++20 source string ready to be written to a ``.cpp`` file.
    """
    emitter = Emitter(source_filename)
    return emitter.emit(program)
