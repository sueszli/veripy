def div(a: int, b: int) -> int:
    # @ requires a >= 0
    # @ requires b > 0
    # @ ensures result * b <= a
    # @ ensures (result + 1) * b > a
    q = 0
    while a - q * b >= b:
        # @ invariant q >= 0
        # @ invariant q * b <= a
        # @ decreases a - q * b
        q = q + 1
    return q
