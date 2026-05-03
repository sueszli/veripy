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


# TODO(xdsl-upstream): verif dialect with first-class assert/invariant/decreases/requires/ensures ops
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


# TODO(xdsl-upstream): scf.SimpleWhileOp with imperative semantics (current scf.WhileOp requires SSA loop-carried values)
@irdl_op_definition
class WhileOp(IRDLOperation):
    name = "py.while"
    cond_text = prop_def(StringAttr)
    invariants = prop_def(ArrayAttr[StringAttr])
    decreases = prop_def(ArrayAttr[StringAttr])
    body = region_def()

    def __init__(self, cond_text: str, body: Region, *, invariants: Sequence[str] | None = None, decreases: Sequence[str] | None = None):
        super().__init__(properties={"cond_text": StringAttr(cond_text), "invariants": ArrayAttr([StringAttr(s) for s in (invariants or [])]), "decreases": ArrayAttr([StringAttr(s) for s in (decreases or [])])}, regions=[body])


Py = Dialect("py", [FuncOp, ConstantOp, ParamRefOp, BinOp, NegOp, IfOp, ReturnOp, AssertOp, CallOp, AssignOp, VarRefOp, WhileOp], [])


#
# verif dialect
#
# Mirrors py but with typed-per-operator binary ops: the string op_kind in
# py.binop is split into one verif op per operator. Spec strings stay as
# StringAttr for now (structured spec lowering is a follow-up).


@irdl_op_definition
class VerifFuncOp(IRDLOperation):
    name = "verif.func"
    sym_name = prop_def(StringAttr)
    function_type = prop_def(FunctionType)
    param_names = prop_def(ArrayAttr[StringAttr])
    requires = prop_def(ArrayAttr[StringAttr])
    ensures = prop_def(ArrayAttr[StringAttr])
    body = region_def()
    traits = traits_def(IsolatedFromAbove())

    def __init__(self, func_name: str, param_names: Sequence[str], function_type: FunctionType, *, requires: ArrayAttr[StringAttr], ensures: ArrayAttr[StringAttr], body: Region):
        super().__init__(properties={"sym_name": StringAttr(func_name), "function_type": function_type, "param_names": ArrayAttr([StringAttr(n) for n in param_names]), "requires": requires, "ensures": ensures}, regions=[body])


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
    "add": VerifAddOp,
    "sub": VerifSubOp,
    "mul": VerifMulOp,
    "floordiv": VerifFloorDivOp,
    "mod": VerifModOp,
    "eq": VerifEqOp,
    "ne": VerifNeOp,
    "lt": VerifLtOp,
    "le": VerifLeOp,
    "gt": VerifGtOp,
    "ge": VerifGeOp,
    "and": VerifAndOp,
    "or": VerifOrOp,
}

VERIF_BIN_SYMBOL: dict[type, str] = {
    VerifAddOp: "+",
    VerifSubOp: "-",
    VerifMulOp: "*",
    VerifFloorDivOp: "/",
    VerifModOp: "%",
    VerifEqOp: "==",
    VerifNeOp: "!=",
    VerifLtOp: "<",
    VerifLeOp: "<=",
    VerifGtOp: ">",
    VerifGeOp: ">=",
    VerifAndOp: "&&",
    VerifOrOp: "||",
}

Verif = Dialect("verif", [VerifFuncOp, VerifConstantOp, VerifParamRefOp, VerifNegOp, VerifIfOp, VerifReturnOp, *VERIF_BIN_BY_KIND.values()], [])


#
# ingestor
#

i64 = IntegerType(64)
i1 = IntegerType(1)

ANNOTATION_RE = re.compile(r"^\s*#@\s+(requires|ensures|invariant|decreases)\s+(.*?)\s*$")

