def abs(x: int) -> int:
    #@ ensures result >= 0
    #@ ensures result == x or result == -x
    if x >= 0:
        return x
    return -x
