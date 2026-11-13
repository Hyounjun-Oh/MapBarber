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
        self.accepted_losses = set()

    @property
    def tr(self):
        return self.window.tr_

    def status(self, text, timeout=5000):
        self.window.statusBar().showMessage(text, timeout)

    def changed(self):
        self.window.document_changed(self)

    def tool_label(self, name):
        return self.tr(f"tool_{name}")

    def view_actions(self):
        """[(label, callable, shortcut)] for the View menu and toolbar."""
        return []

    def extra_actions(self):
        """[(label, shortcut, callable)] registered while this editor is active."""
        return [(self.tr("brush_smaller"), "[", lambda: self.adjust_brush(-1)),
                (self.tr("brush_larger"), "]", lambda: self.adjust_brush(1))]

    def adjust_brush(self, step):
        """Make the brush one step smaller (-1) or larger (+1)."""

    def zoom(self, factor):
        """Zoom the view in (factor > 1) or out."""

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

    def read(self, path):
        """Parse a file into the payload for set_document. Runs on a worker thread: no widgets here."""
        raise NotImplementedError

    def export(self, path, fmt=None):
        """Write the document to a file. Runs on a worker thread: no widgets here."""
        raise NotImplementedError

    def losses(self, fmt):
        """[(what, detail)] the document holds that a file of this format cannot; see loss.py."""
        return []

    def keeps_path(self, path):
        """True when writing to `path` was an export and the document should stay where it is."""
        return False

    def mark_saved(self):
        """Called on the main thread after export succeeded."""

    def shutdown(self):
        """Stop timers and callbacks before the editor's widget is destroyed."""

    def capture(self):
        """Image of the editing area, or None when the widget can be grabbed directly."""
        return None
