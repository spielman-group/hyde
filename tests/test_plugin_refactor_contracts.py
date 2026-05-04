import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = REPO_ROOT / "hyde" / "user_interface" / "main" / "__init__.py"
USER_INTERFACE_DIR = REPO_ROOT / "hyde" / "user_interface"
PLUGINS_DIR = USER_INTERFACE_DIR / "plugins"
PROJECT_STATE_PATH = USER_INTERFACE_DIR / "project_state.py"


class TestPluginRefactorContracts(unittest.TestCase):
    def test_build_plugin_services_does_not_publish_raw_app(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "HydeApp":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "build_plugin_services":
                        service_keys = []
                        for child in ast.walk(item):
                            if not isinstance(child, ast.Dict):
                                continue
                            for key in child.keys:
                                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                    service_keys.append(key.value)
                        self.assertNotIn("app", service_keys)
                        self.assertNotIn("show_new_table_dialog", service_keys)
                        self.assertNotIn("request_window_macros", service_keys)
                        self.assertNotIn("choose_new_project", service_keys)
                        self.assertNotIn("choose_project", service_keys)
                        self.assertNotIn("choose_heal_project", service_keys)
                        self.assertNotIn("save_project", service_keys)
                        self.assertNotIn("save_project_as", service_keys)
                        self.assertNotIn("save_project_copy", service_keys)
                        self.assertNotIn("request_quit", service_keys)
                        self.assertNotIn("open_table", service_keys)
                        self.assertNotIn("lookup_table", service_keys)
                        self.assertNotIn("iter_open_tables", service_keys)
                        self.assertNotIn("get_active_table_handle", service_keys)
                        self.assertNotIn("set_active_table_handle", service_keys)
                        self.assertNotIn("get_table_counter", service_keys)
                        self.assertNotIn("set_table_counter", service_keys)
                        self.assertNotIn("request_save_table_macro", service_keys)
                        return

        self.fail("HydeApp.build_plugin_services was not found")

    def test_shell_discovers_plugins_from_plugin_only_package(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name) or func.id != "HydePluginManager":
                continue

            keyword_values = {
                keyword.arg: keyword.value
                for keyword in node.keywords
                if keyword.arg is not None
            }
            plugin_package = keyword_values.get("plugin_package")
            self.assertIsInstance(plugin_package, ast.Constant)
            self.assertEqual(plugin_package.value, "hyde.user_interface.plugins")
            return

        self.fail("HydePluginManager(...) construction was not found")

    def test_shell_has_no_top_level_imports_from_plugin_packages(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_module = node.module
            elif isinstance(node, ast.Import):
                imported_module = node.names[0].name if node.names else None
            else:
                continue

            if imported_module is None:
                continue
            self.assertFalse(
                imported_module.startswith("hyde.user_interface.plugins."),
                imported_module,
            )

    def test_shell_has_no_imports_from_plugin_packages_anywhere(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_module = node.module
            elif isinstance(node, ast.Import):
                imported_module = node.names[0].name if node.names else None
            else:
                continue

            if imported_module is None:
                continue
            self.assertFalse(
                imported_module.startswith("hyde.user_interface.plugins."),
                imported_module,
            )

    def test_plugin_modules_do_not_import_sibling_feature_packages(self):
        allowed_modules = {
            "hyde.user_interface.base",
            "hyde.user_interface.file_dialogs",
            "hyde.user_interface.plugin_tools",
            "hyde.user_interface.table",
        }

        for path in PLUGINS_DIR.glob("*/__init__.py"):
            module_name = f"hyde.user_interface.plugins.{path.parent.name}"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if not any(isinstance(node, ast.ClassDef) and node.name == "Plugin" for node in tree.body):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported_module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_module = alias.name
                        break
                    else:
                        continue
                else:
                    continue

                if not imported_module.startswith("hyde.user_interface."):
                    continue
                if (
                    imported_module == module_name
                    or imported_module.startswith(f"{module_name}.")
                ):
                    continue
                if imported_module in allowed_modules:
                    continue

                self.fail(
                    f"{module_name} imports sibling feature module {imported_module}"
                )

    def test_capture_session_collects_plugin_save_data(self):
        tree = ast.parse(PROJECT_STATE_PATH.read_text(encoding="utf-8"))
        saw_get_save_data = False
        saw_request_project_save_event = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "get_save_data":
                    saw_get_save_data = True
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "emit_plugin_event"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "request_project_save"
                ):
                    saw_request_project_save_event = True

        self.assertTrue(saw_get_save_data)
        self.assertFalse(saw_request_project_save_event)

    def test_project_state_no_longer_defines_legacy_feature_restore_helpers(self):
        tree = ast.parse(PROJECT_STATE_PATH.read_text(encoding="utf-8"))
        function_names = {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        }

        self.assertNotIn("restore_tool_windows", function_names)
        self.assertNotIn("restore_data_browser_state", function_names)
        self.assertNotIn("restore_tables", function_names)

    def test_shell_no_longer_defines_manual_plugin_window_registry(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != "HydeApp":
                continue
            method_names = {
                item.name for item in node.body if isinstance(item, ast.FunctionDef)
            }
            self.assertNotIn("_register_plugin_window", method_names)
            return

        self.fail("HydeApp class was not found")

    def test_shell_no_longer_defines_table_ownership_methods(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != "HydeApp":
                continue
            method_names = {
                item.name for item in node.body if isinstance(item, ast.FunctionDef)
            }
            self.assertNotIn("lookup_table", method_names)
            self.assertNotIn("iter_open_tables", method_names)
            self.assertNotIn("get_active_table_handle", method_names)
            self.assertNotIn("set_active_table_handle", method_names)
            self.assertNotIn("get_table_counter", method_names)
            self.assertNotIn("set_table_counter", method_names)
            self.assertNotIn("open_table", method_names)
            self.assertNotIn("request_save_table_macro", method_names)
            self.assertNotIn("rebuild_table_macros_menu", method_names)
            self.assertNotIn("update_table_macros", method_names)
            self.assertNotIn("_on_subwindow_activated", method_names)
            return

        self.fail("HydeApp class was not found")

    def test_shell_no_longer_tracks_table_state_fields(self):
        source = MAIN_PATH.read_text(encoding="utf-8")
        self.assertNotIn("self.tables =", source)
        self.assertNotIn("self.active_table_handle =", source)
        self.assertNotIn("self.table_counter =", source)
        self.assertNotIn("self.table_macros =", source)


if __name__ == "__main__":
    unittest.main()