AST_OP: dict[type, tuple[str, IntegerType]] = {
    ast.Eq: ("eq", i1),
    ast.NotEq: ("ne", i1),
    ast.Lt: ("lt", i1),
    ast.LtE: ("le", i1),
    ast.Gt: ("gt", i1),
    ast.GtE: ("ge", i1),
    ast.Add: ("add", i64),
    ast.Sub: ("sub", i64),
    ast.Mult: ("mul", i64),
    ast.FloorDiv: ("floordiv", i64),
    ast.Mod: ("mod", i64),
    ast.And: ("and", i1),
    ast.Or: ("or", i1),
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
        func_op = FuncOp(node.name, param_names, (param_types, return_type), requires=requires, ensures=ensures, body=Region([body_block]))
        saved = self.inserter.insertion_point
        self.inserter.insert_op(func_op)
        self.inserter.set_insertion_point_from_block(body_block)
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
        invariants, decreases_list = _extract_loop_annotations(self.source, node)
        saved = self.inserter.insertion_point

        body_region = Region([Block()])
        self.inserter.set_insertion_point_from_region(body_region)
        for s in node.body:
            self.visit(s)

        self.inserter.set_insertion_point_from_block(saved)
        self.inserter.insert_op(WhileOp(ast.unparse(node.test), body_region, invariants=invariants, decreases=decreases_list))


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
        rewriter.replace_matched_op(VerifFuncOp(op.sym_name.data, [n.data for n in op.param_names], op.function_type, requires=op.requires, ensures=op.ensures, body=new_body))


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


def resolve(module: ModuleOp) -> ModuleOp:
    walker = PatternRewriteWalker(GreedyRewritePatternApplier([_FuncRewrite(), _ConstantRewrite(), _ParamRefRewrite(), _NegRewrite(), _ReturnRewrite(), _IfRewrite(), _BinOpRewrite()]))
    walker.rewrite_module(module)
    return module


#
# printer (consumes verif)
#


def _rewrite_spec(clause: str) -> str:
    return re.sub(r"\band\b", "&&", re.sub(r"\bor\b", "||", re.sub(r"\bresult\b", "r", clause)))


def print_dafny(module: ModuleOp) -> str:
    return "\n".join(_print_func(op) for op in module.body.block.ops if isinstance(op, VerifFuncOp))


def _print_func(func: VerifFuncOp) -> str:
    param_names = [attr.data for attr in func.param_names]
    param_types = list(func.function_type.inputs)
    params = [f"{name}: {'bool' if ty.width.data == 1 else 'int'}" for name, ty in zip(param_names, param_types)]
    ret_type = list(func.function_type.outputs)[0]

    lines = [f"method {func.sym_name.data}({', '.join(params)}) returns (r: {'bool' if ret_type.width.data == 1 else 'int'})"]

    for clause in func.requires:
        lines.append(f"  requires {_rewrite_spec(clause.data)}")
    for clause in func.ensures:
        lines.append(f"  ensures {_rewrite_spec(clause.data)}")

    lines.append("{")
    exprs: dict[SSAValue, str] = {}
    lines.extend(_emit_ops(func.body.block.ops, exprs, "  "))
    lines.append("}")

    return "\n".join(lines)


def _emit_ops(ops: Iterable[Operation], exprs: dict[SSAValue, str], indent: str) -> list[str]:
    lines: list[str] = []
    for op in ops:
        if type(op) in VERIF_BIN_SYMBOL:
            exprs[op.result] = f"{exprs[op.lhs]} {VERIF_BIN_SYMBOL[type(op)]} {exprs[op.rhs]}"
            continue
        match op:
            case VerifConstantOp():
                if op.value.type.width.data == 1:
                    exprs[op.result] = "true" if op.value.value.data else "false"
                else:
                    exprs[op.result] = str(op.value.value.data)
            case VerifParamRefOp():
                exprs[op.result] = op.param_name.data
            case VarRefOp():
                exprs[op.result] = op.var_name.data
            case VerifNegOp():
                exprs[op.result] = f"-{exprs[op.operand]}"
            case CallOp():
                args = ", ".join(exprs[a] for a in op.arguments)
                exprs[op.result] = f"{op.callee.data}({args})"
            case AssignOp():
                decl = "var " if op.is_decl.value.data else ""
                lines.append(f"{indent}{decl}{op.var_name.data} := {exprs[op.value]};")
            case AssertOp():
                lines.append(f"{indent}assert {exprs[op.cond]};")
            case VerifReturnOp():
                lines.append(f"{indent}r := {exprs[op.value]};")
                lines.append(f"{indent}return;")
            case VerifIfOp():
                lines.append(f"{indent}if {exprs[op.cond]} {{")
                lines.extend(_emit_ops(op.then_region.block.ops, exprs, indent + "  "))
                lines.append(f"{indent}}}")
                if len(op.else_region.blocks) > 0:
                    lines.extend(_emit_ops(op.else_region.block.ops, exprs, indent))
            case WhileOp():
                lines.append(f"{indent}while {_rewrite_spec(op.cond_text.data)}")
                for inv in op.invariants:
                    lines.append(f"{indent}  invariant {_rewrite_spec(inv.data)}")
                for dec in op.decreases:
                    lines.append(f"{indent}  decreases {_rewrite_spec(dec.data)}")
                lines.append(f"{indent}{{")
                lines.extend(_emit_ops(op.body.block.ops, exprs, indent + "  "))
                lines.append(f"{indent}}}")
    return lines


#
# lean printer
# TODO(xdsl-upstream): Lean 4 printer/emitter infrastructure
#

OP_SYMBOLS = {"ge": ">=", "le": "<=", "gt": ">", "lt": "<", "eq": "==", "ne": "!=", "add": "+", "sub": "-", "mul": "*", "and": "&&", "or": "||"}


def print_lean(module: ModuleOp) -> str:
    return "\n\n".join(_print_lean_func(op) for op in module.body.block.ops if isinstance(op, VerifFuncOp))


def _lean_type(ty: IntegerType) -> str:
    return "Bool" if ty.width.data == 1 else "Int"


def _print_lean_func(func: VerifFuncOp) -> str:
    param_names = [attr.data for attr in func.param_names]
    param_types = list(func.function_type.inputs)
    params = " ".join(f"({name} : {_lean_type(ty)})" for name, ty in zip(param_names, param_types))
    ret_type = _lean_type(list(func.function_type.outputs)[0])
    lines = [f"def {func.sym_name.data} {params} : {ret_type} :="]
    for clause in func.requires:
        lines.append(f"  -- requires {clause.data}")
    for clause in func.ensures:
        lines.append(f"  -- ensures {clause.data}")
    exprs: dict[SSAValue, str] = {}
    lines.extend(_emit_lean_ops(func.body.block.ops, exprs, "  "))
    return "\n".join(lines)


def _emit_lean_ops(ops: Iterable[Operation], exprs: dict[SSAValue, str], indent: str) -> list[str]:
    lines: list[str] = []
    for op in ops:
        if type(op) in VERIF_BIN_SYMBOL:
            exprs[op.result] = f"{exprs[op.lhs]} {VERIF_BIN_SYMBOL[type(op)]} {exprs[op.rhs]}"
            continue
        match op:
            case VerifConstantOp():
                if op.value.type.width.data == 1:
                    exprs[op.result] = "true" if op.value.value.data else "false"
                else:
                    exprs[op.result] = str(op.value.value.data)
            case VerifParamRefOp():
                exprs[op.result] = op.param_name.data
            case VarRefOp():
                exprs[op.result] = op.var_name.data
            case VerifNegOp():
                exprs[op.result] = f"-{exprs[op.operand]}"
            case CallOp():
                args = " ".join(exprs[a] for a in op.arguments)
                exprs[op.result] = f"{op.callee.data} {args}" if args else op.callee.data
            case AssignOp():
                decl = "let mut " if op.is_decl.value.data else ""
                lines.append(f"{indent}{decl}{op.var_name.data} := {exprs[op.value]}")
            case AssertOp():
                lines.append(f"{indent}assert {exprs[op.cond]}")
            case VerifReturnOp():
                lines.append(f"{indent}{exprs[op.value]}")
            case VerifIfOp():
                lines.append(f"{indent}if {exprs[op.cond]} then")
                lines.extend(_emit_lean_ops(op.then_region.block.ops, exprs, indent + "  "))
                if len(op.else_region.blocks) > 0 and list(op.else_region.block.ops):
                    lines.append(f"{indent}else")
                    lines.extend(_emit_lean_ops(op.else_region.block.ops, exprs, indent))
            case WhileOp():
                lines.append(f"{indent}while {op.cond_text.data} do")
                for inv in op.invariants:
                    lines.append(f"{indent}  invariant {inv.data}")
                for dec in op.decreases:
                    lines.append(f"{indent}  decreasing {dec.data}")
                lines.extend(_emit_lean_ops(op.body.block.ops, exprs, indent + "  "))
    return lines


#
# cli
#


def _llm_add_proof(dfy_source: str, error: str) -> str:
    try:
        import anthropic
    except ImportError:
        click.echo("anthropic package required for --regen (pip install anthropic)", err=True)
        sys.exit(1)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": f"This Dafny program fails verification:\n\n```dafny\n{dfy_source}\n```\n\nError:\n```\n{error}\n```\n\nFix the program by adding assertions, lemma calls, or strengthening invariants. Return ONLY the complete fixed Dafny source, no explanation."}],
    )
    return response.content[0].text


