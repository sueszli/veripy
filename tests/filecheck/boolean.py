# RUN: veripy %s -t dfy | filecheck %s

def both(a: int, b: int) -> int:
    if a >= 0 and b >= 0:
        return a
    return b
# CHECK: if a >= 0 && b >= 0 {

def either(a: int, b: int) -> int:
    if a >= 0 or b >= 0:
        return a
    return b
# CHECK: if a >= 0 || b >= 0 {
