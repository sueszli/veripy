from collections.abc import Sequence

from xdsl.dialects.builtin import ArrayAttr, FunctionType, IntegerAttr, IntegerType, StringAttr
from xdsl.ir import Attribute, Dialect, Operation, Region, SSAValue
from xdsl.irdl import IRDLOperation, irdl_op_definition, operand_def, prop_def, region_def, result_def, traits_def, var_operand_def
from xdsl.traits import IsolatedFromAbove, IsTerminator, Pure

# xdsl's py dialect is dynamically typed (py.object) with only 3 ops.
# We need static i1/i64 types and verification spec ops, so we define our own.
#
# see: https://github.com/xdslproject/xdsl/tree/v0.63.0/xdsl/dialects/py


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

    def __init__(self, func_name: str, param_names: Sequence[str], function_type: tuple[Sequence[Attribute], Sequence[Attribute]] | FunctionType, *, body: Region | None = None):
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
