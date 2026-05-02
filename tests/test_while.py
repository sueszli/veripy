from veripy.main import ingest, print_dafny, resolve


def _dfy(src: str) -> str:
    module = ingest(src)
    resolve(module)
    return print_dafny(module)


def test_simple_while():
    src = "def f(x: int) -> int:\n    while x > 0:\n        x = x - 1\n    return x\n"
    dfy = _dfy(src)
    assert "while x > 0" in dfy
    assert "return;" in dfy


def test_while_with_invariant():
    src = "def f(x: int) -> int:\n    while x > 0:\n        #@ invariant x >= 0\n        x = x - 1\n    return x\n"
    dfy = _dfy(src)
    assert "invariant x >= 0" in dfy


def test_while_with_decreases():
    src = "def f(x: int) -> int:\n    while x > 0:\n        #@ decreases x\n        x = x - 1\n    return x\n"
    dfy = _dfy(src)
    assert "decreases x" in dfy


def test_while_with_invariant_and_decreases():
    src = "def f(x: int) -> int:\n    while x > 0:\n        #@ invariant x >= 0\n        #@ decreases x\n        x = x - 1\n    return x\n"
    dfy = _dfy(src)
    assert "invariant x >= 0" in dfy
    assert "decreases x" in dfy
    assert "while x > 0" in dfy
