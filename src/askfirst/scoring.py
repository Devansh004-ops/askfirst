"""Decide whether two query results mean the same thing."""
from __future__ import annotations

from itertools import product
from typing import Sequence


def _norm(value):
    if value is None:
        return ("n",)
    if isinstance(value, (bool, int, float)):
        return ("x", round(float(value), 2))
    return ("s", str(value))


def equivalent(expected: Sequence[tuple], actual: Sequence[tuple], *, ordered: bool = False,
               extra_columns_ok: bool = True) -> bool:
    """True if `actual` contains the same rows as `expected`.

    * Column names are ignored; columns are matched by their values.
    * Row order is ignored unless `ordered` (use it for "top N" questions).
    * With `extra_columns_ok`, `actual` may carry additional columns (a model
      that also returns an id next to a name is not wrong).
    * Numbers compare to two decimals, so 10.001 equals 10.

    Columns are matched jointly, not independently: (a,1),(b,2) is NOT equivalent
    to (a,2),(b,1), even though each column alone has the same values.
    """
    if len(expected) != len(actual):
        return False
    if not expected:
        return True
    exp = [tuple(map(_norm, row)) for row in expected]
    act = [tuple(map(_norm, row)) for row in actual]
    n_exp, n_act = len(exp[0]), len(act[0])
    if n_exp > n_act or (n_exp < n_act and not extra_columns_ok):
        return False

    def key(seq):
        return list(seq) if ordered else sorted(seq)

    exp_cols = [key(row[i] for row in exp) for i in range(n_exp)]
    act_cols = [key(row[j] for row in act) for j in range(n_act)]
    candidates = [[j for j in range(n_act) if act_cols[j] == col] for col in exp_cols]
    target = key(exp)
    for mapping in product(*candidates):
        if len(set(mapping)) < len(mapping):
            continue
        if key(tuple(row[j] for j in mapping) for row in act) == target:
            return True
    return False
