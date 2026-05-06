# RUN: veripy %s -t dfy | filecheck %s

def one_arg(x: int) -> int:
    return g(x)
# CHECK: r := g(x);

def multi_arg(x: int, y: int) -> int:
    return g(x, y)
# CHECK: r := g(x, y);

def no_arg() -> int:
    return g()
# CHECK: r := g();

def nested(x: int) -> int:
    return g(h(x))
# CHECK: r := g(h(x));
