import ast
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from io import StringIO
from re import compile as re_compile
from typing import IO

from xdsl.dialects.builtin import IntegerType, ModuleOp
from xdsl.frontend.pyast.utils.exceptions import CodeGenerationException
from xdsl.frontend.pyast.utils.op_inserter import OpInserter
from xdsl.ir import Block, Operation, Region, SSAValue
import click
from xdsl.utils.base_printer import BasePrinter

from veripy.ops_py import AssertOp, AssignOp, BinOp, CallOp, ConstantOp, DecreasesOp, EnsuresOp, FuncOp, IfOp, InvariantOp, NegOp, ParamRefOp, RequiresOp, ReturnOp, VarRefOp, WhileOp, YieldOp

#
# parser
#

class Parser(ast.NodeVisitor):
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

    def _extract_annotations(self, node: ast.stmt, keywords: set[str]) -> dict[str, list[str]]:
        annotation_re = re_compile(r"^\s*#@\s+(requires|ensures|invariant|decreases)\s+(.*?)\s*$")
        lines = self.source.splitlines()
        result: dict[str, list[str]] = {k: [] for k in keywords}
        for lineno in range(node.lineno, node.end_lineno or node.lineno + 1):
            line = lines[lineno - 1] if lineno <= len(lines) else ""
            m = annotation_re.match(line)
            if not m:
                continue
            keyword, expr = m.group(1), m.group(2)
            if keyword in result:
                result[keyword].append(expr)
        return result

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
        anns = self._extract_annotations(node, {"requires", "ensures"})
        param_names = [arg.arg for arg in node.args.args]
        param_types = [IntegerType(1) if isinstance(a.annotation, ast.Name) and a.annotation.id == "bool" else IntegerType(64) for a in node.args.args]
        return_type = [IntegerType(1) if isinstance(node.returns, ast.Name) and node.returns.id == "bool" else IntegerType(64)] if node.returns else []
        self.scope = dict(zip(param_names, param_types))
        self.locals_ = set()

        body_block = Block()
        func_op = FuncOp(node.name, param_names, (param_types, return_type), body=Region([body_block]))
        saved = self.inserter.insertion_point
        self.inserter.insert_op(func_op)
        self.inserter.set_insertion_point_from_block(body_block)
        for req in anns["requires"]:
            self._emit_spec_op(RequiresOp, req)
        for ens in anns["ensures"]:
            self._emit_spec_op(EnsuresOp, ens)
        for s in node.body:
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                continue
            self.visit(s)
        self.inserter.set_insertion_point_from_block(saved)

    def visit_Constant(self, node: ast.Constant) -> None:
        match node.value:
            case bool() as v:
                self.inserter.insert_op(ConstantOp(1 if v else 0, IntegerType(1)))
            case int() as v:
                self.inserter.insert_op(ConstantOp(v, IntegerType(64)))
            case _:
                raise self._err(node, f"unsupported constant: {node.value!r}")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.locals_:
            self.inserter.insert_op(VarRefOp(node.id, self.scope.get(node.id, IntegerType(64))))
        else:
            self.inserter.insert_op(ParamRefOp(node.id, self.scope.get(node.id, IntegerType(64))))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if not isinstance(node.op, ast.USub):
            raise self._err(node, f"unsupported unary op: {type(node.op).__name__}")
        self.visit(node.operand)
        self.inserter.insert_op(NegOp(self.inserter.get_operand(), IntegerType(64)))

    def visit_BinOp(self, node: ast.BinOp) -> None:
        ast_op: dict[type[ast.operator], tuple[str, IntegerType]] = {ast.Add: ("add", IntegerType(64)), ast.Sub: ("sub", IntegerType(64)), ast.Mult: ("mul", IntegerType(64)), ast.FloorDiv: ("floordiv", IntegerType(64)), ast.Mod: ("mod", IntegerType(64))}
        self.visit(node.left)
        lhs = self.inserter.get_operand()
        self.visit(node.right)
        rhs = self.inserter.get_operand()
        s, ty = ast_op[type(node.op)]
        self.inserter.insert_op(BinOp(s, lhs, rhs, ty))

    def visit_Compare(self, node: ast.Compare) -> None:
        ast_op: dict[type[ast.cmpop], tuple[str, IntegerType]] = {ast.Eq: ("eq", IntegerType(1)), ast.NotEq: ("ne", IntegerType(1)), ast.Lt: ("lt", IntegerType(1)), ast.LtE: ("le", IntegerType(1)), ast.Gt: ("gt", IntegerType(1)), ast.GtE: ("ge", IntegerType(1))}
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise self._err(node, "only single comparisons supported")
        self.visit(node.left)
        lhs = self.inserter.get_operand()
        self.visit(node.comparators[0])
        rhs = self.inserter.get_operand()
        s, ty = ast_op[type(node.ops[0])]
        self.inserter.insert_op(BinOp(s, lhs, rhs, ty))

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        ast_op: dict[type[ast.boolop], tuple[str, IntegerType]] = {ast.And: ("and", IntegerType(1)), ast.Or: ("or", IntegerType(1))}
        self.visit(node.values[0])
        lhs = self.inserter.get_operand()
        self.visit(node.values[1])
        rhs = self.inserter.get_operand()
        s, ty = ast_op[type(node.op)]
        self.inserter.insert_op(BinOp(s, lhs, rhs, ty))

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            raise self._err(node, "only simple function calls supported")
        args: list[SSAValue] = []
        for a in node.args:
            self.visit(a)
            args.append(self.inserter.get_operand())
        self.inserter.insert_op(CallOp(node.func.id, args, IntegerType(64)))

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise self._err(node, "only single-name assignment supported")
        name = node.targets[0].id
        self.visit(node.value)
        val = self.inserter.get_operand()
        is_decl = name not in self.locals_ and name not in self.scope
        self.inserter.insert_op(AssignOp(name, val, is_decl))
        self.scope[name] = IntegerType(64)
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
        anns = self._extract_annotations(node, {"invariant", "decreases"})
        for inv_str in anns["invariant"]:
            self._emit_spec_op(InvariantOp, inv_str)
        for dec_str in anns["decreases"]:
            self._emit_spec_op(DecreasesOp, dec_str)
        for s in node.body:
            self.visit(s)
        body_region = Region([body_block])

        self.inserter.set_insertion_point_from_block(saved)
        self.inserter.insert_op(WhileOp(cond_region, body_region))

    @staticmethod
    def parse(source: str, file: str | None = None) -> ModuleOp:
        module = ModuleOp([])
        visitor = Parser(module, source, file)
        visitor.visit(ast.parse(source))
        return module


