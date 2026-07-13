"""
Parser module for AILang.
Uses Lark to parse the preprocessed source into an AST.
"""

from typing import Optional, List, Union
import lark
from lark import Lark, Transformer, Token, Tree

from ailang import ast_nodes as ast
from ailang.errors import ErrorCollector, ErrorCode

# The grammar expects INDENT/DEDENT to be actual tokens injected by the lexer.
GRAMMAR = r"""
    ?start: program

    program: _NL* (statement_item (_NL+ statement_item)*)? _NL*
    ?statement_item: import_stmt | statement

    // Imports
    import_stmt: "use" module_path
               | "use" module_path "as" IDENTIFIER  -> import_alias
               | "use" module_path "as" "*"         -> import_star
    
    module_path: IDENTIFIER ("." IDENTIFIER)*

    // Statements
    ?statement: var_decl
              | multi_var_decl
              | assignment_stmt
              | func_decl
              | class_decl
              | enum_decl
              | if_stmt
              | loop_stmt
              | for_stmt
              | match_stmt
              | return_stmt
              | break_stmt
              | continue_stmt
              | throw_stmt
              | try_stmt
              | expr_stmt

    var_decl: [exp_mod] IDENTIFIER [":" type] assign_decl expression

    multi_var_decl: [exp_mod] multi_var_lhs assign_decl expr_list
    multi_var_lhs: multi_var_target ("," multi_var_target)*
    multi_var_target: ("_" | IDENTIFIER) [":" type]

    assign_decl: ":=" -> mut
               | "="  -> immut

    exp_mod: "exp" -> exp

    assignment_stmt: postfix_expr assign_op expression
    !assign_op: "=" | "+=" | "-=" | "*=" | "/=" | "%="

    func_decl: [exp_mod] [async_mod] IDENTIFIER "(" [param_list] ")" ["->" type] func_body
    
    async_mod: "async" -> is_async
    ?func_body: ":" _NL block    -> func_body_block
              | "=>" expression  -> func_body_arrow
              | ":" statement    -> func_body_stmt

    param_list: param ("," param)*
    param: ("_" | IDENTIFIER) ":" type

    return_stmt: "return" [expression]
    break_stmt: "break"
    continue_stmt: "continue"
    throw_stmt: "throw" expression

    try_stmt: "try" ":" (_NL block | statement) (_NL* catch_clause)*
    catch_clause: "catch" [IDENTIFIER ":" type | type] ":" (_NL block | statement)

    class_decl: [exp_mod] "cls" IDENTIFIER ["[" generic_list "]"] ":" _NL _INDENT _NL* (class_member _NL*)* _DEDENT
    ?class_member: var_decl | func_decl
    generic_list: IDENTIFIER ("," IDENTIFIER)*

    enum_decl: [exp_mod] "enum" IDENTIFIER ":" _NL _INDENT _NL* (enum_variant _NL*)* _DEDENT
    enum_variant: IDENTIFIER ["(" type_list ")"]
    type_list: type ("," type)*

    block: _INDENT _NL* (statement (_NL+ statement)*)? _NL* _DEDENT

    if_stmt: "if" expression ":" (_NL block | statement) (_NL* elif_clause)* [_NL* "else" ":" (_NL block | statement)]
    elif_clause: "elif" expression ":" (_NL block | statement)

    loop_stmt: "loop" [expression] ":" (_NL block | statement)

    ?for_stmt: for_range_stmt | for_map_stmt | for_each_stmt

    // Disambiguation: for range requires ..
    for_range_stmt: "for" ("_" | IDENTIFIER) "in" expression ".." expression ["," expression] ":" (_NL block | statement)
    
    // Disambiguation: for map has comma before in
    for_map_stmt: "for" ("_" | IDENTIFIER) "," ("_" | IDENTIFIER) "in" expression ":" (_NL block | statement)
    
    for_each_stmt: "for" ("_" | IDENTIFIER) "in" expression ":" (_NL block | statement)

    match_stmt: "match" expression ":" _NL _INDENT _NL* (match_arm _NL*)* [eof_arm _NL*] _DEDENT
    match_arm: pattern ("|" pattern)* ":" (_NL block | statement)
    eof_arm: "EOF" ":" (_NL block | statement)

    ?pattern: "_" -> pat_wildcard
            | IDENTIFIER "(" [pattern_list] ")" -> pat_destructure
            | IDENTIFIER -> pat_ident
            | literal -> pat_literal
    pattern_list: ("_" | IDENTIFIER) ("," ("_" | IDENTIFIER))*

    expr_stmt: expression

    // Expressions (Lowest to Highest Precedence)
    ?expression: assignment_expr
    ?assignment_expr: logical_or
    
    ?logical_or: logical_and (OR_OP logical_and)*
    ?logical_and: bitwise_or (AND_OP bitwise_or)*
    ?bitwise_or: bitwise_xor (BOR_OP bitwise_xor)*
    ?bitwise_xor: bitwise_and (BXOR_OP bitwise_and)*
    ?bitwise_and: equality (BAND_OP equality)*
    
    ?equality: chained_comparison (EQ_OP chained_comparison)*
    
    ?chained_comparison: shift (COMP_OP shift)*
    
    ?shift: term (SHIFT_OP term)*
    
    ?term: factor (ADD_OP factor)*
    
    ?factor: unary (MUL_OP unary)*
    
    ?unary: "-" unary -> un_neg
          | "!" unary -> un_not
          | "~" unary -> un_bitnot
          | "await" unary -> un_await
          | postfix_expr

    ?postfix_expr: primary
                 | postfix_expr "." IDENTIFIER -> dot_expr
                 | postfix_expr "(" [expr_list] ")" -> call_expr
                 | postfix_expr "[" expression "]" -> index_expr
                 | postfix_expr "?" -> propagate_expr

    ?primary: literal
            | IDENTIFIER -> ident_expr
            | "_" -> ident_expr
            | lambda_expr
            | sized_vector_literal
            | array_literal
            | tuple_literal
            | map_literal
            | "(" expression ")" -> grouped_expr

    expr_list: expression ("," expression)*

    lambda_expr: "(" [lambda_params] ")" "=>" expression
    lambda_params: ("_" | IDENTIFIER) ("," ("_" | IDENTIFIER))*

    array_literal: "[" [expr_list] "]"
    tuple_literal: "(" expression "," [expr_list] ")" // at least one comma
    map_literal: "{" [map_entries] "}"
    map_entries: map_entry ("," map_entry)*
    map_entry: expression ":" expression

    // Disambiguation: sized vector vs factor
    // Grammar structure handles it cleanly: primary -> sized_vector_literal
    sized_vector_literal: expression "*" "[" (integer_literal | float_literal | "true" | "false" | IDENTIFIER)? "]"

    ?literal: integer_literal
            | float_literal
            | string_literal
            | "true" -> bool_true
            | "false" -> bool_false

    integer_literal: SIGNED_INT
    float_literal: FLOAT_TOK
    string_literal: ESCAPED_STRING // String interpolation handled in transformer

    // Types
    ?type: base_type ["?"] -> type_optional
    
    ?base_type: primitive_type
              | builtin_collection_type
              | array_type
              | map_type
              | tuple_type
              | generic_type
              | user_type

    !primitive_type: "i8"|"i16"|"int"|"i64" | "u8"|"u16"|"u32"|"u64" | "float"|"f64"|"chr"|"str"
    
    builtin_collection_type: "Map" "[" type "," type "]" -> builtin_map
                           | "Set" "[" type "]" -> builtin_set
                           | "Deque" "[" type "]" -> builtin_deque
                           | "PQueue" "[" type "]" -> builtin_pqueue
                           
    array_type: "[" type ["," (integer_literal | IDENTIFIER)] "]"
    map_type: "{" type ":" type "}"
    tuple_type: "(" type "," [type_list] ")"
    generic_type: IDENTIFIER "[" type_list "]"
    user_type: IDENTIFIER

    // Terminals
    IDENTIFIER: /[a-zA-Z_][a-zA-Z0-9_]*/
    _INDENT: "__INDENT__"
    _DEDENT: "__DEDENT__"
    _NL: /[\r\n]+/

    OR_OP: "||"
    AND_OP: "&&"
    BOR_OP: "|"
    BXOR_OP: "^"
    BAND_OP: "&"
    EQ_OP: "==" | "!="
    COMP_OP: "<" | ">" | "<=" | ">="
    SHIFT_OP: "<<" | ">>"
    ADD_OP: "+" | "-"
    MUL_OP: "*" | "/" | "%"

    FLOAT_TOK.2: SIGNED_FLOAT
    %import common.SIGNED_INT
    %import common.SIGNED_FLOAT
    %import common.ESCAPED_STRING
    %import common.WS_INLINE
    %ignore WS_INLINE
"""

