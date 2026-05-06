# RUN: veripy %s -t dfy | filecheck %s
def abs(x: int) -> int:
    #@ ensures result >= 0
    #@ ensures result == x or result == -x
    if x >= 0:
        return x
    return -x
# CHECK: method abs(x: int) returns (r: int)
# CHECK-NEXT:   ensures r >= 0
# CHECK-NEXT:   ensures r == x || r == -x
# CHECK-NEXT: {
# CHECK-NEXT:   if x >= 0 {
# CHECK-NEXT:     r := x;
# CHECK-NEXT:     return;
# CHECK-NEXT:   }
# CHECK-NEXT:   r := -x;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
