import argparse
import ast
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import StringIO
from re import compile as re_compile
from typing import IO

from xdsl.context import Context
from xdsl.dialects.builtin import ArrayAttr, FunctionType, IntegerAttr, IntegerType, ModuleOp, StringAttr
from xdsl.frontend.pyast.utils.exceptions import CodeGenerationException
from xdsl.frontend.pyast.utils.op_inserter import OpInserter
from xdsl.ir import Block, Dialect, Operation, Region, SSAValue
from xdsl.irdl import IRDLOperation, irdl_op_definition, operand_def, prop_def, region_def, result_def, traits_def, var_operand_def
from xdsl.utils.base_printer import BasePrinter
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


BINOP_INFO: dict[str, tuple[str, int]] = {
    "or": ("||", PREC_OR), "and": ("&&", PREC_AND),
    "eq": ("==", PREC_EQ), "ne": ("!=", PREC_EQ),
    "lt": ("<", PREC_CMP), "le": ("<=", PREC_CMP),
    "gt": (">", PREC_CMP), "ge": (">=", PREC_CMP),
    "add": ("+", PREC_ADD), "sub": ("-", PREC_ADD),
    "mul": ("*", PREC_MUL), "floordiv": ("/", PREC_MUL), "mod": ("%", PREC_MUL),
}


class DafnyPrinter(BasePrinter):
    exprs: dict[SSAValue, DfyExpr]

    def __init__(self, stream: IO[str] | None = None):
        super().__init__(stream)
        self.exprs = {}

    def print_module(self, module: ModuleOp) -> None:
        first = True
        for op in module.body.block.ops:
            if isinstance(op, FuncOp):
                if not first:
                    self.print_string("\n")
                self.print_func(op)
                first = False

    def print_func(self, func: FuncOp) -> None:
        self.exprs = {}
        param_names = [attr.data for attr in func.param_names]
        param_types = list(func.function_type.inputs)
        params = ", ".join(
            f"{name}: {'bool' if ty.width.data == 1 else 'int'}"
            for name, ty in zip(param_names, param_types)
        )
        ret_type = list(func.function_type.outputs)[0]
        ret_type_str = "bool" if ret_type.width.data == 1 else "int"

        self.print_string(f"method {func.sym_name.data}({params}) returns (r: {ret_type_str})")

        body_ops: list[Operation] = []
        for op in func.body.block.ops:
            match op:
                case RequiresOp():
                    self.print_string(f"\n  requires {self._eval_region(op.cond_region)}")
                case EnsuresOp():
                    self.print_string(f"\n  ensures {self._eval_region(op.cond_region)}")
                case _:
                    body_ops.append(op)

        self.print_string("\n{")
        with self.indented():
            self._emit_ops(body_ops)
        self.print_string("\n}")

    def _eval_expr_op(self, op: Operation) -> None:
        match op:
            case BinOp():
                kind = op.op_kind.data
                sym, prec = BINOP_INFO[kind]
                l, r = self.exprs[op.lhs], self.exprs[op.rhs]
                lt = f"({l.text})" if l.prec < prec else l.text
                rt = f"({r.text})" if r.prec <= prec else r.text
                self.exprs[op.result] = DfyExpr(f"{lt} {sym} {rt}", prec)
            case ConstantOp():
                if op.value.type.width.data == 1:
                    text = "true" if op.value.value.data else "false"
                else:
                    text = str(op.value.value.data)
                self.exprs[op.result] = DfyExpr(text, PREC_ATOM)
            case ParamRefOp():
                name = op.param_name.data
                if name == "result":
                    name = "r"
                self.exprs[op.result] = DfyExpr(name, PREC_ATOM)
            case VarRefOp():
                self.exprs[op.result] = DfyExpr(op.var_name.data, PREC_ATOM)
            case NegOp():
                inner = self.exprs[op.operand]
                text = f"-{inner.text}" if inner.prec >= PREC_UNARY else f"-({inner.text})"
                self.exprs[op.result] = DfyExpr(text, PREC_UNARY)
            case CallOp():
                args = ", ".join(self.exprs[a].text for a in op.arguments)
                self.exprs[op.result] = DfyExpr(f"{op.callee.data}({args})", PREC_ATOM)

    def _emit_stmt(self, op: Operation) -> None:
        match op:
            case AssignOp():
                expr = self.exprs[op.value].text
                if op.is_decl.value.data:
                    self.print_string(f"\nvar {op.var_name.data} := {expr};")
                else:
                    self.print_string(f"\n{op.var_name.data} := {expr};")
            case AssertOp():
                self.print_string(f"\nassert {self.exprs[op.cond].text};")
            case ReturnOp():
                self.print_string(f"\nr := {self.exprs[op.value].text};")
                self.print_string("\nreturn;")
            case IfOp():
                self.print_string(f"\nif {self.exprs[op.cond].text} {{")
                with self.indented():
                    self._emit_ops(op.then_region.block.ops)
                self.print_string("\n}")
                if len(op.else_region.blocks) > 0:
                    self._emit_ops(op.else_region.block.ops)
            case WhileOp():
                cond = self._eval_region(op.cond_region)
                invariants: list[str] = []
                decreases_list: list[str] = []
                body_ops: list[Operation] = []
                for inner_op in op.body.block.ops:
                    match inner_op:
                        case InvariantOp():
                            invariants.append(self._eval_region(inner_op.cond_region))
                        case DecreasesOp():
                            decreases_list.append(self._eval_region(inner_op.expr_region))
                        case _:
                            body_ops.append(inner_op)
                self.print_string(f"\nwhile {cond}")
                with self.indented():
                    for inv in invariants:
                        self.print_string(f"\ninvariant {inv}")
                    for dec in decreases_list:
                        self.print_string(f"\ndecreases {dec}")
                self.print_string("\n{")
                with self.indented():
                    self._emit_ops(body_ops)
                self.print_string("\n}")

    def _eval_region(self, region: Region) -> str:
        for op in region.block.ops:
            if op.results:
                self._eval_expr_op(op)
            elif isinstance(op, YieldOp):
                return self.exprs[op.value].text
        raise ValueError("region missing py.yield")

    def _emit_ops(self, ops: Iterable[Operation]) -> None:
        for op in ops:
            if op.results:
                self._eval_expr_op(op)
            elif isinstance(op, (YieldOp, RequiresOp, EnsuresOp)):
                pass
            else:
                self._emit_stmt(op)


