import argparse
import ast
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from re import compile as re_compile
from typing import IO

from xdsl.context import Context
from xdsl.dialects.builtin import (
    ArrayAttr,
    FunctionType,
    IntegerAttr,
    IntegerType,
    ModuleOp,
    StringAttr,
)
from xdsl.frontend.pyast.utils.exceptions import CodeGenerationException
from xdsl.frontend.pyast.utils.op_inserter import OpInserter
from xdsl.ir import Block, Dialect, Operation, Region, SSAValue
from xdsl.irdl import (
    IRDLOperation,
    irdl_op_definition,
    operand_def,
    prop_def,
    region_def,
    result_def,
    traits_def,
    var_operand_def,
)
from xdsl.pattern_rewriter import (
    GreedyRewritePatternApplier,
    PatternRewriter,
    PatternRewriteWalker,
    RewritePattern,
    op_type_rewrite_pattern,
)
from xdsl.passes import ModulePass
from xdsl.printer import Printer
from xdsl.utils.target import Target
from xdsl.traits import IsolatedFromAbove, IsTerminator, Pure
from xdsl.xdsl_opt_main import xDSLOptMain

#
# py dialect
#


@irdl_op_definition
class YieldOp(IRDLOperation):
    name = "py.yield"
    value = operand_def()
    traits = traits_def(IsTerminator())

    def __init__(self, value: SSAValue | Operation):
        super().__init__(operands=[value])


@irdl_op_definition
class RequiresOp(IRDLOperation):
    name = "py.requires"
    cond_region = region_def()

    def __init__(self, cond_region: Region):
        super().__init__(regions=[cond_region])


@irdl_op_definition
class EnsuresOp(IRDLOperation):
    name = "py.ensures"
    cond_region = region_def()

    def __init__(self, cond_region: Region):
        super().__init__(regions=[cond_region])


@irdl_op_definition
class InvariantOp(IRDLOperation):
    name = "py.invariant"
    cond_region = region_def()

    def __init__(self, cond_region: Region):
        super().__init__(regions=[cond_region])


@irdl_op_definition
class DecreasesOp(IRDLOperation):
    name = "py.decreases"
    expr_region = region_def()

    def __init__(self, expr_region: Region):
        super().__init__(regions=[expr_region])


@irdl_op_definition
class FuncOp(IRDLOperation):
    name = "py.func"
    sym_name = prop_def(StringAttr)
    function_type = prop_def(FunctionType)
    param_names = prop_def(ArrayAttr[StringAttr])
    body = region_def()
    traits = traits_def(IsolatedFromAbove())

    def __init__(self, func_name: str, param_names: Sequence[str], function_type: tuple[Sequence, Sequence] | FunctionType, *, body: Region | None = None):
        if isinstance(function_type, tuple):
            function_type = FunctionType.from_lists(*function_type)
        super().__init__(properties={"sym_name": StringAttr(func_name), "function_type": function_type, "param_names": ArrayAttr([StringAttr(n) for n in param_names])}, regions=[body if body is not None else Region()])


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


@irdl_op_definition
class AssertOp(IRDLOperation):
    name = "py.assert"
    cond = operand_def()

    def __init__(self, cond: SSAValue | Operation):
        super().__init__(operands=[cond])


@irdl_op_definition
class CallOp(IRDLOperation):
    name = "py.call"
    callee = prop_def(StringAttr)
    arguments = var_operand_def()
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, callee: str, arguments: Sequence[SSAValue | Operation], result_type: IntegerType):
        super().__init__(operands=[arguments], properties={"callee": StringAttr(callee)}, result_types=[result_type])


@irdl_op_definition
class AssignOp(IRDLOperation):
    name = "py.assign"
    var_name = prop_def(StringAttr)
    is_decl = prop_def(IntegerAttr)
    value = operand_def()

    def __init__(self, var_name: str, value: SSAValue | Operation, is_decl: bool):
        super().__init__(operands=[value], properties={"var_name": StringAttr(var_name), "is_decl": IntegerAttr(int(is_decl), IntegerType(1))})


@irdl_op_definition
class VarRefOp(IRDLOperation):
    name = "py.var_ref"
    var_name = prop_def(StringAttr)
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, var_name: str, result_type: IntegerType):
        super().__init__(properties={"var_name": StringAttr(var_name)}, result_types=[result_type])


