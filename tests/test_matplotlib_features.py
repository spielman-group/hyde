import gc
import sys
import types
import unittest
import weakref
from unittest.mock import patch

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("matplotlib is required") from exc

import hyde

from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.matplotlib_backend import (
    FigureCanvasHyde,
    FigureManagerHyde,
    _install_first_class_figure_resync_hook,
    _resync_dirty_first_class_figures,
    _figure_defaults_snapshot,
    figure_snapshot_payload,
)
from hyde.features.matplotlib_features import (
    MatplotlibCodec,
    FigureGraphicsExportModel,
    figure_ir_from_live_state,
    figure_graphics_export_command_source,
    figure_patch_source,
    graphics_output_options,
    graphics_output_transparency_supported,
    graphics_export_formats,
)
from hyde.features.hyde_ir import HydeAppIR
from hyde.project_tools import (
    HYDE_MATPLOTLIB_BACKEND,
    configure_gui_matplotlib_backend,
    is_excluded,
)
from hyde.user_interface.shared.plugin import HydePlugin
from hyde.user_interface.plugins.figure_interactive import (
    FigureContextService,
    FigureFeatureService,
    FigureWorkspaceService,
    Plugin,
)
from hyde.user_interface.plugins.figure_interactive.dialogs import NewFigureDialog
from hyde.features.matplotlib_figure_state import FigureIRAuthority
from hyde.features.matplotlib_ir import FigureIR, FigureIRDiff
from hyde.user_interface.plugins.figure_interactive.window import FigureWindow
from hyde.user_interface.plugins.kernel_runtime import KernelRequest
from tests.kernel_fakes import KernelRequestRecorder
from hyde.user_interface.shared.core import log_hyde_dispatch_debug
from hyde.user_interface.plugins.figure_interactive.context import EditableFigureContext


class FakeNamespaceViewService:
    def __init__(self, view=None):
        self._view = dict(view or {})
        self._callbacks = []
        self.connected = False

    def namespace_view(self):
        return dict(self._view)

    def connect_namespace_view_updated(self, callback):
        self.connected = True
        self._callbacks.append(callback)

    def disconnect_namespace_view_updated(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, view):
        self._view = dict(view)
        for callback in list(self._callbacks):
            callback(dict(self._view))


class FakeExecutionService(KernelRequestRecorder):
    def __init__(self, hidden_calls=None, visible_calls=None):
        self.hidden_calls = hidden_calls if hidden_calls is not None else []
        self.visible_calls = visible_calls if visible_calls is not None else []

    def execute_hidden(self, code, silent=True):
        log_hyde_dispatch_debug("hidden", code)
        self.hidden_calls.append((code, silent))
        return True


    def execute_visible(self, code):
        self.visible_calls.append(code)
        return True


class FakeShellEvents:
    def __init__(self):
        self.registered = {}

    def register(self, name, callback):
        self.registered.setdefault(name, []).append(callback)


class FakeShell:
    def __init__(self):
        self.events = FakeShellEvents()
        self.enabled_gui = []

    def enable_gui(self, gui=None):
        self.enabled_gui.append(gui)


class TestGraphicsExportFormats(unittest.TestCase):
    def test_matplotlib_codec_rejects_the_ambiguous_figure_feature_name(self):
        # Not migration scaffolding: unrecognised feature kinds fall through to
        # figure_command, so a plausible-looking "figure" would silently lower
        # as the wrong kind rather than being rejected.
        with self.assertRaisesRegex(ValueError, "Ambiguous matplotlib feature"):
            MatplotlibCodec.validate_state(
                {
                    "feature": "figure",
                    "settings": {"title": "DelayGraph"},
                }
            )

    def test_graphics_export_macro_source_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            MatplotlibCodec.state_to_macro_source(
                {
                    "feature": MatplotlibCodec.figure_graphics_export_feature,
                    "settings": {
                        "figure_name": "Figure9",
                        "output_path": "/tmp/Figure9.png",
                        "output_format": "png",
                        "dpi": 300,
                        "transparent": False,
                    }
                },
                "SaveFigure",
            )

    def test_matplotlib_figure_lowerers_emit_only_matplotlib_python(self):
        figure_command = MatplotlibCodec.state_to_python(
            {
                "feature": "figure_command",
                "settings": {
                    "command": "create",
                    "title": "DelayGraph",
                    "x_name": "delay",
                    "subplot_code": "111",
                },
                "items": ["fit_delay"],
            }
        )
        self.assertNotIn("@hyde", figure_command)
        self.assertNotIn("hyde.", figure_command)
        self.assertIn("fig = plt.figure('DelayGraph')", figure_command)
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", figure_command)

        figure_ir = figure_ir_from_live_state(
            {
                "feature": "figure_command",
                "settings": {
                    "command": "create",
                    "title": "DelayGraph",
                    "x_name": "delay",
                    "subplot_code": "111",
                },
                "items": ["fit_delay"],
            }
        )
        target_ir = MatplotlibCodec.update_state(
            figure_ir,
            {
                "type": "set_legend_visible",
                "visible": True,
            },
        )
        figure_patch = MatplotlibCodec.state_to_python(
            {
                "feature": "figure_patch",
                "settings": {
                    "figure_name": "Figure9",
                    "source_state": figure_ir,
                    "target_state": target_ir,
                    "refresh_trace_ids": (),
                    "refresh_legend": True,
                },
            }
        )
        self.assertNotIn("@hyde", figure_patch)
        self.assertNotIn("hyde.", figure_patch)
        self.assertIn("ax.legend()", figure_patch)

        figure_export = MatplotlibCodec.state_to_python(
            {
                "feature": "figure_graphics_export",
                "settings": {
                    "figure_name": "Figure9",
                    "output_path": "/tmp/Figure9.png",
                    "output_format": "png",
                    "dpi": 450,
                    "transparent": True,
                    "size_inches": (4.0, 2.5),
                },
            }
        )
        self.assertNotIn("@hyde", figure_export)
        self.assertNotIn("hyde.", figure_export)
        self.assertIn(
            "fig.savefig('/tmp/Figure9.png', format='png', dpi=450, transparent=True)",
            figure_export,
        )

    def test_figure_ir_owns_hyde_wrapping_for_create_patch_and_export_commands(self):
        current_ir = (
            FigureIR()
            .with_title("DelayGraph")
            .with_x_name("delay")
            .with_items(["fit_delay"])
        )

        figure_command = current_ir.python_source(log=False)
        self.assertIn("@hyde.figure(register=False)", figure_command)
        self.assertIn("fig = plt.figure('DelayGraph')", figure_command)
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", figure_command)

        patch_source = current_ir.current_diff(
            current_ir.set_legend_visible(True)
        ).as_patch("Figure9").python_source(log=False)
        self.assertIn("fig = hyde.get_figure('Figure9')", patch_source)
        self.assertIn("ax = fig.axes[0]", patch_source)
        self.assertIn("ax.legend()", patch_source)

        figure_export = FigureIR(figure_name="Figure9").with_save_graphics(
            "/tmp/Figure9.png",
            output_format="png",
            dpi=450,
            transparent=True,
            size_inches=(4.0, 2.5),
        )
        export_source = figure_export.python_source(log=False)
        self.assertIn("fig = hyde.get_figure('Figure9')", export_source)
        self.assertIn(
            "fig.savefig('/tmp/Figure9.png', format='png', dpi=450, transparent=True)",
            export_source,
        )

    def test_graphics_export_lowers_state_to_savefig_command(self):
        source = FigureGraphicsExportModel.state_to_python(
            {
                "settings": {
                    "figure_name": "Figure9",
                    "output_path": "/tmp/Figure9.png",
                    "output_format": "png",
                    "dpi": 450,
                    "transparent": True,
                    "size_inches": (4.0, 2.5),
                }
            }
        )

        self.assertNotIn("import hyde", source)
        self.assertNotIn("hyde.", source)
        self.assertIn("_hyde_original_size = tuple(fig.get_size_inches())", source)
        self.assertIn("fig.set_size_inches(4.0, 2.5, forward=False)", source)
        self.assertIn(
            "fig.savefig('/tmp/Figure9.png', format='png', dpi=450, transparent=True)",
            source,
        )
        self.assertIn(
            "fig.set_size_inches(*_hyde_original_size, forward=False)",
            source,
        )

    def test_graphics_export_formats_orders_defaults_and_tracks_suffix_variants(self):
        formats = graphics_export_formats(
            {
                "svg": "Scalable Vector Graphics",
                "png": "Portable Network Graphics",
                "jpeg": "Joint Photographic Experts Group",
                "jpg": "Joint Photographic Experts Group",
                "pdf": "Portable Document Format",
                "tiff": "Tagged Image File Format",
                "tif": "Tagged Image File Format",
            }
        )

        self.assertEqual(
            [item.key for item in formats],
            ["pdf", "png", "jpeg", "jpg", "svg", "tif", "tiff"],
        )

        jpg_format = next(item for item in formats if item.key == "jpg")
        jpeg_format = next(item for item in formats if item.key == "jpeg")

        self.assertEqual(jpg_format.display_label, "JPG")
        self.assertEqual(jpg_format.compatible_suffixes, (".jpg", ".jpeg"))
        self.assertEqual(jpg_format.name_filter, "JPG Files (*.jpg *.jpeg)")
        self.assertEqual(jpeg_format.display_label, "JPEG")
        self.assertEqual(jpeg_format.compatible_suffixes, (".jpeg", ".jpg"))
        self.assertEqual(jpeg_format.name_filter, "JPEG Files (*.jpeg *.jpg)")

    def test_graphics_output_options_normalize_savefig_controls(self):
        options = graphics_output_options(
            "png",
            dpi=450,
            transparent=True,
            size_inches=(4, 2.5),
        )

        self.assertEqual(
            options,
            {
                "format": "png",
                "dpi": 450,
                "transparent": True,
                "size_inches": (4.0, 2.5),
            },
        )

    def test_transparency_support_is_disabled_only_for_clearly_opaque_formats(self):
        self.assertTrue(graphics_output_transparency_supported("pdf"))
        self.assertTrue(graphics_output_transparency_supported("svg"))
        self.assertFalse(graphics_output_transparency_supported("jpg"))
        self.assertFalse(graphics_output_transparency_supported("jpeg"))

    def test_graphics_export_command_source_applies_size_override_dpi_and_transparency(self):
        source = figure_graphics_export_command_source(
            "Figure9",
            "/tmp/Figure9.png",
            output_format="png",
            dpi=450,
            transparent=True,
            size_inches=(4.0, 2.5),
        )

        self.assertNotIn("import hyde", source)
        self.assertNotIn("hyde.", source)
        self.assertIn("_hyde_original_size = tuple(fig.get_size_inches())", source)
        self.assertIn("fig.set_size_inches(4.0, 2.5, forward=False)", source)
        self.assertIn(
            "fig.savefig('/tmp/Figure9.png', format='png', dpi=450, transparent=True)",
            source,
        )
        self.assertIn(
            "fig.set_size_inches(*_hyde_original_size, forward=False)",
            source,
        )


