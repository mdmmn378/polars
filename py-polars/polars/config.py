from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

from polars.dependencies import json
from polars.utils.deprecation import deprecate_nonkeyword_arguments
from polars.utils.various import normalize_filepath

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    pass

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import TypeAlias

    from polars.type_aliases import FloatFmt

TableFormatNames: TypeAlias = Literal[
    "ASCII_FULL",
    "ASCII_FULL_CONDENSED",
    "ASCII_NO_BORDERS",
    "ASCII_BORDERS_ONLY",
    "ASCII_BORDERS_ONLY_CONDENSED",
    "ASCII_HORIZONTAL_ONLY",
    "ASCII_MARKDOWN",
    "UTF8_FULL",
    "UTF8_FULL_CONDENSED",
    "UTF8_NO_BORDERS",
    "UTF8_BORDERS_ONLY",
    "UTF8_HORIZONTAL_ONLY",
    "NOTHING",
]


# note: register all Config-specific environment variable names here; need to constrain
# which 'POLARS_' environment variables are recognized, as there are other lower-level
# and/or unstable settings that should not be saved or reset with the Config vars.
_POLARS_CFG_ENV_VARS = {
    "POLARS_WARN_UNSTABLE",
    "POLARS_ACTIVATE_DECIMAL",
    "POLARS_AUTO_STRUCTIFY",
    "POLARS_FMT_MAX_COLS",
    "POLARS_FMT_MAX_ROWS",
    "POLARS_FMT_NUM_DECIMAL",
    "POLARS_FMT_NUM_GROUP_SEPARATOR",
    "POLARS_FMT_NUM_LEN",
    "POLARS_FMT_STR_LEN",
    "POLARS_FMT_TABLE_CELL_ALIGNMENT",
    "POLARS_FMT_TABLE_CELL_LIST_LEN",
    "POLARS_FMT_TABLE_CELL_NUMERIC_ALIGNMENT",
    "POLARS_FMT_TABLE_DATAFRAME_SHAPE_BELOW",
    "POLARS_FMT_TABLE_FORMATTING",
    "POLARS_FMT_TABLE_HIDE_COLUMN_DATA_TYPES",
    "POLARS_FMT_TABLE_HIDE_COLUMN_NAMES",
    "POLARS_FMT_TABLE_HIDE_COLUMN_SEPARATOR",
    "POLARS_FMT_TABLE_HIDE_DATAFRAME_SHAPE_INFORMATION",
    "POLARS_FMT_TABLE_INLINE_COLUMN_DATA_TYPE",
    "POLARS_FMT_TABLE_ROUNDED_CORNERS",
    "POLARS_STREAMING_CHUNK_SIZE",
    "POLARS_TABLE_WIDTH",
    "POLARS_VERBOSE",
}

# vars that set the rust env directly should declare themselves here as the Config
# method name paired with a callable that returns the current state of that value:
with contextlib.suppress(ImportError, NameError):
    # note: 'plr' not available when building docs
    import polars.polars as plr

    _POLARS_CFG_DIRECT_VARS = {
        "set_fmt_float": plr.get_float_fmt,
        "set_float_precision": plr.get_float_precision,
        "set_thousands_separator": plr.get_thousands_separator,
        "set_decimal_separator": plr.get_decimal_separator,
        "set_trim_decimal_zeros": plr.get_trim_decimal_zeros,
    }