#
# dafny lowering
#

@dataclass
class DfyExpr:
    text: str
    prec: int


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
        params = ", ".join(f"{name}: {'bool' if ty == IntegerType(1) else 'int'}" for name, ty in zip(param_names, param_types))
        ret_attr = list(func.function_type.outputs)[0]
        ret_type_str = "bool" if ret_attr == IntegerType(1) else "int"

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
        binop_info = {"or": ("||", 1), "and": ("&&", 2), "eq": ("==", 3), "ne": ("!=", 3), "lt": ("<", 4), "le": ("<=", 4), "gt": (">", 4), "ge": (">=", 4), "add": ("+", 5), "sub": ("-", 5), "mul": ("*", 6), "floordiv": ("/", 6), "mod": ("%", 6)}
        match op:
            case BinOp():
                sym, prec = binop_info[op.op_kind.data]
                l, r = self.exprs[op.lhs], self.exprs[op.rhs]
                lt = f"({l.text})" if l.prec < prec else l.text
                rt = f"({r.text})" if r.prec <= prec else r.text
                self.exprs[op.result] = DfyExpr(f"{lt} {sym} {rt}", prec)
            case ConstantOp():
                if op.value.type == IntegerType(1):
                    text = "true" if op.value.value.data else "false"
                else:
                    text = str(op.value.value.data)
                self.exprs[op.result] = DfyExpr(text, 8)
            case ParamRefOp():
                name = op.param_name.data
                if name == "result":
                    name = "r"
                self.exprs[op.result] = DfyExpr(name, 8)
            case VarRefOp():
                self.exprs[op.result] = DfyExpr(op.var_name.data, 8)
            case NegOp():
                inner = self.exprs[op.operand]
                text = f"-{inner.text}" if inner.prec >= 7 else f"-({inner.text})"
                self.exprs[op.result] = DfyExpr(text, 7)
            case CallOp():
                args = ", ".join(self.exprs[a].text for a in op.arguments)
                self.exprs[op.result] = DfyExpr(f"{op.callee.data}({args})", 8)
            case _:
                pass

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
            case _:
                pass

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


#
# cli
#


@click.command()
@click.argument("input", default="-")
@click.option("--verify", is_flag=True, help="Compile to Dafny and verify via Docker")
def cli(input: str, verify: bool) -> None:
    source = sys.stdin.read() if input == "-" else open(input).read()
    buf = StringIO()
    DafnyPrinter(buf).print_module(Parser.parse(source, None if input == "-" else input))
    dfy = buf.getvalue()

    if not verify:
        print(dfy)
        return

    result = subprocess.run(["docker", "run", "--rm", "-i", "--platform", "linux/amd64", "xtrm0/dafny:4.9.1", "sh", "-c", "cat > /tmp/out.dfy && dafny verify /tmp/out.dfy"], input=dfy + "\n", capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
