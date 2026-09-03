import importlib
import logging
import os
import sys
import traceback

from labscript_utils.plugins import (
    DEFAULT_PRIORITY,
    DEFAULT_SETUP_PRIORITY,
    BasePlugin,
    MenuContext,
    PluginManager,
)
from qtutils.qt import QtCore, QtGui, QtWidgets
from zprocess import raise_exception_in_thread

from hyde.features.hyde_ir import HydeAppIR
from hyde.user_interface.base_hyde_widgets import HydeToolWidget
LOGGER = logging.getLogger(__name__)
SETUP_PRIORITY_BIND_SERVICES = DEFAULT_SETUP_PRIORITY
SETUP_PRIORITY_PLUGIN_SETUP = DEFAULT_SETUP_PRIORITY + 10
# Side-effectful runtime startup must wait until all plugins have received
# services and completed ordinary setup, including output-window creation.
SETUP_PRIORITY_RUNTIME_START = DEFAULT_SETUP_PRIORITY + 20
_TOOL_WINDOW_STATES = frozenset({"hidden", "visible", "minimized", "maximized"})


class HydePluginFailure(RuntimeError):
    """Names a part of Hyde that did not load, in the report the user sees."""


def report_plugin_failure(logger, message, *args):
    """Log a swallowed plugin failure, and put it in front of the user.

    labscript-utils' ``PluginManager`` catches a plugin that will not import,
    instantiate, contribute or complete its setup activities, and reports it
    through its logger rather than raising, so that one bad plugin cannot stop
    the application. That trade is deliberate and this keeps it. What it does
    not keep is the silence: in a windowed application the log alone is not a
    report. Hyde's log pane is itself a plugin, and ``HydeApp.__init__``
    connects the logger to it only after every plugin has already loaded, so a
    plugin that failed on the way up leaves an application that looks merely
    featureless.

    The suite's answer to exactly this - carry on, but let the user see it - is
    ``zprocess.raise_exception_in_thread``: BLACS uses it for a device tab that
    will not instantiate (``blacs/blacs/__main__.py:270``), lyse for its shot
    and analysis loops (``lyse/lyse/filebox.py:911`` and ``:955``), runmanager
    for its queue and submission threads. Raising on another thread reaches
    ``labscript_utils.excepthook``, which Hyde already installs
    (``hyde/__main__.py:20``), without unwinding the caller - so the failure
    becomes an error window while the start-up that swallowed it carries on.
    """
    formatted = message % args if args else message
    exception_class, exception, exception_traceback = sys.exc_info()
    if exception is None:
        logger.error(formatted)
        headline = formatted
    else:
        logger.exception(formatted)
        # The dialog's headline is this message, and its body is the traceback
        # below. Naming the original exception here means the headline alone
        # says which plugin broke and why.
        original = "".join(
            traceback.format_exception_only(exception_class, exception)
        ).strip()
        headline = f"{formatted} Original exception was: {original}"
    raise_exception_in_thread(
        (HydePluginFailure, HydePluginFailure(headline), exception_traceback)
    )


class VisibleFailureLogger:
    """A logger whose error reports are also shown to the user.

    The plugin host has no seam for "report a failure" other than its logger,
    so this is the seam. Everything else is delegated unchanged, including
    warnings: the host's own level convention is that a warning describes
    something odd worth recording and an error describes a plugin that is not
    working, and only the latter is worth interrupting the user for.
    """

    def __init__(self, logger):
        self.logger = logger

    def __getattr__(self, name):
        return getattr(self.logger, name)

    def error(self, message, *args, **kwargs):
        del kwargs
        report_plugin_failure(self.logger, message, *args)

    exception = error
    critical = error

    def log(self, level, message, *args, **kwargs):
        if level >= logging.ERROR:
            report_plugin_failure(self.logger, message, *args)
        else:
            self.logger.log(level, message, *args, **kwargs)


class NullConfig:
    def has_section(self, section):
        del section
        return True

    def add_section(self, section):
        del section

    def items(self, section):
        del section
        return []

    def set(self, section, name, value):
        del section, name, value

    def getboolean(self, section, name):
        del section, name
        return True


