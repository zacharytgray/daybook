# the board: a live page for the day, where every to-do can be handed to your agent


def iso(t):
    return t.isoformat(timespec="seconds") if t else ""