class Config(contextlib.ContextDecorator):
    """
    Configure polars; offers options for table formatting and more.

    Notes
    -----
    Can also be used as a context manager OR a function decorator in order to
    temporarily scope the lifetime of specific options. For example:

    >>> with pl.Config() as cfg:
    ...     # set verbose for more detailed output within the scope
    ...     cfg.set_verbose(True)  # doctest: +IGNORE_RESULT
    >>> # scope exit - no longer in verbose mode

    This can also be written more compactly as:

    >>> with pl.Config(verbose=True):
    ...     pass

    (The compact format is available for all `Config` methods that take a single value).

    Alternatively, you can use as a decorator in order to scope the duration of the
    selected options to a specific function:

    >>> @pl.Config(verbose=True)
    ... def test():
    ...     pass
    """

    _original_state: str = ""

    def __init__(self, *, restore_defaults: bool = False, **options: Any) -> None:
        """
        Initialise a Config object instance for context manager usage.

        Any `options` kwargs should correspond to the available named "set_*"
        methods, but are allowed to omit the "set_" prefix for brevity.

        Parameters
        ----------
        restore_defaults
            set all options to their default values (this is applied before
            setting any other options).
        **options
            keyword args that will set the option; equivalent to calling the
            named "set_<option>" method with the given value.

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> with pl.Config(
        ...     # these options will be set for scope duration
        ...     tbl_formatting="ASCII_MARKDOWN",
        ...     tbl_hide_dataframe_shape=True,
        ...     tbl_rows=10,
        ... ):
        ...     print(df)
        | abc | xyz   |
        | --- | ---   |
        | f64 | bool  |
        |-----|-------|
        | 1.0 | true  |
        | 2.5 | false |
        | 5.0 | true  |
        """
        # save original state _before_ any changes are made
        self._original_state = self.save()

        if restore_defaults:
            self.restore_defaults()

        for opt, value in options.items():
            if not hasattr(self, opt) and not opt.startswith("set_"):
                opt = f"set_{opt}"
            if not hasattr(self, opt):
                msg = f"`Config` has no option {opt!r}"
                raise AttributeError(msg)
            getattr(self, opt)(value)

    def __enter__(self) -> Config:
        """Support setting temporary Config options that are reset on scope exit."""
        self._original_state = self._original_state or self.save()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Reset any Config options that were set within the scope."""
        self.restore_defaults().load(self._original_state)
        self._original_state = ""

    @classmethod
    def load(cls, cfg: str) -> type[Config]:
        """
        Load (and set) previously saved Config options from a JSON string.

        Parameters
        ----------
        cfg : str
            JSON string produced by `Config.save()`.

        See Also
        --------
        load_from_file : Load (and set) Config options from a JSON file.
        save: Save the current set of Config options as a JSON string or file.
        """
        try:
            options = json.loads(cfg)
        except json.JSONDecodeError as err:
            msg = "invalid Config string (did you mean to use `load_from_file`?)"
            raise ValueError(msg) from err

        os.environ.update(options.get("environment", {}))
        for cfg_methodname, value in options.get("direct", {}).items():
            if hasattr(cls, cfg_methodname):
                getattr(cls, cfg_methodname)(value)
        return cls

    @classmethod
    def load_from_file(cls, file: Path | str) -> type[Config]:
        """
        Load (and set) previously saved Config options from file.

        Parameters
        ----------
        file : Path | str
            File path to a JSON string produced by `Config.save()`.

        See Also
        --------
        load : Load (and set) Config options from a JSON string.
        save: Save the current set of Config options as a JSON string or file.
        """
        try:
            options = Path(normalize_filepath(file)).read_text()
        except OSError as err:
            msg = f"invalid Config file (did you mean to use `load`?)\n{err}"
            raise ValueError(msg) from err

        return cls.load(options)

    @classmethod
    def restore_defaults(cls) -> type[Config]:
        """
        Reset all polars Config settings to their default state.

        Notes
        -----
        This method operates by removing all Config options from the environment,
        and then setting any local (non-env) options back to their default value.

        Examples
        --------
        >>> cfg = pl.Config.restore_defaults()  # doctest: +SKIP
        """
        # unset all Config environment variables
        for var in _POLARS_CFG_ENV_VARS:
            os.environ.pop(var, None)

        # reset all 'direct' defaults
        for method in _POLARS_CFG_DIRECT_VARS:
            getattr(cls, method)(None)

        return cls

    @classmethod
    def save(cls) -> str:
        """
        Save the current set of Config options as a JSON string.

        See Also
        --------
        load : Load (and set) Config options from a JSON string.
        load_from_file : Load (and set) Config options from a JSON file.
        save_to_file : Save the current set of Config options as a JSON file.

        Examples
        --------
        >>> json_str = pl.Config.save()

        Returns
        -------
        str
            JSON string containing current Config options.
        """
        environment_vars = {
            key: os.environ[key]
            for key in sorted(_POLARS_CFG_ENV_VARS)
            if (key in os.environ)
        }
        direct_vars = {
            cfg_methodname: get_value()
            for cfg_methodname, get_value in _POLARS_CFG_DIRECT_VARS.items()
        }
        options = json.dumps(
            {"environment": environment_vars, "direct": direct_vars},
            separators=(",", ":"),
        )
        return options

    @classmethod
    def save_to_file(cls, file: Path | str) -> None:
        """
        Save the current set of Config options as a JSON file.

        Parameters
        ----------
        file
            Optional path to a file into which the JSON string will be written.
            Leave as `None` to return the JSON string directly.

        See Also
        --------
        load : Load (and set) Config options from a JSON string.
        load_from_file : Load (and set) Config options from a JSON file.
        save : Save the current set of Config options as a JSON string.

        Examples
        --------
        >>> pl.Config().save_to_file("~/polars/config.json")  # doctest: +SKIP
        """
        file = Path(normalize_filepath(file)).resolve()
        file.write_text(cls.save())

    @classmethod
    @deprecate_nonkeyword_arguments(version="0.19.3")
    def state(
        cls,
        if_set: bool = False,  # noqa: FBT001
        env_only: bool = False,  # noqa: FBT001
    ) -> dict[str, str | None]:
        """
        Show the current state of all Config variables as a dict.

        Parameters
        ----------
        if_set : bool
            By default this will show the state of all `Config` environment variables.
            change this to `True` to restrict the returned dictionary to include only
            those that have been set to a specific value.

        env_only : bool
            Include only Config environment variables in the output; some options (such
            as "set_fmt_float") are set directly, not via an environment variable.

        Examples
        --------
        >>> set_state = pl.Config.state(if_set=True)
        >>> all_state = pl.Config.state()
        """
        config_state = {
            var: os.environ.get(var)
            for var in sorted(_POLARS_CFG_ENV_VARS)
            if not if_set or (os.environ.get(var) is not None)
        }
        if not env_only:
            for cfg_methodname, get_value in _POLARS_CFG_DIRECT_VARS.items():
                config_state[cfg_methodname] = get_value()

        return config_state

    @classmethod
    def activate_decimals(cls, active: bool | None = True) -> type[Config]:
        """
        Activate `Decimal` data types.

        This is a temporary setting that will be removed once the `Decimal` type
        stabilizes (`Decimal` is currently considered to be in beta testing).
        """
        if not active:
            os.environ.pop("POLARS_ACTIVATE_DECIMAL", None)
        else:
            os.environ["POLARS_ACTIVATE_DECIMAL"] = str(int(active))
        return cls

    @classmethod
    def set_ascii_tables(cls, active: bool | None = True) -> type[Config]:
        """
        Use ASCII characters to display table outlines.

        Set False to revert to the default UTF8_FULL_CONDENSED formatting style.

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> pl.Config.set_ascii_tables(True)  # doctest: +SKIP
        # ...
        # shape: (3, 2)        shape: (3, 2)
        # ┌─────┬───────┐      +-----+-------+
        # │ abc ┆ xyz   │      | abc | xyz   |
        # │ --- ┆ ---   │      | --- | ---   |
        # │ f64 ┆ bool  │      | f64 | bool  |
        # ╞═════╪═══════╡      +=============+
        # │ 1.0 ┆ true  │  >>  | 1.0 | true  |
        # │ 2.5 ┆ false │      | 2.5 | false |
        # │ 5.0 ┆ true  │      | 5.0 | true  |
        # └─────┴───────┘      +-----+-------+
        """
        if active is None:
            os.environ.pop("POLARS_FMT_TABLE_FORMATTING", None)
        else:
            fmt = "ASCII_FULL_CONDENSED" if active else "UTF8_FULL_CONDENSED"
            os.environ["POLARS_FMT_TABLE_FORMATTING"] = fmt
        return cls

    @classmethod
    def set_auto_structify(cls, active: bool | None = False) -> type[Config]:
        """
        Allow multi-output expressions to be automatically turned into Structs.

        Examples
        --------
        >>> df = pl.DataFrame({"v": [1, 2, 3], "v2": [4, 5, 6]})
        >>> with pl.Config(set_auto_structify=True):
        ...     out = df.select(pl.all())
        >>> out
        shape: (3, 1)
        ┌───────────┐
        │ v         │
        │ ---       │
        │ struct[2] │
        ╞═══════════╡
        │ {1,4}     │
        │ {2,5}     │
        │ {3,6}     │
        └───────────┘
        """
        if active is None:
            os.environ.pop("POLARS_AUTO_STRUCTIFY", None)
        else:
            os.environ["POLARS_AUTO_STRUCTIFY"] = str(int(active))
        return cls

    @classmethod
    def set_decimal_separator(cls, separator: str | None = None) -> type[Config]:
        """
        Set the decimal separator character.

        Parameters
        ----------
        separator : str, bool
            Character to use as the decimal separator.
            Set to ``None`` to revert to the default (".").

        See Also
        --------
        set_thousands_separator : Set the thousands grouping separator character.

        Examples
        --------
        >>> df = pl.DataFrame({"v": [9876.54321, 1010101.0, -123456.78]})
        >>> with pl.Config(
        ...     tbl_cell_numeric_alignment="RIGHT",
        ...     thousands_separator=".",
        ...     decimal_separator=",",
        ...     float_precision=3,
        ... ):
        ...     print(df)
        shape: (3, 1)
        ┌───────────────┐
        │             v │
        │           --- │
        │           f64 │
        ╞═══════════════╡
        │     9.876,543 │
        │ 1.010.101,000 │
        │  -123.456,780 │
        └───────────────┘
        """
        if isinstance(separator, str) and len(separator) != 1:
            msg = f"`separator` must be a single character; found {separator!r}"
            raise ValueError(msg)
        plr.set_decimal_separator(sep=separator)
        return cls

    @classmethod
    def set_thousands_separator(
        cls, separator: str | bool | None = None
    ) -> type[Config]:
        """
        Set the thousands grouping separator character.

        Parameters
        ----------
        separator : str, bool
            Set True to use the default "," (thousands) and "." (decimal) separators.
            Can also set a custom char, or set ``None`` to omit the separator.

        See Also
        --------
        set_decimal_separator : Set the decimal separator character.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "x": [1234567, -987654, 10101],
        ...         "y": [1234.5, 100000.0, -7654321.25],
        ...     }
        ... )
        >>> with pl.Config(
        ...     tbl_cell_numeric_alignment="RIGHT",
        ...     thousands_separator=True,
        ...     float_precision=2,
        ... ):
        ...     print(df)
        shape: (3, 2)
        ┌───────────┬───────────────┐
        │         x ┆             y │
        │       --- ┆           --- │
        │       i64 ┆           f64 │
        ╞═══════════╪═══════════════╡
        │ 1,234,567 ┆      1,234.50 │
        │  -987,654 ┆    100,000.00 │
        │    10,101 ┆ -7,654,321.25 │
        └───────────┴───────────────┘
        >>> with pl.Config(
        ...     tbl_cell_numeric_alignment="RIGHT",
        ...     thousands_separator=".",
        ...     decimal_separator=",",
        ...     float_precision=2,
        ... ):
        ...     print(df)
        shape: (3, 2)
        ┌───────────┬───────────────┐
        │         x ┆             y │
        │       --- ┆           --- │
        │       i64 ┆           f64 │
        ╞═══════════╪═══════════════╡
        │ 1.234.567 ┆      1.234,50 │
        │  -987.654 ┆    100.000,00 │
        │    10.101 ┆ -7.654.321,25 │
        └───────────┴───────────────┘
        """
        if separator is True:
            plr.set_decimal_separator(sep=".")
            plr.set_thousands_separator(sep=",")
        else:
            if isinstance(separator, str) and len(separator) > 1:
                msg = f"`separator` must be a single character; found {separator!r}"
                raise ValueError(msg)
            plr.set_thousands_separator(sep=separator or None)
        return cls

    @classmethod
    def set_float_precision(cls, precision: int | None = None) -> type[Config]:
        """
        Control the number of decimal places displayed for floating point values.

        Parameters
        ----------
        precision : int
            Number of decimal places to display; set to `None` to revert to the
            default/standard behaviour.

        Notes
        -----
        When setting this to a larger value you should ensure that you are aware of both
        the limitations of floating point representations, and of the precision of the
        data that you are looking at.

        This setting only applies to Float32 and Float64 dtypes; it does not cover
        Decimal dtype values (which are displayed at their native level of precision).

        Examples
        --------
        Set a large maximum float precision:

        >>> from math import pi, e
        >>> df = pl.DataFrame({"const": ["pi", "e"], "value": [pi, e]})
        >>> with pl.Config(float_precision=15):
        ...     print(df)
        shape: (2, 2)
        ┌───────┬───────────────────┐
        │ const ┆ value             │
        │ ---   ┆ ---               │
        │ str   ┆ f64               │
        ╞═══════╪═══════════════════╡
        │ pi    ┆ 3.141592653589793 │
        │ e     ┆ 2.718281828459045 │
        └───────┴───────────────────┘

        Set a fixed float precision and align numeric columns to the
        right in order to cleanly line-up the decimal separator:

        >>> df = pl.DataFrame(
        ...     {
        ...         "a": ["xx", "yy"],
        ...         "b": [-11111111, 44444444444],
        ...         "c": [100000.987654321, -23456789],
        ...     }
        ... )
        >>> with pl.Config(
        ...     tbl_cell_numeric_alignment="RIGHT",
        ...     thousands_separator=",",
        ...     float_precision=3,
        ... ):
        ...     print(df)
        shape: (2, 3)
        ┌─────┬────────────────┬─────────────────┐
        │ a   ┆              b ┆               c │
        │ --- ┆            --- ┆             --- │
        │ str ┆            i64 ┆             f64 │
        ╞═════╪════════════════╪═════════════════╡
        │ xx  ┆    -11,111,111 ┆     100,000.988 │
        │ yy  ┆ 44,444,444,444 ┆ -23,456,789.000 │
        └─────┴────────────────┴─────────────────┘
        """
        plr.set_float_precision(precision)
        return cls

    @classmethod
    def set_fmt_float(cls, fmt: FloatFmt | None = "mixed") -> type[Config]:
        """
        Control how floating point values are displayed.

        Parameters
        ----------
        fmt : {"mixed", "full"}
            How to format floating point numbers:

            - "mixed": Limit the number of decimal places and use scientific
              notation for large/small values.
            - "full": Print the full precision of the floating point number.

        Examples
        --------
        "mixed" float formatting:

        >>> s = pl.Series([1.2304980958725870923, 1e6, 1e-8])
        >>> with pl.Config(set_fmt_float="mixed"):
        ...     print(s)
        shape: (3,)
        Series: '' [f64]
        [
            1.230498
            1e6
            1.0000e-8
        ]

        "full" float formatting:

        >>> with pl.Config(set_fmt_float="full"):
        ...     print(s)
        shape: (3,)
        Series: '' [f64]
        [
            1.230498095872587
            1000000
            0.00000001
        ]
        """
        plr.set_float_fmt(fmt="mixed" if fmt is None else fmt)
        return cls

    @classmethod
    def set_fmt_str_lengths(cls, n: int | None) -> type[Config]:
        """
        Set the number of characters used to display string values.

        Parameters
        ----------
        n : int
            Number of characters to display.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "txt": [
        ...             "Play it, Sam. Play 'As Time Goes By'.",
        ...             "This is the beginning of a beautiful friendship.",
        ...         ]
        ...     }
        ... )
        >>> df.with_columns(pl.col("txt").str.len_bytes().alias("len"))
        shape: (2, 2)
        ┌───────────────────────────────────┬─────┐
        │ txt                               ┆ len │
        │ ---                               ┆ --- │
        │ str                               ┆ u32 │
        ╞═══════════════════════════════════╪═════╡
        │ Play it, Sam. Play 'As Time Goes… ┆ 37  │
        │ This is the beginning of a beaut… ┆ 48  │
        └───────────────────────────────────┴─────┘
        >>> with pl.Config(fmt_str_lengths=50):
        ...     print(df)
        shape: (2, 1)
        ┌──────────────────────────────────────────────────┐
        │ txt                                              │
        │ ---                                              │
        │ str                                              │
        ╞══════════════════════════════════════════════════╡
        │ Play it, Sam. Play 'As Time Goes By'.            │
        │ This is the beginning of a beautiful friendship. │
        └──────────────────────────────────────────────────┘
        """
        if n is None:
            os.environ.pop("POLARS_FMT_STR_LEN", None)
        else:
            if n <= 0:
                msg = "number of characters must be > 0"
                raise ValueError(msg)

            os.environ["POLARS_FMT_STR_LEN"] = str(n)
        return cls

    @classmethod
    def set_fmt_table_cell_list_len(cls, n: int | None) -> type[Config]:
        """
        Set the number of elements to display for List values.

        Empty lists will always print "[]". Negative values will result in all values
        being printed. A value of 0 will always "[…]" for lists with contents. A value
        of 1 will print only the final item in the list.

        Parameters
        ----------
        n : int
            Number of values to display.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "nums": [
        ...             [1, 2, 3, 4, 5, 6],
        ...         ]
        ...     }
        ... )
        >>> df
        shape: (1, 1)
        ┌─────────────┐
        │ nums        │
        │ ---         │
        │ list[i64]   │
        ╞═════════════╡
        │ [1, 2, … 6] │
        └─────────────┘
        >>> with pl.Config(fmt_table_cell_list_len=10):
        ...     print(df)
        shape: (1, 1)
        ┌────────────────────┐
        │ nums               │
        │ ---                │
        │ list[i64]          │
        ╞════════════════════╡
        │ [1, 2, 3, 4, 5, 6] │
        └────────────────────┘
        """
        if n is None:
            os.environ.pop("POLARS_FMT_TABLE_CELL_LIST_LEN", None)
        else:
            os.environ["POLARS_FMT_TABLE_CELL_LIST_LEN"] = str(n)
        return cls

    @classmethod
    def set_streaming_chunk_size(cls, size: int | None) -> type[Config]:
        """
        Overwrite chunk size used in `streaming` engine.

        By default, the chunk size is determined by the schema
        and size of the thread pool. For some datasets (esp.
        when you have large string elements) this can be too
        optimistic and lead to Out of Memory errors.

        Parameters
        ----------
        size
            Number of rows per chunk. Every thread will process chunks
            of this size.
        """
        if size is None:
            os.environ.pop("POLARS_STREAMING_CHUNK_SIZE", None)
        else:
            if size < 1:
                msg = "number of rows per chunk must be >= 1"
                raise ValueError(msg)

            os.environ["POLARS_STREAMING_CHUNK_SIZE"] = str(size)
        return cls

    @classmethod
    def set_tbl_cell_alignment(
        cls, format: Literal["LEFT", "CENTER", "RIGHT"] | None
    ) -> type[Config]:
        """
        Set table cell alignment.

        Parameters
        ----------
        format : str
            * "LEFT": left aligned
            * "CENTER": center aligned
            * "RIGHT": right aligned

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {"column_abc": [1.0, 2.5, 5.0], "column_xyz": [True, False, True]}
        ... )
        >>> pl.Config.set_tbl_cell_alignment("RIGHT")  # doctest: +IGNORE_RESULT
        >>> print(df)
        shape: (3, 2)
        ┌────────────┬────────────┐
        │ column_abc ┆ column_xyz │
        │        --- ┆        --- │
        │        f64 ┆       bool │
        ╞════════════╪════════════╡
        │        1.0 ┆       true │
        │        2.5 ┆      false │
        │        5.0 ┆       true │
        └────────────┴────────────┘

        Raises
        ------
        ValueError: if alignment string not recognised.
        """
        if format is None:
            os.environ.pop("POLARS_FMT_TABLE_CELL_ALIGNMENT", None)
        elif format not in {"LEFT", "CENTER", "RIGHT"}:
            msg = f"invalid alignment: {format!r}"
            raise ValueError(msg)
        else:
            os.environ["POLARS_FMT_TABLE_CELL_ALIGNMENT"] = format
        return cls

    @classmethod
    def set_tbl_cell_numeric_alignment(
        cls, format: Literal["LEFT", "CENTER", "RIGHT"] | None
    ) -> type[Config]:
        """
        Set table cell alignment for numeric columns.

        Parameters
        ----------
        format : str
            * "LEFT": left aligned
            * "CENTER": center aligned
            * "RIGHT": right aligned

        Examples
        --------
        >>> from datetime import date
        >>> df = pl.DataFrame(
        ...     {
        ...         "abc": [11, 2, 333],
        ...         "mno": [date(2023, 10, 29), None, date(2001, 7, 5)],
        ...         "xyz": [True, False, None],
        ...     }
        ... )
        >>> pl.Config.set_tbl_cell_numeric_alignment("RIGHT")  # doctest: +IGNORE_RESULT
        >>> print(df)
        shape: (3, 3)
        ┌─────┬────────────┬───────┐
        │ abc ┆ mno        ┆ xyz   │
        │ --- ┆ ---        ┆ ---   │
        │ i64 ┆ date       ┆ bool  │
        ╞═════╪════════════╪═══════╡
        │  11 ┆ 2023-10-29 ┆ true  │
        │   2 ┆ null       ┆ false │
        │ 333 ┆ 2001-07-05 ┆ null  │
        └─────┴────────────┴───────┘

        Raises
        ------
        KeyError: if alignment string not recognised.
        """
        if format is None:
            os.environ.pop("POLARS_FMT_TABLE_CELL_NUMERIC_ALIGNMENT", None)
        elif format not in {"LEFT", "CENTER", "RIGHT"}:
            msg = f"invalid alignment: {format!r}"
            raise ValueError(msg)
        else:
            os.environ["POLARS_FMT_TABLE_CELL_NUMERIC_ALIGNMENT"] = format
        return cls

    @classmethod
    def set_tbl_cols(cls, n: int | None) -> type[Config]:
        """
        Set the number of columns that are visible when displaying tables.

        Parameters
        ----------
        n : int
            Number of columns to display; if `n < 0` (eg: -1), display all columns.

        Examples
        --------
        Set number of displayed columns to a low value:

        >>> with pl.Config() as cfg:
        ...     cfg.set_tbl_cols(5)
        ...     df = pl.DataFrame({str(i): [i] for i in range(100)})
        ...     print(df)
        <class 'polars.config.Config'>
        shape: (1, 100)
        ┌─────┬─────┬─────┬───┬─────┬─────┐
        │ 0   ┆ 1   ┆ 2   ┆ … ┆ 98  ┆ 99  │
        │ --- ┆ --- ┆ --- ┆   ┆ --- ┆ --- │
        │ i64 ┆ i64 ┆ i64 ┆   ┆ i64 ┆ i64 │
        ╞═════╪═════╪═════╪═══╪═════╪═════╡
        │ 0   ┆ 1   ┆ 2   ┆ … ┆ 98  ┆ 99  │
        └─────┴─────┴─────┴───┴─────┴─────┘

        >>> with pl.Config(tbl_cols=10):
        ...     print(df)
        shape: (1, 100)
        ┌─────┬─────┬─────┬─────┬─────┬───┬─────┬─────┬─────┬─────┬─────┐
        │ 0   ┆ 1   ┆ 2   ┆ 3   ┆ 4   ┆ … ┆ 95  ┆ 96  ┆ 97  ┆ 98  ┆ 99  │
        │ --- ┆ --- ┆ --- ┆ --- ┆ --- ┆   ┆ --- ┆ --- ┆ --- ┆ --- ┆ --- │
        │ i64 ┆ i64 ┆ i64 ┆ i64 ┆ i64 ┆   ┆ i64 ┆ i64 ┆ i64 ┆ i64 ┆ i64 │
        ╞═════╪═════╪═════╪═════╪═════╪═══╪═════╪═════╪═════╪═════╪═════╡
        │ 0   ┆ 1   ┆ 2   ┆ 3   ┆ 4   ┆ … ┆ 95  ┆ 96  ┆ 97  ┆ 98  ┆ 99  │
        └─────┴─────┴─────┴─────┴─────┴───┴─────┴─────┴─────┴─────┴─────┘
        """
        if n is None:
            os.environ.pop("POLARS_FMT_MAX_COLS", None)
        else:
            os.environ["POLARS_FMT_MAX_COLS"] = str(n)
        return cls

    @classmethod
    def set_tbl_column_data_type_inline(
        cls, active: bool | None = True
    ) -> type[Config]:
        """
        Moves the data type inline with the column name (to the right, in parentheses).

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> pl.Config.set_tbl_column_data_type_inline(True)  # doctest: +SKIP
        # ...
        # shape: (3, 2)        shape: (3, 2)
        # ┌─────┬───────┐      ┌───────────┬────────────┐
        # │ abc ┆ xyz   │      │ abc (f64) ┆ xyz (bool) │
        # │ --- ┆ ---   │      ╞═══════════╪════════════╡
        # │ f64 ┆ bool  │      │ 1.0       ┆ true       │
        # ╞═════╪═══════╡  >>  │ 2.5       ┆ false      │
        # │ 1.0 ┆ true  │      │ 5.0       ┆ true       │
        # │ 2.5 ┆ false │      └───────────┴────────────┘
        # │ 5.0 ┆ true  │
        # └─────┴───────┘
        """
        if active is None:
            os.environ.pop("POLARS_FMT_TABLE_INLINE_COLUMN_DATA_TYPE", None)
        else:
            os.environ["POLARS_FMT_TABLE_INLINE_COLUMN_DATA_TYPE"] = str(int(active))
        return cls

    @classmethod
    def set_tbl_dataframe_shape_below(cls, active: bool | None = True) -> type[Config]:
        """
        Print the DataFrame shape information below the data when displaying tables.

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> pl.Config.set_tbl_dataframe_shape_below(True)  # doctest: +SKIP
        # ...
        # shape: (3, 2)        ┌─────┬───────┐
        # ┌─────┬───────┐      │ abc ┆ xyz   │
        # │ abc ┆ xyz   │      │ --- ┆ ---   │
        # │ --- ┆ ---   │      │ f64 ┆ bool  │
        # │ f64 ┆ bool  │      ╞═════╪═══════╡
        # ╞═════╪═══════╡  >>  │ 1.0 ┆ true  │
        # │ 1.0 ┆ true  │      │ 2.5 ┆ false │
        # │ 2.5 ┆ false │      │ 5.0 ┆ true  │
        # │ 5.0 ┆ true  │      └─────┴───────┘
        # └─────┴───────┘      shape: (3, 2)
        """
        if active is None:
            os.environ.pop("POLARS_FMT_TABLE_DATAFRAME_SHAPE_BELOW", None)
        else:
            os.environ["POLARS_FMT_TABLE_DATAFRAME_SHAPE_BELOW"] = str(int(active))
        return cls

    @classmethod
    def set_tbl_formatting(
        cls,
        format: TableFormatNames | None = None,
        rounded_corners: bool | None = False,
    ) -> type[Config]:
        """
        Set table formatting style.

        Parameters
        ----------
        format : str
            * "ASCII_FULL": ASCII, with all borders and lines, including row dividers.
            * "ASCII_FULL_CONDENSED": Same as ASCII_FULL, but with dense row spacing.
            * "ASCII_NO_BORDERS": ASCII, no borders.
            * "ASCII_BORDERS_ONLY": ASCII, borders only.
            * "ASCII_BORDERS_ONLY_CONDENSED": ASCII, borders only, dense row spacing.
            * "ASCII_HORIZONTAL_ONLY": ASCII, horizontal lines only.
            * "ASCII_MARKDOWN": ASCII, Markdown compatible.
            * "UTF8_FULL": UTF8, with all borders and lines, including row dividers.
            * "UTF8_FULL_CONDENSED": Same as UTF8_FULL, but with dense row spacing.
            * "UTF8_NO_BORDERS": UTF8, no borders.
            * "UTF8_BORDERS_ONLY": UTF8, borders only.
            * "UTF8_HORIZONTAL_ONLY": UTF8, horizontal lines only.
            * "NOTHING": No borders or other lines.

        rounded_corners : bool
            Apply rounded corners to UTF8-styled tables (no-op for ASCII formats).

        Notes
        -----
        The UTF8 styles all use one or more of the semigraphic box-drawing characters
        found in the Unicode Box Drawing block, which are not ASCII compatible:
        https://en.wikipedia.org/wiki/Box-drawing_character#Box_Drawing

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {"abc": [-2.5, 5.0], "mno": ["hello", "world"], "xyz": [True, False]}
        ... )
        >>> with pl.Config(
        ...     tbl_formatting="ASCII_MARKDOWN",
        ...     tbl_hide_column_data_types=True,
        ...     tbl_hide_dataframe_shape=True,
        ... ):
        ...     print(df)
        | abc  | mno   | xyz   |
        |------|-------|-------|
        | -2.5 | hello | true  |
        | 5.0  | world | false |

        Raises
        ------
        ValueError: if format string not recognised.
        """
        # note: can see what the different styles look like in the comfy-table tests
        # https://github.com/Nukesor/comfy-table/blob/main/tests/all/presets_test.rs
        if format is None:
            os.environ.pop("POLARS_FMT_TABLE_FORMATTING", None)
        else:
            valid_format_names = get_args(TableFormatNames)
            if format not in valid_format_names:
                msg = f"invalid table format name: {format!r}\nExpected one of: {', '.join(valid_format_names)}"
                raise ValueError(msg)
            os.environ["POLARS_FMT_TABLE_FORMATTING"] = format

        if rounded_corners is None:
            os.environ.pop("POLARS_FMT_TABLE_ROUNDED_CORNERS", None)
        else:
            os.environ["POLARS_FMT_TABLE_ROUNDED_CORNERS"] = str(int(rounded_corners))

        return cls

    @classmethod
    def set_tbl_hide_column_data_types(cls, active: bool | None = True) -> type[Config]:
        """
        Hide table column data types (i64, f64, str etc.).

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> pl.Config.set_tbl_hide_column_data_types(True)  # doctest: +SKIP
        # ...
        # shape: (3, 2)        shape: (3, 2)
        # ┌─────┬───────┐      ┌─────┬───────┐
        # │ abc ┆ xyz   │      │ abc ┆ xyz   │
        # │ --- ┆ ---   │      ╞═════╪═══════╡
        # │ f64 ┆ bool  │      │ 1.0 ┆ true  │
        # ╞═════╪═══════╡  >>  │ 2.5 ┆ false │
        # │ 1.0 ┆ true  │      │ 5.0 ┆ true  │
        # │ 2.5 ┆ false │      └─────┴───────┘
        # │ 5.0 ┆ true  │
        # └─────┴───────┘
        """
        if active is None:
            os.environ.pop("POLARS_FMT_TABLE_HIDE_COLUMN_DATA_TYPES", None)
        else:
            os.environ["POLARS_FMT_TABLE_HIDE_COLUMN_DATA_TYPES"] = str(int(active))
        return cls

    @classmethod
    def set_tbl_hide_column_names(cls, active: bool | None = True) -> type[Config]:
        """
        Hide table column names.

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> pl.Config.set_tbl_hide_column_names(True)  # doctest: +SKIP
        # ...
        # shape: (3, 2)        shape: (3, 2)
        # ┌─────┬───────┐      ┌─────┬───────┐
        # │ abc ┆ xyz   │      │ f64 ┆ bool  │
        # │ --- ┆ ---   │      ╞═════╪═══════╡
        # │ f64 ┆ bool  │      │ 1.0 ┆ true  │
        # ╞═════╪═══════╡  >>  │ 2.5 ┆ false │
        # │ 1.0 ┆ true  │      │ 5.0 ┆ true  │
        # │ 2.5 ┆ false │      └─────┴───────┘
        # │ 5.0 ┆ true  │
        # └─────┴───────┘
        """
        if active is None:
            os.environ.pop("POLARS_FMT_TABLE_HIDE_COLUMN_NAMES", None)
        else:
            os.environ["POLARS_FMT_TABLE_HIDE_COLUMN_NAMES"] = str(int(active))
        return cls

    @classmethod
    def set_tbl_hide_dtype_separator(cls, active: bool | None = True) -> type[Config]:
        """
        Hide the '---' separator between the column names and column types.

        See Also
        --------
        set_tbl_column_data_type_inline

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> pl.Config.set_tbl_hide_dtype_separator(True)  # doctest: +SKIP
        # ...
        # shape: (3, 2)        shape: (3, 2)
        # ┌─────┬───────┐      ┌─────┬───────┐
        # │ abc ┆ xyz   │      │ abc ┆ xyz   │
        # │ --- ┆ ---   │      │ f64 ┆ bool  │
        # │ f64 ┆ bool  │      ╞═════╪═══════╡
        # ╞═════╪═══════╡      │ 1.0 ┆ true  │
        # │ 1.0 ┆ true  │  >>  │ 2.5 ┆ false │
        # │ 2.5 ┆ false │      │ 5.0 ┆ true  │
        # │ 5.0 ┆ true  │      └─────┴───────┘
        # └─────┴───────┘
        """
        if active is None:
            os.environ.pop("POLARS_FMT_TABLE_HIDE_COLUMN_SEPARATOR", None)
        else:
            os.environ["POLARS_FMT_TABLE_HIDE_COLUMN_SEPARATOR"] = str(int(active))
        return cls

    @classmethod
    def set_tbl_hide_dataframe_shape(cls, active: bool | None = True) -> type[Config]:
        """
        Hide the DataFrame shape information when displaying tables.

        Examples
        --------
        >>> df = pl.DataFrame({"abc": [1.0, 2.5, 5.0], "xyz": [True, False, True]})
        >>> pl.Config.set_tbl_hide_dataframe_shape(True)  # doctest: +SKIP
        # ...
        # shape: (3, 2)        ┌─────┬───────┐
        # ┌─────┬───────┐      │ abc ┆ xyz   │
        # │ abc ┆ xyz   │      │ --- ┆ ---   │
        # │ --- ┆ ---   │      │ f64 ┆ bool  │
        # │ f64 ┆ bool  │      ╞═════╪═══════╡
        # ╞═════╪═══════╡      │ 1.0 ┆ true  │
        # │ 1.0 ┆ true  │  >>  │ 2.5 ┆ false │
        # │ 2.5 ┆ false │      │ 5.0 ┆ true  │
        # │ 5.0 ┆ true  │      └─────┴───────┘
        # └─────┴───────┘
        """
        if active is None:
            os.environ.pop("POLARS_FMT_TABLE_HIDE_DATAFRAME_SHAPE_INFORMATION", None)
        else:
            os.environ["POLARS_FMT_TABLE_HIDE_DATAFRAME_SHAPE_INFORMATION"] = str(
                int(active)
            )
        return cls

    @classmethod
    def set_tbl_rows(cls, n: int | None) -> type[Config]:
        """
        Set the max number of rows used to draw the table (both Dataframe and Series).

        Parameters
        ----------
        n : int
            Number of rows to display; if `n < 0` (eg: -1), display all
            rows (DataFrame) and all elements (Series).

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {"abc": [1.0, 2.5, 3.5, 5.0], "xyz": [True, False, True, False]}
        ... )
        >>> with pl.Config(tbl_rows=2):
        ...     print(df)
        shape: (4, 2)
        ┌─────┬───────┐
        │ abc ┆ xyz   │
        │ --- ┆ ---   │
        │ f64 ┆ bool  │
        ╞═════╪═══════╡
        │ 1.0 ┆ true  │
        │ …   ┆ …     │
        │ 5.0 ┆ false │
        └─────┴───────┘
        """
        if n is None:
            os.environ.pop("POLARS_FMT_MAX_ROWS", None)
        else:
            os.environ["POLARS_FMT_MAX_ROWS"] = str(n)
        return cls

    @classmethod
    def set_tbl_width_chars(cls, width: int | None) -> type[Config]:
        """
        Set the maximum width of a table in characters.

        Parameters
        ----------
        width : int
            Maximum table width in characters.
        """
        if width is None:
            os.environ.pop("POLARS_TABLE_WIDTH", None)
        else:
            os.environ["POLARS_TABLE_WIDTH"] = str(width)
        return cls

    @classmethod
    def set_trim_decimal_zeros(cls, active: bool | None = True) -> type[Config]:
        """
        Strip trailing zeros from Decimal data type values.

        Parameters
        ----------
        active : bool
            Enable stripping of trailing '0' characters from Decimal values.

        Examples
        --------
        >>> from decimal import Decimal as D
        >>> df = pl.DataFrame(
        ...     data={"d": [D("1.01"), D("-5.6789")]},
        ...     schema={"d": pl.Decimal(scale=5)},
        ... )
        >>> with pl.Config(trim_decimal_zeros=False):
        ...     print(df)
        shape: (2, 1)
        ┌──────────────┐
        │ d            │
        │ ---          │
        │ decimal[*,5] │
        ╞══════════════╡
        │ 1.01000      │
        │ -5.67890     │
        └──────────────┘
        >>> with pl.Config(trim_decimal_zeros=True):
        ...     print(df)
        shape: (2, 1)
        ┌──────────────┐
        │ d            │
        │ ---          │
        │ decimal[*,5] │
        ╞══════════════╡
        │ 1.01         │
        │ -5.6789      │
        └──────────────┘
        """
        plr.set_trim_decimal_zeros(active)
        return cls

    @classmethod
    def set_verbose(cls, active: bool | None = True) -> type[Config]:
        """
        Enable additional verbose/debug logging.

        Examples
        --------
        >>> pl.Config.set_verbose(True)  # doctest: +SKIP
        >>> with pl.Config(verbose=True):  # doctest: +SKIP
        ...     do_polars_operations()
        """
        if active is None:
            os.environ.pop("POLARS_VERBOSE", None)
        else:
            os.environ["POLARS_VERBOSE"] = str(int(active))
        return cls

    @classmethod
    def warn_unstable(cls, active: bool | None = True) -> type[Config]:
        """
        Issue a warning when unstable functionality is used.

        Enabling this setting may help avoid functionality that is still evolving,
        potentially reducing maintenance burden from API changes and bugs.

        Examples
        --------
        >>> pl.Config.warn_unstable(True)  # doctest: +SKIP
        >>> pl.col("a").qcut(5)  # doctest: +SKIP
        UnstableWarning: `qcut` is considered unstable. It may be changed at any point without it being considered a breaking change.
        """  # noqa: W505
        if active is None:
            os.environ.pop("POLARS_WARN_UNSTABLE", None)
        else:
            os.environ["POLARS_WARN_UNSTABLE"] = str(int(active))
        return cls