class HydePluginManager(PluginManager):
    """Plugin manager with unconditional discovery for Hyde UI packages."""

    def __init__(self, plugin_package, plugins_dir, logger=None):
        super().__init__(
            plugin_package=plugin_package,
            plugins_dir=plugins_dir,
            config=NullConfig(),
            config_section="hyde/user_interface",
            default_plugins=(),
            logger=VisibleFailureLogger(logger or logging.getLogger(__name__)),
        )

    def discover_modules(self):
        modules = {}
        for module_name in os.listdir(self.plugins_dir):
            module_path = os.path.join(self.plugins_dir, module_name)
            if not os.path.isdir(module_path) or module_name == "__pycache__":
                continue
            try:
                module = importlib.import_module(f"{self.plugin_package}.{module_name}")
            except Exception:
                self.logger.exception(
                    "Could not import plugin '%s'. Skipping." % module_name
                )
                continue
            if not hasattr(module, "Plugin"):
                # A package under the plugins directory that exports no Plugin
                # is not evidence of breakage - a shared helper package is a
                # legitimate reason - so this is recorded rather than shown,
                # which is the difference between a warning and an error here.
                # Upstream leaves it to fail in instantiate_plugins as an
                # unexplained AttributeError; saying so plainly is better.
                self.logger.warning(
                    "Package '%s' under the plugins directory exports no "
                    "Plugin. Not loading it as a plugin." % module_name
                )
                continue
            modules[module_name] = module

        self.modules = modules
        return modules


class HydePlugin(BasePlugin):
    """Hyde-local plugin base with shared service and menu-action helpers."""

    window_macros_menu_title = None
    window_macros_empty_label = None
    window_macros_new_action_name = None
    window_macros_new_action_attr = None
    window_macros_attr = None
    window_macros_menu_attr = "_macro_menu"

    def __init__(self, initial_settings):
        super().__init__(initial_settings)
        self.services = {}

    def get_setup_activities(self):
        return [
            {
                "name": "bind_services",
                "priority": SETUP_PRIORITY_BIND_SERVICES,
                "action": self.bind_services,
            },
            {
                "name": "setup",
                "priority": SETUP_PRIORITY_PLUGIN_SETUP,
                "action": self.setup,
            },
        ]

    def bind_services(self, data=None):
        data = data or {}
        self.services = data.get("services", {})

    def setup(self, data=None):
        del data

    def active_editable_figure(self):
        """The active first-class figure as an editable context, or None.

        Figure-working plugins all need this to decide whether their actions
        can run, so it is one accessor here rather than a copy per plugin.
        """
        figure_context_service = self.service("figure_context_service")
        if figure_context_service is None:
            return None
        return figure_context_service.active_editable_figure()

    def has_active_editable_figure(self):
        return self.active_editable_figure() is not None

    def service(self, key, default=None):
        return self.services.get(key, default)

    def current_app_ir(self):
        get_current_app_ir = self.services.get("get_current_app_ir")
        if callable(get_current_app_ir):
            app_ir = get_current_app_ir()
            if isinstance(app_ir, HydeAppIR):
                return app_ir
        get_current_project_dir = self.services.get("get_current_project_dir")
        current_project_dir = (
            get_current_project_dir() if callable(get_current_project_dir) else None
        )
        return HydeAppIR(current_project_dir=current_project_dir)

    def get_session_toml_data(self):
        return {}

    def get_session_restore_source(self):
        return ""

    def menu_action(self, location, name, path=()):
        lookup_menu_action = self.service("lookup_menu_action")
        if lookup_menu_action is None:
            return None
        return lookup_menu_action(location, name, path=path)

    def bind_menu_action(self, attr_name, location, name, path=()):
        action = self.menu_action(location, name, path=path)
        setattr(self, attr_name, action)
        return action

    def set_bound_action_enabled(self, attr_name, enabled):
        action = getattr(self, attr_name, None)
        if action is not None:
            action.setEnabled(bool(enabled))

    def rebuild_window_macros_menu(
        self,
        *,
        menu,
        macros,
        empty_label,
        new_action_attr,
        on_trigger,
    ):
        menu.clear()
        get_current_project_dir = self.service("get_current_project_dir")
        has_project = (
            False
            if get_current_project_dir is None
            else get_current_project_dir() is not None
        )
        self.set_bound_action_enabled(new_action_attr, has_project)
        if not has_project:
            menu.setEnabled(False)
            return
        if not macros:
            placeholder = menu.addAction(empty_label)
            placeholder.setEnabled(False)
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        for macro in macros:
            macro_name = macro["name"]
            macro_args = tuple(macro.get("args", ()))
            action = menu.addAction(macro_name)
            action.triggered.connect(
                lambda checked=False, name=macro_name, args=macro_args: (
                    on_trigger(name, args)
                )
            )

    def setup_configured_window_macros_menu(self):
        menu_title = self.window_macros_menu_title
        if not menu_title:
            return None
        if self.window_macros_new_action_attr and self.window_macros_new_action_name:
            self.bind_menu_action(
                self.window_macros_new_action_attr,
                "window",
                self.window_macros_new_action_name,
            )
        menu_attr = self.window_macros_menu_attr
        menu = getattr(self, menu_attr, None)
        if menu is None:
            ui = self.services["ui"]
            menu = QtWidgets.QMenu(menu_title, ui.menuWindow)
            ui.menuWindow.addMenu(menu)
            setattr(self, menu_attr, menu)
            menu.aboutToShow.connect(self.rebuild_configured_window_macros_menu)
        self.rebuild_configured_window_macros_menu()
        return menu

    def rebuild_configured_window_macros_menu(self):
        menu = getattr(self, self.window_macros_menu_attr, None)
        if menu is None:
            return None
        macros = []
        if self.window_macros_attr:
            macros = getattr(self, self.window_macros_attr, [])
        self.rebuild_window_macros_menu(
            menu=menu,
            macros=macros,
            empty_label=self.window_macros_empty_label,
            new_action_attr=self.window_macros_new_action_attr,
            on_trigger=self._execute_macro,
        )
        return menu

    def _execute_macro(self, macro_name, macro_args):
        app_ir = self.current_app_ir()
        macro_ir = app_ir.with_callable_invocation(macro_name, macro_args)
        self.service("python_execution_service").execute_visible(
            app_ir.current_diff(macro_ir).python_source()
        )

    def mdi_context(self):
        return self.service("mdi_context")

    def ensure_mdi_widget(self, key):
        return self.mdi_context().ensure_widget(key)

    def mdi_widget(self, key):
        return self.mdi_context().widget(key)

    def mdi_subwindow(self, key):
        return self.mdi_context().subwindow(key)

    def destroy_mdi_widget(self, key):
        return self.mdi_context().destroy(key)

    def hide_mdi_subwindow(self, key):
        subwindow = self.mdi_subwindow(key)
        if subwindow is not None:
            subwindow.hide()
        return subwindow

    def tool_window_save_data(self, session_key, mdi_key=None):
        subwindow = self.mdi_subwindow(mdi_key or session_key)
        if subwindow is None:
            return {}
        object_name = HydeToolWidget.read_subwindow_identifier(
            subwindow,
            fallback=mdi_key or session_key,
        )
        return {
            "tool_windows": {
                object_name: capture_subwindow_state(subwindow),
            }
        }

    def restore_tool_window(self, session, session_key, mdi_key=None):
        key = mdi_key or session_key
        subwindow = self.mdi_subwindow(key)
        if subwindow is None:
            return None
        object_name = HydeToolWidget.read_subwindow_identifier(
            subwindow,
            fallback=key,
        )
        tool_windows = session.get("tool_windows", {})
        info = tool_windows.get(session_key, tool_windows.get(object_name, {}))
        presentation_deferred = False
        deferred_getter = self.service(
            "get_session_restore_presentation_deferred"
        )
        if deferred_getter is not None:
            presentation_deferred = bool(deferred_getter())
        if presentation_deferred:
            restored = stage_subwindow_state(
                subwindow,
                info,
                session_key=object_name,
            )
            if restored:
                register_tool_window = self.service(
                    "register_session_restore_tool_window"
                )
                if register_tool_window is not None:
                    register_tool_window(object_name, subwindow, info)
            return subwindow
        restore_subwindow_state(
            subwindow,
            info,
            session_key=object_name,
        )
        return subwindow