class TestFigureCodec(unittest.TestCase):
    def test_figure_ir_generates_first_class_figure_builder_code(self):
        figure_ir = (
            FigureIR()
            .with_title("DelayGraph")
            .with_x_name("delay")
            .with_items(["fit_delay", "raw_delay"])
        )

        source = figure_ir.python_source()

        self.assertIn("@hyde.figure(register=False)", source)
        self.assertIn("def _hyde_figure(delay, fit_delay, raw_delay):", source)
        self.assertIn("_hyde_figure(delay, fit_delay, raw_delay)", source)
        self.assertIn("del _hyde_figure", source)
        self.assertIn("fig = plt.figure('DelayGraph')", source)
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", source)
        self.assertIn("ax.plot(delay, raw_delay, label='raw_delay')", source)
        self.assertIsInstance(figure_ir.current_diff(), FigureIRDiff)

    def test_figure_ir_generates_refresh_publish_and_close_commands(self):
        self.assertEqual(
            FigureIR().with_refresh_figure("DelayGraph", use_bound_values=True).python_source(
                log=False
            ),
            "fig = hyde.get_figure('DelayGraph')\n"
            "hyde.refresh_figure(fig, use_bound_values=True)",
        )
        self.assertEqual(
            FigureIR().with_publish_figure_macros().python_source(log=False),
            "hyde.recreation_registry.publish_registry('figure')",
        )
        self.assertEqual(
            FigureIR().with_close_figure(3).python_source(log=False),
            "plt.close(3)",
        )

    def test_figure_ir_generates_decorated_macro_source(self):
        macro = (
            FigureIR()
            .with_title("DelayGraph")
            .with_x_name("delay")
            .with_items(["fit_delay"])
            .macro_source("Graph0")
        )

        self.assertIn("@hyde.figure", macro)
        self.assertIn("def Graph0(delay, fit_delay):", macro)
        self.assertIn("fig = plt.figure('DelayGraph')", macro)
        self.assertIn("ax = fig.add_subplot(111)", macro)
        self.assertIn("ax.plot(delay, fit_delay, label='fit_delay')", macro)

    def test_figure_ir_python_source_logs_through_standard_hyde_debug_channel(self):
        figure_ir = (
            FigureIR()
            .with_title("DelayGraph")
            .with_x_name("delay")
            .with_items(["fit_delay"])
        )

        with self.assertLogs("hyde", level="DEBUG") as logs:
            source = figure_ir.python_source()

        output = "\n".join(logs.output)
        self.assertIn("[Hyde state] FigureIR", output)
        self.assertIn("python:\n", output)
        self.assertIn(source, output)


class TestFigureIRAuthorityIsShared(unittest.TestCase):
    """The kernel and the GUI must normalize figure IR through one authority.

    The kernel reaches figure IR through `MatplotlibCodec`; the GUI reaches it
    through `FigureIRAuthority`. While those were separate copies they silently
    diverged on the `feature` key and on wrong-kind validation, so the same
    state normalized differently on either side of the process boundary.
    """

    def _live_figure_ir(self):
        return figure_ir_from_live_state(
            {
                "feature": "figure_command",
                "settings": {
                    "command": "create",
                    "title": "DelayGraph",
                    "x_name": "delay",
                    "subplot_code": "111",
                    "figsize": (5.0, 3.0),
                },
                "items": ["fit_delay", "raw_delay"],
                "ui": {},
            }
        )

    def test_default_state_matches_across_the_process_boundary(self):
        self.assertEqual(
            MatplotlibCodec.default_state(feature=MatplotlibCodec.figure_ir_feature),
            FigureIRAuthority.default_state(),
        )

    def test_validated_state_matches_across_the_process_boundary(self):
        figure_ir = self._live_figure_ir()

        self.assertEqual(
            MatplotlibCodec.validate_state(figure_ir),
            FigureIRAuthority.validate_state(figure_ir),
        )

    def test_lowering_and_tracked_names_match_across_the_process_boundary(self):
        figure_ir = self._live_figure_ir()

        self.assertEqual(
            MatplotlibCodec.state_to_python(figure_ir),
            FigureIRAuthority.state_to_python(figure_ir),
        )
        self.assertEqual(
            tuple(MatplotlibCodec.tracked_names(figure_ir)),
            tuple(FigureIRAuthority.tracked_names(figure_ir)),
        )

    def test_axis_edits_lower_identically_across_the_process_boundary(self):
        action = {
            "type": "set_axis_label",
            "subplot_id": "subplot0",
            "axis": "x",
            "label": {"text": "Delay"},
        }
        figure_ir = self._live_figure_ir()

        self.assertEqual(
            MatplotlibCodec.update_state(figure_ir, action),
            FigureIRAuthority.update_state(figure_ir, action),
        )

    def test_authority_rejects_a_state_of_another_feature_kind(self):
        with self.assertRaisesRegex(ValueError, "Expected feature='figure_ir'"):
            FigureIRAuthority.validate_state(
                {
                    "feature": "figure_patch",
                    "layout": {"kind": "single_subplot", "subplots": []},
                }
            )


class TestFigurePluginDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_new_figure_dialog_launcher_passes_services_and_stops_post_exec_dispatch(self):
        executed = []
        captured = {}

        plugin = type("FakePlugin", (), {})()
        plugin.workspace = type(
            "FakeWorkspace",
            (),
            {"next_generated_title": lambda self: "Figure0"},
        )()
        plugin.services = {
            "python_execution_service": FakeExecutionService(executed),
        }

        service = FigureFeatureService(plugin)

        class FakeDialog:
            def __init__(
                self,
                objects_metadata,
                preselection=None,
                services=None,
                parent=None,
            ):
                del objects_metadata, preselection, parent
                captured["services"] = services

            def exec(self):
                return True

        with patch(
            "hyde.user_interface.plugins.figure_interactive.dialogs.NewFigureDialog",
            FakeDialog,
        ):
            self.assertTrue(service.show_new_figure_dialog({"arr": {}}, parent=None))

        self.assertIs(captured["services"], plugin.services)
        self.assertEqual(executed, [])

    def test_new_figure_dialog_defaults_to_reasonable_figure_size(self):
        dialog = NewFigureDialog({"arr": {"python_type": "ndarray", "numpy_type": "Array", "ndim": 1, "numpy_kind": "f"}})
        try:
            state = dialog.normalized_state()
            self.assertEqual(dialog.ui.widthSpinBox.value(), 5.0)
            self.assertEqual(dialog.ui.heightSpinBox.value(), 3.0)
            self.assertEqual(dialog.ui.widthSpinBox.prefix(), "x: ")
            self.assertEqual(dialog.ui.heightSpinBox.prefix(), "y: ")
            self.assertEqual(state["settings"]["figsize"], (5.0, 3.0))
        finally:
            dialog.close()

    def test_new_figure_dialog_uses_shared_shell_for_canonical_command_text(self):
        dialog = NewFigureDialog(
            {
                "arr": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                }
            },
            preselection=["arr"],
        )
        try:
            dialog.show()
            self.qapp.processEvents()

            self.assertFalse(hasattr(dialog.ui, "buttonBox"))
            self.assertEqual(
                dialog.lower_text_edit.toPlainText(),
                dialog.preview_string(),
            )
            self.assertEqual(
                dialog.preview_string(),
                dialog.widget_ir.python_source(log=False),
            )
            self.assertIsInstance(dialog.widget_ir, FigureIR)
            self.assertTrue(dialog.ok_button.isEnabled())
            self.assertFalse(dialog.to_ipython_button.isEnabled())
            self.assertTrue(dialog.copy_button.isEnabled())

            dialog.ui.titleEdit.setText("Delay Graph")
            self.qapp.processEvents()

            self.assertEqual(
                dialog.lower_text_edit.toPlainText(),
                dialog.preview_string(),
            )
            self.assertEqual(
                dialog.preview_string(),
                dialog.widget_ir.python_source(log=False),
            )
            self.assertIn("fig = plt.figure('Delay Graph'", dialog.preview_string())
        finally:
            dialog.close()

    def test_new_figure_dialog_ok_dispatches_hidden_python_and_accepts(self):
        execution = FakeExecutionService()
        terminal = FakeExecutionService()
        dialog = NewFigureDialog(
            {
                "arr": {
                    "python_type": "ndarray",
                    "numpy_type": "Array",
                    "ndim": 1,
                    "numpy_kind": "f",
                }
            },
            preselection=["arr"],
            services={
                "python_execution_service": execution,
                "visible_terminal_service": terminal,
            },
        )
        try:
            dialog.show()
            self.qapp.processEvents()

            payload = dialog.preview_string()
            self.assertTrue(dialog.to_ipython_button.isEnabled())
            dialog.to_ipython_button.click()
            self.assertEqual(terminal.visible_calls, [payload])

            dialog.ok_button.click()
            self.assertEqual(execution.hidden_calls, [(payload, True)])
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
        finally:
            dialog.close()

    def test_figure_macro_dispatch_uses_shared_callable_invocation(self):
        executed = []
        plugin = HydePlugin({})
        plugin.services = {
            "get_current_app_ir": lambda: HydeAppIR(current_project_dir="/tmp/demo.hy"),
            "python_execution_service": FakeExecutionService(
                hidden_calls=[],
                visible_calls=executed,
            )
        }

        Plugin._execute_macro(plugin, "Figure0", ("x", "y"))

        app_ir = plugin.services["get_current_app_ir"]()
        macro_ir = app_ir.with_callable_invocation("Figure0", ("x", "y"))
        self.assertEqual(executed, [app_ir.current_diff(macro_ir).python_source()])

    def test_project_activation_publishes_figure_macros_from_figure_ir(self):
        execution = FakeExecutionService()
        plugin = Plugin({})
        plugin.services = {"python_execution_service": execution}
        plugin.rebuild_configured_window_macros_menu = lambda: None

        plugin.on_project_activated(None)

        expected = FigureIR().with_publish_figure_macros().python_source(log=False)
        self.assertEqual(execution.hidden_calls, [(expected, True)])


