# RUN: veripy %s -p resolve -t dfy | filecheck %s
def max(a: int, b: int) -> int:
    #@ ensures result >= a
    #@ ensures result >= b
    if a >= b:
        return a
    else:
        return b
# CHECK: method max(a: int, b: int) returns (r: int)
# CHECK-NEXT:   ensures r >= a
# CHECK-NEXT:   ensures r >= b
# CHECK-NEXT: {
# CHECK-NEXT:   if a >= b {
# CHECK-NEXT:     r := a;
# CHECK-NEXT:     return;
# CHECK-NEXT:   }
# CHECK-NEXT:   r := b;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