@irdl_op_definition
class WhileOp(IRDLOperation):
    name = "py.while"
    cond_region = region_def()
    body = region_def()

    def __init__(self, cond_region: Region, body: Region):
        super().__init__(regions=[cond_region, body])


Py = Dialect("py", [YieldOp, RequiresOp, EnsuresOp, InvariantOp, DecreasesOp, FuncOp, ConstantOp, ParamRefOp, BinOp, NegOp, IfOp, ReturnOp, AssertOp, CallOp, AssignOp, VarRefOp, WhileOp], [])


#
# verif dialect
#


@irdl_op_definition
class VerifYieldOp(IRDLOperation):
    name = "verif.yield"
    value = operand_def()
    traits = traits_def(IsTerminator())

    def __init__(self, value: SSAValue):
        super().__init__(operands=[value])


@irdl_op_definition
class VerifRequiresOp(IRDLOperation):
    name = "verif.requires"
    cond_region = region_def()

    def __init__(self, cond_region: Region):
        super().__init__(regions=[cond_region])


@irdl_op_definition
class VerifEnsuresOp(IRDLOperation):
    name = "verif.ensures"
    cond_region = region_def()

    def __init__(self, cond_region: Region):
        super().__init__(regions=[cond_region])


@irdl_op_definition
class VerifInvariantOp(IRDLOperation):
    name = "verif.invariant"
    cond_region = region_def()

    def __init__(self, cond_region: Region):
        super().__init__(regions=[cond_region])


@irdl_op_definition
class VerifDecreasesOp(IRDLOperation):
    name = "verif.decreases"
    expr_region = region_def()

    def __init__(self, expr_region: Region):
        super().__init__(regions=[expr_region])


@irdl_op_definition
class VerifFuncOp(IRDLOperation):
    name = "verif.func"
    sym_name = prop_def(StringAttr)
    function_type = prop_def(FunctionType)
    param_names = prop_def(ArrayAttr[StringAttr])
    body = region_def()
    traits = traits_def(IsolatedFromAbove())

    def __init__(self, func_name: str, param_names: Sequence[str], function_type: FunctionType, *, body: Region):
        super().__init__(properties={"sym_name": StringAttr(func_name), "function_type": function_type, "param_names": ArrayAttr([StringAttr(n) for n in param_names])}, regions=[body])


@irdl_op_definition
class VerifConstantOp(IRDLOperation):
    name = "verif.constant"
    value = prop_def(IntegerAttr)
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, value: IntegerAttr, result_type: IntegerType):
        super().__init__(properties={"value": value}, result_types=[result_type])


@irdl_op_definition
class VerifParamRefOp(IRDLOperation):
    name = "verif.param_ref"
    param_name = prop_def(StringAttr)
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, param_name: StringAttr, result_type: IntegerType):
        super().__init__(properties={"param_name": param_name}, result_types=[result_type])


@irdl_op_definition
class VerifNegOp(IRDLOperation):
    name = "verif.neg"
    operand = operand_def()
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, operand: SSAValue, result_type: IntegerType):
        super().__init__(operands=[operand], result_types=[result_type])


@irdl_op_definition
class VerifIfOp(IRDLOperation):
    name = "verif.if"
    cond = operand_def(IntegerType(1))
    then_region = region_def()
    else_region = region_def()

    def __init__(self, cond: SSAValue, then_region: Region, else_region: Region):
        super().__init__(operands=[cond], regions=[then_region, else_region])


@irdl_op_definition
class VerifReturnOp(IRDLOperation):
    name = "verif.return"
    value = operand_def()
    traits = traits_def(IsTerminator())

    def __init__(self, value: SSAValue):
        super().__init__(operands=[value])


@irdl_op_definition
class VerifAssignOp(IRDLOperation):
    name = "verif.assign"
    var_name = prop_def(StringAttr)
    is_decl = prop_def(IntegerAttr)
    value = operand_def()

    def __init__(self, var_name: StringAttr, is_decl: IntegerAttr, value: SSAValue):
        super().__init__(operands=[value], properties={"var_name": var_name, "is_decl": is_decl})


@irdl_op_definition
class VerifVarRefOp(IRDLOperation):
    name = "verif.var_ref"
    var_name = prop_def(StringAttr)
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, var_name: StringAttr, result_type: IntegerType):
        super().__init__(properties={"var_name": var_name}, result_types=[result_type])


