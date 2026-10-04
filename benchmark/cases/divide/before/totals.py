def div(a, b):
    if b == 0:
        raise ValueError("division by zero")
    return a / b


def mean(values):
    if not values:
        raise ValueError("mean of nothing")
    return sum(values) / len(values)