class HydeToolWindowPlugin(HydePlugin):
    """Shared plugin plumbing for ordinary persistent tool windows."""

    session_key = None
    window_title = None
    menu_name = None
    window_size = None
    # Menu groups order by name, so the name carries the ordinal. See
    # `HydeMenuContext.render`.
    menu_group = "10_tool_windows"
    menu_order = DEFAULT_PRIORITY
    creation_policy = "lazy"
    restore_on_project_loaded = False
    enable_action_with_project = False
    hide_on_enter_no_project = False
    ensure_widget_on_kernel_ready = False
    destroy_widget_on_kernel_crash = False

    def create_tool_window_widget(self, parent=None):
        raise NotImplementedError

    def _tool_window_factory(self, parent=None, data=None):
        del data
        return self.create_tool_window_widget(parent=parent)

    def get_ui_contributions(self):
        key = self.session_key
        title = self.window_title or self.menu_name or key
        contribution = {
            "context": "mdi",
            "key": key,
            "title": title,
            "factory": self._tool_window_factory,
        }
        if self.window_size is not None:
            contribution["size"] = self.window_size
        return [contribution]

    def get_menu_contributions(self):
        title = self.window_title or self.menu_name or self.session_key
        menu_name = self.menu_name or title
        return [
            {
                "location": "window",
                "group": self.menu_group,
                "order": self.menu_order,
                "name": menu_name,
                "action": self.show_window,
            }
        ]

    def setup(self, data=None):
        del data
        title = self.window_title or self.menu_name or self.session_key
        menu_name = self.menu_name or title
        self.bind_menu_action("_action", "window", menu_name)
        if self.creation_policy == "eager":
            self.ensure_mdi_widget(self.session_key)
            self.hide_mdi_subwindow(self.session_key)

    def show_window(self, checked=False):
        del checked
        self.service("show_window")(self.session_key)

    def get_event_handlers(self):
        handlers = {}
        if self.restore_on_project_loaded:
            handlers["project_loaded"] = self.on_project_loaded
        if self.enable_action_with_project or self.hide_on_enter_no_project:
            handlers["enter_no_project_state"] = self.on_enter_no_project_state
        if self.enable_action_with_project:
            handlers["project_activated"] = self.on_project_activated
        if self.ensure_widget_on_kernel_ready:
            handlers["kernel_ready"] = self.on_kernel_ready
        if self.destroy_widget_on_kernel_crash:
            handlers["kernel_crashed"] = self.on_kernel_crashed
        return handlers

    def on_project_loaded(self, data):
        self.restore_tool_window_session(data["session"])

    def on_enter_no_project_state(self, data):
        del data
        if self.enable_action_with_project:
            self.set_bound_action_enabled("_action", False)
        if self.hide_on_enter_no_project:
            self.hide_mdi_subwindow(self.session_key)

    def on_project_activated(self, data):
        del data
        if self.enable_action_with_project:
            self.set_bound_action_enabled("_action", True)

    def on_kernel_ready(self, data):
        del data
        if self.ensure_widget_on_kernel_ready:
            self.ensure_mdi_widget(self.session_key)

    def on_kernel_crashed(self, data):
        del data
        if self.destroy_widget_on_kernel_crash:
            self.destroy_mdi_widget(self.session_key)

    def get_session_toml_data(self):
        session = self.tool_window_save_data(self.session_key)
        widget = self.mdi_widget(self.session_key)
        if widget is None:
            return session
        getter = getattr(widget, "get_session_toml_data", None)
        widget_session = getter() if callable(getter) else {}
        if widget_session:
            session[self.session_key] = widget_session
        return session

    def restore_tool_window_session(self, session):
        widget = self.ensure_mdi_widget(self.session_key)
        self.restore_tool_window(session, self.session_key)
        restorer = getattr(widget, "restore_session_toml_data", None)
        if callable(restorer):
            restorer(dict(session.get(self.session_key, {}) or {}))
        return widget