class TestFigureBackendSnapshot(unittest.TestCase):
    def tearDown(self):
        pyplot = getattr(matplotlib, "pyplot", None)
        if pyplot is not None:
            pyplot.close("all")

    def _configure_hyde_pyplot(self):
        matplotlib.use("module://hyde.matplotlib_backend", force=True)
        import matplotlib.pyplot as pyplot

        return pyplot

    def _live_state(self):
        return {
            "feature": "figure_command",
            "settings": {
                "command": "create",
                "title": "DelayGraph",
                "x_name": "delay",
                "subplot_code": "111",
                "figsize": None,
            },
            "items": ["fit_delay", "raw_delay"],
            "ui": {},
        }

    def _live_state_with_title(self, title):
        return {
            "feature": "figure_command",
            "settings": {
                "command": "create",
                "title": title,
                "x_name": "delay",
                "subplot_code": "111",
                "figsize": None,
            },
            "items": ["fit_delay", "raw_delay"],
            "ui": {},
        }

    def test_figure_ir_trace_style_edit_preserves_broader_line2d_kwargs(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        updated = FigureIRAuthority.update_state(
            figure_ir,
            {
                "type": "set_trace_style",
                "subplot_id": "subplot0",
                "trace_id": "trace0",
                "style": {
                    "visible": False,
                    "alpha": 0.25,
                    "linestyle": "None",
                    "linewidth": 3.5,
                    "drawstyle": "steps-mid",
                    "markersize": 7.0,
                    "markerfacecolor": "red",
                    "markeredgecolor": "black",
                    "markeredgewidth": 2.0,
                },
            },
        )

        trace_kwargs = updated["layout"]["subplots"][0]["traces"][0]["kwargs"]
        self.assertFalse(trace_kwargs["visible"])
        self.assertEqual(trace_kwargs["alpha"], 0.25)
        self.assertEqual(trace_kwargs["linestyle"], "None")
        self.assertEqual(trace_kwargs["linewidth"], 3.5)
        self.assertEqual(trace_kwargs["drawstyle"], "steps-mid")
        self.assertEqual(trace_kwargs["markersize"], 7.0)
        self.assertEqual(trace_kwargs["markerfacecolor"], "red")
        self.assertEqual(trace_kwargs["markeredgecolor"], "black")
        self.assertEqual(trace_kwargs["markeredgewidth"], 2.0)

        source = FigureIRAuthority.state_to_python(updated)
        self.assertIn("visible=False", source)
        self.assertIn("alpha=0.25", source)
        self.assertIn("linestyle='None'", source)
        self.assertIn("linewidth=3.5", source)
        self.assertIn("drawstyle='steps-mid'", source)
        self.assertIn("markersize=7.0", source)
        self.assertIn("markerfacecolor='red'", source)
        self.assertIn("markeredgecolor='black'", source)
        self.assertIn("markeredgewidth=2.0", source)

    def test_trace_style_patch_does_not_remove_hidden_legend_when_visibility_is_unchanged(self):
        source_ir = figure_ir_from_live_state(
            self._live_state_with_title("FigureA")
        )
        source_ir["layout"]["subplots"][0]["traces"] = [
            source_ir["layout"]["subplots"][0]["traces"][0]
        ]
        source_ir["layout"]["subplots"][0]["legend"] = False
        source_ir = FigureIRAuthority.validate_state(source_ir)

        target_ir = FigureIRAuthority.update_state(
            source_ir,
            {
                "type": "set_trace_style",
                "subplot_id": "subplot0",
                "trace_id": "trace0",
                "style": {
                    "linestyle": "None",
                    "marker": "o",
                },
            },
        )

        source = figure_patch_source(source_ir, target_ir)

        self.assertIn("line.set_linestyle('None')", source)
        self.assertIn("line.set_marker('o')", source)
        self.assertNotIn("ax.legend()", source)
        self.assertNotIn("ax.get_legend()", source)

    def test_figure_patch_source_keeps_remove_only_trace_edits_package_pure(self):
        source_ir = figure_ir_from_live_state(
            self._live_state_with_title("FigureA")
        )
        target_ir = FigureIRAuthority.update_state(
            source_ir,
            {
                "type": "set_trace",
                "subplot_id": "subplot0",
                "trace_id": "trace0",
                "trace": None,
            },
        )

        source = figure_patch_source(source_ir, target_ir)

        self.assertNotIn("import hyde", source)
        self.assertNotIn("hyde.", source)
        self.assertIn("_hyde_line.remove()", source)

    def test_figure_ir_diff_lowers_remove_only_trace_edits_through_hyde_helper(self):
        opening_ir = FigureIR(
            figure_state=figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        )
        updated_ir = opening_ir.remove_traces(("trace0",))

        source = opening_ir.current_diff(updated_ir).as_patch("FigureA").python_source(
            log=False
        )

        self.assertIn("fig = hyde.get_figure('FigureA')", source)
        self.assertIn("hyde.remove_traces(fig, 'trace0')", source)
        self.assertNotIn("_hyde_line.remove()", source)

    def test_figure_ir_axis_edit_surface_lowers_axis_state_to_python(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        with_bottom_hidden = FigureIRAuthority.update_state(
            figure_ir,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "bottom",
                "state": {
                    "spine_visible": False,
                    "ticks_visible": False,
                    "tick_labels_visible": False,
                },
            },
        )
        with_x_axis = FigureIRAuthority.update_state(
            with_bottom_hidden,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {
                    "scale_mode": "log2",
                    "range": {
                        "limits": (1.0, 8.0),
                        "limit_mode": {"min": "manual", "max": "manual"},
                        "autoscale": "data",
                    },
                    "label": {
                        "text": "Delay",
                        "visible": True,
                        "side": "top",
                        "position_mode": "manual",
                        "position": 0.35,
                        "offset": 14.0,
                        "line_spacing": 1.6,
                        "color": "#aa5500",
                    },
                    "ticks": {
                        "major": {
                            "mode": "manual",
                            "positions": [1.0, 2.0, 4.0, 8.0],
                            "labels": ["1", "2", "4", "8"],
                        },
                        "minor": {"visible": True},
                        "direction": "both",
                    },
                    "grid": {
                        "visible": True,
                        "linestyle": ":",
                        "linewidth": 1.25,
                        "color": "#123456",
                    },
                },
            },
        )
        with_right_side = FigureIRAuthority.update_state(
            with_x_axis,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "right",
                "state": {
                    "spine_visible": True,
                    "ticks_visible": True,
                    "tick_labels_visible": True,
                    "tick_label_color": "#00aa00",
                    "tick_label_rotation": 35.0,
                },
            },
        )
        updated = FigureIRAuthority.update_state(
            with_right_side,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "y",
                "state": {
                    "label": {
                        "text": "Signal",
                        "visible": False,
                        "side": "right",
                    },
                    "range": {
                        "limits": (-2.0, 12.0),
                        "limit_mode": {"min": "manual", "max": "manual"},
                        "autoscale": "data",
                    },
                    "zero_line": {
                        "visible": True,
                        "linestyle": "--",
                        "linewidth": 2.0,
                        "color": "#654321",
                    },
                },
            },
        )

        subplot = updated["layout"]["subplots"][0]
        self.assertEqual(subplot["axes"]["x"]["label"]["side"], "top")
        self.assertEqual(subplot["axes"]["y"]["label"]["side"], "right")
        self.assertFalse(subplot["axes"]["y"]["label"]["visible"])
        self.assertFalse(subplot["axis_sides"]["bottom"]["spine_visible"])
        self.assertFalse(subplot["axis_sides"]["top"]["ticks_visible"])
        self.assertEqual(subplot["axis_sides"]["right"]["tick_label_color"], "#00aa00")

        source = FigureIRAuthority.state_to_python(updated)
        self.assertIn("import matplotlib.ticker as mticker", source)
        self.assertIn("ax.set_xscale('log', base=2)", source)
        self.assertIn("ax.set_xlim(1.0, 8.0)", source)
        self.assertIn("ax.xaxis.set_label_position('top')", source)
        self.assertIn("ax.set_xlabel('Delay')", source)
        self.assertIn("ax.xaxis.label.set_color('#aa5500')", source)
        self.assertIn("ax.xaxis.label.set_linespacing(1.6)", source)
        self.assertIn("ax.xaxis.set_label_coords(0.35, _hyde_x_label_coords[1])", source)
        self.assertIn("ax.xaxis.labelpad = 14.0", source)
        self.assertIn("ax.tick_params(axis='x', which='both', top=False, labeltop=False, bottom=False, labelbottom=False, direction='inout')", source)
        self.assertIn("ax.xaxis.set_major_locator(mticker.FixedLocator([1.0, 2.0, 4.0, 8.0]))", source)
        self.assertIn("ax.xaxis.set_major_formatter(mticker.FixedFormatter(['1', '2', '4', '8']))", source)
        self.assertIn("ax.grid(True, axis='x', which='major', linestyle=':', linewidth=1.25, color='#123456')", source)
        self.assertIn("ax.yaxis.set_label_position('right')", source)
        self.assertIn("ax.set_ylabel('Signal')", source)
        self.assertIn("ax.yaxis.label.set_visible(False)", source)
        self.assertIn("ax.set_ylim(-2.0, 12.0)", source)
        self.assertIn("for _hyde_tick in ax.yaxis.get_major_ticks() + ax.yaxis.get_minor_ticks():", source)
        self.assertIn("_hyde_tick.label2.set_color('#00aa00')", source)
        self.assertIn("_hyde_tick.label2.set_rotation(35.0)", source)
        self.assertIn("ax.axhline(0, linestyle='--', linewidth=2.0, color='#654321')", source)

    def test_figure_ir_lowers_partial_axis_ranges_and_resolved_side_state_to_python(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        with_top_layer = FigureIRAuthority.update_state(
            figure_ir,
            {
                "type": "set_axis_side_state",
                "subplot_id": "subplot0",
                "side": "top",
                "state": {
                    "draw_on_top": True,
                },
            },
        )
        updated = FigureIRAuthority.update_state(
            with_top_layer,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {
                    "range": {
                        "limits": (0.0, 8.0),
                        "limit_mode": {"min": "manual", "max": "auto"},
                        "autoscale": "data",
                    },
                },
            },
        )
        updated = FigureIRAuthority.update_state(
            updated,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "y",
                "state": {
                    "range": {
                        "limits": (-4.0, 3.0),
                        "limit_mode": {"min": "auto", "max": "manual"},
                        "autoscale": "data",
                    },
                },
            },
        )

        source = FigureIRAuthority.state_to_python(updated)

        self.assertIn("ax.autoscale(enable=True, axis='x')", source)
        self.assertIn("ax.set_xlim(left=0.0)", source)
        self.assertIn("ax.autoscale(enable=True, axis='y')", source)
        self.assertIn("ax.set_ylim(top=3.0)", source)
        self.assertIn("ax.set_axisbelow(False)", source)
        self.assertNotIn("import matplotlib.transforms as mtransforms", source)
        self.assertNotIn("set_bounds(", source)
        self.assertNotIn("ax.set_position(", source)

    def test_figure_ir_lowers_subplot_margins_to_python(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        updated = FigureIRAuthority.update_state(
            figure_ir,
            {
                "type": "set_subplot_margins",
                "subplot_id": "subplot0",
                "state": {
                    "left": 0.12,
                    "bottom": 0.2,
                    "right": 0.97,
                    "top": 0.98,
                },
            },
        )

        subplot = updated["layout"]["subplots"][0]
        self.assertEqual(
            subplot["margins"],
            {"left": 0.12, "bottom": 0.2, "right": 0.97, "top": 0.98},
        )

        source = FigureIRAuthority.state_to_python(updated)

        self.assertIn(
            "fig.subplots_adjust(left=0.12, bottom=0.2, right=0.97, top=0.98)",
            source,
        )

    def test_default_diff_lowering_omits_blank_label_visibility_until_explicitly_hidden(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        defaults = _figure_defaults_snapshot(figure_ir)

        source = FigureIRAuthority.state_to_python(
            figure_ir,
            context={"figure_defaults": defaults},
        )

        self.assertNotIn("label.set_visible(False)", source)

        hidden = FigureIRAuthority.update_state(
            figure_ir,
            {
                "type": "set_axis_state",
                "subplot_id": "subplot0",
                "axis": "x",
                "state": {"label": {"visible": False}},
            },
        )
        hidden_source = FigureIRAuthority.state_to_python(
            hidden,
            context={"figure_defaults": defaults},
        )

        self.assertIn("ax.xaxis.label.set_visible(False)", hidden_source)

    def test_set_axis_label_action_does_not_hide_blank_label_artist(self):
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        cleared = FigureIRAuthority.update_state(
            figure_ir,
            {
                "type": "set_axis_label",
                "subplot_id": "subplot0",
                "axis": "x",
                "label": "",
            },
        )

        self.assertIsNone(cleared["layout"]["subplots"][0]["axes"]["x"]["label"]["text"])
        self.assertTrue(cleared["layout"]["subplots"][0]["axes"]["x"]["label"]["visible"])

    def test_snapshot_payload_serializes_simple_single_axes_line_figure(self):
        figure = Figure()
        axes = figure.add_subplot(111)
        axes.set_title("DelayGraph")
        axes.plot([0, 1, 2], [1, 4, 9], label="fit_delay")

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["default_macro_name"], "Figure1")
        self.assertIsNone(payload["save_error"])
        self.assertIn("fig = plt.figure('Figure1')", payload["call_source"])
        self.assertIn("ax = fig.add_subplot(111)", payload["call_source"])
        self.assertIn("ax.plot(np.array([1, 4, 9])", payload["call_source"])
        self.assertEqual(
            payload["figure_size"],
            tuple(int(value * figure.dpi) for value in figure.get_size_inches()),
        )

    def test_snapshot_payload_prefers_figure_ir_for_first_class_decorated_figure(self):
        plt = self._configure_hyde_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["tracked_names"], ["x", "y"])
        self.assertIsNone(payload["live_state"])
        self.assertEqual(payload["figure_ir"]["settings"]["title"], "Graph0")
        self.assertEqual(
            payload["resolved_axis_limits"]["subplot0"]["x"],
            tuple(float(value) for value in figure.axes[0].get_xlim()),
        )
        self.assertEqual(
            payload["resolved_axis_limits"]["subplot0"]["y"],
            tuple(float(value) for value in figure.axes[0].get_ylim()),
        )
        self.assertEqual(
            payload["trace_styles"]["subplot0"]["trace0"]["label"],
            "y",
        )
        self.assertEqual(
            payload["trace_styles"]["subplot0"]["trace0"]["linestyle"],
            "-",
        )
        self.assertIn("ax.plot(x, y, label='y')", payload["call_source"])
        self.assertEqual(
            [entry["op"] for entry in payload["command_log"]],
            ["add_subplot", "plot"],
        )
        subplot = payload["figure_ir"]["layout"]["subplots"][0]
        self.assertEqual(subplot["axes"]["x"]["label"]["side"], "bottom")
        self.assertEqual(subplot["axes"]["x"]["range"]["limit_mode"], {"min": "auto", "max": "auto"})
        self.assertEqual(
            sorted(subplot["axis_sides"]),
            ["bottom", "left", "right", "top"],
        )

    def test_snapshot_payload_keeps_build_time_defaults_when_rcparams_change_later(self):
        plt = self._configure_hyde_pyplot()

        with matplotlib.rc_context({"lines.linewidth": 3.25}):
            @hyde.figure
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])

        with matplotlib.rc_context({"lines.linewidth": 7.5}):
            payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(
            payload["figure_defaults"]["trace_styles"]["subplot0"]["trace0"]["linewidth"],
            3.25,
        )
        self.assertEqual(
            figure._hyde_defaults["trace_styles"]["subplot0"]["trace0"]["linewidth"],
            3.25,
        )
        self.assertNotIn("linewidth=3.25", payload["call_source"])

    def test_snapshot_payload_preserves_figsize_for_first_class_decorated_figure(self):
        plt = self._configure_hyde_pyplot()

        @hyde.figure
        def Graph0(x, y):
            fig = plt.figure("Graph0", figsize=(5.0, 3.0))
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])

        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["figure_ir"]["settings"]["figsize"], (5.0, 3.0))
        self.assertIn("fig = plt.figure('Graph0', figsize=(5.0, 3.0))", payload["call_source"])

    def test_snapshot_payload_includes_kernel_defaults_and_omits_matching_default_output(self):
        plt = self._configure_hyde_pyplot()

        with matplotlib.rc_context(
            {
                "axes.labelpad": 9.0,
                "lines.linestyle": "--",
                "lines.linewidth": 3.25,
                "xtick.direction": "in",
                "ytick.direction": "in",
            }
        ):
            @hyde.figure
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])
            axis = figure.axes[0]
            axis.lines[0].set_linestyle("--")
            axis.lines[0].set_linewidth(3.25)
            axis.xaxis.labelpad = 9.0
            axis.tick_params(axis="x", direction="in")
            _resync_dirty_first_class_figures(None)

            payload = figure_snapshot_payload(figure, 1)

        defaults = payload["figure_defaults"]
        subplot_defaults = defaults["layout"]["subplots"][0]
        self.assertEqual(subplot_defaults["traces"][0]["kwargs"]["linestyle"], "--")
        self.assertEqual(subplot_defaults["traces"][0]["kwargs"]["linewidth"], 3.25)
        self.assertEqual(subplot_defaults["axes"]["x"]["label"]["offset"], 9.0)
        self.assertEqual(subplot_defaults["axes"]["x"]["ticks"]["direction"], "inside")
        self.assertEqual(defaults, figure._hyde_defaults)
        self.assertNotIn("linestyle='--'", payload["call_source"])
        self.assertNotIn("linewidth=3.25", payload["call_source"])
        self.assertNotIn("ax.tick_params(", payload["call_source"])
        self.assertNotIn("labelpad = 9.0", payload["call_source"])
        self.assertNotIn("ax.set_xlabel(None)", payload["call_source"])

    def test_snapshot_payload_includes_hyde_figure_metadata(self):
        plt = self._configure_hyde_pyplot()

        @hyde.figure(window_pos=(10, 20), window_state="minimized")
        def Graph0(x, y):
            fig = plt.figure("Graph0")
            ax = fig.add_subplot(111)
            ax.plot(x, y, label="y")
            return fig

        figure = Graph0([0, 1, 2], [1, 4, 9])
        payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(
            payload["hyde_metadata"],
            {"window_pos": (10, 20), "window_state": "minimized"},
        )

    def test_snapshot_payload_keeps_undecorated_hyde_backend_figures_second_class(self):
        plt = self._configure_hyde_pyplot()
        figure = plt.figure("Plain")
        axis = figure.add_subplot(111)
        axis.plot([0, 1, 2], [1, 4, 9], label="y")

        payload = figure_snapshot_payload(figure, 1)

        self.assertFalse(payload["is_first_class"])
        self.assertIsNone(payload.get("figure_ir"))
        self.assertIsNone(payload.get("command_log"))
        self.assertIn("ax.plot(np.array([1, 4, 9])", payload["call_source"])

    def test_snapshot_payload_does_not_infer_second_class_live_state_from_namespace(self):
        figure = Figure()
        axes = figure.add_subplot(111)
        axes.set_title("DelayGraph")
        main_namespace = sys.modules["__main__"].__dict__
        previous_values = {
            name: main_namespace.get(name)
            for name in ("delay", "fit_delay")
        }
        try:
            main_namespace["delay"] = [0, 1, 2]
            main_namespace["fit_delay"] = [1, 4, 9]
            axes.plot(main_namespace["delay"], main_namespace["fit_delay"], label="fit_delay")

            payload = figure_snapshot_payload(figure, 1)

            self.assertEqual(payload["tracked_names"], [])
            self.assertIsNone(payload["live_state"])
            self.assertIn("ax.plot(np.array([1, 4, 9])", payload["call_source"])
        finally:
            for name, value in previous_values.items():
                if value is None:
                    main_namespace.pop(name, None)
                else:
                    main_namespace[name] = value

    def test_manager_initialization_does_not_push_draw_before_backend_is_ready(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)

        with patch("hyde.matplotlib_backend.Comm") as comm_cls:
            manager = FigureManagerHyde(canvas, 3)

        self.assertIs(canvas.manager, manager)
        self.assertEqual(manager.num, 3)
        self.assertTrue(manager._ready_to_push)
        comm_cls.assert_not_called()

    def test_set_window_title_does_not_push_draw(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)
        manager = FigureManagerHyde(canvas, 3)

        with patch.object(manager, "_push_draw") as push_draw:
            manager.set_window_title("Retitled")

        push_draw.assert_not_called()
        self.assertEqual(figure.get_label(), "Retitled")

    def test_manager_shows_undecorated_figure_in_terminal_without_comm(self):
        plt = self._configure_hyde_pyplot()
        figure = plt.figure("Plain")
        figure.add_subplot(111).plot([0, 1, 2], [1, 4, 9], label="y")
        manager = figure.canvas.manager

        with patch("hyde.matplotlib_backend.Comm") as comm_cls, patch(
            "hyde.matplotlib_backend._display_in_ipython_terminal"
        ) as display_terminal:
            manager.show()

        comm_cls.assert_not_called()
        display_terminal.assert_called_once_with(figure)

    def test_manager_opens_comm_for_decorated_figure_before_builder_returns(self):
        plt = self._configure_hyde_pyplot()

        with patch("hyde.matplotlib_backend.Comm") as comm_cls:
            fake_comm = comm_cls.return_value
            fake_comm.send.return_value = None
            fake_comm.close.return_value = None

            @hyde.figure(register=False)
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                fig.show()
                return fig

            Graph0([0, 1, 2], [1, 4, 9])

        comm_cls.assert_called()

    def test_post_run_cell_resync_hook_registers_once_and_draws_only_dirty_first_class_figures(self):
        plt = self._configure_hyde_pyplot()
        shell = FakeShell()

        with patch("hyde.matplotlib_backend.Comm"):
            @hyde.figure(register=False)
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            @hyde.figure(register=False)
            def Graph1(x, y):
                fig = plt.figure("Graph1")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            first = Graph0([0, 1, 2], [1, 4, 9])
            second = Graph1([0, 1, 2], [1, 2, 3])

            self.assertTrue(_install_first_class_figure_resync_hook(shell))
            self.assertTrue(_install_first_class_figure_resync_hook(shell))
            callbacks = shell.events.registered["post_run_cell"]
            self.assertEqual(len(callbacks), 1)

            first.canvas.draw()
            second.canvas.draw()

            with patch.object(first.canvas.manager, "_push_draw") as first_push, patch.object(
                second.canvas.manager, "_push_draw"
            ) as second_push:
                first.axes[0].set_xlabel("Delay")
                callbacks[0](None)

            first_push.assert_called_once()
            second_push.assert_not_called()

    def test_first_class_figure_creation_installs_post_run_cell_resync_hook_once(self):
        plt = self._configure_hyde_pyplot()
        shell = FakeShell()

        with patch("hyde.matplotlib_backend.Comm"), patch(
            "IPython.get_ipython",
            return_value=shell,
        ):
            @hyde.figure(register=False)
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            @hyde.figure(register=False)
            def Graph1(x, y):
                fig = plt.figure("Graph1")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            Graph0([0, 1, 2], [1, 4, 9])
            Graph1([0, 1, 2], [1, 2, 3])

        self.assertEqual(len(shell.events.registered["post_run_cell"]), 1)

    def test_post_run_cell_resync_draws_dirty_first_class_figures_after_exception_result(self):
        plt = self._configure_hyde_pyplot()
        shell = FakeShell()

        with patch("hyde.matplotlib_backend.Comm"):
            @hyde.figure(register=False)
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])
            _install_first_class_figure_resync_hook(shell)
            callback = shell.events.registered["post_run_cell"][0]

            with patch.object(figure.canvas.manager, "_push_draw") as push_draw:
                figure.axes[0].set_ylabel("Signal")
                callback(type("FakeResult", (), {"error_in_exec": RuntimeError("boom")})())

            push_draw.assert_called_once()

    def test_post_run_cell_resync_reimports_supported_ir_from_live_first_class_figure(self):
        plt = self._configure_hyde_pyplot()

        with patch("hyde.matplotlib_backend.Comm"):
            @hyde.figure(register=False)
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])
            figure.canvas.draw()

            axis = figure.axes[0]
            axis.set_xlabel("Delay")
            axis.set_xlim(-1, 5)
            axis.lines[0].set_color("green")

            _resync_dirty_first_class_figures(None)

        subplot = figure._hyde_ir["layout"]["subplots"][0]
        self.assertEqual(subplot["axes"]["x"]["label"]["text"], "Delay")
        self.assertEqual(
            subplot["axes"]["x"]["range"]["limits"],
            (-1.0, 5.0),
        )
        self.assertEqual(subplot["traces"][0]["kwargs"]["color"], "#008000")

    def test_post_run_cell_resync_marks_unsupported_live_features_macro_incomplete(self):
        plt = self._configure_hyde_pyplot()

        with patch("hyde.matplotlib_backend.Comm"):
            @hyde.figure(register=False)
            def Graph0(x, y):
                fig = plt.figure("Graph0")
                ax = fig.add_subplot(111)
                ax.plot(x, y, label="y")
                return fig

            figure = Graph0([0, 1, 2], [1, 4, 9])
            figure.canvas.draw()
            figure.axes[0].imshow([[1, 2], [3, 4]])

            _resync_dirty_first_class_figures(None)
            payload = figure_snapshot_payload(figure, 1)

        self.assertEqual(payload["figure_ir"]["layout"]["subplots"][0]["traces"][0]["id"], "trace0")
        self.assertIn("unsupported", payload["save_error"].lower())

    def test_manager_destroy_closes_comm_even_if_close_payload_send_fails(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)
        manager = FigureManagerHyde(canvas, 3)
        closed = []

        class FakeComm:
            def send(self, payload):
                del payload
                raise RuntimeError("boom")

            def close(self):
                closed.append(True)

        manager._comm = FakeComm()

        manager.destroy()

        self.assertEqual(closed, [True])

    def test_manager_destroy_logs_close_payload_send_failure(self):
        figure = Figure()
        canvas = FigureCanvasHyde(figure)
        manager = FigureManagerHyde(canvas, 3)

        class FakeComm:
            def send(self, payload):
                del payload
                raise RuntimeError("boom")

            def close(self):
                return None

        manager._comm = FakeComm()

        with self.assertLogs("hyde", level="ERROR") as logs:
            manager.destroy()

        self.assertTrue(
            any("close payload" in message and "figure 3" in message for message in logs.output)
        )

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    class _FakeSaveWindowDialogService:
        def __init__(self, result=True):
            self.result = result
            self.calls = []

        def prompt_to_save_window_macro(self, **kwargs):
            self.calls.append(kwargs)
            return self.result

    def test_figure_window_refreshes_from_same_namespace_signal_as_tables(self):
        namespace_service = FakeNamespaceViewService(
            {
                "delay": {"type": "ndarray", "view": "[0 1 2]"},
                "fit_delay": {"type": "ndarray", "view": "[1 4 9]"},
                "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
            }
        )
        widget = FigureWindow(
            figure_number=1,
            services={
                "namespace_view_service": namespace_service,
                "python_execution_service": FakeExecutionService(),
            },
        )
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {
                        "figure_ir": figure_ir_from_live_state(self._live_state()),
                        "live_state": None,
                    },
                }
            )

            namespace_service.emit(
                {
                    "delay": {"type": "ndarray", "view": "[0 1 2]"},
                    "fit_delay": {"type": "ndarray", "view": "[10 40 90]"},
                    "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
                }
            )

            self.assertEqual(len(widget.services["python_execution_service"].hidden_calls), 1)
            code, silent = widget.services["python_execution_service"].hidden_calls[0]
            self.assertEqual(
                code,
                FigureIR()
                .with_refresh_figure("DelayGraph", use_bound_values=False)
                .python_source(log=False),
            )
            self.assertTrue(silent)
        finally:
            widget.close()

    def test_figure_window_detects_in_place_namespace_metadata_mutation(self):
        shared_view = ["[1 4 9]"]
        execution = FakeExecutionService()
        namespace_service = FakeNamespaceViewService(
            {
                "delay": {"type": "ndarray", "view": "[0 1 2]"},
                "fit_delay": {"type": "ndarray", "view": shared_view},
                "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
            }
        )
        widget = FigureWindow(
            figure_number=1,
            services={
                "namespace_view_service": namespace_service,
                "python_execution_service": execution,
            },
        )
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {
                        "figure_ir": figure_ir_from_live_state(self._live_state()),
                        "live_state": None,
                    },
                }
            )
            shared_view[0] = "[10 40 90]"
            namespace_service.emit(
                {
                    "delay": {"type": "ndarray", "view": "[0 1 2]"},
                    "fit_delay": {"type": "ndarray", "view": shared_view},
                    "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
                }
            )

            self.assertEqual(len(execution.hidden_calls), 1)
            code, silent = execution.hidden_calls[0]
            self.assertEqual(
                code,
                FigureIR()
                .with_refresh_figure("DelayGraph", use_bound_values=False)
                .python_source(log=False),
            )
            self.assertTrue(silent)
        finally:
            widget.close()

    def test_figure_window_subscribes_to_namespace_updates(self):
        namespace_service = FakeNamespaceViewService()
        widget = FigureWindow(
            figure_number=1,
            services={"namespace_view_service": namespace_service},
        )
        try:
            self.assertTrue(namespace_service.connected)
        finally:
            widget.close()

    def test_figure_window_refresh_recovers_after_timed_out_request(self):
        execution = FakeExecutionService()
        namespace_service = FakeNamespaceViewService(
            {
                "delay": {"type": "ndarray", "view": "[0 1 2]"},
                "fit_delay": {"type": "ndarray", "view": "[1 4 9]"},
                "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
            }
        )
        widget = FigureWindow(
            figure_number=1,
            services={
                "namespace_view_service": namespace_service,
                "python_execution_service": execution,
            },
        )
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {
                        "figure_ir": figure_ir_from_live_state(self._live_state()),
                        "live_state": None,
                    },
                }
            )
            widget.PAYLOAD_TIMEOUT_MS = 0
            widget.refresh_figure()
            execution.answer_last()
            for _ in range(3):
                self.qapp.processEvents()

            namespace_service.emit(
                {
                    "delay": {"type": "ndarray", "view": "[0 1 2]"},
                    "fit_delay": {"type": "ndarray", "view": "[10 40 90]"},
                    "raw_delay": {"type": "ndarray", "view": "[1 2 3]"},
                }
            )

            self.assertEqual(len(execution.hidden_calls), 2)
            code, silent = execution.hidden_calls[1]
            self.assertEqual(
                code,
                FigureIR()
                .with_refresh_figure("DelayGraph", use_bound_values=False)
                .python_source(log=False),
            )
            self.assertTrue(silent)
        finally:
            widget.close()

    def test_figure_window_hidden_refresh_logs_through_transport_debug_channel(self):
        execution = FakeExecutionService()
        widget = FigureWindow(
            figure_number=1,
            services={"python_execution_service": execution},
        )
        try:
            widget.update_payload(
                {
                    "figure_number": 1,
                    "snapshot": {
                        "figure_ir": figure_ir_from_live_state(self._live_state()),
                        "live_state": None,
                    },
                }
            )

            with self.assertLogs("hyde", level="DEBUG") as logs:
                self.assertTrue(widget.request_regenerate_from_ir())
        finally:
            widget.close()

        output = "\n".join(logs.output)
        self.assertIn("[Hyde state] TransportDispatchState", output)
        self.assertIn("'mode': 'hidden'", output)
        self.assertIn("python:\n", output)
        self.assertIn("fig = hyde.get_figure('DelayGraph')", output)
        self.assertIn("hyde.refresh_figure(fig, use_bound_values=True)", output)

    def test_figure_window_context_menu_activates_bound_subwindow(self):
        popup_calls = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "mdi_area": mdi_area,
                "popup_menu": lambda location, global_pos: popup_calls.append(
                    (location, global_pos)
                ),
            },
        )
        other = QtWidgets.QWidget()
        other_subwindow = mdi_area.addSubWindow(other)
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        other_subwindow.show()
        subwindow.show()
        self.qapp.processEvents()
        mdi_area.setActiveSubWindow(other_subwindow)

        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse,
            QtCore.QPoint(5, 5),
            QtCore.QPoint(20, 30),
        )
        widget.contextMenuEvent(event)

        self.assertIs(mdi_area.activeSubWindow(), subwindow)
        self.assertEqual(popup_calls, [("figure", QtCore.QPoint(20, 30))])

        widget.force_close()
        other.close()

    def test_figure_window_close_honors_save_prompt_cancel(self):
        queued = []
        save_window_dialog_service = self._FakeSaveWindowDialogService(result=False)
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": save_window_dialog_service,
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()

        self.assertEqual(len(save_window_dialog_service.calls), 1)
        self.assertEqual(set(save_window_dialog_service.calls[0]), {"saveable"})
        self.assertEqual(queued, [])

        widget.force_close()

    def test_figure_window_close_waits_for_kernel_confirmation(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()

        expected_close = FigureIR().with_close_figure(1).python_source(log=False)
        self.assertEqual(queued, [(expected_close, True)])

        widget.close_from_kernel()
        widget.close_from_kernel()
        self.qapp.processEvents()

    def test_figure_window_ignores_duplicate_close_while_waiting_for_kernel_confirmation(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()
        subwindow.close()
        self.qapp.processEvents()

        expected_close = FigureIR().with_close_figure(1).python_source(log=False)
        self.assertEqual(queued, [(expected_close, True)])

        widget.close_from_kernel()
        self.qapp.processEvents()

    def test_figure_window_shutdown_close_bypasses_kernel_queue_and_closes_immediately(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": FakeExecutionService(queued),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
                "get_shutting_down": lambda: True,
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()

        self.assertEqual(queued, [])
        self.assertFalse(subwindow.isVisible())

    def test_figure_window_close_waits_while_the_kernel_is_busy(self):
        """A close queued behind the user's own cell has not failed."""
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        execution = FakeExecutionService(queued)
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": execution,
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        subwindow.close()
        for _ in range(3):
            self.qapp.processEvents()

        # No reply: the close is outstanding, so a second close sends nothing new.
        subwindow.close()
        self.qapp.processEvents()
        self.assertEqual(1, len(queued))
        widget.close_from_kernel()
        self.qapp.processEvents()

    def test_figure_window_close_reports_a_kernel_error(self):
        mdi_area = QtWidgets.QMdiArea()
        execution = FakeExecutionService([])
        widget = FigureWindow(
            figure_number=7,
            services={
                "python_execution_service": execution,
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        with self.assertLogs("hyde", level="WARNING") as logs:
            subwindow.close()
            self.qapp.processEvents()
            execution.answer_last(KernelRequest.RAISED, "KeyError: 7")

        self.assertTrue(any("KeyError: 7" in message for message in logs.output))
        widget.force_close()

    def test_figure_window_close_timeout_clears_in_flight_close(self):
        queued = []
        mdi_area = QtWidgets.QMdiArea()
        execution = FakeExecutionService(queued)
        widget = FigureWindow(
            figure_number=1,
            services={
                "python_execution_service": execution,
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        widget.PAYLOAD_TIMEOUT_MS = 0
        subwindow.close()
        execution.answer_last()
        for _ in range(3):
            self.qapp.processEvents()

        subwindow.close()
        self.qapp.processEvents()
        expected = (FigureIR().with_close_figure(1).python_source(log=False), True)
        self.assertEqual(queued, [expected, expected])
        widget.close_from_kernel()
        self.qapp.processEvents()

    def test_figure_window_close_that_is_never_confirmed_logs_warning(self):
        mdi_area = QtWidgets.QMdiArea()
        execution = FakeExecutionService([])
        widget = FigureWindow(
            figure_number=7,
            services={
                "python_execution_service": execution,
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            },
        )
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        widget.bind_subwindow(subwindow)
        subwindow.show()
        self.qapp.processEvents()

        widget.PAYLOAD_TIMEOUT_MS = 0
        with self.assertLogs("hyde", level="WARNING") as logs:
            subwindow.close()
            execution.answer_last()
            for _ in range(3):
                self.qapp.processEvents()

        self.assertTrue(
            any("its data never arrived" in message for message in logs.output),
            logs.output,
        )
        widget.force_close()

    def test_figure_window_uses_snapshot_size_for_initial_subwindow_geometry(self):
        main = QtWidgets.QMainWindow()
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(320, 240)
        main.setCentralWidget(mdi_area)
        main.show()
        self.qapp.processEvents()

        widget = FigureWindow(figure_number=1)
        subwindow = mdi_area.addSubWindow(widget)
        widget.bind_subwindow(subwindow)
        widget.snapshot_state.update(
            default_macro_name="Figure0",
            call_source="fig = plt.figure('Figure0')",
            save_error=None,
            figure_size=(640, 480),
        )

        widget._apply_initial_subwindow_size()

        frame_size = subwindow.size() - subwindow.contentsRect().size()
        expected_size = QtCore.QSize(640, 480)
        available_size = QtCore.QSize(
            max(160, mdi_area.viewport().width() - max(0, frame_size.width())),
            max(120, mdi_area.viewport().height() - max(0, frame_size.height())),
        )
        if (
            expected_size.width() > available_size.width()
            or expected_size.height() > available_size.height()
        ):
            expected_size.scale(available_size, QtCore.Qt.KeepAspectRatio)
        contents_size = subwindow.contentsRect().size()

        self.assertEqual(contents_size.width(), expected_size.width())
        self.assertEqual(contents_size.height(), expected_size.height())
        self.assertLessEqual(subwindow.width(), mdi_area.viewport().width())
        self.assertLessEqual(subwindow.height(), mdi_area.viewport().height())
        main.close()

    def test_figure_window_does_not_resize_redraw_before_initial_size_is_applied(self):
        sent = []
        widget = FigureWindow(
            figure_number=1,
            services={
                "figure_action_service": type(
                    "FigureActionService",
                    (),
                    {
                        "request_figure_action": (
                            lambda _self, figure_number, action: (
                                sent.append((figure_number, action)) or True
                            )
                        )
                    },
                )(),
            },
        )
        try:
            widget._on_resize_redraw_timeout()
            self.assertEqual(sent, [])

            widget._initial_size_applied = True
            widget.image_label.resize(320, 240)
            widget._on_resize_redraw_timeout()

            self.assertEqual(
                sent,
                [(1, {"type": "resize_redraw", "width": 320, "height": 240})],
            )
        finally:
            widget.close()

    def test_workspace_ignores_non_first_class_figure_payload(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)

        figure = workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": False,
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "live_state": self._live_state_with_title("FigureA"),
                },
            }
        )
        self.qapp.processEvents()

        self.assertIsNone(figure)
        self.assertEqual(workspace.figures, {})
        workspace.clear()
        mdi_area.close()

    def test_workspace_uses_snapshot_figure_ir_without_live_state_bridge(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                },
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertEqual(figure.window_handle(), "FigureA")
        self.assertEqual(figure.parentWidget().objectName(), "FigureA")
        self.assertEqual(
            figure.parentWidget().windowTitle(),
            "FigureA: fit_delay: fit_delay vs delay, raw_delay: raw_delay vs delay",
        )
        self.assertEqual(figure.snapshot_state.figure_ir()["settings"]["title"], "FigureA")
        workspace.clear()
        mdi_area.close()

    def test_deferred_subwindow_delete_does_not_retain_cleared_workspace(self):
        mdi_area = QtWidgets.QMdiArea()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "figure_ir": figure_ir,
                },
            }
        )

        workspace.clear()
        workspace_ref = weakref.ref(workspace)
        del workspace
        gc.collect()

        self.assertIsNone(workspace_ref())
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.qapp.processEvents()

    def test_workspace_requires_save_window_dialog_service_for_first_class_windows(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        with self.assertRaises(KeyError):
            workspace.open_or_update_figure(
                {
                    "figure_number": 1,
                    "title": "FigureA",
                    "snapshot": {
                        "is_first_class": True,
                        "default_macro_name": "FigureA",
                        "call_source": "fig = plt.figure('FigureA')",
                        "figure_size": (320, 240),
                        "figure_ir": figure_ir,
                    },
                }
            )

        mdi_area.close()

    def test_workspace_applies_snapshot_window_metadata_for_new_macro_window(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {
                        "window_pos": [30, 40],
                        "window_state": "minimized",
                    },
                },
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertEqual(figure.capture_geometry()[:2], [30, 40])
        self.assertTrue(figure.parentWidget().isMinimized())
        workspace.clear()
        mdi_area.close()

    def test_workspace_reapplies_window_pos_after_first_draw_initial_size(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {"window_pos": [120, 130]},
                },
            }
        )
        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {"window_pos": [120, 130]},
                },
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertEqual(figure.capture_geometry()[:2], [120, 130])
        workspace.clear()
        mdi_area.close()

    def test_workspace_applies_snapshot_minimized_metadata_for_new_macro_window(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "hyde_metadata": {"window_state": "minimized"},
            },
        }
        workspace.open_or_update_figure(payload)
        workspace.open_or_update_figure(
            {
                **payload,
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertTrue(figure.parentWidget().isMinimized())
        workspace.clear()
        mdi_area.close()

    def test_minimized_workspace_restore_keeps_first_draw_pixmap(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "hyde_metadata": {"window_state": "minimized"},
            },
        }
        workspace.open_or_update_figure(payload)
        workspace.open_or_update_figure(
            {
                **payload,
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertTrue(figure.parentWidget().isMinimized())
        self.assertIsNotNone(figure.image_label.pixmap())
        self.assertFalse(figure.image_label.pixmap().isNull())
        figure.parentWidget().showNormal()
        self.qapp.processEvents()
        self.assertFalse(figure.parentWidget().isMinimized())
        self.assertIsNotNone(figure.image_label.pixmap())
        self.assertFalse(figure.image_label.pixmap().isNull())
        workspace.clear()
        mdi_area.close()

    def test_workspace_applies_snapshot_maximized_metadata_for_new_macro_window(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {"window_state": "maximized"},
                },
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        self.assertTrue(figure.parentWidget().isMaximized())
        workspace.clear()
        mdi_area.close()

    def test_minimized_workspace_restore_returns_to_saved_normal_position(self):
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.resize(800, 600)
        mdi_area.show()
        plugin = type("FakePlugin", (), {})()
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        workspace = FigureWorkspaceService(plugin)
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        image = QtGui.QImage(320, 240, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_base64 = bytes(buffer.data().toBase64()).decode("ascii")

        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {
                        "window_pos": [120, 130],
                        "window_state": "minimized",
                    },
                },
            }
        )
        workspace.open_or_update_figure(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "is_first_class": True,
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "hyde_metadata": {
                        "window_pos": [120, 130],
                        "window_state": "minimized",
                    },
                },
                "image_png_base64": png_base64,
            }
        )
        self.qapp.processEvents()

        figure = workspace.figures[1]
        subwindow = figure.parentWidget()
        self.assertTrue(subwindow.isMinimized())
        subwindow.showNormal()
        self.qapp.processEvents()

        self.assertEqual(figure.capture_geometry()[:2], [120, 130])
        workspace.clear()
        mdi_area.close()

    def test_plugin_session_toml_omits_figure_name_counters(self):
        plugin = Plugin({})
        plugin.services = {
            "python_execution_service": FakeExecutionService(),
        }
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin.services.update(
            {
                "mdi_area": mdi_area,
                "namespace_view_service": FakeNamespaceViewService(),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
                "get_shutting_down": lambda: False,
            }
        )
        figure = FigureWindow(figure_number=1)
        subwindow = mdi_area.addSubWindow(figure)
        figure.bind_subwindow(subwindow)
        subwindow.destroyed.connect(
            lambda *_, number=1, workspace=plugin.workspace: (
                workspace._remove_figure(number)
            )
        )
        subwindow.setGeometry(10, 20, 300, 220)
        plugin.workspace.figures[1] = figure
        figure.update_payload(
            {
                "figure_number": 1,
                "title": "FigureA",
                "snapshot": {
                    "default_macro_name": "FigureA",
                    "call_source": "fig = plt.figure('FigureA')",
                    "figure_size": (320, 240),
                    "figure_ir": figure_ir,
                    "live_state": None,
                },
            }
        )

        toml_data = plugin.get_session_toml_data()

        self.assertEqual(toml_data, {})
        figure.close()
        mdi_area.close()

    def test_closed_figures_are_absent_from_session_restore_source(self):
        plugin = Plugin({})
        plugin.services = {
            "python_execution_service": FakeExecutionService(),
        }
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        plugin.services.update(
            {
                "mdi_area": mdi_area,
                "namespace_view_service": FakeNamespaceViewService(),
                "save_window_dialog_service": self._FakeSaveWindowDialogService(),
                "get_shutting_down": lambda: False,
            }
        )
        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "live_state": None,
            },
        }
        figure = plugin.workspace.open_or_update_figure(payload)
        figure.parentWidget().setGeometry(10, 20, 300, 220)

        session_source = plugin.get_session_restore_source()

        self.assertIn("FigureA(delay, fit_delay, raw_delay)", session_source)
        self.assertIn("fig = plt.figure('FigureA')", session_source)

        plugin.workspace.close_figure(1)
        self.qapp.processEvents()

        self.assertEqual(plugin.get_session_restore_source(), "")
        mdi_area.close()

    def test_plugin_batches_figure_payload_application_until_event_loop_flush(self):
        plugin = Plugin({})
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        initial_payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
            },
        }
        unsupported_payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "save_error": "unsupported trace source",
            },
        }
        try:
            plugin._handle_figure_payload(initial_payload)
            plugin._handle_figure_payload(unsupported_payload)

            self.assertEqual(plugin.workspace.figures, {})

            self.qapp.processEvents()

            figure = plugin.workspace.figures[1]
            self.assertEqual(
                figure.parentWidget().windowTitle(),
                "FigureA: fit_delay: fit_delay vs delay, raw_delay: raw_delay vs delay [Unsupported Feature]",
            )
            self.assertFalse(figure.warning_label.isHidden())
            self.assertIn("unsupported trace source", figure.warning_label.text().lower())
        finally:
            plugin.workspace.clear()
            mdi_area.close()

    def test_plugin_discards_pending_batched_payloads_when_workspace_is_cleared(self):
        plugin = Plugin({})
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
            },
        }
        try:
            plugin._handle_figure_payload(payload)

            plugin.on_project_loaded(None)
            self.qapp.processEvents()

            self.assertEqual(plugin.workspace.figures, {})
        finally:
            plugin.workspace.clear()
            mdi_area.close()

    def test_plugin_reports_session_restore_warnings_for_unsupported_figures(self):
        plugin = Plugin({})
        mdi_area = QtWidgets.QMdiArea()
        mdi_area.show()
        figure_ir = figure_ir_from_live_state(self._live_state_with_title("FigureA"))
        plugin.services = {
            "mdi_area": mdi_area,
            "namespace_view_service": FakeNamespaceViewService(),
            "python_execution_service": FakeExecutionService(),
            "save_window_dialog_service": self._FakeSaveWindowDialogService(),
            "get_shutting_down": lambda: False,
        }
        payload = {
            "figure_number": 1,
            "title": "FigureA",
            "snapshot": {
                "is_first_class": True,
                "default_macro_name": "FigureA",
                "call_source": "fig = plt.figure('FigureA')",
                "figure_size": (320, 240),
                "figure_ir": figure_ir,
                "save_error": "unsupported trace source",
            },
        }
        try:
            plugin._handle_figure_payload(payload)
            self.qapp.processEvents()

            self.assertEqual(
                plugin.get_session_restore_warnings(),
                ["FigureA: Unsupported Feature: unsupported trace source"],
            )
            self.assertIn("FigureA(delay, fit_delay, raw_delay)", plugin.get_session_restore_source())
        finally:
            plugin.workspace.clear()
            mdi_area.close()


