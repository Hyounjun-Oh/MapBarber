"""Main window: recognises what each file contains and opens it in a tab with the matching editor."""
import os
import shutil
import time

from . import __version__, formats
from .cloud_editor import CloudEditor
from .formats import CLOUD, GRID, VOXEL
from .grid import UNKNOWN, GridMap
from .grid_editor import GridEditor
from . import icons
from .i18n import LANGUAGES, Translator
from .qt import QAction, QActionGroup, QtCore, QtGui, QtWidgets, run
from .voxel_editor import VoxelEditor
from .voxels import EMPTY
from .widgets import ask_numbers

Qt = QtCore.Qt
EDITORS = {VOXEL: VoxelEditor, CLOUD: CloudEditor, GRID: GridEditor}
STANDARD_KEYS = getattr(QtGui.QKeySequence, "StandardKey", QtGui.QKeySequence)


def key_sequences(spec):
    """Shortcut spec -> unique QKeySequences; '@Name' expands to the platform's standard binding."""
    if not spec:
        return []
    out = []
    for item in [spec] if isinstance(spec, str) else spec:
        found = QtGui.QKeySequence.keyBindings(getattr(STANDARD_KEYS, item[1:])) if item.startswith("@") \
            else [QtGui.QKeySequence(item)]
        out += [sequence for sequence in found if not sequence.isEmpty() and sequence not in out]
    return out
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.svg")