class HydeToolWindowService:
    """Shared MDI-backed service helpers for persistent tool windows."""

    use_mounted_child = False

    def __init__(self, plugin, window_key=None):
        self.plugin = plugin
        self.window_key = (
            window_key
            if window_key is not None
            else getattr(plugin, "session_key", None)
        )

    def _service_widget(self, widget):
        if widget is None or not self.use_mounted_child:
            return widget
        return getattr(widget, "mounted_child", None)

    def ensure_widget(self):
        return self._service_widget(self.plugin.ensure_mdi_widget(self.window_key))

    def widget(self):
        return self._service_widget(self.plugin.mdi_widget(self.window_key))

    def subwindow(self):
        return self.plugin.mdi_subwindow(self.window_key)

    def destroy(self):
        return self.plugin.destroy_mdi_widget(self.window_key)


def resolve_menu_enabled(enabled):
    """Resolve a menu contribution's `enabled` value to a boolean.

    A contribution may declare `enabled` as a callable so that its state tracks
    a live precondition, such as whether a first-class figure is active. Menus
    are rendered once, so a static flag can only describe the state at launch.

    The framework understands callable `enabled` too, but resolves it inline in
    `MenuContext.render()` and reports a raising precondition through the
    context's logger. Hyde cannot delegate to that: this runs again on every
    `aboutToShow` and every subwindow activation, and Hyde's context logger is
    `VisibleFailureLogger`, so a precondition that keeps raising would put an
    error dialog in front of the user every time a menu opened. Silence is the
    right level for something re-evaluated that often.
    """
    if not callable(enabled):
        return bool(enabled)
    try:
        return bool(enabled())
    except Exception:
        # A broken precondition must not take the menu down with it. Disabling
        # is the safe reading: the action reports itself unavailable rather than
        # offering an operation whose precondition could not be established.
        return False


