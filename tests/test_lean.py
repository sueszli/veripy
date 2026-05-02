from veripy.main import ingest, print_lean, resolve


def _lean(src: str) -> str:
    module = ingest(src)
    resolve(module)
    return print_lean(module)


def test_lean_identity():
    lean = _lean("def f(x: int) -> int:\n    return x\n")
    assert "def f (x : Int) : Int :=" in lean
    assert "x" in lean


def test_lean_constant():
    lean = _lean("def f() -> int:\n    return 42\n")
    assert ": Int :=" in lean
    assert "42" in lean


def test_lean_if_else():
    src = "def f(a: int, b: int) -> int:\n    if a >= b:\n        return a\n    else:\n        return b\n"
    lean = _lean(src)
    assert "if a >= b then" in lean
    assert "else" in lean


def test_lean_bool():
    lean = _lean("def f() -> bool:\n    return True\n")
    assert ": Bool :=" in lean
    assert "true" in lean


def test_lean_negation():
    lean = _lean("def f(x: int) -> int:\n    return -x\n")
    assert "-x" in lean


def test_lean_requires_ensures():
    src = "def f(x: int) -> int:\n    #@ requires x >= 0\n    #@ ensures result >= 0\n    return x\n"
    lean = _lean(src)
    assert "-- requires x >= 0" in lean
    assert "-- ensures result >= 0" in lean


def test_lean_call():
    lean = _lean("def f(x: int) -> int:\n    return g(x)\n")
    assert "g x" in lean


def test_lean_assign():
    lean = _lean("def f(x: int) -> int:\n    y = x + 1\n    return y\n")
    assert "let mut y := x + 1" in lean
    assert "y" in lean
