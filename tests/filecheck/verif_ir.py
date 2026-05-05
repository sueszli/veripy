# RUN: veripy %s -t mlir | filecheck %s

def f(a: int, b: int) -> int:
    if a >= b:
        return a + b
    return a

# CHECK: "verif.func"
# CHECK-SAME: sym_name = "f"
# CHECK: "verif.param_ref"() <{param_name = "a"}>
# CHECK: "verif.param_ref"() <{param_name = "b"}>
# CHECK: "verif.ge"
# CHECK: "verif.if"
# CHECK: "verif.add"
# CHECK: "verif.return"
