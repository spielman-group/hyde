from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class ObservableArray(np.ndarray):
    def __new__(cls, input_array, owner=None):
        obj = np.asarray(input_array).view(cls)
        obj._hyde_owner = owner
        return obj

    def __array_finalize__(self, obj):
        self._hyde_owner = getattr(obj, "_hyde_owner", None)

    def _notify(self):
        owner = getattr(self, "_hyde_owner", None)
        if owner is not None:
            owner.touch()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._notify()

    def fill(self, value):
        super().fill(value)
        self._notify()

    def sort(self, axis=-1, kind=None, order=None):
        super().sort(axis=axis, kind=kind, order=order)
        self._notify()


@dataclass
class HydeObjectSummary:
    name: str
    kind: str
    type_name: str
    shape: list[int]
    dtype: str
    revision: int
    preview: str


class TrackedArray(np.lib.mixins.NDArrayOperatorsMixin):
    __array_priority__ = 1000

    def __init__(self, name, data, title=None):
        self.name = str(name)
        self.title = title or self.name
        self._array = ObservableArray(np.asarray(data), owner=self)
        self.revision = 0

    @property
    def array(self):
        return self._array

    @property
    def shape(self):
        return list(self._array.shape)

    @property
    def dtype(self):
        return str(self._array.dtype)

    def __array__(self, dtype=None):
        return np.asarray(self._array, dtype=dtype)

    def __len__(self):
        return len(self._array)

    def __getitem__(self, item):
        return self._array[item]

    def __setitem__(self, item, value):
        self._array[item] = value

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        out_arrays = []
        out_targets = ()

        def unwrap(value):
            if isinstance(value, TrackedArray):
                return value.array
            if isinstance(value, tuple):
                return tuple(unwrap(item) for item in value)
            return value

        def coerce_result(value):
            if isinstance(value, ObservableArray):
                return np.asarray(value)
            if isinstance(value, tuple):
                return tuple(coerce_result(item) for item in value)
            return value

        if "out" in kwargs and kwargs["out"] is not None:
            out_targets = kwargs["out"]
            kwargs["out"] = tuple(unwrap(value) for value in kwargs["out"])
            out_arrays = [value for value in kwargs["out"] if isinstance(value, ObservableArray)]

        result = getattr(ufunc, method)(*(unwrap(value) for value in inputs), **kwargs)

        for array in out_arrays:
            owner = getattr(array, "_hyde_owner", None)
            if owner is not None:
                owner.touch()
        if out_targets:
            if len(out_targets) == 1:
                return out_targets[0]
            return out_targets
        return coerce_result(result)

    def set_data(self, data):
        self._array = ObservableArray(np.asarray(data), owner=self)
        self.touch()

    def touch(self):
        self.revision += 1

    def append(self, values):
        self._array = ObservableArray(
            np.append(self._array, values, axis=0 if self._array.ndim else None),
            owner=self,
        )
        self.touch()

    def summary(self):
        preview = np.array2string(
            np.asarray(self._array).reshape(-1)[:6],
            precision=4,
            separator=", ",
        )
        return HydeObjectSummary(
            name=self.name,
            kind="numpy",
            type_name="ndarray",
            shape=self.shape,
            dtype=self.dtype,
            revision=self.revision,
            preview=preview,
        )

    def to_serializable(self):
        return {
            "kind": "wave",
            "name": self.name,
            "title": self.title,
            "dtype": self.dtype,
            "shape": self.shape,
            "revision": self.revision,
        }


def summarize_object(name, value):
    if isinstance(value, TrackedArray):
        return value.summary().__dict__
    if isinstance(value, np.ndarray):
        return TrackedArray(name, value).summary().__dict__
    preview = repr(value)
    if len(preview) > 80:
        preview = preview[:77] + "..."
    return HydeObjectSummary(
        name=name,
        kind="python",
        type_name=type(value).__name__,
        shape=[],
        dtype="",
        revision=0,
        preview=preview,
    ).__dict__
