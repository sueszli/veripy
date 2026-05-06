# RUN: veripy %s -t dfy | filecheck %s

def f(x: int) -> int:
    assert x >= 0
    return x
# CHECK:      method f(x: int) returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   assert x >= 0;
# CHECK-NEXT:   r := x;
# CHECK-NEXT:   return;
# CHECK-NEXT: }

def g(x: int, y: int) -> int:
    assert x == y
    return x
# CHECK:      method g(x: int, y: int) returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   assert x == y;
# CHECK-NEXT:   r := x;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
