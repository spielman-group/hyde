import unittest

from qtutils.qt import QtWidgets

from plugin_package.window import ExampleInteractiveWindow


class TestExampleInteractiveWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_interactive_window_exposes_base_saveable_contract(self):
        window = ExampleInteractiveWindow(initial_window_name="ExampleInteractive0")
        try:
            self.assertEqual(window.default_macro_name(), "ExampleInteractive0")
            self.assertEqual(window.tracked_namespace_names(), ("example_data",))
        finally:
            window.close()
