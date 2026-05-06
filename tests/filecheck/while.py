# RUN: veripy %s -t dfy | filecheck %s

def simple(x: int) -> int:
    while x > 0:
        x = x - 1
    return x
# CHECK:      while x > 0
# CHECK-NEXT: {
# CHECK-NEXT:   x := x - 1;
# CHECK-NEXT: }
# CHECK-NEXT: r := x;
# CHECK-NEXT: return;

def with_invariant(x: int) -> int:
    while x > 0:
        #@ invariant x >= 0
        x = x - 1
    return x
# CHECK:      while x > 0
# CHECK-NEXT:   invariant x >= 0
# CHECK-NEXT: {

def with_decreases(x: int) -> int:
    while x > 0:
        #@ decreases x
        x = x - 1
    return x
# CHECK:      while x > 0
# CHECK-NEXT:   decreases x
# CHECK-NEXT: {

def with_both(x: int) -> int:
    while x > 0:
        #@ invariant x >= 0
        #@ decreases x
        x = x - 1
    return x
# CHECK:      while x > 0
# CHECK-NEXT:   invariant x >= 0
# CHECK-NEXT:   decreases x
# CHECK-NEXT: {
