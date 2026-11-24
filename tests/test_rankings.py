import pytest

from app.services.rankings import rank_places


def test_competition_places_skip_after_a_tie():
    assert rank_places([90, 80, 80, 70]) == [1, 2, 2, 4]


def test_dense_places_do_not_skip():
    assert rank_places([90, 80, 80, 70], "dense") == [1, 2, 2, 3]


def test_places_follow_the_order_given():
    assert rank_places([70, 90, 80]) == [3, 1, 2]


def test_averages_equal_as_shown_share_a_place():
    assert rank_places([83.33333, 83.32999, 83.2]) == [1, 1, 3]


def test_everyone_tied_is_first():
    assert rank_places([50, 50, 50], "dense") == [1, 1, 1]
    assert rank_places([50, 50, 50]) == [1, 1, 1]


def test_nothing_to_rank():
    assert rank_places([]) == []


def test_unknown_method_is_refused():
    with pytest.raises(ValueError):
        rank_places([1], "olympic")
