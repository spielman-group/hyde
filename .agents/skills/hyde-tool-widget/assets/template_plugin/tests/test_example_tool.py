import unittest

from qtutils.qt import QtWidgets

from plugin_package.window import ExampleTool, ExampleContent


class TestExampleTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_tool_mounts_one_content_widget_through_base_shell(self):
        tool = ExampleTool(window_identifier="example_tool")
        try:
            self.assertIsInstance(tool.mounted_child, ExampleContent)
            self.assertEqual(tool.window_identifier(), "example_tool")
        finally:
            tool.close()