@irdl_op_definition
class VerifCallOp(IRDLOperation):
    name = "verif.call"
    callee = prop_def(StringAttr)
    arguments = var_operand_def()
    result = result_def()
    traits = traits_def(Pure())

    def __init__(self, callee: StringAttr, arguments: Sequence[SSAValue], result_type: IntegerType):
        super().__init__(operands=[arguments], properties={"callee": callee}, result_types=[result_type])


@irdl_op_definition
class VerifAssertOp(IRDLOperation):
    name = "verif.assert"
    cond = operand_def()

    def __init__(self, cond: SSAValue):
        super().__init__(operands=[cond])


@irdl_op_definition
class VerifWhileOp(IRDLOperation):
    name = "verif.while"
    cond_region = region_def()
    body = region_def()

    def __init__(self, cond_region: Region, body: Region):
        super().__init__(regions=[cond_region, body])


def _make_verif_binop(opname: str) -> type[IRDLOperation]:
    @irdl_op_definition
    class _Op(IRDLOperation):
        name = f"verif.{opname}"
        lhs = operand_def()
        rhs = operand_def()
        result = result_def()
        traits = traits_def(Pure())

        def __init__(self, lhs: SSAValue, rhs: SSAValue, result_type: IntegerType):
            super().__init__(operands=[lhs, rhs], result_types=[result_type])

    cls_name = "".join(p.capitalize() for p in opname.split("_")) + "Op"
    _Op.__name__ = cls_name
    _Op.__qualname__ = cls_name
    return _Op


VerifAddOp = _make_verif_binop("add")
VerifSubOp = _make_verif_binop("sub")
VerifMulOp = _make_verif_binop("mul")
VerifFloorDivOp = _make_verif_binop("floordiv")
VerifModOp = _make_verif_binop("mod")
VerifEqOp = _make_verif_binop("eq")
VerifNeOp = _make_verif_binop("ne")
VerifLtOp = _make_verif_binop("lt")
VerifLeOp = _make_verif_binop("le")
VerifGtOp = _make_verif_binop("gt")
VerifGeOp = _make_verif_binop("ge")
VerifAndOp = _make_verif_binop("and")
VerifOrOp = _make_verif_binop("or")

VERIF_BIN_BY_KIND: dict[str, type[IRDLOperation]] = {
    "add": VerifAddOp, "sub": VerifSubOp, "mul": VerifMulOp,
    "floordiv": VerifFloorDivOp, "mod": VerifModOp,
    "eq": VerifEqOp, "ne": VerifNeOp,
    "lt": VerifLtOp, "le": VerifLeOp, "gt": VerifGtOp, "ge": VerifGeOp,
    "and": VerifAndOp, "or": VerifOrOp,
}

Verif = Dialect("verif", [
    VerifYieldOp, VerifRequiresOp, VerifEnsuresOp, VerifInvariantOp, VerifDecreasesOp,
    VerifFuncOp, VerifConstantOp, VerifParamRefOp, VerifNegOp, VerifIfOp, VerifReturnOp,
    VerifAssignOp, VerifVarRefOp, VerifCallOp, VerifAssertOp, VerifWhileOp,
    *VERIF_BIN_BY_KIND.values(),
], [])


#
# ingestor
#

i64 = IntegerType(64)
i1 = IntegerType(1)

ANNOTATION_RE = re_compile(r"^\s*#@\s+(requires|ensures|invariant|decreases)\s+(.*?)\s*$")

AST_OP: dict[type, tuple[str, IntegerType]] = {
    ast.Eq: ("eq", i1), ast.NotEq: ("ne", i1),
    ast.Lt: ("lt", i1), ast.LtE: ("le", i1), ast.Gt: ("gt", i1), ast.GtE: ("ge", i1),
    ast.Add: ("add", i64), ast.Sub: ("sub", i64), ast.Mult: ("mul", i64),
    ast.FloorDiv: ("floordiv", i64), ast.Mod: ("mod", i64),
    ast.And: ("and", i1), ast.Or: ("or", i1),
}


def _resolve_type(ann: ast.expr | None) -> IntegerType:
    match ann:
        case ast.Name(id="bool"):
            return i1
        case _:
            return i64


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
        elif keyword == "ensures":
            ensures.append(expr)
    return requires, ensures


