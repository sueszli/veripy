# uv run veripy --dfy example/example.py | docker run --rm -i xtrm0/dafny:4.9.1 sh -c 'cat > /tmp/out.dfy && dafny verify /tmp/out.dfy'

def abs(x: int) -> int:
    #@ ensures result >= 0
    #@ ensures result == x or result == -x
    if x >= 0:
        return x
    return -x
