import unittest

from hyde.user_interface.window_naming import window_title


class TestWindowTitle(unittest.TestCase):
    def test_window_title_defaults_to_stable_name_with_optional_detail(self):
        self.assertEqual(window_title("Figure7"), "Figure7")
        self.assertEqual(window_title("Table7", title_suffix="a, b"), "Table7: a, b")

    def test_window_title_uses_explicit_title_as_suffix_and_warning_suffix(self):
        self.assertEqual(
            window_title(
                "Figure7",
                title_suffix="Shared Plot",
                warning_text="Macro Incomplete",
            ),
            "Figure7: Shared Plot [Macro Incomplete]",
        )
        self.assertEqual(
            window_title("Figure7", warning_text="Macro Incomplete"),
            "Figure7 [Macro Incomplete]",
        )
        self.assertEqual(
            window_title(
                "Figure7",
                title_suffix="Figure7",
                warning_text="Macro Incomplete",
            ),
            "Figure7: Figure7 [Macro Incomplete]",
        )