class Workbench(QtWidgets.QMainWindow):
    def __init__(self, paths=None, language=None):
        super().__init__()
        self.settings = QtCore.QSettings("mapbarber", "mapbarber")
        self.tr_ = Translator(language or self.settings.value("language"))
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.editor = None
        self._owners = {}
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)
        self.welcome = QtWidgets.QWidget()
        self.stack.addWidget(self.welcome)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(lambda index: self.close_document(self._owners[self.tabs.widget(index)]))
        self.tabs.currentChanged.connect(self._tab_changed)
        self.stack.addWidget(self.tabs)
        self.counts = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.counts)
        self.dock = None
        self.toolbar = None
        self._panel_owner = None
        self._build_ui()
        if isinstance(paths, str):
            paths = [paths]
        if paths:
            QtCore.QTimer.singleShot(0, lambda: [self.open(path) for path in paths])

    @property
    def documents(self):
        """Open editors in tab order."""
        return [self._owners[self.tabs.widget(i)] for i in range(self.tabs.count())]

    def _action(self, text, slot, shortcut=None, checkable=False, enabled=True):
        """shortcut: a key string, an '@StandardKey' name, or a list of them (the first one is shown)."""
        action = QAction(text, self)
        action.triggered.connect(lambda *_: slot())
        sequences = key_sequences(shortcut)
        if sequences:
            action.setShortcuts(sequences)
            action.setShortcutContext(Qt.WindowShortcut)
            action.setToolTip(f"{text} ({sequences[0].toString(QtGui.QKeySequence.NativeText)})")
        action.setCheckable(checkable)
        action.setEnabled(enabled)
        self.addAction(action)
        return action

    def _build_ui(self):
        t = self.tr_
        editor = self.editor
        if self._panel_owner is not None:
            self._panel_owner.store_panel()
            self._panel_owner.panel_alive = False
            self._panel_owner = None
        for action in self.actions():
            self.removeAction(action)
        if self.toolbar:
            self.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
        if self.dock:
            self.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.menuBar().clear()

        file_menu = self.menuBar().addMenu(t("menu_file"))
        open_ = self._action(t("open"), self.open_dialog, "@Open")
        save = self._action(t("save"), self.save, "@Save", enabled=editor is not None)
        file_menu.addAction(self._action(t("new_voxel"), self.new_voxel_map, "@New"))
        file_menu.addAction(self._action(t("new_grid"), self.new_grid, "Ctrl+Shift+N"))
        file_menu.addActions([open_, save, self._action(t("save_as"), self.save_as, ["@SaveAs", "Ctrl+Shift+S"],
                                                        enabled=editor is not None)])
        file_menu.addAction(self._action(t("close_tab"), lambda: editor and self.close_document(editor), ["@Close", "Ctrl+W"],
                                         enabled=editor is not None))
        file_menu.addSeparator()
        self.backup_action = self._action(t("backup"), self._toggle_backup, checkable=True)
        self.backup_action.setChecked(self.settings.value("backup", "true") in (True, "true"))
        file_menu.addAction(self.backup_action)
        file_menu.addAction(self._action(t("screenshot"), self.save_screenshot, enabled=editor is not None))
        file_menu.addSeparator()
        file_menu.addAction(self._action(t("quit"), self.close, ["@Quit", "Ctrl+Q"]))

        edit_menu = self.menuBar().addMenu(t("menu_edit"))
        undo = self._action(t("undo"), lambda: editor and editor.undo(), "@Undo", enabled=editor is not None)
        redo = self._action(t("redo"), lambda: editor and editor.redo(), ["@Redo", "Ctrl+Y", "Ctrl+Shift+Z"],
                            enabled=editor is not None)
        edit_menu.addActions([undo, redo])
        selection = editor.selection_actions() if editor else {}
        if selection:
            edit_menu.addSeparator()
            for key, label, shortcut in (("delete", "delete_selection", ["Delete", "Backspace"]),
                                         ("select_all", "select_all", "@SelectAll"),
                                         ("invert", "invert_selection", "Ctrl+Shift+I"),
                                         ("clear", "clear_selection", ["Ctrl+D", "Escape", "@Deselect"])):
                edit_menu.addAction(self._action(t(label), selection[key], shortcut))
        extras = [self._action(label, slot, shortcut) for label, shortcut, slot in (editor.extra_actions() if editor else [])]
        if extras:
            edit_menu.addSeparator()
            edit_menu.addActions(extras)

        view_menu = self.menuBar().addMenu(t("menu_view"))
        view_actions = [self._action(label, slot, shortcut) for label, slot, shortcut in (editor.view_actions() if editor else [])]
        view_menu.addActions(view_actions)
        if editor:
            view_menu.addSeparator()
            view_menu.addAction(self._action(t("zoom_in"), lambda: editor.zoom(1.25), ["@ZoomIn", "Ctrl+="]))
            view_menu.addAction(self._action(t("zoom_out"), lambda: editor.zoom(0.8), "@ZoomOut"))
        view_menu.addAction(self._action(t("full_screen"), self.toggle_full_screen, ["@FullScreen", "F11"]))
        view_menu.addSeparator()
        several = self.tabs.count() > 1
        view_menu.addAction(self._action(t("next_tab"), lambda: self._step_tab(1), ["@NextChild", "Ctrl+PgDown"],
                                         enabled=several))
        view_menu.addAction(self._action(t("previous_tab"), lambda: self._step_tab(-1), ["@PreviousChild", "Ctrl+PgUp"],
                                         enabled=several))

        convert_menu = self.menuBar().addMenu(t("menu_convert"))
        for label, make in (editor.conversions() if editor else []):
            convert_menu.addAction(self._action(label, lambda m=make: self.convert(m)))
        convert_menu.setEnabled(bool(editor and editor.conversions()))

        language_menu = self.menuBar().addMenu(t("menu_language"))
        group = QActionGroup(self)
        for code, name in LANGUAGES.items():
            action = self._action(name, lambda c=code: self.set_language(c), checkable=True)
            action.setChecked(code == t.language)
            group.addAction(action)
            language_menu.addAction(action)

        help_menu = self.menuBar().addMenu(t("menu_help"))
        help_menu.addAction(self._action(t("controls"), self.show_controls, ["@HelpContents", "F1"]))
        help_menu.addAction(self._action(t("about"), lambda: QtWidgets.QMessageBox.about(
            self, "MapBarber", t("about_text", version=__version__))))

        self.toolbar = self.addToolBar("main")
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toolbar.setIconSize(QtCore.QSize(18, 18))
        for action, name in ((open_, "open"), (save, "save"), (undo, "undo"), (redo, "redo")):
            action.setIcon(icons.icon(name))
        self.toolbar.addActions([open_, save, undo, redo])
        self.tool_actions = {}
        if editor:
            self.toolbar.addSeparator()
            tools = QActionGroup(self)
            for name, key in editor.tools:
                action = self._action(editor.tool_label(name), lambda n=name: self.set_tool(n), key, checkable=True)
                action.setIcon(icons.icon(f"tool_{name}"))
                tools.addAction(action)
                self.tool_actions[name] = action
                self.toolbar.addAction(action)
            self.tool_actions[editor.tool].setChecked(True)
            self.toolbar.addSeparator()
            self.toolbar.addActions(view_actions)

            self.dock = QtWidgets.QDockWidget(t(f"kind_{editor.kind}"), self)
            self.dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidget(editor.build_panel())
            editor.panel_alive = True
            self._panel_owner = editor
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(320)
            self.dock.setWidget(scroll)
            self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self._build_welcome()
        self.document_changed()

    def _build_welcome(self):
        t = self.tr_
        old = self.welcome.layout()
        if old is not None:
            QtWidgets.QWidget().setLayout(old)
        layout = QtWidgets.QVBoxLayout(self.welcome)
        layout.addStretch(1)
        logo = QtWidgets.QLabel()
        logo.setPixmap(QtGui.QIcon(ICON).pixmap(128, 128))
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)
        title = QtWidgets.QLabel("MapBarber")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 34px; font-weight: 600;")
        layout.addWidget(title)
        subtitle = QtWidgets.QLabel(t("welcome_text"))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: gray; font-size: 14px;")
        layout.addWidget(subtitle)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        for label, slot in ((t("open"), self.open_dialog), (t("new_voxel"), self.new_voxel_map), (t("new_grid"), self.new_grid)):
            widget = QtWidgets.QPushButton(label)
            widget.setMinimumSize(180, 42)
            widget.clicked.connect(slot)
            row.addWidget(widget)
        row.addStretch(1)
        layout.addSpacing(18)
        layout.addLayout(row)
        layout.addStretch(2)

    def set_language(self, code):
        self.tr_ = Translator(code)
        self.settings.setValue("language", code)
        self._build_ui()

    def toggle_full_screen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _toggle_backup(self):
        self.settings.setValue("backup", "true" if self.backup_action.isChecked() else "false")

    def set_tool(self, name):
        if self.editor:
            self.editor.set_tool(name)
            self.tool_actions[name].setChecked(True)

    def show_controls(self):
        key = f"controls_{self.editor.kind}" if self.editor else "controls_general"
        QtWidgets.QMessageBox.information(self, self.tr_("controls"), self.tr_(key))

    def _title(self, editor):
        name = os.path.basename(editor.path) if editor.path else self.tr_("untitled")
        return f"{name}{' *' if editor.dirty else ''}"

    def document_changed(self, editor=None):
        editor = editor or self.editor
        if editor is not None:
            index = self.tabs.indexOf(editor.widget)
            if index >= 0:
                self.tabs.setTabText(index, self._title(editor))
                self.tabs.setTabToolTip(index, f"{editor.path or self.tr_('untitled')}\n{self.tr_('kind_' + editor.kind)}")
        if self.editor is None:
            self.counts.setText("")
            self.setWindowTitle("MapBarber")
            return
        if editor is self.editor:
            self.counts.setText(editor.summary())
            self.setWindowTitle(f"{self._title(editor)} [{self.tr_('kind_' + editor.kind)}] — MapBarber")

    def _tab_changed(self, index):
        self.editor = self._owners.get(self.tabs.widget(index)) if index >= 0 else None
        self.stack.setCurrentWidget(self.tabs if self.editor else self.welcome)
        self._build_ui()
        if self.editor is not None:
            self.editor.set_tool(self.editor.tool)
        for document in self.documents:
            self.document_changed(document)

    def _step_tab(self, step):
        if self.tabs.count() > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def _add_document(self, editor):
        self._owners[editor.widget] = editor
        self.tabs.blockSignals(True)
        index = self.tabs.addTab(editor.widget, self._title(editor))
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        self._tab_changed(index)
        editor.activate()
        self.document_changed(editor)

    def _dispose(self, editor):
        if hasattr(editor, "viewport"):
            editor.viewport.widget.Finalize()
        self._owners.pop(editor.widget, None)
        editor.widget.deleteLater()

    def close_document(self, editor, ask=True):
        """Close one tab; returns False when the user kept it open."""
        if ask and editor.dirty:
            name = os.path.basename(editor.path) if editor.path else self.tr_("untitled")
            answer = QtWidgets.QMessageBox.question(self, self.tr_("unsaved_title"), self.tr_("unsaved_tab_text", name=name))
            if answer != QtWidgets.QMessageBox.Yes:
                return False
        if self._panel_owner is editor:
            editor.panel_alive = False
            self._panel_owner = None
        index = self.tabs.indexOf(editor.widget)
        self.tabs.removeTab(index)
        self._dispose(editor)
        return True

    def close_all(self, ask=True):
        dirty = [d for d in self.documents if d.dirty]
        if ask and dirty:
            names = ", ".join(os.path.basename(d.path) if d.path else self.tr_("untitled") for d in dirty)
            answer = QtWidgets.QMessageBox.question(self, self.tr_("unsaved_title"), self.tr_("unsaved_all_text", names=names))
            if answer != QtWidgets.QMessageBox.Yes:
                return False
        for document in self.documents:
            self.close_document(document, ask=False)
        return True

    def show_document(self, kind, payload):
        """Open data that is not (yet) a file in a new tab."""
        editor = EDITORS[kind](self)
        editor.widget.hide()
        editor.set_document(payload)
        self._add_document(editor)
        return editor

    def open(self, path):
        """Detect what the file holds and open it in a new tab (or switch to it); returns False on failure."""
        path = os.path.abspath(path)
        for document in self.documents:
            if document.path == path:
                self.tabs.setCurrentWidget(document.widget)
                return True
        editor = None
        try:
            kind = formats.kind(path)
            editor = EDITORS[kind](self)
            editor.widget.hide()
            editor.load(path)
        except Exception as error:
            if editor is not None:
                self._dispose(editor)
            QtWidgets.QMessageBox.critical(self, self.tr_("open_failed"), f"{path}\n\n{error}")
            return False
        editor.path = path
        self.settings.setValue("directory", os.path.dirname(path))
        self._add_document(editor)
        self.statusBar().showMessage(self.tr_("status_opened", path=path, kind=self.tr_("kind_" + kind)), 8000)
        return True

    def _directory(self):
        if self.editor and self.editor.path:
            return os.path.dirname(self.editor.path)
        return str(self.settings.value("directory") or os.getcwd())

    def open_dialog(self):
        t = self.tr_
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, t("open"), self._directory(), f"{t('filter_maps')} ({formats.OPEN_PATTERNS});;{t('filter_all')} (*)")
        for path in paths:
            self.open(path)

    def new_voxel_map(self):
        answer = ask_numbers(self, self.tr_("new_voxel"), [(self.tr_("voxel_size_new"), 0.05, 1e-4, 1e3, 4)])
        if answer:
            self.show_document(VOXEL, (EMPTY, answer[0]))
            self.set_tool("add")

    def new_grid(self):
        t = self.tr_
        answer = ask_numbers(self, t("new_grid"), [(t("grid_width"), 200, 1, 20000, 0), (t("grid_height"), 200, 1, 20000, 0),
                                                   (t("resolution_label"), 0.05, 1e-4, 100.0, 4)])
        if answer:
            import numpy as np
            width, height, resolution = int(answer[0]), int(answer[1]), answer[2]
            self.show_document(GRID, GridMap(np.full((height, width), UNKNOWN, np.uint8), resolution))
            self.set_tool("pen")

    def convert(self, make):
        result = make()
        if result is None:
            return
        source = self.tr_("kind_" + self.editor.kind)
        kind, payload = result
        self.show_document(kind, payload)
        self.statusBar().showMessage(self.tr_("status_converted", source=source, kind=self.tr_("kind_" + kind)), 10000)

    def save(self):
        editor = self.editor
        if editor is None:
            return False
        if editor.path is None:
            return self.save_as()
        if not editor.dirty:
            self.statusBar().showMessage(self.tr_("status_nothing_to_save"), 5000)
            return True
        return self.write(editor.path, editor.format)

    def save_as(self):
        editor = self.editor
        if editor is None:
            return False
        filters = ";;".join(f"{label} (*.{ext})" for label, ext in editor.export_filters)
        default = {VOXEL: "map.bt", CLOUD: "cloud.pcd", GRID: "map.yaml"}[editor.kind]
        start = editor.path or os.path.join(self._directory(), default)
        path, chosen = QtWidgets.QFileDialog.getSaveFileName(self, self.tr_("save_as"), start, filters)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += "." + chosen.rsplit("*.", 1)[-1].rstrip(")")
        return self.write(path, None)

    def write(self, path, fmt):
        t = self.tr_
        editor = self.editor
        notes = []
        try:
            if os.path.exists(path) and self.backup_action.isChecked():
                backup = f"{path}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
                shutil.copy2(path, backup)
                notes.append(t("status_backup", name=os.path.basename(backup)))
            editor.save(path, fmt)
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, t("save_failed"), f"{path}\n\n{error}")
            return False
        editor.path, editor.format = os.path.abspath(path), fmt or formats.detect(path)
        self.settings.setValue("directory", os.path.dirname(editor.path))
        self.document_changed()
        notes.insert(0, t("status_saved", path=editor.path))
        self.statusBar().showMessage("  ·  ".join(notes), 10000)
        return True

    def capture(self):
        """The whole window as a QImage, including the 3D view."""
        image = self.grab().toImage()
        if self.editor is not None:
            view = self.editor.capture()
            if view is not None:
                painter = QtGui.QPainter(image)
                corner = self.editor.widget.mapTo(self, QtCore.QPoint(0, 0))
                ratio = image.devicePixelRatio()
                painter.drawImage(QtCore.QRectF(corner.x(), corner.y(), view.width() / ratio, view.height() / ratio), view)
                painter.end()
        return image

    def save_screenshot(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, self.tr_("screenshot"),
                                                        os.path.join(self._directory(), "screenshot.png"), "PNG (*.png)")
        if path:
            self.capture().save(path)

    def closeEvent(self, event):
        if self.close_all():
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for path in [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]:
            self.open(path)


def launch(paths=None, language=None):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["mapbarber"])
    app.setApplicationName("MapBarber")
    app.setWindowIcon(QtGui.QIcon(ICON))
    window = Workbench(paths, language)
    window.show()
    return app, window


def main(paths=None, language=None):
    app, _window = launch(paths, language)
    return run(app)
