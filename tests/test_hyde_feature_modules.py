import importlib
import importlib.util
import inspect
import unittest

from hyde.features.base import (
    FeatureCodec,
    is_eligible_for_numeric_series,
    sorted_eligible_names,
)


class TestHydeFeatureModuleLayout(unittest.TestCase):
    def test_hyde_codec_rejects_non_hyde_mutation_feature_state(self):
        from hyde.features.hyde_features import HydeCodec

        with self.assertRaises(ValueError):
            HydeCodec.default_state(feature="mutation")

    def test_feature_modules_expose_one_package_local_codec_surface_each(self):
        for module_name, expected_codec in (
            ("hyde.features.hyde_features", "HydeCodec"),
            ("hyde.features.matplotlib_features", "MatplotlibCodec"),
        ):
            with self.subTest(module_name=module_name):
                spec = importlib.util.find_spec(module_name)
                self.assertIsNotNone(spec)

                module = importlib.import_module(module_name)
                codec_classes = [
                    value
                    for _, value in inspect.getmembers(module, inspect.isclass)
                    if issubclass(value, FeatureCodec) and value is not FeatureCodec
                ]

                self.assertEqual(
                    [codec.__name__ for codec in codec_classes],
                    [expected_codec],
                )

    def test_shared_numeric_series_helpers_are_neutral_and_used_by_callers(self):
        from hyde.features import lmfit_features
        from hyde.user_interface.plugins.figure_interactive import dialogs as figure_dialogs
        from hyde.user_interface.plugins.table_interactive import dialogs as table_dialogs
        python_variables_tool = importlib.import_module(
            "hyde.user_interface.plugins.python_variables_tool"
        )

        metadata = {
            "delay": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "f", "ndim": 1},
            "label": {"python_type": "str", "numpy_type": "", "numpy_kind": "U", "ndim": 0},
            "count": {"python_type": "ndarray", "numpy_type": "Array", "numpy_kind": "i", "ndim": 1},
        }

        self.assertEqual(sorted_eligible_names(metadata), ["count", "delay"])
        self.assertTrue(is_eligible_for_numeric_series(metadata["delay"]))
        self.assertFalse(is_eligible_for_numeric_series(metadata["label"]))
        self.assertIs(lmfit_features.sorted_eligible_names, sorted_eligible_names)
        self.assertIs(figure_dialogs.sorted_eligible_names, sorted_eligible_names)
        self.assertIs(
            table_dialogs.is_eligible_for_numeric_series,
            is_eligible_for_numeric_series,
        )
        self.assertIs(
            python_variables_tool.is_eligible_for_numeric_series,
            is_eligible_for_numeric_series,
        )
