from veripy.main import ingest, print_dafny, resolve


def _dfy(src: str) -> str:
    module = ingest(src)
    resolve(module)
    return print_dafny(module)


def test_simple_assign():
    dfy = _dfy("def f(x: int) -> int:\n    y = x + 1\n    return y\n")
    assert "var y := x + 1;" in dfy
    assert "r := y;" in dfy


def test_reassign():
    dfy = _dfy("def f() -> int:\n    y = 1\n    y = 2\n    return y\n")
    assert "var y := 1;" in dfy
    assert dfy.count("var y") == 1
    assert "y := 2;" in dfy


def test_assign_from_param():
    dfy = _dfy("def f(x: int) -> int:\n    y = x\n    return y\n")
    assert "var y := x;" in dfy
    assert "r := y;" in dfy


def test_multiple_assigns():
    dfy = _dfy("def f(a: int, b: int) -> int:\n    x = a + b\n    y = x * 2\n    return y\n")
    assert "var x := a + b;" in dfy
    assert "var y := x * 2;" in dfy
    assert "r := y;" in dfy
