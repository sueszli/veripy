from veripy.main import ingest, print_dafny, resolve


def _dfy(src: str) -> str:
    module = ingest(src)
    resolve(module)
    return print_dafny(module)


def test_assert_simple():
    dfy = _dfy("def f(x: int) -> int:\n    assert x >= 0\n    return x\n")
    assert "assert x >= 0;" in dfy
    assert "r := x;" in dfy


def test_assert_equality():
    dfy = _dfy("def f(x: int, y: int) -> int:\n    assert x == y\n    return x\n")
    assert "assert x == y;" in dfy
