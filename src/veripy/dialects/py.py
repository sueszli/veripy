from __future__ import annotations

from collections.abc import Sequence

from xdsl.dialects.builtin import ArrayAttr, FunctionType, IntegerAttr, IntegerType, StringAttr
from xdsl.ir import Dialect, Operation, Region, SSAValue
from xdsl.irdl import IRDLOperation, irdl_op_definition, operand_def, prop_def, region_def, result_def, traits_def
from xdsl.traits import IsolatedFromAbove, IsTerminator, Pure


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

    def __init__(
        self,
        func_name: str,
        param_names: Sequence[str],
        function_type: tuple[Sequence, Sequence] | FunctionType,
        *,
        requires: Sequence[str] | None = None,
        ensures: Sequence[str] | None = None,
        body: Region | None = None,
    ):
        if isinstance(function_type, tuple):
            function_type = FunctionType.from_lists(*function_type)
        super().__init__(
            properties={
                "sym_name": StringAttr(func_name),
                "function_type": function_type,
                "param_names": ArrayAttr([StringAttr(n) for n in param_names]),
                "requires": ArrayAttr([StringAttr(s) for s in (requires or [])]),
                "ensures": ArrayAttr([StringAttr(s) for s in (ensures or [])]),
            },
            regions=[body if body is not None else Region()],
        )


@irdl_op_definition
class ConstantOp(IRDLOperation):
    name = "py.constant"

    value = prop_def(IntegerAttr)
    result = result_def()

    traits = traits_def(Pure())

    def __init__(self, value: int, result_type: IntegerType):
        super().__init__(
            properties={"value": IntegerAttr(value, result_type)},
            result_types=[result_type],
        )


@irdl_op_definition
class ParamRefOp(IRDLOperation):
    name = "py.param_ref"

    param_name = prop_def(StringAttr)
    result = result_def()

    traits = traits_def(Pure())

    def __init__(self, param_name: str, result_type: IntegerType):
        super().__init__(
            properties={"param_name": StringAttr(param_name)},
            result_types=[result_type],
        )


@irdl_op_definition
class BinOp(IRDLOperation):
    name = "py.binop"

    op_kind = prop_def(StringAttr)
    lhs = operand_def()
    rhs = operand_def()
    result = result_def()

    traits = traits_def(Pure())

    def __init__(
        self,
        op: str,
        lhs: SSAValue | Operation,
        rhs: SSAValue | Operation,
        result_type: IntegerType,
    ):
        super().__init__(
            operands=[lhs, rhs],
            properties={"op_kind": StringAttr(op)},
            result_types=[result_type],
        )


@irdl_op_definition
class NegOp(IRDLOperation):
    name = "py.neg"

    operand = operand_def()
    result = result_def()

    traits = traits_def(Pure())

    def __init__(self, operand: SSAValue | Operation, result_type: IntegerType):
        super().__init__(
            operands=[operand],
            result_types=[result_type],
        )


@irdl_op_definition
class IfOp(IRDLOperation):
    name = "py.if"

    cond = operand_def(IntegerType(1))
    then_region = region_def()
    else_region = region_def()

    def __init__(
        self,
        cond: SSAValue | Operation,
        then_region: Region,
        else_region: Region | None = None,
    ):
        super().__init__(
            operands=[cond],
            regions=[then_region, else_region if else_region is not None else Region()],
        )


@irdl_op_definition
class ReturnOp(IRDLOperation):
    name = "py.return"

    value = operand_def()

    traits = traits_def(IsTerminator())

    def __init__(self, value: SSAValue | Operation):
        super().__init__(operands=[value])


Py = Dialect("py", [FuncOp, ConstantOp, ParamRefOp, BinOp, NegOp, IfOp, ReturnOp], [])