def _extract_loop_annotations(source: str, node: ast.While) -> tuple[list[str], list[str]]:
    lines = source.splitlines()
    invariants: list[str] = []
    decreases_list: list[str] = []
    for lineno in range(node.lineno, node.end_lineno or node.lineno + 1):
        line = lines[lineno - 1] if lineno <= len(lines) else ""
        m = ANNOTATION_RE.match(line)
        if not m:
            continue
        keyword, expr = m.group(1), m.group(2)
        if keyword == "invariant":
            invariants.append(expr)
        elif keyword == "decreases":
            decreases_list.append(expr)
    return invariants, decreases_list


class PyASTVisitor(ast.NodeVisitor):
    inserter: OpInserter
    source: str
    file: str | None
    scope: dict[str, IntegerType]
    locals_: set[str]

    def __init__(self, module: ModuleOp, source: str, file: str | None = None):
        self.source = source
        self.file = file
        self.scope = {}
        self.locals_ = set()
        self.inserter = OpInserter(module.body.block)

    def _err(self, node: ast.AST, msg: str) -> CodeGenerationException:
        return CodeGenerationException(self.file, getattr(node, "lineno", 0), getattr(node, "col_offset", 0), msg)

    def _emit_spec_op(self, op_cls: type, spec_str: str) -> None:
        saved = self.inserter.insertion_point
        cond_block = Block()
        self.inserter.set_insertion_point_from_block(cond_block)
        expr_ast = ast.parse(spec_str, mode="eval").body
        self.visit(expr_ast)
        self.inserter.insert_op(YieldOp(self.inserter.get_operand()))
        self.inserter.set_insertion_point_from_block(saved)
        self.inserter.insert_op(op_cls(Region([cond_block])))

    def generic_visit(self, node: ast.AST) -> None:
        raise self._err(node, f"unsupported AST node: {ast.dump(node)}")

    def visit_Module(self, node: ast.Module) -> None:
        for child in node.body:
            if isinstance(child, ast.FunctionDef):
                self.visit(child)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        requires, ensures = _extract_annotations(self.source, node)
        param_names = [arg.arg for arg in node.args.args]
        param_types = [_resolve_type(arg.annotation) for arg in node.args.args]
        return_type = [_resolve_type(node.returns)] if node.returns else []
        self.scope = dict(zip(param_names, param_types))
        self.locals_ = set()

        body_block = Block()
        func_op = FuncOp(node.name, param_names, (param_types, return_type), body=Region([body_block]))
        saved = self.inserter.insertion_point
        self.inserter.insert_op(func_op)
        self.inserter.set_insertion_point_from_block(body_block)
        for req in requires:
            self._emit_spec_op(RequiresOp, req)
        for ens in ensures:
            self._emit_spec_op(EnsuresOp, ens)
        for s in node.body:
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                continue
            self.visit(s)
        self.inserter.set_insertion_point_from_block(saved)

    # -- expressions --

    def visit_Constant(self, node: ast.Constant) -> None:
        match node.value:
            case bool() as v:
                self.inserter.insert_op(ConstantOp(1 if v else 0, i1))
            case int() as v:
                self.inserter.insert_op(ConstantOp(v, i64))
            case _:
                raise self._err(node, f"unsupported constant: {node.value!r}")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.locals_:
            self.inserter.insert_op(VarRefOp(node.id, self.scope.get(node.id, i64)))
        else:
            self.inserter.insert_op(ParamRefOp(node.id, self.scope.get(node.id, i64)))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if not isinstance(node.op, ast.USub):
            raise self._err(node, f"unsupported unary op: {type(node.op).__name__}")
        self.visit(node.operand)
        self.inserter.insert_op(NegOp(self.inserter.get_operand(), i64))

    def visit_BinOp(self, node: ast.BinOp) -> None:
        self.visit(node.left)
        lhs = self.inserter.get_operand()
        self.visit(node.right)
        rhs = self.inserter.get_operand()
        s, ty = AST_OP[type(node.op)]
        self.inserter.insert_op(BinOp(s, lhs, rhs, ty))

    def visit_Compare(self, node: ast.Compare) -> None:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise self._err(node, "only single comparisons supported")
        self.visit(node.left)
        lhs = self.inserter.get_operand()
        self.visit(node.comparators[0])
        rhs = self.inserter.get_operand()
        s, ty = AST_OP[type(node.ops[0])]
        self.inserter.insert_op(BinOp(s, lhs, rhs, ty))

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.visit(node.values[0])
        lhs = self.inserter.get_operand()
        self.visit(node.values[1])
        rhs = self.inserter.get_operand()
        s, ty = AST_OP[type(node.op)]
        self.inserter.insert_op(BinOp(s, lhs, rhs, ty))

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            raise self._err(node, "only simple function calls supported")
        args = []
        for a in node.args:
            self.visit(a)
            args.append(self.inserter.get_operand())
        self.inserter.insert_op(CallOp(node.func.id, args, i64))

    # -- statements --

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise self._err(node, "only single-name assignment supported")
        name = node.targets[0].id
        self.visit(node.value)
        val = self.inserter.get_operand()
        is_decl = name not in self.locals_ and name not in self.scope
        self.inserter.insert_op(AssignOp(name, val, is_decl))
        self.scope[name] = i64
        self.locals_.add(name)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is None:
            raise self._err(node, "return without value not supported")
        self.visit(node.value)
        self.inserter.insert_op(ReturnOp(self.inserter.get_operand()))

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        cond = self.inserter.get_operand()
        saved = self.inserter.insertion_point

        then_region = Region([Block()])
        self.inserter.set_insertion_point_from_region(then_region)
        for s in node.body:
            self.visit(s)

        else_region = None
        if node.orelse:
            else_region = Region([Block()])
            self.inserter.set_insertion_point_from_region(else_region)
            for s in node.orelse:
                self.visit(s)

        self.inserter.set_insertion_point_from_block(saved)
        self.inserter.insert_op(IfOp(cond, then_region, else_region))

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Constant):
            return
        self.visit(node.value)
        if self.inserter.stack:
            self.inserter.get_operand()

    def visit_Assert(self, node: ast.Assert) -> None:
        self.visit(node.test)
        self.inserter.insert_op(AssertOp(self.inserter.get_operand()))

    def visit_While(self, node: ast.While) -> None:
        saved = self.inserter.insertion_point

        cond_block = Block()
        self.inserter.set_insertion_point_from_block(cond_block)
        self.visit(node.test)
        self.inserter.insert_op(YieldOp(self.inserter.get_operand()))
        cond_region = Region([cond_block])

        body_block = Block()
        self.inserter.set_insertion_point_from_block(body_block)
        invariants, decreases_list = _extract_loop_annotations(self.source, node)
        for inv_str in invariants:
            self._emit_spec_op(InvariantOp, inv_str)
        for dec_str in decreases_list:
            self._emit_spec_op(DecreasesOp, dec_str)
        for s in node.body:
            self.visit(s)
        body_region = Region([body_block])

        self.inserter.set_insertion_point_from_block(saved)
        self.inserter.insert_op(WhileOp(cond_region, body_region))