class HydeMenuContext(MenuContext):
    """Hyde-local menu context that retains rendered QAction objects."""

    def __init__(self, icon_factory=None, logger=None):
        # A rejected menu contribution is a plugin that half loaded: its menu
        # entry is simply not there. Reported the same way as one that would
        # not import at all.
        super().__init__(
            icon_factory=icon_factory,
            logger=VisibleFailureLogger(logger or logging.getLogger(__name__)),
        )
        self._actions = {}
        self._grouped_contributions = {}
        self._group_orders = {}
        self._live_enabled = {}

    def refresh_enabled_states(self):
        """Re-evaluate every callable precondition in the rendered menus."""
        for entries in list(self._live_enabled.values()):
            for action, enabled in entries:
                action.setEnabled(resolve_menu_enabled(enabled))

    def lookup_action(self, location, name, path=()):
        if isinstance(path, str):
            path = (path,)
        else:
            path = tuple(path)
        return self._actions.get((location, path, name))

    def _register_action(self, location, path, name, action):
        self._actions[(location, path, name)] = action

    def _normalized_path(self, path):
        if isinstance(path, str):
            return (path,)
        return tuple(path)

    def _group_index(self, location, path, group):
        """Where `group` sits among the groups of one menu.

        A group that menu has no entry in sorts after every group it does have.
        That is the case of a submenu whose entries name a group its parent menu
        does not use: there is no position among the parent's groups for it to
        take, so it goes last rather than silently taking the first one's.
        """
        group_orders = self._group_orders.get(
            (location, self._normalized_path(path)), {}
        )
        return group_orders.get(group, len(group_orders))

    def _sorted_contributions(self, location, path):
        key = (location, self._normalized_path(path))
        contributions = self._grouped_contributions.get(key, [])
        return sorted(
            contributions,
            key=lambda item: (
                self._group_index(location, path, item[1].get("group", None)),
                item[1].get("order", DEFAULT_PRIORITY),
                item[0],
                item[1]["name"],
            ),
        )

    def _submenu_sort_key(self, location, submenu_path):
        """Where a submenu sits among its parent's entries.

        A submenu carries no group or order of its own, so it takes the position
        of its first entry. Without this a submenu lands wherever it happened to
        be created, which for a location that also has plain actions means the
        top of the menu regardless of intent.

        The group is resolved against the *parent* menu's groups, because that
        is the menu the submenu is being placed in. Resolving it against the
        submenu's own groups compares an index counted over one menu with
        indices counted over another: a submenu is usually the only thing in its
        own path's first group, so its key came out as group zero and it landed
        at the top of whatever the parent's first group is.
        """
        parent_path = submenu_path[:-1]
        best = None
        for current_location, path in self._grouped_contributions:
            if current_location != location:
                continue
            if path[: len(submenu_path)] != submenu_path:
                continue
            for plugin_name, contribution in self._sorted_contributions(location, path):
                candidate = (
                    self._group_index(
                        location, parent_path, contribution.get("group", None)
                    ),
                    contribution.get("order", DEFAULT_PRIORITY),
                    plugin_name,
                    contribution["name"],
                )
                if best is None or candidate < best:
                    best = candidate
                break
        return best if best is not None else (DEFAULT_PRIORITY, DEFAULT_PRIORITY, "", "")

    def _render_menu_tree(self, location, root_menu, register_actions):
        menus = {(location, ()): root_menu}
        paths = {
            path
            for current_location, path in self._grouped_contributions
            if current_location == location
        }
        # Submenus of a parent, in the order they should appear among its
        # entries, so a submenu can be created at the right moment below.
        pending_submenus = {}
        for path in sorted(paths):
            parent_path = ()
            for submenu_name in path:
                submenu_path = parent_path + (submenu_name,)
                pending_submenus.setdefault(parent_path, {})[submenu_name] = (
                    self._submenu_sort_key(location, submenu_path)
                )
                parent_path = submenu_path

        def ensure_submenu(parent_path, submenu_name):
            submenu_path = parent_path + (submenu_name,)
            submenu_key = (location, submenu_path)
            if submenu_key not in menus:
                parent_menu = menus[(location, parent_path)]
                menus[submenu_key] = parent_menu.addMenu(submenu_name)
            return menus[submenu_key]

        for path in sorted(paths):
            # Create this path's ancestors before rendering into it, in case no
            # entry of the parent triggered their creation.
            parent_path = ()
            for submenu_name in path:
                ensure_submenu(parent_path, submenu_name)
                parent_path = parent_path + (submenu_name,)
            menu = menus[(location, path)]
            previous_group = None
            # Interleave this menu's own actions with its child submenus, so a
            # submenu sits where its first entry says it belongs rather than
            # wherever it happened to be created.
            entries = [
                (
                    (
                        self._group_index(
                            location, path, contribution.get("group", None)
                        ),
                        contribution.get("order", DEFAULT_PRIORITY),
                        plugin_name,
                        contribution["name"],
                    ),
                    "action",
                    (plugin_name, contribution),
                )
                for plugin_name, contribution in self._sorted_contributions(location, path)
            ]
            entries.extend(
                (sort_key, "submenu", submenu_name)
                for submenu_name, sort_key in pending_submenus.get(path, {}).items()
            )
            entries.sort(key=lambda entry: entry[0])

            for index, (_sort_key, kind, payload) in enumerate(entries):
                if kind == "submenu":
                    ensure_submenu(path, payload)
                    previous_group = None
                    continue

                plugin_name, contribution = payload
                group = contribution.get("group", None)
                if index and group != previous_group:
                    menu.addSeparator()
                previous_group = group

                name = contribution["name"]
                icon = contribution.get("icon", None)
                if icon is not None and self.icon_factory is not None:
                    action = menu.addAction(self.icon_factory(icon), name)
                else:
                    action = menu.addAction(name)

                callback = contribution.get("action", None)
                if callback is not None:
                    action.triggered.connect(callback)

                shortcut = contribution.get("shortcut", None)
                if shortcut is not None and hasattr(action, "setShortcut"):
                    action.setShortcut(shortcut)

                checkable = contribution.get("checkable", False)
                if hasattr(action, "setCheckable"):
                    action.setCheckable(checkable)

                enabled = contribution.get("enabled", True)
                if hasattr(action, "setEnabled"):
                    action.setEnabled(resolve_menu_enabled(enabled))
                if callable(enabled) and register_actions:
                    self._live_enabled.setdefault(menu, []).append((action, enabled))

                if register_actions:
                    self._register_action(location, path, name, action)

    def build_popup_menu(self, location, parent=None):
        if location not in self.locations:
            return None
        base_menu = self.locations[location]
        popup_menu = base_menu.__class__(base_menu.title(), parent or base_menu.parent())
        self._render_menu_tree(location, popup_menu, register_actions=False)
        return popup_menu

    def render(self):
        """Render every collected contribution into its registered location.

        Groups order by name, which is the framework's rule and the reason no
        contribution here carries an ordering key of its own: a group name is an
        internal key, never shown to anyone and never persisted, so Hyde's
        groups are named with a leading ordinal and the sort puts them in the
        intended order. The alternative -- ordering groups by the order they
        were first contributed -- makes the File menu's layout a function of
        `os.listdir()` over the plugins directory, which is to say a function of
        the machine: reverse that listing and Quit moves to the top of the File
        menu.

        This overrides the base renderer permanently, and not over any key a
        contribution carries. It exists for four things the base has no notion
        of, all of them load-bearing for Hyde:

        * rendered actions are retained, so `lookup_action` can hand a plugin
          its own menu item to enable, rename or check;
        * the computed grouping is retained rather than consumed, so
          `build_popup_menu` can render the same contributions again into a
          fresh menu -- which is how the figure and table right-click menus are
          built;
        * `aboutToShow` is wired to `refresh_enabled_states`, so a callable
          precondition is re-read each time a menu opens rather than once at
          start-up;
        * submenus interleave with actions by `_submenu_sort_key` instead of
          being appended after their parent's own entries.
        """
        self._actions = {}
        grouped = {}
        groups_by_key = {}

        for plugin_name, contribution in self.contributions:
            if not isinstance(contribution, dict):
                self.logger.error(
                    "Menu contribution from plugin '%s' is not a dictionary. "
                    "Skipping." % plugin_name
                )
                continue
            if "location" not in contribution:
                self.logger.error(
                    "Menu contribution from plugin '%s' missing location. "
                    "Skipping." % plugin_name
                )
                continue
            if "name" not in contribution:
                self.logger.error(
                    "Menu contribution from plugin '%s' missing name. "
                    "Skipping." % plugin_name
                )
                continue

            location = contribution["location"]
            if location not in self.locations:
                self.logger.error(
                    "Menu contribution from plugin '%s' requested unknown "
                    "location '%s'. Skipping." % (plugin_name, location)
                )
                continue

            path = self._normalized_path(contribution.get("path", ()))

            key = (location, path)
            groups_by_key.setdefault(key, set()).add(contribution.get("group", None))
            grouped.setdefault(key, []).append((plugin_name, contribution))

        self._grouped_contributions = grouped
        # An ungrouped contribution sorts first, then the rest by name.
        self._group_orders = {
            key: {
                group: index
                for index, group in enumerate(
                    sorted(groups, key=lambda group: (group is not None, str(group)))
                )
            }
            for key, groups in groups_by_key.items()
        }

        self._live_enabled = {}
        for name, menu in self.locations.items():
            menu.clear()
            self._render_menu_tree(name, menu, register_actions=True)

        for menu in self._live_enabled:
            about_to_show = getattr(menu, "aboutToShow", None)
            if about_to_show is None:
                continue
            try:
                about_to_show.disconnect(self.refresh_enabled_states)
            except (TypeError, RuntimeError):
                pass
            about_to_show.connect(self.refresh_enabled_states)


