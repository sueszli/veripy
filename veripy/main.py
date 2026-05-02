from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

import click
from xdsl.dialects.builtin import (
    ArrayAttr,
    FunctionType,
    IntegerAttr,
    IntegerType,
    ModuleOp,
    StringAttr,
)
from xdsl.ir import Block, Dialect, Operation, Region, SSAValue
from xdsl.irdl import (
    IRDLOperation,
    irdl_op_definition,
    operand_def,
    prop_def,
    region_def,
    result_def,
    traits_def,
)
from xdsl.printer import Printer
from xdsl.traits import IsolatedFromAbove, IsTerminator, Pure

#
# dialect
#


@irdl_op_definition
class FuncOp(IRDLOperation):
    name = "py.func"
    sym_name = prop_def(StringAttr)
    function_type = prop_def(FunctionType)
    param_names = prop_def(ArrayAttr[StringAttr])
    requires = prop_def(ArrayAttr[StringAttr])
    ensures = prop_def(ArrayAttr[StringAttr])
    body = region_def()
    traits = traits_def(IsolatedFromAbove())

    def __init__(self, func_name: str, param_names: Sequence[str], function_type: tuple[Sequence, Sequence] | FunctionType, *, requires: Sequence[str] | None = None, ensures: Sequence[str] | None = None, body: Region | None = None):
        if isinstance(function_type, tuple):
            function_type = FunctionType.from_lists(*function_type)
        super().__init__(properties={"sym_name": StringAttr(func_name), "function_type": function_type, "param_names": ArrayAttr([StringAttr(n) for n in param_names]), "requires": ArrayAttr([StringAttr(s) for s in (requires or [])]), "ensures": ArrayAttr([StringAttr(s) for s in (ensures or [])])}, regions=[body if body is not None else Region()])


@irdl_op_definition
class ConstantOp(IRDLOperation):
    name = "py.constant"
    value = prop_def(IntegerAttr)
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, value: int, result_type: IntegerType):
        super().__init__(properties={"value": IntegerAttr(value, result_type)}, result_types=[result_type])


@irdl_op_definition
class ParamRefOp(IRDLOperation):
    name = "py.param_ref"
    param_name = prop_def(StringAttr)
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, param_name: str, result_type: IntegerType):
        super().__init__(properties={"param_name": StringAttr(param_name)}, result_types=[result_type])


@irdl_op_definition
class BinOp(IRDLOperation):
    name = "py.binop"
    op_kind = prop_def(StringAttr)
    lhs = operand_def()
    rhs = operand_def()
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, op: str, lhs: SSAValue | Operation, rhs: SSAValue | Operation, result_type: IntegerType):
        super().__init__(operands=[lhs, rhs], properties={"op_kind": StringAttr(op)}, result_types=[result_type])


@irdl_op_definition
class NegOp(IRDLOperation):
    name = "py.neg"
    operand = operand_def()
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, operand: SSAValue | Operation, result_type: IntegerType):
        super().__init__(operands=[operand], result_types=[result_type])


@irdl_op_definition
class IfOp(IRDLOperation):
    name = "py.if"
    cond = operand_def(IntegerType(1))
    then_region = region_def()
    else_region = region_def()

    def __init__(self, cond: SSAValue | Operation, then_region: Region, else_region: Region | None = None):
        super().__init__(operands=[cond], regions=[then_region, else_region if else_region is not None else Region()])


@irdl_op_definition
class ReturnOp(IRDLOperation):
    name = "py.return"
    value = operand_def()
    traits = traits_def(IsTerminator())

    def __init__(self, value: SSAValue | Operation):
        super().__init__(operands=[value])


Py = Dialect("py", [FuncOp, ConstantOp, ParamRefOp, BinOp, NegOp, IfOp, ReturnOp], [])


#
# ingestor
#

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


#
# printer
#

OP_SYMBOLS = {"ge": ">=", "le": "<=", "gt": ">", "lt": "<", "eq": "==", "ne": "!=", "add": "+", "sub": "-", "mul": "*"}


def rewrite_ensures(clause: str) -> str:
    s = re.sub(r"\bresult\b", "r", clause)
    return re.sub(r"\bor\b", "||", s)


def print_dafny(module: ModuleOp) -> str:
    parts = []
    for op in module.body.block.ops:
        if isinstance(op, FuncOp):
            parts.append(_print_func(op))
    return "\n".join(parts)


def _type_str(ty: IntegerType) -> str:
    if ty.width.data == 1:
        return "bool"
    return "int"


def _print_func(func: FuncOp) -> str:
    param_names = [attr.data for attr in func.param_names]
    param_types = list(func.function_type.inputs)
    params = [f"{name}: {_type_str(ty)}" for name, ty in zip(param_names, param_types)]
    ret_type = list(func.function_type.outputs)[0]

    lines = [f"method {func.sym_name.data}({', '.join(params)}) returns (r: {_type_str(ret_type)})"]

    for clause in func.requires:
        lines.append(f"  requires {rewrite_ensures(clause.data)}")
    for clause in func.ensures:
        lines.append(f"  ensures {rewrite_ensures(clause.data)}")

    lines.append("{")
    exprs: dict[SSAValue, str] = {}
    lines.extend(_emit_ops(func.body.block.ops, exprs, "  "))
    lines.append("}")

    return "\n".join(lines)


def _emit_ops(ops: Iterable[Operation], exprs: dict[SSAValue, str], indent: str) -> list[str]:
    lines: list[str] = []
    for op in ops:
        if isinstance(op, ConstantOp):
            exprs[op.result] = str(op.value.value.data)
        elif isinstance(op, ParamRefOp):
            exprs[op.result] = op.param_name.data
        elif isinstance(op, BinOp):
            exprs[op.result] = f"{exprs[op.lhs]} {OP_SYMBOLS[op.op_kind.data]} {exprs[op.rhs]}"
        elif isinstance(op, NegOp):
            exprs[op.result] = f"-{exprs[op.operand]}"
        elif isinstance(op, ReturnOp):
            lines.append(f"{indent}r := {exprs[op.value]};")
            lines.append(f"{indent}return;")
        elif isinstance(op, IfOp):
            lines.append(f"{indent}if {exprs[op.cond]} {{")
            lines.extend(_emit_ops(op.then_region.block.ops, exprs, indent + "  "))
            lines.append(f"{indent}}}")
            if len(op.else_region.blocks) > 0:
                lines.extend(_emit_ops(op.else_region.block.ops, exprs, indent))
    return lines


#
# cli
#


@click.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--ir", "fmt", flag_value="ir", help="Print xDSL IR")
@click.option("--dfy", "fmt", flag_value="dfy", help="Print Dafny source")
def cli(file: Path, fmt: str | None):
    source = Path(file).read_text()
    module = ingest(source)
    if fmt == "ir":
        Printer().print(module)
        return
    dfy = print_dafny(module)
    if fmt == "dfy":
        click.echo(dfy)
        return
    dfy_path = Path(file).with_suffix(".dfy")
    dfy_path.write_text(dfy + "\n")
    result = subprocess.run(["docker", "run", "--rm", "-v", f"{dfy_path.parent}:/work", "-w", "/work", "veripy-dafny", "dafny", "verify", dfy_path.name])
    sys.exit(result.returncode)