class TestBackendBootstrap(unittest.TestCase):
    def test_configure_gui_matplotlib_backend_forces_module_backend_only(self):
        fake_matplotlib = types.ModuleType("matplotlib")
        calls = []

        def fake_use(backend, *args, **kwargs):
            del args, kwargs
            calls.append(backend)

        fake_matplotlib.use = fake_use
        fake_matplotlib.get_backend = lambda: "MacOSX"

        with patch.dict(sys.modules, {"matplotlib": fake_matplotlib}, clear=False):
            sys.modules.pop("matplotlib.pyplot", None)
            configure_gui_matplotlib_backend()

            self.assertEqual(calls, [HYDE_MATPLOTLIB_BACKEND])


class TestMatplotlibPersistenceExclusion(unittest.TestCase):
    def test_matplotlib_figure_and_axes_are_excluded_from_kernel_persistence(self):
        figure = Figure()
        axes = figure.add_subplot(111)

        self.assertTrue(is_excluded("fig", figure))
        self.assertTrue(is_excluded("ax", axes))


class TestFigureWindowBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _figure_ir(self, *, items=("trace_a", "trace_b")):
        return (
            FigureIR()
            .with_title("Figure0")
            .with_x_name("x")
            .with_items(list(items))
            .normalized_state()
        )

    def test_figure_window_reports_supported_trace_records_from_snapshot_ir(self):
        widget = FigureWindow(figure_number=1)
        try:
            widget.update_payload(
                {
                    "snapshot": {
                        "figure_ir": self._figure_ir(),
                    }
                }
            )

            self.assertEqual(
                widget.supported_trace_records(),
                (
                    {
                        "subplot_id": "subplot0",
                        "trace_id": "trace0",
                        "label": "trace_a",
                        "display_name": "trace_a: trace_a vs x",
                        "x_name": "x",
                        "y_name": "trace_a",
                        "trace": {
                            "id": "trace0",
                            "kind": "line",
                            "kwargs": {"label": "trace_a"},
                            "x_source": {"kind": "name", "value": "x"},
                            "y_source": {"kind": "name", "value": "trace_a"},
                        },
                    },
                    {
                        "subplot_id": "subplot0",
                        "trace_id": "trace1",
                        "label": "trace_b",
                        "display_name": "trace_b: trace_b vs x",
                        "x_name": "x",
                        "y_name": "trace_b",
                        "trace": {
                            "id": "trace1",
                            "kind": "line",
                            "kwargs": {"label": "trace_b"},
                            "x_source": {"kind": "name", "value": "x"},
                            "y_source": {"kind": "name", "value": "trace_b"},
                        },
                    },
                ),
            )
            self.assertTrue(widget.has_supported_traces())
        finally:
            widget.close()

    def test_figure_window_reports_editable_readiness_from_ir_without_control_lane(self):
        widget = FigureWindow(figure_number=1, services={})
        try:
            self.assertFalse(widget.has_figure_ir())
            self.assertFalse(widget.can_request_figure_actions())
            self.assertFalse(widget.is_editable_figure_ready())

            widget.update_payload(
                {
                    "snapshot": {
                        "figure_ir": self._figure_ir(items=("trace_a",)),
                    }
                }
            )

            self.assertTrue(widget.has_figure_ir())
            self.assertFalse(widget.can_request_figure_actions())
            self.assertTrue(widget.is_editable_figure_ready())
        finally:
            widget.close()


