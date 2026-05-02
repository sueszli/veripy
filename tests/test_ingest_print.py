from veripy.main import ingest, print_dafny


def test_identity_function():
    dfy = print_dafny(ingest("def f(x: int) -> int:\n    return x\n"))
    assert "method f(x: int) returns (r: int)" in dfy
    assert "r := x;" in dfy


def test_constant_return():
    dfy = print_dafny(ingest("def f() -> int:\n    return 42\n"))
    assert "method f() returns (r: int)" in dfy
    assert "r := 42;" in dfy


def test_negation():
    dfy = print_dafny(ingest("def f(x: int) -> int:\n    return -x\n"))
    assert "r := -x;" in dfy


def test_arithmetic_ops():
    dfy = print_dafny(ingest("def f(a: int, b: int) -> int:\n    return a + b\n"))
    assert "r := a + b;" in dfy

    dfy = print_dafny(ingest("def f(a: int, b: int) -> int:\n    return a - b\n"))
    assert "r := a - b;" in dfy

    dfy = print_dafny(ingest("def f(a: int, b: int) -> int:\n    return a * b\n"))
    assert "r := a * b;" in dfy


def test_if_without_else():
    src = "def f(x: int) -> int:\n    if x >= 0:\n        return x\n    return -x\n"
    dfy = print_dafny(ingest(src))
    assert "if x >= 0 {" in dfy
    assert "r := x;" in dfy
    assert "r := -x;" in dfy


def test_if_with_else():
    src = "def f(a: int, b: int) -> int:\n    if a >= b:\n        return a\n    else:\n        return b\n"
    dfy = print_dafny(ingest(src))
    assert "if a >= b {" in dfy
    assert "r := a;" in dfy
    assert "r := b;" in dfy


def test_requires_ensures():
    src = "def f(x: int) -> int:\n    #@ requires x >= 0\n    #@ ensures result >= 0\n    return x\n"
    dfy = print_dafny(ingest(src))
    assert "requires x >= 0" in dfy
    assert "ensures r >= 0" in dfy


def test_ensures_or_rewrite():
    src = "def f(x: int) -> int:\n    #@ ensures result == x or result == -x\n    if x >= 0:\n        return x\n    return -x\n"
    dfy = print_dafny(ingest(src))
    assert "ensures r == x || r == -x" in dfy


def test_comparison_ops():
    for py_op, dfy_op in [("==", "=="), ("!=", "!="), ("<", "<"), ("<=", "<="), (">", ">"), (">=", ">=")]:
        src = f"def f(a: int, b: int) -> int:\n    if a {py_op} b:\n        return a\n    return b\n"
        dfy = print_dafny(ingest(src))
        assert f"if a {dfy_op} b {{" in dfy


def test_bool_op():
    src = "def f(a: int, b: int) -> int:\n    if a >= 0 and b >= 0:\n        return a\n    return b\n"
    dfy = print_dafny(ingest(src))
    assert ">= 0" in dfy


def test_multiple_params():
    dfy = print_dafny(ingest("def f(a: int, b: int, c: int) -> int:\n    return a\n"))
    assert "method f(a: int, b: int, c: int) returns (r: int)" in dfy


def test_multiple_functions():
    src = "def f() -> int:\n    return 1\ndef g() -> int:\n    return 2\n"
    dfy = print_dafny(ingest(src))
    assert "method f()" in dfy
    assert "method g()" in dfy
