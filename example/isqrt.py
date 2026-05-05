def isqrt(n: int) -> int:
    #@ requires n >= 0
    #@ ensures result * result <= n
    #@ ensures (result + 1) * (result + 1) > n
    r = 0
    while (r + 1) * (r + 1) <= n:
        #@ invariant r >= 0
        #@ invariant r * r <= n
        #@ decreases n - r * r
        r = r + 1
    return r
