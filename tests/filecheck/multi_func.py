# RUN: veripy %s -t dfy | filecheck %s

def f() -> int:
    return 1

def g(a: int, b: int, c: int) -> int:
    return a

# CHECK:      method f() returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   r := 1;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
# CHECK-NEXT: method g(a: int, b: int, c: int) returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   r := a;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
