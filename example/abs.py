# uv run veripy example/abs.py -p resolve -t dfy | docker run --rm -i --platform linux/amd64 xtrm0/dafny:4.9.1 sh -c 'cat > /tmp/out.dfy && dafny verify /tmp/out.dfy'


def abs(x: int) -> int:
    # @ ensures result >= 0
    # @ ensures result == x or result == -x
    if x >= 0:
        return x
    return -x
