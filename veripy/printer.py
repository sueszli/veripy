from __future__ import annotations

import re
from collections.abc import Iterable

from xdsl.dialects.builtin import IntegerType, ModuleOp
from xdsl.ir import Operation, SSAValue

from veripy.py import BinOp, ConstantOp, FuncOp, IfOp, NegOp, ParamRefOp, ReturnOp

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
