from __future__ import annotations

import ast
import re

from xdsl.dialects.builtin import IntegerType, ModuleOp
from xdsl.ir import Block, Region

from veripy.py import BinOp, ConstantOp, FuncOp, IfOp, NegOp, ParamRefOp, ReturnOp

i64 = IntegerType(64)
i1 = IntegerType(1)

ANNOTATION_RE = re.compile(r"^\s*#@\s+(requires|ensures)\s+(.*?)\s*$")

AST_CMPOP_TO_STR = {
    ast.Eq: "eq",
    ast.NotEq: "ne",
    ast.Lt: "lt",
    ast.LtE: "le",
    ast.Gt: "gt",
    ast.GtE: "ge",
}

AST_BINOP_TO_STR = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.FloorDiv: "floordiv",
    ast.Mod: "mod",
}

AST_BOOLOP_TO_STR = {
    ast.And: "and",
    ast.Or: "or",
}


def _extract_annotations(source: str, func_node: ast.FunctionDef) -> tuple[list[str], list[str]]:
    lines = source.splitlines()
    requires: list[str] = []
    ensures: list[str] = []
    for lineno in range(func_node.lineno, func_node.end_lineno or func_node.lineno + 1):
        line = lines[lineno - 1] if lineno <= len(lines) else ""
        m = ANNOTATION_RE.match(line)
        if not m:
            continue
        keyword, expr = m.group(1), m.group(2)
        if keyword == "requires":
            requires.append(expr)
        else:
            ensures.append(expr)
    return requires, ensures


def _lower_expr(node: ast.expr) -> list:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        op = ConstantOp(node.value, i64)
        return [op]

    if isinstance(node, ast.Name):
        op = ParamRefOp(node.id, i64)
        return [op]

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner_ops = _lower_expr(node.operand)
        neg = NegOp(inner_ops[-1], i64)
        return inner_ops + [neg]

    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        lhs_ops = _lower_expr(node.left)
        rhs_ops = _lower_expr(node.comparators[0])
        op_str = AST_CMPOP_TO_STR[type(node.ops[0])]
        binop = BinOp(op_str, lhs_ops[-1], rhs_ops[-1], i1)
        return lhs_ops + rhs_ops + [binop]

    if isinstance(node, ast.BinOp):
        lhs_ops = _lower_expr(node.left)
        rhs_ops = _lower_expr(node.right)
        op_str = AST_BINOP_TO_STR[type(node.op)]
        binop = BinOp(op_str, lhs_ops[-1], rhs_ops[-1], i64)
        return lhs_ops + rhs_ops + [binop]

    if isinstance(node, ast.BoolOp):
        lhs_ops = _lower_expr(node.values[0])
        rhs_ops = _lower_expr(node.values[1])
        op_str = AST_BOOLOP_TO_STR[type(node.op)]
        binop = BinOp(op_str, lhs_ops[-1], rhs_ops[-1], i1)
        return lhs_ops + rhs_ops + [binop]

    raise NotImplementedError(f"unsupported expression: {ast.dump(node)}")


def _lower_stmt(stmt: ast.stmt) -> list:
    if isinstance(stmt, ast.Return) and stmt.value is not None:
        expr_ops = _lower_expr(stmt.value)
        ret = ReturnOp(expr_ops[-1])
        return expr_ops + [ret]

    if isinstance(stmt, ast.If):
        cond_ops = _lower_expr(stmt.test)

        then_ops: list = []
        for s in stmt.body:
            then_ops.extend(_lower_stmt(s))
        then_block = Block(then_ops)

        else_ops: list = []
        for s in stmt.orelse:
            else_ops.extend(_lower_stmt(s))
        else_region = Region([Block(else_ops)]) if else_ops else None

        if_op = IfOp(cond_ops[-1], Region([then_block]), else_region)
        return cond_ops + [if_op]

    raise NotImplementedError(f"unsupported statement: {ast.dump(stmt)}")


def _fold_trailing_else(stmts: list[ast.stmt]) -> list[ast.stmt]:
    if len(stmts) >= 2 and isinstance(stmts[-2], ast.If) and not stmts[-2].orelse:
        folded_if = stmts[-2]
        folded_if.orelse = [stmts[-1]]
        return stmts[:-1]
    return stmts


def _lower_function(source: str, func_node: ast.FunctionDef) -> FuncOp:
    requires, ensures = _extract_annotations(source, func_node)

    param_names = [arg.arg for arg in func_node.args.args]
    param_types = [i64] * len(param_names)
    return_type = [i64] if func_node.returns else []

    body_stmts = [s for s in func_node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    body_stmts = _fold_trailing_else(body_stmts)

    body_ops: list = []
    for stmt in body_stmts:
        body_ops.extend(_lower_stmt(stmt))

    body = Region([Block(body_ops)])

    return FuncOp(func_node.name, param_names, (param_types, return_type), requires=requires, ensures=ensures, body=body)


def ingest(source: str) -> ModuleOp:
    tree = ast.parse(source)
    ops = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            ops.append(_lower_function(source, node))
    return ModuleOp(ops)