@click.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--ir-py", "fmt", flag_value="ir-py", help="Print py-dialect IR (pre-resolve)")
@click.option("--ir", "fmt", flag_value="ir", help="Print verif-dialect IR (post-resolve)")
@click.option("--dfy", "fmt", flag_value="dfy", help="Print Dafny source")
@click.option("--lean", "fmt", flag_value="lean", help="Print Lean 4 source")
@click.option("--regen", is_flag=True, help="On verify failure, use LLM to add proof annotations and retry")
def cli(file: Path, fmt: str | None, regen: bool):
    source = Path(file).read_text()
    module = ingest(source)
    if fmt == "ir-py":
        Printer().print(module)
        return
    resolve(module)
    if fmt == "ir":
        Printer().print(module)
        return
    if fmt == "lean":
        click.echo(print_lean(module))
        return
    dfy = print_dafny(module)
    if fmt == "dfy":
        click.echo(dfy)
        return
    dfy_path = Path(file).with_suffix(".dfy")
    dfy_path.write_text(dfy + "\n")
    result = subprocess.run(["docker", "run", "--rm", "-v", f"{dfy_path.parent}:/work", "-w", "/work", "veripy-dafny", "dafny", "verify", dfy_path.name], capture_output=True, text=True)
    if result.returncode == 0 or not regen:
        if result.stdout:
            click.echo(result.stdout)
        if result.stderr:
            click.echo(result.stderr, err=True)
        sys.exit(result.returncode)
    for attempt in range(3):
        click.echo(f"Verification failed, regen attempt {attempt + 1}/3...", err=True)
        error = result.stdout + result.stderr
        dfy = _llm_add_proof(dfy, error)
        dfy_path.write_text(dfy + "\n")
        result = subprocess.run(["docker", "run", "--rm", "-v", f"{dfy_path.parent}:/work", "-w", "/work", "veripy-dafny", "dafny", "verify", dfy_path.name], capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(f"Verification succeeded after {attempt + 1} regen attempt(s).", err=True)
            break
    if result.stdout:
        click.echo(result.stdout)
    if result.stderr:
        click.echo(result.stderr, err=True)
    sys.exit(result.returncode)
