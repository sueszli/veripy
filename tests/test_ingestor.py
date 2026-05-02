from xdsl.dialects.builtin import ModuleOp

from veripy.ingestor import ingest
from veripy.py import BinOp, FuncOp, IfOp, NegOp, ParamRefOp, ReturnOp

ABS_SOURCE = """\
def abs(x: int) -> int:
    #@ ensures result >= 0
    #@ ensures result == x or result == -x
    if x >= 0:
        return x
    return -x
"""


def test_single_ensures_extracted():
    src = """\
def f(x: int) -> int:
    #@ ensures result >= 0
    return x
"""
    module = ingest(src)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert [a.data for a in func.ensures] == ["result >= 0"]


def test_multiple_ensures_extracted_in_order():
    module = ingest(ABS_SOURCE)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert [a.data for a in func.ensures] == ["result >= 0", "result == x or result == -x"]


def test_requires_extracted():
    src = """\
def f(x: int) -> int:
    #@ requires x > 0
    return x
"""
    module = ingest(src)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert [a.data for a in func.requires] == ["x > 0"]


def test_non_annotation_lines_ignored():
    src = """\
def f(x: int) -> int:
    # regular comment
    return x
"""
    module = ingest(src)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert len(func.ensures) == 0
    assert len(func.requires) == 0


def test_annotation_with_leading_whitespace():
    src = """\
def f(x: int) -> int:
      #@ ensures result >= 0
    return x
"""
    module = ingest(src)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert [a.data for a in func.ensures] == ["result >= 0"]


def test_no_annotations_gives_empty_lists():
    src = """\
def f(x: int) -> int:
    return x
"""
    module = ingest(src)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert len(func.ensures) == 0
    assert len(func.requires) == 0


def test_only_requires_no_ensures():
    src = """\
def f(x: int) -> int:
    #@ requires x > 0
    return x
"""
    module = ingest(src)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert [a.data for a in func.requires] == ["x > 0"]
    assert len(func.ensures) == 0


def test_abs_funcop_name_and_signature():
    module = ingest(ABS_SOURCE)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    assert func.sym_name.data == "abs"
    assert [a.data for a in func.param_names] == ["x"]
    assert len(func.function_type.inputs) == 1
    assert len(func.function_type.outputs) == 1


def test_abs_body_has_ifop():
    module = ingest(ABS_SOURCE)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    body_ops = list(func.body.block.ops)
    assert any(isinstance(op, IfOp) for op in body_ops)


def test_abs_if_condition_is_ge_binop():
    module = ingest(ABS_SOURCE)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    if_op = next(op for op in func.body.block.ops if isinstance(op, IfOp))
    cond_op = if_op.cond.owner
    assert isinstance(cond_op, BinOp)
    assert cond_op.op_kind.data == "ge"


def test_abs_then_branch_returns_param_ref():
    module = ingest(ABS_SOURCE)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    if_op = next(op for op in func.body.block.ops if isinstance(op, IfOp))
    then_ops = list(if_op.then_region.block.ops)
    ret = next(op for op in then_ops if isinstance(op, ReturnOp))
    assert isinstance(ret.value.owner, ParamRefOp)


def test_abs_else_branch_returns_negop():
    module = ingest(ABS_SOURCE)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    if_op = next(op for op in func.body.block.ops if isinstance(op, IfOp))
    else_ops = list(if_op.else_region.block.ops)
    neg = next(op for op in else_ops if isinstance(op, NegOp))
    assert isinstance(neg, NegOp)
    ret = next(op for op in else_ops if isinstance(op, ReturnOp))
    assert ret.value.owner is neg


def test_abs_return_minus_x_has_negop_wrapping_paramref():
    module = ingest(ABS_SOURCE)
    func = next(op for op in module.body.block.ops if isinstance(op, FuncOp))
    if_op = next(op for op in func.body.block.ops if isinstance(op, IfOp))
    else_ops = list(if_op.else_region.block.ops)
    neg = next(op for op in else_ops if isinstance(op, NegOp))
    assert isinstance(neg.operand.owner, ParamRefOp)


def test_ingest_returns_module_op():
    module = ingest(ABS_SOURCE)
    assert isinstance(module, ModuleOp)
