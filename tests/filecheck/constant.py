# RUN: veripy %s -p resolve -t dfy | filecheck %s
def forty_two() -> int:
    return 42
# CHECK: method forty_two() returns (r: int)
# CHECK-NEXT: {
# CHECK-NEXT:   r := 42;
# CHECK-NEXT:   return;
# CHECK-NEXT: }
