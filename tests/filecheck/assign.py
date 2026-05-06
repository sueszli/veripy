# RUN: veripy %s -t dfy | filecheck %s

def simple(x: int) -> int:
    y = x + 1
    return y
# CHECK:      method simple(x: int) returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   var y := x + 1;
# CHECK-NEXT:   r := y;
# CHECK-NEXT:   return;
# CHECK-NEXT: }

def reassign() -> int:
    y = 1
    y = 2
    return y
# CHECK:      method reassign() returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   var y := 1;
# CHECK-NEXT:   y := 2;
# CHECK-NEXT:   r := y;
# CHECK-NEXT:   return;
# CHECK-NEXT: }

def multi(a: int, b: int) -> int:
    x = a + b
    y = x * 2
    return y
# CHECK:      method multi(a: int, b: int) returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   var x := a + b;
# CHECK-NEXT:   var y := x * 2;
# CHECK-NEXT:   r := y;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