class TestFigureContextService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _figure_ir(self):
        return (
            FigureIR()
            .with_title("Figure0")
            .with_x_name("x")
            .with_items(["trace_a"])
            .normalized_state()
        )

    def test_active_editable_figure_returns_boundary_context(self):
        mdi_area = QtWidgets.QMdiArea()
        widget = FigureWindow(figure_number=1, services={})
        subwindow = mdi_area.addSubWindow(widget)
        subwindow.show()
        mdi_area.setActiveSubWindow(subwindow)
        widget.update_payload({"snapshot": {"figure_ir": self._figure_ir()}})

        service = FigureContextService(type("Plugin", (), {"services": {"mdi_area": mdi_area}})())
        try:
            context = service.active_editable_figure()
            figure_ir = context.current_figure_ir()

            self.assertIsNotNone(context)
            self.assertEqual(context.figure_number, 1)
            self.assertTrue(context.has_supported_traces())
            self.assertEqual(figure_ir.trace_ids(), ("trace0",))
            self.assertEqual(
                tuple(record["trace_id"] for record in figure_ir.supported_trace_records()),
                ("trace0",),
            )
        finally:
            widget.force_close()


class TestEditableFigureContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def _figure_ir(self):
        return (
            FigureIR()
            .with_title("Figure0")
            .with_x_name("x")
            .with_items(["trace_a"])
            .normalized_state()
        )

    def _editable_context(self):
        widget = FigureWindow(figure_number=1, services={})
        widget.update_payload({"snapshot": {"figure_ir": self._figure_ir()}})
        return EditableFigureContext(widget), widget

    def test_current_figure_ir_returns_detached_non_qt_boundary(self):
        context, widget = self._editable_context()
        try:
            figure_ir = context.current_figure_ir()
            second_figure_ir = context.current_figure_ir()

            self.assertEqual(figure_ir.figure_number, 1)
            self.assertFalse(isinstance(figure_ir, QtCore.QObject))
            self.assertFalse(hasattr(figure_ir, "request_figure_action"))
            self.assertFalse(hasattr(figure_ir, "apply_live"))
            self.assertFalse(hasattr(figure_ir, "commit"))
            self.assertFalse(hasattr(figure_ir, "revert"))
            self.assertEqual(figure_ir.figure_title(), "Figure0")
            self.assertEqual(figure_ir.trace_ids(), ("trace0",))
            self.assertEqual(figure_ir.trace_style("trace0", "label"), "trace_a")

            updated_ir = figure_ir.set_axis_label("x", "Delay")

            self.assertNotEqual(figure_ir.axis_label("x"), "Delay")
            self.assertEqual(updated_ir.axis_label("x"), "Delay")
            self.assertIn("ax.set_xlabel('Delay')", updated_ir.preview_source())
            self.assertNotEqual(second_figure_ir.axis_label("x"), "Delay")
        finally:
            widget.force_close()


if __name__ == "__main__":
    unittest.main()