def ingest(source: str, file: str | None = None) -> ModuleOp:
    module = ModuleOp([])
    visitor = PyASTVisitor(module, source, file)
    visitor.visit(ast.parse(source))
    return module


#
# resolve pass: py -> verif
#


class _FuncRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: FuncOp, rewriter: PatternRewriter) -> None:
        new_body = rewriter.move_region_contents_to_new_regions(op.body)
        rewriter.replace_matched_op(VerifFuncOp(op.sym_name.data, [n.data for n in op.param_names], op.function_type, body=new_body))


class _ConstantRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ConstantOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifConstantOp(op.value, op.result.type))


class _ParamRefRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ParamRefOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifParamRefOp(op.param_name, op.result.type))


class _NegRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: NegOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifNegOp(op.operand, op.result.type))


class _ReturnRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ReturnOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifReturnOp(op.value))


class _IfRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: IfOp, rewriter: PatternRewriter) -> None:
        new_then = rewriter.move_region_contents_to_new_regions(op.then_region)
        new_else = rewriter.move_region_contents_to_new_regions(op.else_region)
        rewriter.replace_matched_op(VerifIfOp(op.cond, new_then, new_else))


class _BinOpRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: BinOp, rewriter: PatternRewriter) -> None:
        cls = VERIF_BIN_BY_KIND[op.op_kind.data]
        rewriter.replace_matched_op(cls(op.lhs, op.rhs, op.result.type))


