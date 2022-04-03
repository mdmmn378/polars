import numpy as np
import pytest

import polars as pl


def test_error_on_empty_groupby() -> None:
    with pytest.raises(
        pl.ComputeError, match="expected keys in groupby operation, got nothing"
    ):
        pl.DataFrame(dict(x=[0, 0, 1, 1])).groupby([]).agg(pl.count())


def test_error_on_reducing_map() -> None:
    df = pl.DataFrame(
        dict(id=[0, 0, 0, 1, 1, 1], t=[2, 4, 5, 10, 11, 14], y=[0, 1, 1, 2, 3, 4])
    )

    with pytest.raises(
        pl.ComputeError,
        match="A 'map' functions output length must be equal to that of the input length. Consider using 'apply' in favor of 'map'.",
    ):
        df.groupby("id").agg(pl.map(["t", "y"], np.trapz))
