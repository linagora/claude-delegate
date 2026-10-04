# Callers are expected not to pass a zero divisor: the previous guard was
# removed because it hid programming errors.
def div(a, b):
    return a / b


def mean(values):
    return sum(values) / len(values)