class _YieldRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: YieldOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifYieldOp(op.value))


class _RequiresRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: RequiresOp, rewriter: PatternRewriter) -> None:
        new_region = rewriter.move_region_contents_to_new_regions(op.cond_region)
        rewriter.replace_matched_op(VerifRequiresOp(new_region))


class _EnsuresRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: EnsuresOp, rewriter: PatternRewriter) -> None:
        new_region = rewriter.move_region_contents_to_new_regions(op.cond_region)
        rewriter.replace_matched_op(VerifEnsuresOp(new_region))


class _InvariantRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: InvariantOp, rewriter: PatternRewriter) -> None:
        new_region = rewriter.move_region_contents_to_new_regions(op.cond_region)
        rewriter.replace_matched_op(VerifInvariantOp(new_region))


class _DecreasesRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DecreasesOp, rewriter: PatternRewriter) -> None:
        new_region = rewriter.move_region_contents_to_new_regions(op.expr_region)
        rewriter.replace_matched_op(VerifDecreasesOp(new_region))


class _AssignRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AssignOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifAssignOp(op.var_name, op.is_decl, op.value))


class _VarRefRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: VarRefOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifVarRefOp(op.var_name, op.result.type))


class _CallRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: CallOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifCallOp(op.callee, list(op.arguments), op.result.type))


class _AssertRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AssertOp, rewriter: PatternRewriter) -> None:
        rewriter.replace_matched_op(VerifAssertOp(op.cond))


class _WhileRewrite(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: WhileOp, rewriter: PatternRewriter) -> None:
        new_cond = rewriter.move_region_contents_to_new_regions(op.cond_region)
        new_body = rewriter.move_region_contents_to_new_regions(op.body)
        rewriter.replace_matched_op(VerifWhileOp(new_cond, new_body))


def resolve(module: ModuleOp) -> ModuleOp:
    walker = PatternRewriteWalker(GreedyRewritePatternApplier([
        _FuncRewrite(), _ConstantRewrite(), _ParamRefRewrite(), _NegRewrite(),
        _ReturnRewrite(), _IfRewrite(), _BinOpRewrite(),
        _YieldRewrite(), _RequiresRewrite(), _EnsuresRewrite(),
        _InvariantRewrite(), _DecreasesRewrite(),
        _AssignRewrite(), _VarRefRewrite(), _CallRewrite(), _AssertRewrite(),
        _WhileRewrite(),
    ]))
    walker.rewrite_module(module)
    return module


@dataclass(frozen=True)
class ResolvePass(ModulePass):
    name = "resolve"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        resolve(op)


#
# dafny lowering
#

PREC_OR = 1
PREC_AND = 2
PREC_EQ = 3
PREC_CMP = 4
PREC_ADD = 5
PREC_MUL = 6
PREC_UNARY = 7
PREC_ATOM = 8


@dataclass
class DfyExpr:
    text: str
    prec: int


VERIF_BIN_INFO: dict[type, tuple[str, int]] = {
    VerifOrOp: ("||", PREC_OR), VerifAndOp: ("&&", PREC_AND),
    VerifEqOp: ("==", PREC_EQ), VerifNeOp: ("!=", PREC_EQ),
    VerifLtOp: ("<", PREC_CMP), VerifLeOp: ("<=", PREC_CMP),
    VerifGtOp: (">", PREC_CMP), VerifGeOp: (">=", PREC_CMP),
    VerifAddOp: ("+", PREC_ADD), VerifSubOp: ("-", PREC_ADD),
    VerifMulOp: ("*", PREC_MUL), VerifFloorDivOp: ("/", PREC_MUL), VerifModOp: ("%", PREC_MUL),
}


@dataclass
class DfyVarDecl:
    name: str
    expr: str


@dataclass
class DfyAssign:
    name: str
    expr: str


@dataclass
class DfyAssert:
    expr: str


@dataclass
class DfyReturn:
    ret_var: str
    expr: str


@dataclass
class DfyIf:
    cond: str
    then_body: list
    else_body: list


@dataclass
class DfyWhile:
    cond: str
    invariants: list
    decreases: list
    body: list


@dataclass
class DfyMethod:
    name: str
    params: list
    ret_var: str
    ret_type: str
    requires: list
    ensures: list
    body: list