class HydeMDIContext:
    """Register and lazily open plugin-owned MDI windows."""

    def __init__(self, mdi_area, configure_subwindow=None, created_callback=None):
        self.mdi_area = mdi_area
        self.configure_subwindow = configure_subwindow
        self.created_callback = created_callback
        self._contributions = {}
        self._widgets = {}
        self._subwindows = {}

    def add(self, plugin_name, contribution, data):
        key = contribution["key"]
        self._contributions[key] = {
            "plugin_name": plugin_name,
            "contribution": dict(contribution),
            "data": dict(data),
        }

    def ensure_widget(self, key):
        if key in self._widgets:
            return self._widgets[key]

        info = self._contributions[key]
        contribution = info["contribution"]
        widget = contribution["factory"](parent=self.mdi_area, data=info["data"])
        subwindow = self.mdi_area.addSubWindow(widget)
        HydeToolWidget.bind_subwindow_identifier(subwindow, key)
        bind_subwindow = getattr(widget, "bind_subwindow", None)
        if callable(bind_subwindow):
            bind_subwindow(subwindow)
        if self.configure_subwindow is not None:
            self.configure_subwindow(subwindow)
        title = contribution.get("title")
        if title:
            subwindow.setWindowTitle(title)
        size = contribution.get("size")
        if size:
            subwindow.resize(*size)

        self._widgets[key] = widget
        self._subwindows[key] = subwindow
        if self.created_callback is not None:
            self.created_callback(key, widget, subwindow)
        return widget

    def show(self, key):
        widget = self.ensure_widget(key)
        subwindow = self._subwindows[key]
        subwindow.show()
        subwindow.setFocus()
        subwindow.raise_()
        return widget

    def widget(self, key):
        return self._widgets.get(key)

    def subwindow(self, key):
        return self._subwindows.get(key)

    def destroy(self, key):
        widget = self._widgets.pop(key, None)
        subwindow = self._subwindows.pop(key, None)
        if widget is None:
            return None, None
        if subwindow is not None:
            self.mdi_area.removeSubWindow(widget)
        if hasattr(widget, "shutdown"):
            widget.shutdown()
        widget.deleteLater()
        if subwindow is not None:
            subwindow.deleteLater()
        if self.created_callback is not None:
            self.created_callback(key, None, None)
        return widget, subwindow

