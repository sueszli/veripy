# RUN: veripy %s -p resolve -t dfy | filecheck %s

def add_nonneg(a: int, b: int) -> int:
    #@ requires a >= 0
    #@ requires b >= 0
    #@ ensures result >= a
    #@ ensures result >= b
    return a + b
# CHECK:      method add_nonneg(a: int, b: int) returns (r: int)
# CHECK-NEXT:   requires a >= 0
# CHECK-NEXT:   requires b >= 0
# CHECK-NEXT:   ensures r >= a
# CHECK-NEXT:   ensures r >= b
# CHECK-NEXT: {
# CHECK-NEXT:   r := a + b;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