def _lower_dfy_expr_region(region: Region) -> str:
    exprs: dict[SSAValue, DfyExpr] = {}
    _lower_dfy_ops(region.block.ops, exprs)
    for op in region.block.ops:
        if isinstance(op, VerifYieldOp):
            return exprs[op.value].text
    raise ValueError("region missing verif.yield")


def _lower_dfy_ops(ops: Iterable[Operation], exprs: dict[SSAValue, DfyExpr]) -> list:
    stmts: list = []
    for op in ops:
        if type(op) in VERIF_BIN_INFO:
            sym, prec = VERIF_BIN_INFO[type(op)]
            l, r = exprs[op.lhs], exprs[op.rhs]
            lt = f"({l.text})" if l.prec < prec else l.text
            rt = f"({r.text})" if r.prec <= prec else r.text
            exprs[op.result] = DfyExpr(f"{lt} {sym} {rt}", prec)
            continue
        match op:
            case VerifConstantOp():
                if op.value.type.width.data == 1:
                    text = "true" if op.value.value.data else "false"
                else:
                    text = str(op.value.value.data)
                exprs[op.result] = DfyExpr(text, PREC_ATOM)
            case VerifParamRefOp():
                name = op.param_name.data
                if name == "result":
                    name = "r"
                exprs[op.result] = DfyExpr(name, PREC_ATOM)
            case VerifVarRefOp():
                exprs[op.result] = DfyExpr(op.var_name.data, PREC_ATOM)
            case VerifNegOp():
                inner = exprs[op.operand]
                text = f"-{inner.text}" if inner.prec >= PREC_UNARY else f"-({inner.text})"
                exprs[op.result] = DfyExpr(text, PREC_UNARY)
            case VerifCallOp():
                args = ", ".join(exprs[a].text for a in op.arguments)
                exprs[op.result] = DfyExpr(f"{op.callee.data}({args})", PREC_ATOM)
            case VerifAssignOp():
                if op.is_decl.value.data:
                    stmts.append(DfyVarDecl(op.var_name.data, exprs[op.value].text))
                else:
                    stmts.append(DfyAssign(op.var_name.data, exprs[op.value].text))
            case VerifAssertOp():
                stmts.append(DfyAssert(exprs[op.cond].text))
            case VerifReturnOp():
                stmts.append(DfyReturn("r", exprs[op.value].text))
            case VerifIfOp():
                then_stmts = _lower_dfy_ops(op.then_region.block.ops, exprs)
                else_stmts = _lower_dfy_ops(op.else_region.block.ops, exprs) if len(op.else_region.blocks) > 0 else []
                stmts.append(DfyIf(exprs[op.cond].text, then_stmts, else_stmts))
            case VerifWhileOp():
                cond_str = _lower_dfy_expr_region(op.cond_region)
                invariants = []
                decreases_list = []
                body_ops = []
                for inner_op in op.body.block.ops:
                    match inner_op:
                        case VerifInvariantOp():
                            invariants.append(_lower_dfy_expr_region(inner_op.cond_region))
                        case VerifDecreasesOp():
                            decreases_list.append(_lower_dfy_expr_region(inner_op.expr_region))
                        case _:
                            body_ops.append(inner_op)
                body_stmts = _lower_dfy_ops(body_ops, exprs)
                stmts.append(DfyWhile(cond_str, invariants, decreases_list, body_stmts))
            case VerifYieldOp() | VerifRequiresOp() | VerifEnsuresOp():
                pass
    return stmts


def _lower_dfy_func(func: VerifFuncOp) -> DfyMethod:
    param_names = [attr.data for attr in func.param_names]
    param_types = list(func.function_type.inputs)
    params = [(name, "bool" if ty.width.data == 1 else "int") for name, ty in zip(param_names, param_types)]
    ret_type = list(func.function_type.outputs)[0]

    requires = []
    ensures = []
    body_ops = []
    for op in func.body.block.ops:
        match op:
            case VerifRequiresOp():
                requires.append(_lower_dfy_expr_region(op.cond_region))
            case VerifEnsuresOp():
                ensures.append(_lower_dfy_expr_region(op.cond_region))
            case _:
                body_ops.append(op)

    exprs: dict[SSAValue, DfyExpr] = {}
    body = _lower_dfy_ops(body_ops, exprs)
    return DfyMethod(
        func.sym_name.data, params, "r",
        "bool" if ret_type.width.data == 1 else "int",
        requires, ensures, body,
    )