def capture_subwindow_state(subwindow):
    window_state = capture_subwindow_window_state(subwindow)
    return {
        "window_state": window_state,
        "geometry": capture_subwindow_geometry(subwindow),
    }


def restore_subwindow_state(subwindow, info, *, session_key="tool window"):
    normalized = normalize_subwindow_restore_info(
        subwindow,
        info,
        session_key=session_key,
    )
    if normalized is None:
        return False
    apply_staged_subwindow_restore(subwindow, normalized)
    apply_subwindow_presentation_state(subwindow, normalized)
    return True


def stage_subwindow_state(subwindow, info, *, session_key="tool window"):
    normalized = normalize_subwindow_restore_info(
        subwindow,
        info,
        session_key=session_key,
    )
    if normalized is None:
        return False
    apply_staged_subwindow_restore(subwindow, normalized)
    return True


def finalize_subwindow_state(subwindow, info, *, session_key="tool window"):
    normalized = normalize_subwindow_restore_info(
        subwindow,
        info,
        session_key=session_key,
    )
    if normalized is None:
        return False
    apply_subwindow_presentation_state(subwindow, normalized)
    return True


def capture_subwindow_geometry(subwindow):
    was_hidden = subwindow.isHidden()
    was_minimized = subwindow.isMinimized()
    was_maximized = subwindow.isMaximized()
    if was_minimized or was_maximized:
        subwindow.showNormal()
    geometry = qrect_to_list(subwindow.geometry())
    if was_maximized:
        subwindow.showMaximized()
    elif was_minimized:
        subwindow.showMinimized()
    if was_hidden:
        subwindow.hide()
    return geometry


def capture_subwindow_window_state(subwindow):
    if subwindow.isHidden():
        return "hidden"
    if subwindow.isMinimized():
        return "minimized"
    if subwindow.isMaximized():
        return "maximized"
    return "visible"


