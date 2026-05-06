# RUN: veripy %s -t mlir | filecheck %s

def f(a: int, b: int) -> int:
    if a >= b:
        return a + b
    return a

# CHECK: "py.func"
# CHECK-SAME: sym_name = "f"
# CHECK: "py.param_ref"() <{param_name = "a"}>
# CHECK: "py.param_ref"() <{param_name = "b"}>
# CHECK: "py.binop"
# CHECK-SAME: op_kind = "ge"
# CHECK: "py.if"
# CHECK: "py.binop"
# CHECK-SAME: op_kind = "add"
# CHECK: "py.return"
