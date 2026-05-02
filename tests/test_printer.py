import re

from xdsl.dialects.builtin import IntegerType, ModuleOp
from xdsl.ir import Block, Region

from veripy.printer import print_dafny, rewrite_ensures
from veripy.py import BinOp, ConstantOp, FuncOp, IfOp, NegOp, ParamRefOp, ReturnOp

i64 = IntegerType(64)
i1 = IntegerType(1)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# --- ensures rewriting ---


def test_rewrite_ensures_replaces_result_with_r():
    assert rewrite_ensures("result >= 0") == "r >= 0"


def test_rewrite_ensures_replaces_or_with_logical_or():
    assert rewrite_ensures("result == x or result == -x") == "r == x || r == -x"


def test_rewrite_ensures_leaves_unrelated_string_unchanged():
    assert rewrite_ensures("x > 0") == "x > 0"


def test_rewrite_ensures_preserves_result_prefix_in_identifier():
    assert rewrite_ensures("result_code >= 0") == "result_code >= 0"


# --- per-op emission ---


def test_constant_emits_literal():
    c = ConstantOp(0, i64)
    func = FuncOp("f", ["x"], ([i64], [i64]), body=Region([Block([c, ReturnOp(c)])]))
    out = print_dafny(ModuleOp([func]))
    assert "r := 0;" in out


def test_param_ref_emits_name():
    p = ParamRefOp("x", i64)
    func = FuncOp("f", ["x"], ([i64], [i64]), body=Region([Block([p, ReturnOp(p)])]))
    out = print_dafny(ModuleOp([func]))
    assert "r := x;" in out


def test_binop_ge_emits_infix():
    x = ParamRefOp("x", i64)
    zero = ConstantOp(0, i64)
    cmp = BinOp("ge", x, zero, i1)
    then_block = Block([ReturnOp(x)])
    if_op = IfOp(cmp, Region([then_block]))
    func = FuncOp("f", ["x"], ([i64], [i64]), body=Region([Block([x, zero, cmp, if_op])]))
    out = print_dafny(ModuleOp([func]))
    assert "if x >= 0 {" in out


def test_neg_emits_minus_prefix():
    x = ParamRefOp("x", i64)
    neg = NegOp(x, i64)
    func = FuncOp("f", ["x"], ([i64], [i64]), body=Region([Block([x, neg, ReturnOp(neg)])]))
    out = print_dafny(ModuleOp([func]))
    assert "r := -x;" in out


def test_return_emits_assign_then_return():
    c = ConstantOp(42, i64)
    func = FuncOp("f", [], ([], [i64]), body=Region([Block([c, ReturnOp(c)])]))
    out = print_dafny(ModuleOp([func]))
    assert "r := 42;" in out
    assert "return;" in out


def test_if_with_else_emits_both_branches():
    x = ParamRefOp("x", i64)
    zero = ConstantOp(0, i64)
    cmp = BinOp("ge", x, zero, i1)
    then_block = Block([ReturnOp(x)])
    neg = NegOp(x, i64)
    else_block = Block([neg, ReturnOp(neg)])
    if_op = IfOp(cmp, Region([then_block]), Region([else_block]))
    func = FuncOp("f", ["x"], ([i64], [i64]), body=Region([Block([x, zero, cmp, if_op])]))
    out = print_dafny(ModuleOp([func]))
    assert "if x >= 0 {" in out
    assert "r := x;" in out
    assert "r := -x;" in out


# --- full function ---


def test_abs_full_output_matches_expected_dafny():
    x_ref = ParamRefOp("x", i64)
    zero = ConstantOp(0, i64)
    cond = BinOp("ge", x_ref, zero, i1)
    then_block = Block([ReturnOp(x_ref)])
    neg_x = NegOp(x_ref, i64)
    else_block = Block([neg_x, ReturnOp(neg_x)])
    if_op = IfOp(cond, Region([then_block]), Region([else_block]))
    body = Region([Block([x_ref, zero, cond, if_op])])
    func = FuncOp("abs", ["x"], ([i64], [i64]), ensures=["result >= 0", "result == x or result == -x"], body=body)
    module = ModuleOp([func])

    expected = """\
method abs(x: int) returns (r: int)
  ensures r >= 0
  ensures r == x || r == -x
{
  if x >= 0 {
    r := x;
    return;
  }
  r := -x;
  return;
}"""

    assert _normalize(print_dafny(module)) == _normalize(expected)
