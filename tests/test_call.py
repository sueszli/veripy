from veripy.main import ingest, print_dafny, resolve


def _dfy(src: str) -> str:
    module = ingest(src)
    resolve(module)
    return print_dafny(module)


def test_call_in_return():
    dfy = _dfy("def f(x: int) -> int:\n    return g(x)\n")
    assert "r := g(x);" in dfy


def test_call_multiple_args():
    dfy = _dfy("def f(x: int, y: int) -> int:\n    return g(x, y)\n")
    assert "r := g(x, y);" in dfy


def test_call_no_args():
    dfy = _dfy("def f() -> int:\n    return g()\n")
    assert "r := g();" in dfy


def test_call_nested():
    dfy = _dfy("def f(x: int) -> int:\n    return g(h(x))\n")
    assert "r := g(h(x));" in dfy
