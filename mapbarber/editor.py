"""Interface every editor implements for the main window."""
from .qt import QtCore

Qt = QtCore.Qt


class Editor:
    kind = None
    tools = (("view", "1"),)
    export_filters = ()

    def __init__(self, window):
        self.window = window
        self.tool = "view"
        self.path = None
        self.format = None
        self.panel_values = {}
        self.panel_alive = False

    @property
    def tr(self):
        return self.window.tr_

    def status(self, text, timeout=5000):
        self.window.statusBar().showMessage(text, timeout)

    def changed(self):
        self.window.document_changed()

    def tool_label(self, name):
        return self.tr(f"tool_{name}")

    def view_actions(self):
        """[(label, callable)] for the View menu and toolbar."""
        return []

    def extra_actions(self):
        """[(label, shortcut, callable)] registered while this editor is active."""
        return []

    def selection_actions(self):
        """{'delete', 'select_all', 'invert', 'clear'} -> callable, for editors with a selection."""
        return {}

    def conversions(self):
        """[(label, callable returning (kind, payload) or None)]."""
        return []

    def set_tool(self, name):
        self.tool = name

    def build_panel(self):
        raise NotImplementedError

    def store_panel(self):
        """Remember panel values so the panel can be rebuilt (for example after a language change)."""

    def activate(self):
        """Called after the editor's widget became visible."""

    def capture(self):
        """Image of the editing area, or None when the widget can be grabbed directly."""
        return None
