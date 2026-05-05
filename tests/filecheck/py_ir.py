# RUN: veripy %s -p "" -t mlir | filecheck %s

def f(a: int, b: int) -> int:
    return a + b

# CHECK: "py.func"
# CHECK-SAME: sym_name = "f"
# CHECK: "py.param_ref"
# CHECK: "py.binop"
# CHECK-SAME: op_kind = "add"
# CHECK: "py.return"
