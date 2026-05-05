# RUN: veripy %s -p resolve -t dfy | filecheck %s

def eq(a: int, b: int) -> int:
    if a == b:
        return a
    return b
# CHECK: if a == b {

def ne(a: int, b: int) -> int:
    if a != b:
        return a
    return b
# CHECK: if a != b {

def lt(a: int, b: int) -> int:
    if a < b:
        return a
    return b
# CHECK: if a < b {

def le(a: int, b: int) -> int:
    if a <= b:
        return a
    return b
# CHECK: if a <= b {

def gt(a: int, b: int) -> int:
    if a > b:
        return a
    return b
# CHECK: if a > b {

def ge(a: int, b: int) -> int:
    if a >= b:
        return a
    return b
# CHECK: if a >= b {