def print_dafny(module: ModuleOp) -> str:
    output = StringIO()
    DafnyPrinter(output).print_module(module)
    return output.getvalue()


#
# targets
#


@dataclass(frozen=True)
class DafnyTarget(Target):
    name = "dfy"

    def emit(self, ctx: Context, module: ModuleOp, output: IO[str]) -> None:
        DafnyPrinter(output).print_module(module)
        output.write("\n")


#
# cli
#


class VeriPyMain(xDSLOptMain):
    def register_all_dialects(self):
        self.ctx.register_dialect("py", lambda: Py)

    def register_all_frontends(self):
        super().register_all_frontends()

        def parse_python(io: IO[str]):
            return ingest(io.read(), self.get_input_name())

        self.available_frontends["py"] = parse_python

    def register_all_targets(self):
        super().register_all_targets()
        self.available_targets["dfy"] = lambda: DafnyTarget

    def register_all_arguments(self, arg_parser: argparse.ArgumentParser):
        super().register_all_arguments(arg_parser)
        arg_parser.set_defaults(target="dfy")
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
            dfy = print_dafny(module)
            result = subprocess.run(["docker", "run", "--rm", "-i", "xtrm0/dafny:4.9.1", "sh", "-c", "cat > /tmp/out.dfy && dafny verify /tmp/out.dfy"], input=dfy + "\n", capture_output=True, text=True)
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode)


def cli():
    VeriPyMain(description="VeriPy: Python to Dafny verification compiler").run()