class ASTTransformer(Transformer):
    def __init__(self):
        super().__init__()
    
    def _loc(self, meta_or_token) -> tuple:
        if isinstance(meta_or_token, Token):
            return meta_or_token.line, meta_or_token.column
        if hasattr(meta_or_token, 'line'):
            return meta_or_token.line, meta_or_token.column
        return 1, 1

    def program(self, items):
        imports = [i for i in items if isinstance(i, ast.ImportStmt)]
        stmts = [s for s in items if isinstance(s, tuple(ast.StmtNode.__args__))]
        return ast.Program(imports=imports, statements=stmts)

    # Imports
    def import_stmt(self, items):
        mod_path = items[0]
        line, col = self._loc(items[0]) if items else (1,1)
        return ast.ImportStmt(module_path=mod_path, alias=None, line=line, col=col)
    
    def import_alias(self, items):
        mod_path = items[0]
        alias = str(items[1])
        line, col = self._loc(items[0]) if items else (1,1)
        return ast.ImportStmt(module_path=mod_path, alias=alias, line=line, col=col)
    
    def import_star(self, items):
        mod_path = items[0]
        line, col = self._loc(items[0]) if items else (1,1)
        return ast.ImportStmt(module_path=mod_path, alias="*", line=line, col=col)

    def module_path(self, items):
        return [str(i) for i in items]

    # Statements
    def var_decl(self, items):
        exported = getattr(items[0], 'data', None) == 'exp'
        name_tok = items[1]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        typ = items[2]
        mutable = getattr(items[3], 'data', None) == 'mut'
        val = items[4]
        return ast.VarDecl(name=name, type=typ, mutable=mutable, exported=exported, value=val, line=line, col=col)

    def multi_var_decl(self, items):
        exported = getattr(items[0], 'data', None) == 'exp'
        targets = items[1]
        mutable = getattr(items[2], 'data', None) == 'mut'
        vals = items[3]
        line, col = targets[0].line, targets[0].col
        return ast.MultiVarDecl(targets=targets, mutable=mutable, exported=exported, values=vals, line=line, col=col)

    def multi_var_lhs(self, items):
        return items

    def multi_var_target(self, items):
        name_tok = items[0]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        typ = items[1] if len(items) > 1 else None
        return ast.MultiVarTarget(name=name, type=typ, line=line, col=col)

    def assignment_stmt(self, items):
        target, op_tok, value = items
        line, col = target.line, target.col
        return ast.AssignmentStmt(target=target, op=str(op_tok), value=value, line=line, col=col)
        
    def assign_op(self, items):
        return str(items[0])

    def func_decl(self, items):
        exported = getattr(items[0], 'data', None) == 'exp'
        is_async = getattr(items[1], 'data', None) == 'is_async'
        name_tok = items[2]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        
        params = items[3] if items[3] else []
        ret_type = items[4]
        
        body_data = items[5]
        is_arrow = body_data['is_arrow']
        body = body_data['body']
        
        return ast.FuncDecl(name=name, params=params, return_type=ret_type, body=body, is_async=is_async, exported=exported, is_arrow=is_arrow, line=line, col=col)

    def func_body_block(self, items):
        return {'is_arrow': False, 'body': items[0]}

    def func_body_arrow(self, items):
        val = items[0]
        ret_stmt = ast.ReturnStmt(value=val, line=val.line, col=val.col)
        return {'is_arrow': True, 'body': [ret_stmt]}

    def func_body_stmt(self, items):
        return {'is_arrow': False, 'body': [items[0]]}

    def param_list(self, items):
        return items

    def param(self, items):
        name_tok = items[0]
        typ = items[1]
        line, col = self._loc(name_tok)
        return ast.Param(name=str(name_tok), type=typ, line=line, col=col)

    def return_stmt(self, items):
        val = items[0] if items else None
        # line/col might be tricky without tokens, we'll use a dummy or get it from context if possible
        # Lark will pass Tokens for strings if we don't suppress them, but we didn't capture 'return' as a terminal
        # Let's just use line=1, col=1 and rely on analyzer to fix it, or we could extract it from val
        line, col = (val.line, val.col) if val else (1,1)
        return ast.ReturnStmt(value=val, line=line, col=col)
    
    def break_stmt(self, items):
        return ast.BreakStmt(line=1, col=1)

    def continue_stmt(self, items):
        return ast.ContinueStmt(line=1, col=1)
        
    def throw_stmt(self, items):
        val = items[0]
        return ast.ThrowStmt(value=val, line=val.line, col=val.col)

    def try_stmt(self, items):
        body = items[0] if isinstance(items[0], list) else [items[0]]
        catches = items[1:]
        line, col = (body[0].line, body[0].col) if body else (1,1)
        return ast.TryStmt(body=body, catches=catches, line=line, col=col)

    def catch_clause(self, items):
        name = None
        typ = None
        idx = 0
        if isinstance(items[idx], Token) and items[idx].type == 'IDENTIFIER':
            name = str(items[idx])
            idx += 1
            if isinstance(items[idx], tuple(ast.TypeNode.__args__)):
                typ = items[idx]
                idx += 1
        elif isinstance(items[idx], tuple(ast.TypeNode.__args__)):
            typ = items[idx]
            idx += 1
            
        body = items[idx] if isinstance(items[idx], list) else [items[idx]]
        line, col = (body[0].line, body[0].col) if body else (1,1)
        return ast.CatchClause(name=name, type=typ, body=body, line=line, col=col)

    def class_decl(self, items):
        exported = getattr(items[0], 'data', None) == 'exp'
        name_tok = items[1]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        
        generics = items[2] if items[2] else []
        members = items[3:]
        return ast.ClassDecl(name=name, generics=generics, members=members, exported=exported, line=line, col=col)

    def generic_list(self, items):
        return [str(i) for i in items]

    def enum_decl(self, items):
        exported = getattr(items[0], 'data', None) == 'exp'
        name_tok = items[1]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        variants = items[2:]
        return ast.EnumDecl(name=name, variants=variants, exported=exported, line=line, col=col)

    def enum_variant(self, items):
        name_tok = items[0]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        fields = items[1] if len(items) > 1 else []
        return ast.EnumVariant(name=name, fields=fields, line=line, col=col)

    def type_list(self, items):
        return items

    def block(self, items):
        return [i for i in items if i is not None]

    def if_stmt(self, items):
        items = [i for i in items if i is not None]
        cond = items[0]
        body = items[1] if isinstance(items[1], list) else [items[1]]
        line, col = cond.line, cond.col
        elifs = []
        else_body = None
        
        idx = 2
        while idx < len(items):
            if isinstance(items[idx], ast.ElifClause):
                elifs.append(items[idx])
                idx += 1
            else:
                else_body = items[idx] if isinstance(items[idx], list) else [items[idx]]
                idx += 1
                
        return ast.IfStmt(condition=cond, body=body, elifs=elifs, else_body=else_body, line=line, col=col)

    def elif_clause(self, items):
        cond = items[0]
        body = items[1] if isinstance(items[1], list) else [items[1]]
        line, col = cond.line, cond.col
        return ast.ElifClause(condition=cond, body=body, line=line, col=col)

    def loop_stmt(self, items):
        items = [i for i in items if i is not None]
        cond = items[0] if isinstance(items[0], tuple(ast.ExprNode.__args__)) else None
        body_idx = 1 if cond else 0
        body = items[body_idx] if isinstance(items[body_idx], list) else [items[body_idx]]
        line, col = (cond.line, cond.col) if cond else (body[0].line, body[0].col)
        return ast.LoopStmt(condition=cond, body=body, line=line, col=col)

    def for_range_stmt(self, items):
        items = [i for i in items if i is not None]
        var_name_tok = items[0]
        var_name = str(var_name_tok)
        line, col = self._loc(var_name_tok)
        
        start = items[1]
        end = items[2]
        step = None
        idx = 3
        if idx < len(items) and isinstance(items[idx], tuple(ast.ExprNode.__args__)):
            step = items[idx]
            idx += 1
            
        body = items[idx] if isinstance(items[idx], list) else [items[idx]]
        return ast.ForRangeStmt(var_name=var_name, start=start, end=end, step=step, body=body, line=line, col=col)

    def for_map_stmt(self, items):
        k_tok = items[0]
        v_tok = items[1]
        k = str(k_tok)
        v = str(v_tok)
        line, col = self._loc(k_tok)
        
        iterable = items[2]
        body = items[3] if isinstance(items[3], list) else [items[3]]
        return ast.ForMapStmt(key_name=k, value_name=v, iterable=iterable, body=body, line=line, col=col)

    def for_each_stmt(self, items):
        var_name_tok = items[0]
        var_name = str(var_name_tok)
        line, col = self._loc(var_name_tok)
        
        iterable = items[1]
        body = items[2] if isinstance(items[2], list) else [items[2]]
        return ast.ForEachStmt(var_name=var_name, iterable=iterable, body=body, line=line, col=col)

    def match_stmt(self, items):
        expr = items[0]
        line, col = expr.line, expr.col
        
        arms = []
        eof_arm = None
        for i in items[1:]:
            if isinstance(i, ast.MatchArm):
                arms.append(i)
            elif isinstance(i, ast.EofArm):
                eof_arm = i
                
        return ast.MatchStmt(expr=expr, arms=arms, eof_arm=eof_arm, line=line, col=col)

    def match_arm(self, items):
        patterns = []
        idx = 0
        while idx < len(items) and isinstance(items[idx], tuple(ast.PatternNode.__args__)):
            patterns.append(items[idx])
            idx += 1
            
        body = items[idx] if isinstance(items[idx], list) else [items[idx]]
        line, col = patterns[0].line, patterns[0].col
        return ast.MatchArm(patterns=patterns, body=body, line=line, col=col)

    def eof_arm(self, items):
        body = items[0] if isinstance(items[0], list) else [items[0]]
        line, col = body[0].line, body[0].col
        return ast.EofArm(body=body, line=line, col=col)

    def pat_wildcard(self, items):
        return ast.WildcardPattern(line=1, col=1)

    def pat_destructure(self, items):
        name_tok = items[0]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        fields = items[1] if len(items) > 1 else []
        return ast.DestructurePattern(name=name, fields=fields, line=line, col=col)

    def pat_ident(self, items):
        name_tok = items[0]
        name = str(name_tok)
        line, col = self._loc(name_tok)
        return ast.DestructurePattern(name=name, fields=[], line=line, col=col)

    def pat_literal(self, items):
        val = items[0]
        return ast.LiteralPattern(value=val, line=val.line, col=val.col)

    def pattern_list(self, items):
        return [str(i) for i in items]

    def expr_stmt(self, items):
        expr = items[0]
        return ast.ExprStmt(expr=expr, line=expr.line, col=expr.col)

    # Expressions
    def logical_or(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items)):
            res = ast.BinaryExpr(op="||", left=res, right=items[i], line=res.line, col=res.col)
        return res

    def logical_and(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items)):
            res = ast.BinaryExpr(op="&&", left=res, right=items[i], line=res.line, col=res.col)
        return res

    def bitwise_or(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items)):
            res = ast.BinaryExpr(op="|", left=res, right=items[i], line=res.line, col=res.col)
        return res

    def bitwise_xor(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items)):
            res = ast.BinaryExpr(op="^", left=res, right=items[i], line=res.line, col=res.col)
        return res

    def bitwise_and(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items)):
            res = ast.BinaryExpr(op="&", left=res, right=items[i], line=res.line, col=res.col)
        return res

    def equality(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items), 2):
            op = str(items[i])
            right = items[i+1]
            res = ast.BinaryExpr(op=op, left=res, right=right, line=res.line, col=res.col)
        return res

    def chained_comparison(self, items):
        if len(items) == 1: return items[0]
        operands = [items[0]]
        operators = []
        for i in range(1, len(items), 2):
            operators.append(str(items[i]))
            operands.append(items[i+1])
            
        if len(operators) == 1:
            return ast.BinaryExpr(op=operators[0], left=operands[0], right=operands[1], line=operands[0].line, col=operands[0].col)
            
        return ast.ChainedCompareExpr(operands=operands, operators=operators, line=operands[0].line, col=operands[0].col)

    def shift(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items), 2):
            op = str(items[i])
            right = items[i+1]
            res = ast.BinaryExpr(op=op, left=res, right=right, line=res.line, col=res.col)
        return res

    def term(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items), 2):
            op = str(items[i])
            right = items[i+1]
            res = ast.BinaryExpr(op=op, left=res, right=right, line=res.line, col=res.col)
        return res

    def factor(self, items):
        if len(items) == 1: return items[0]
        res = items[0]
        for i in range(1, len(items), 2):
            op = str(items[i])
            right = items[i+1]
            res = ast.BinaryExpr(op=op, left=res, right=right, line=res.line, col=res.col)
        return res

    def un_neg(self, items):
        expr = items[0]
        return ast.UnaryExpr(op="-", operand=expr, line=expr.line, col=expr.col)

    def un_not(self, items):
        expr = items[0]
        return ast.UnaryExpr(op="!", operand=expr, line=expr.line, col=expr.col)

    def un_bitnot(self, items):
        expr = items[0]
        return ast.UnaryExpr(op="~", operand=expr, line=expr.line, col=expr.col)

    def un_await(self, items):
        expr = items[0]
        return ast.AwaitExpr(expr=expr, line=expr.line, col=expr.col)

    def dot_expr(self, items):
        obj = items[0]
        attr = str(items[1])
        return ast.DotExpr(obj=obj, attr=attr, line=obj.line, col=obj.col)

    def call_expr(self, items):
        callee = items[0]
        args = items[1] if len(items) > 1 else []
        return ast.CallExpr(callee=callee, args=args, line=callee.line, col=callee.col)

    def index_expr(self, items):
        obj = items[0]
        index = items[1]
        return ast.IndexExpr(obj=obj, index=index, line=obj.line, col=obj.col)

    def propagate_expr(self, items):
        expr = items[0]
        return ast.PropagateExpr(expr=expr, line=expr.line, col=expr.col)

    def ident_expr(self, items):
        tok = items[0]
        return ast.IdentExpr(name=str(tok), line=self._loc(tok)[0], col=self._loc(tok)[1])

    def grouped_expr(self, items):
        expr = items[0]
        return ast.GroupedExpr(expr=expr, line=expr.line, col=expr.col)

    def expr_list(self, items):
        return items

    def lambda_expr(self, items):
        params = items[0] if len(items) > 1 else []
        body = items[-1]
        line, col = (1, 1) # hard to extract cleanly
        return ast.LambdaExpr(params=params, body=body, line=line, col=col)

    def lambda_params(self, items):
        return [str(i) for i in items]

    def array_literal(self, items):
        elements = items[0] if items else []
        line, col = (elements[0].line, elements[0].col) if elements else (1,1)
        return ast.ArrayLiteral(elements=elements, line=line, col=col)

    def tuple_literal(self, items):
        elements = items[0:] if len(items) > 0 and isinstance(items[0], tuple(ast.ExprNode.__args__)) else []
        if items and len(items) > 1 and isinstance(items[1], list):
            elements = [items[0]] + items[1]
        line, col = (elements[0].line, elements[0].col) if elements else (1,1)
        return ast.TupleLiteral(elements=elements, line=line, col=col)

    def map_literal(self, items):
        entries = items[0] if items else []
        line, col = (entries[0][0].line, entries[0][0].col) if entries else (1,1)
        return ast.MapLiteral(entries=entries, line=line, col=col)

    def map_entries(self, items):
        return items

    def map_entry(self, items):
        return (items[0], items[1])

    def sized_vector_literal(self, items):
        size_expr = items[0]
        fill_val = None
        if len(items) > 1:
            tok_or_expr = items[1]
            if isinstance(tok_or_expr, Token):
                if tok_or_expr.type == 'IDENTIFIER':
                    fill_val = ast.IdentExpr(name=str(tok_or_expr), line=size_expr.line, col=size_expr.col)
                elif tok_or_expr.type == 'bool_true':
                    fill_val = ast.LiteralExpr(value=True, literal_type="bool", line=size_expr.line, col=size_expr.col)
                elif tok_or_expr.type == 'bool_false':
                    fill_val = ast.LiteralExpr(value=False, literal_type="bool", line=size_expr.line, col=size_expr.col)
            elif isinstance(tok_or_expr, ast.LiteralExpr):
                fill_val = tok_or_expr
        return ast.SizedVectorLiteral(size_expr=size_expr, fill_value=fill_val, line=size_expr.line, col=size_expr.col)

    def integer_literal(self, items):
        tok = items[0]
        line, col = self._loc(tok)
        return ast.LiteralExpr(value=int(tok), literal_type="int", line=line, col=col)

    def float_literal(self, items):
        tok = items[0]
        line, col = self._loc(tok)
        return ast.LiteralExpr(value=float(tok), literal_type="float", line=line, col=col)

    def string_literal(self, items):
        tok = items[0]
        line, col = self._loc(tok)
        raw = str(tok)[1:-1] # strip quotes
        
        import re
        parts = []
        last_idx = 0
        
        # Super simple interpolation regex {expr}
        # In a real parser we'd need to handle nested braces or escaped braces.
        # But this is sufficient for typical {name} usages.
        for match in re.finditer(r'\{([^}]+)\}', raw):
            if match.start() > last_idx:
                parts.append(raw[last_idx:match.start()])
            
            expr_str = match.group(1)
            # recursively parse expr
            try:
                # We need a mini-parser just for expressions to support {a+b}.
                # Lark makes this slightly tricky without a separate entry point.
                # So we instantiate a parser for just 'expression' if needed.
                # To keep it simple, we'll construct a dummy IdentExpr or BinaryExpr manually if we can't parse easily.
                # Actually, we can use the same parser by wrapping in a statement, but that might be heavy.
                # Let's just create a quick parser for expr:
                expr_parser = Lark(GRAMMAR, start="expression", parser="lalr")
                tree = expr_parser.parse(expr_str)
                transformer = ASTTransformer()
                expr_node = transformer.transform(tree)
                parts.append(expr_node)
            except Exception:
                # fallback to raw string if expression parsing fails
                parts.append("{" + expr_str + "}")
                
            last_idx = match.end()
            
        if last_idx < len(raw):
            parts.append(raw[last_idx:])
            
        if not any(isinstance(p, tuple(ast.ExprNode.__args__)) for p in parts):
            return ast.LiteralExpr(value=raw, literal_type="string", line=line, col=col)
        return ast.StringInterp(parts=parts, line=line, col=col)

    def bool_true(self, items):
        return ast.LiteralExpr(value=True, literal_type="bool", line=1, col=1)

    def bool_false(self, items):
        return ast.LiteralExpr(value=False, literal_type="bool", line=1, col=1)

    # Types
    def type_optional(self, items):
        if len(items) == 1:
            if isinstance(items[0], Token):
                # if it parsed as base_type base_type...
                pass
            return items[0]
        return ast.OptionalType(inner_type=items[0], line=1, col=1)
        
    def primitive_type(self, items):
        tok = items[0]
        return ast.PrimitiveType(name=str(tok), line=1, col=1)
        
    def builtin_map(self, items):
        return ast.BuiltinCollectionType(collection="Map", type_args=[items[0], items[1]], line=1, col=1)
        
    def builtin_set(self, items):
        return ast.BuiltinCollectionType(collection="Set", type_args=[items[0]], line=1, col=1)
        
    def builtin_deque(self, items):
        return ast.BuiltinCollectionType(collection="Deque", type_args=[items[0]], line=1, col=1)
        
    def builtin_pqueue(self, items):
        return ast.BuiltinCollectionType(collection="PQueue", type_args=[items[0]], line=1, col=1)

    def array_type(self, items):
        elem_type = items[0]
        size = None
        if len(items) > 1:
            tok = items[1]
            if isinstance(tok, ast.LiteralExpr):
                size = tok
            else:
                size = ast.IdentExpr(name=str(tok), line=1, col=1)
        return ast.ArrayType(element_type=elem_type, size=size, line=1, col=1)
        
    def map_type(self, items):
        return ast.MapType(key_type=items[0], value_type=items[1], line=1, col=1)
        
    def tuple_type(self, items):
        type_args = [items[0]] + items[1]
        return ast.TupleType(element_types=type_args, line=1, col=1)
        
    def generic_type(self, items):
        name = str(items[0])
        type_args = items[1]
        return ast.GenericType(name=name, type_args=type_args, line=1, col=1)
        
    def user_type(self, items):
        return ast.UserType(name=str(items[0]), line=1, col=1)

def parse(source: str, errors: ErrorCollector) -> Optional[ast.Program]:
    """Parse preprocessed AILang source into an AST."""
    try:
        # Using Earley parser to handle grammar ambiguities naturally
        _parser = Lark(GRAMMAR, start="start", parser="earley")
        tree = _parser.parse(source)
        transformer = ASTTransformer()
        return transformer.transform(tree)
    except lark.exceptions.UnexpectedInput as e:
        # e.line and e.column are available
        errors.add(ErrorCode.E002, e.line, e.column, str(e).split("\n")[0])
        return None
    except lark.exceptions.UnexpectedToken as e:
        errors.add(ErrorCode.E002, e.line, e.column, f"Unexpected token: {e.token}")
        return None
    except lark.exceptions.UnexpectedCharacters as e:
        errors.add(ErrorCode.E001, e.line, e.column, f"Unknown character: {source[e.pos_in_stream]}")
        return None
    except Exception as e:
        errors.add(ErrorCode.E002, 1, 1, f"Parse error: {str(e)}")
        return None