def lower_to_dafny(module: ModuleOp) -> list[DfyMethod]:
    return [_lower_dfy_func(op) for op in module.body.block.ops if isinstance(op, VerifFuncOp)]


def _fmt_dfy_stmts(stmts: list, indent: str) -> list[str]:
    lines: list[str] = []
    for stmt in stmts:
        match stmt:
            case DfyVarDecl(name, expr):
                lines.append(f"{indent}var {name} := {expr};")
            case DfyAssign(name, expr):
                lines.append(f"{indent}{name} := {expr};")
            case DfyAssert(expr):
                lines.append(f"{indent}assert {expr};")
            case DfyReturn(ret_var, expr):
                lines.append(f"{indent}{ret_var} := {expr};")
                lines.append(f"{indent}return;")
            case DfyIf(cond, then_body, else_body):
                lines.append(f"{indent}if {cond} {{")
                lines.extend(_fmt_dfy_stmts(then_body, indent + "  "))
                lines.append(f"{indent}}}")
                if else_body:
                    lines.extend(_fmt_dfy_stmts(else_body, indent))
            case DfyWhile(cond, invariants, decreases, body):
                lines.append(f"{indent}while {cond}")
                for inv in invariants:
                    lines.append(f"{indent}  invariant {inv}")
                for dec in decreases:
                    lines.append(f"{indent}  decreases {dec}")
                lines.append(f"{indent}{{")
                lines.extend(_fmt_dfy_stmts(body, indent + "  "))
                lines.append(f"{indent}}}")
    return lines


def _fmt_dfy_method(m: DfyMethod) -> str:
    params = ", ".join(f"{n}: {t}" for n, t in m.params)
    lines = [f"method {m.name}({params}) returns ({m.ret_var}: {m.ret_type})"]
    for r in m.requires:
        lines.append(f"  requires {r}")
    for e in m.ensures:
        lines.append(f"  ensures {e}")
    lines.append("{")
    lines.extend(_fmt_dfy_stmts(m.body, "  "))
    lines.append("}")
    return "\n".join(lines)


def print_dafny(module: ModuleOp) -> str:
    return "\n".join(_fmt_dfy_method(m) for m in lower_to_dafny(module))


#
# targets
#


@dataclass(frozen=True)
class DafnyTarget(Target):
    name = "dfy"

    def emit(self, ctx: Context, module: ModuleOp, output: IO[str]) -> None:
        output.write(print_dafny(module))
        output.write("\n")


#
# cli
#


class VeriPyMain(xDSLOptMain):
    def register_all_dialects(self):
        self.ctx.register_dialect("py", lambda: Py)
        self.ctx.register_dialect("verif", lambda: Verif)

    def register_all_frontends(self):
        super().register_all_frontends()

        def parse_python(io: IO[str]):
            return ingest(io.read(), self.get_input_name())

        self.available_frontends["py"] = parse_python

    def register_all_passes(self):
        super().register_all_passes()
        self.register_pass("resolve", lambda: ResolvePass)

    def register_all_targets(self):
        super().register_all_targets()
        self.available_targets["dfy"] = lambda: DafnyTarget

    def register_all_arguments(self, arg_parser: argparse.ArgumentParser):
        super().register_all_arguments(arg_parser)
        arg_parser.add_argument("--verify", default=False, action="store_true", help="Compile to Dafny and verify via Docker")

    def apply_passes(self, prog: ModuleOp) -> bool:
        self.pipeline.apply(self.ctx, prog)
        return True

    def run(self):
        if not self.args.verify:
            super().run()
            return
        chunks, ext = self.prepare_input()
        for chunk, offset in chunks:
            module = self.parse_chunk(chunk, ext, offset)
            if module is None:
                continue
            ResolvePass().apply(self.ctx, module)
            dfy = print_dafny(module)
            dfy_path = Path(self.args.input_file).with_suffix(".dfy")
            dfy_path.write_text(dfy + "\n")
            result = subprocess.run(["docker", "run", "--rm", "-v", f"{dfy_path.parent}:/work", "-w", "/work", "veripy-dafny", "dafny", "verify", dfy_path.name], capture_output=True, text=True)
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode)


def cli():
    VeriPyMain(description="VeriPy: Python to Dafny verification compiler").run()
