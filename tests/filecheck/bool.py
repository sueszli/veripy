# RUN: veripy %s -t dfy | filecheck %s

def identity(x: bool) -> bool:
    return x
# CHECK: method identity(x: bool) returns (r: bool)
# CHECK: r := x;

def const_true() -> bool:
    return True
# CHECK: method const_true() returns (r: bool)
# CHECK: r := true;

def const_false() -> bool:
    return False
# CHECK: method const_false() returns (r: bool)
# CHECK: r := false;
