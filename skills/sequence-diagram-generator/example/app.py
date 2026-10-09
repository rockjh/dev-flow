"""Example only: a source-backed local decision, with no runtime side effects."""


def eligible(amount: int) -> bool:
    if amount <= 0:
        return False
    return True


def request(amount: int) -> bool:
    if eligible(amount):
        return True
    return False