def coerce_geometry(geometry):
    if not isinstance(geometry, (list, tuple)) or len(geometry) != 4:
        return None
    try:
        x, y, width, height = [int(value) for value in geometry]
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return QtCore.QRect(x, y, width, height)


def hide_subwindow_with_warning(subwindow, session_key, detail):
    subwindow.hide()
    LOGGER.warning("%s: %s.", session_key, detail)


def outdated_tool_window_session_keys(session):
    """Tool-window entries written before `window_state` replaced `visible`.

    That schema change shipped without a migration, so such a project still
    parses and still loads -- it simply restores none of its tool windows. The
    entry is the evidence: every window Hyde saves now records `window_state`,
    so one without it predates the change.

    Reported rather than migrated because the two are not equivalent: `visible`
    said nothing about minimized, maximized, or geometry validity, so guessing
    a `window_state` from it would invent state the user never saved.
    """
    tool_windows = session.get("tool_windows", {}) or {}
    return sorted(
        str(key)
        for key, info in tool_windows.items()
        if isinstance(info, dict) and "window_state" not in info
    )


def normalize_subwindow_restore_info(subwindow, info, *, session_key):
    if not isinstance(info, dict) or not info:
        # Nothing was saved for this window: a new project, or a tool added
        # since the session was written. A tool window shows only what a
        # session recorded, so it is hidden -- switching to a project that does
        # not mention it must not leave it showing from the last one. Ordinary,
        # and nothing to report.
        subwindow.hide()
        return None

    window_state = info.get("window_state")
    if window_state not in _TOOL_WINDOW_STATES:
        hide_subwindow_with_warning(
            subwindow,
            session_key,
            "invalid or missing tool-window window_state",
        )
        return None

    geometry = coerce_geometry(info.get("geometry"))
    if geometry is None:
        hide_subwindow_with_warning(
            subwindow,
            session_key,
            "invalid or missing tool-window geometry",
        )
        return None

    return {
        "window_state": window_state,
        "geometry": geometry,
    }


def apply_staged_subwindow_restore(subwindow, info):
    if info["window_state"] == "hidden":
        subwindow.hide()
        subwindow.setGeometry(info["geometry"])
        return
    subwindow.showNormal()
    subwindow.setGeometry(info["geometry"])


def apply_subwindow_presentation_state(subwindow, info):
    window_state = info["window_state"]
    if window_state == "hidden":
        subwindow.hide()
        return
    if window_state == "maximized":
        subwindow.showMaximized()
        return
    if window_state == "minimized":
        subwindow.showMinimized()


def qrect_to_list(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def capture_saveable_window_state(subwindow):
    if subwindow is None:
        return None
    if subwindow.isMinimized():
        return "minimized"
    if subwindow.isMaximized():
        return "maximized"
    return None


def apply_saveable_window_state(subwindow, window_state):
    if subwindow is None:
        return
    if window_state == "maximized":
        subwindow.showMaximized()
        return
    if window_state != "minimized":
        return
    subwindow.showMinimized()


def with_window_metadata(
    macro_source,
    *,
    decorator_name,
    register=None,
    window_pos=None,
    window_state=None,
):
    if not macro_source:
        return macro_source
    decorator_args = []
    if window_pos and len(window_pos) == 2:
        decorator_args.append(f"window_pos=({int(window_pos[0])}, {int(window_pos[1])})")
    if window_state:
        decorator_args.append(f"window_state={window_state!r}")
    if register is False:
        decorator_args.append("register=False")
    if not decorator_args:
        return macro_source
    lines = macro_source.splitlines()
    if not lines:
        return macro_source
    lines[0] = f"{decorator_name}({', '.join(decorator_args)})"
    return "\n".join(lines)


def build_window_function_source(
    function_source,
    *,
    decorator_name,
    register=None,
    window_pos=None,
    window_state=None,
):
    return with_window_metadata(
        function_source,
        decorator_name=decorator_name,
        register=register,
        window_pos=window_pos,
        window_state=window_state,
    )


def build_window_restore_source(
    function_source,
    *,
    handle,
    arguments,
    decorator_name,
    register=False,
    window_pos=None,
    window_state=None,
):
    wrapped_source = build_window_function_source(
        function_source,
        decorator_name=decorator_name,
        register=register,
        window_pos=window_pos,
        window_state=window_state,
    )
    invocation_arguments = ", ".join(arguments or ())
    return f"{wrapped_source}\n\n{handle}({invocation_arguments})\n"


def blank_window_icon():
    pixmap = QtGui.QPixmap(1, 1)
    pixmap.fill(QtCore.Qt.transparent)
    return QtGui.QIcon(pixmap)
