"""A stand-in for the `HydeApp` a plugin is set up against.

`HydePlugin` reaches its host through a fixed surface -- the menu bar and MDI
area on `app.ui`, and the accessors `build_plugin_services` hands out -- so a
test that sets a plugin up needs all of it present whether or not the test is
about any of it. Every attribute below names a real `HydeApp` method; the body
is a stub of that interface, not a fixture shaped to any one test, which is why
it can be shared.

It was six near-copies before, and they had drifted: one had grown
`get_procedures_init` and the others had not, so a plugin that asked its host
for procedures worked in one module's tests and not in another's. A module whose
host genuinely differs wraps this one and says so in the one line that differs.
"""

from qtutils.qt import QtWidgets

from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.main import HydeApp


def make_plugin_host(plugin_manager, *, menu_class=QtWidgets.QMenu):
    """A host `HydeApp.setup_plugins` can be run against.

    `menu_class` builds the Figure and Table menus, for a module that needs to
    observe what is popped up on them.
    """
    main_window = QtWidgets.QMainWindow()
    main_window.setMenuBar(QtWidgets.QMenuBar())
    main_window.menuFile = main_window.menuBar().addMenu("File")
    main_window.menuEdit = main_window.menuBar().addMenu("Edit")
    main_window.menuAnalysis = main_window.menuBar().addMenu("Analysis")
    main_window.menuWindow = main_window.menuBar().addMenu("Windows")
    main_window.menuFigure = menu_class("Figure", main_window.menuBar())
    main_window.menuTable = menu_class("Table", main_window.menuBar())
    main_window.menuBar().addMenu(main_window.menuFigure)
    main_window.menuBar().addMenu(main_window.menuTable)
    main_window.mdiArea = QtWidgets.QMdiArea()
    main_window.setCentralWidget(main_window.mdiArea)

    app = type("DummyApp", (), {})()
    app.ui = main_window
    app.plugin_manager = plugin_manager
    app.configure_persistent_subwindow = lambda subwindow: None
    # Records rather than dispatches, so a plugin under test cannot be
    # perturbed by another plugin reacting to its events. A module that wants
    # the real bus rebinds this to `HydeApp.emit_plugin_event`.
    app.emit_plugin_event = lambda name, data=None: (name, data)
    app.show_status_message = lambda label: label
    app.show_transient_status_message = lambda label, timeout_ms: label
    app.clear_status_message = lambda label: None
    app.process_tree = object()
    app.show_plugin_window = lambda key: key
    app.build_plugin_services = lambda: HydeApp.build_plugin_services(app)
    # Reads the accessor rather than closing over None, so a test that points
    # the host at a project gets an app IR that agrees with it.
    app.get_current_app_ir = lambda: HydeAppIR(
        current_project_dir=app.get_current_project_dir()
    )
    app.lookup_menu_action = lambda location, name, path=(): (
        None
        if getattr(app, "menu_context", None) is None
        else app.menu_context.lookup_action(location, name, path=path)
    )
    app.show_menu = lambda location: HydeApp.show_menu(app, location)
    app.hide_menu = lambda location: HydeApp.hide_menu(app, location)
    app.popup_menu = lambda location, global_pos: HydeApp.popup_menu(
        app, location, global_pos
    )
    app.get_current_project_dir = lambda: None
    app.get_procedures_init = lambda: None
    app.get_shutting_down = lambda: False
    app.set_shutting_down = lambda value: value
    app.get_quit_command_sent = lambda: False
    app.set_quit_command_sent = lambda value: value
    app.begin_project_operation = lambda label: label
    app.project_target_needs_confirmation = lambda path: False
    app.confirm_overwrite_project = lambda path: False
    app.begin_shutdown_from_close_event = lambda: None
    app.finalize_quit = lambda: None
    app.on_kernel_ready = lambda: None
    app.on_kernel_crashed = lambda: None
    app.enter_no_project_state = lambda: None
    app.activate_project = lambda project_dir: project_dir
    app.on_project_state_result = lambda data: data
    app.request_gui_quit = lambda: None
    return app
