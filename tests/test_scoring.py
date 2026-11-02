import pytest

from askfirst.scoring import equivalent


def test_row_order_is_ignored_unless_asked():
    assert equivalent([(1,), (2,), (3,)], [(3,), (1,), (2,)])
    assert not equivalent([(1,), (2,)], [(2,), (1,)], ordered=True)
    assert equivalent([(1,), (2,)], [(1,), (2,)], ordered=True)


def test_numbers_compare_to_two_decimals_and_ignore_type():
    assert equivalent([(10.001,)], [(10,)])
    assert equivalent([(5,)], [(5.0,)])
    assert not equivalent([(10.02,)], [(10.0,)])


def test_row_count_must_match():
    assert not equivalent([(1,)], [(1,), (1,)])
    assert equivalent([], [])
    assert not equivalent([], [(1,)])


def test_extra_columns_are_allowed_by_default_and_found_anywhere():
    assert equivalent([("A",)], [(7, "A", 1.5)])
    assert not equivalent([("A",)], [(7, "A", 1.5)], extra_columns_ok=False)


def test_missing_columns_fail():
    assert not equivalent([("A", 1)], [("A",)])


def test_columns_are_matched_jointly_not_independently():
    # Each column alone has the same values, but the rows pair them differently.
    assert not equivalent([("a", 1), ("b", 2)], [("a", 2), ("b", 1)])
    assert equivalent([("a", 1), ("b", 2)], [(2, "b"), (1, "a")])        # same pairs, columns swapped


def test_nulls_and_strings():
    assert equivalent([(None,), ("x",)], [("x",), (None,)])
    assert not equivalent([(None,)], [("None",)])
    assert not equivalent([("1",)], [(1,)])                              # text '1' is not the number 1


@pytest.mark.parametrize("expected,actual", [([(1, 1)], [(1, 1)]), ([(2, 2)], [(2, 2, 9)])])
def test_duplicate_valued_columns_map_to_distinct_columns(expected, actual):
    assert equivalent(expected, actual)
