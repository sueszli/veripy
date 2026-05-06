# RUN: veripy %s | filecheck %s

def add(a: int, b: int) -> int:
    return a + b
# CHECK: method add(a: int, b: int) returns (r: int)
# CHECK: r := a + b;

def sub(a: int, b: int) -> int:
    return a - b
# CHECK: method sub(a: int, b: int) returns (r: int)
# CHECK: r := a - b;

def mul(a: int, b: int) -> int:
    return a * b
# CHECK: method mul(a: int, b: int) returns (r: int)
# CHECK: r := a * b;

def floordiv(a: int, b: int) -> int:
    return a // b
# CHECK: method floordiv(a: int, b: int) returns (r: int)
# CHECK: r := a / b;

def mod(a: int, b: int) -> int:
    return a % b
# CHECK: method mod(a: int, b: int) returns (r: int)
# CHECK: r := a % b;
