"""Rankings: the students of a class in order of their averages, with their places.

How shared places are numbered is a setting (see config.RANKING_METHODS):
"competition" skips places after a tie (1, 2, 2, 4), "dense" doesn't (1, 2, 2, 3).
"""

from app.config import RANKING_METHODS

TIE_DECIMALS = 1  # averages equal to this many decimals, as shown, share a place


def rank_places(values: list[float], method: str = "competition") -> list[int]:
    """The place of each of `values` (higher is better), in the same order.
    Values equal when rounded to TIE_DECIMALS share a place."""
    if method not in RANKING_METHODS:
        raise ValueError(f"Unknown ranking method {method!r}")
    keys = [round(v, TIE_DECIMALS) for v in values]
    distinct = sorted(set(keys), reverse=True)
    if method == "dense":
        place_of = {k: i + 1 for i, k in enumerate(distinct)}
    else:
        place_of = {k: 1 + sum(other > k for other in keys) for k in distinct}
    return [place_of[k] for k in keys]
