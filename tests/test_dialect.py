from xdsl.dialects.builtin import IntegerType, ModuleOp
from xdsl.ir import Block, Region

from veripy.dialects.py import BinOp, ConstantOp, FuncOp, IfOp, NegOp, ParamRefOp, Py, ReturnOp

i64 = IntegerType(64)
i1 = IntegerType(1)


def test_funcop_stores_name():
    func = FuncOp("abs", ["x"], ([i64], [i64]))
    assert func.sym_name.data == "abs"


def test_funcop_stores_function_type():
    func = FuncOp("abs", ["x"], ([i64], [i64]))
    assert tuple(func.function_type.inputs) == (i64,)
    assert tuple(func.function_type.outputs) == (i64,)


def test_funcop_stores_param_names():
    func = FuncOp("f", ["x", "y"], ([i64, i64], [i64]))
    names = [attr.data for attr in func.param_names]
    assert names == ["x", "y"]


def test_funcop_stores_ensures():
    func = FuncOp(
        "abs",
        ["x"],
        ([i64], [i64]),
        ensures=["result >= 0", "result == x or result == -x"],
    )
    assert [a.data for a in func.ensures] == [
        "result >= 0",
        "result == x or result == -x",
    ]


def test_funcop_stores_requires():
    func = FuncOp("f", ["x"], ([i64], [i64]), requires=["x > 0"])
    assert [a.data for a in func.requires] == ["x > 0"]


def test_funcop_defaults_empty_specs():
    func = FuncOp("f", [], ([], [i64]))
    assert len(func.ensures) == 0
    assert len(func.requires) == 0


def test_constantop_stores_value():
    c = ConstantOp(42, i64)
    assert c.value.value.data == 42
    assert c.result.type == i64


def test_paramrefop_stores_param_name():
    p = ParamRefOp("x", i64)
    assert p.param_name.data == "x"
    assert p.result.type == i64


def test_binop_preserves_operator_kind():
    lhs = ConstantOp(1, i64)
    rhs = ConstantOp(2, i64)
    b = BinOp("ge", lhs, rhs, i1)
    assert b.op_kind.data == "ge"


def test_binop_connects_operands():
    lhs = ConstantOp(1, i64)
    rhs = ConstantOp(2, i64)
    b = BinOp("ge", lhs, rhs, i1)
    assert b.lhs == lhs.result
    assert b.rhs == rhs.result
    assert b.result.type == i1


def test_negop_connects_operand():
    c = ConstantOp(42, i64)
    n = NegOp(c, i64)
    assert n.operand == c.result
    assert n.result.type == i64


def test_ifop_has_then_and_else_regions():
    cond = ConstantOp(1, i1)
    op = IfOp(cond, Region([Block()]), Region([Block()]))
    assert len(op.then_region.blocks) == 1
    assert len(op.else_region.blocks) == 1


def test_ifop_else_region_defaults_empty():
    cond = ConstantOp(1, i1)
    op = IfOp(cond, Region([Block()]))
    assert len(op.else_region.blocks) == 0


def test_returnop_connects_operand():
    c = ConstantOp(0, i64)
    r = ReturnOp(c)
    assert r.value == c.result


def test_abs_ir_builds_and_prints():
    x_ref = ParamRefOp("x", i64)
    zero = ConstantOp(0, i64)
    cond = BinOp("ge", x_ref, zero, i1)

    then_ret = ReturnOp(x_ref)
    then_block = Block([then_ret])

    neg_x = NegOp(x_ref, i64)
    else_ret = ReturnOp(neg_x)
    else_block = Block([neg_x, else_ret])

    if_op = IfOp(cond, Region([then_block]), Region([else_block]))

    body = Region([Block([x_ref, zero, cond, if_op])])
    func = FuncOp(
        "abs",
        ["x"],
        ([i64], [i64]),
        ensures=["result >= 0", "result == x or result == -x"],
        body=body,
    )

    _module = ModuleOp([func])

    body_ops = list(body.block.ops)
    assert len(body_ops) == 4
    assert isinstance(body_ops[0], ParamRefOp)
    assert isinstance(body_ops[1], ConstantOp)
    assert isinstance(body_ops[2], BinOp)
    assert isinstance(body_ops[3], IfOp)


def test_dialect_has_seven_ops():
    assert len(list(Py.operations)) == 7
