"""Main window: recognises what a file contains and hands it to the matching editor."""
import os
import shutil
import time

from . import __version__, formats
from .cloud_editor import CloudEditor
from .formats import CLOUD, GRID, VOXEL
from .grid import UNKNOWN, GridMap
from .grid_editor import GridEditor
from .i18n import LANGUAGES, Translator
from .qt import QAction, QActionGroup, QtCore, QtGui, QtWidgets, run
from .voxel_editor import VoxelEditor
from .voxels import EMPTY
from .widgets import ask_numbers

Qt = QtCore.Qt
EDITORS = {VOXEL: VoxelEditor, CLOUD: CloudEditor, GRID: GridEditor}
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.svg")


class Workbench(QtWidgets.QMainWindow):
    def __init__(self, path=None, language=None):
        super().__init__()
        self.settings = QtCore.QSettings("mapbarber", "mapbarber")
        self.tr_ = Translator(language or self.settings.value("language"))
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.editors = {}
        self.editor = None
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)
        self.welcome = QtWidgets.QWidget()
        self.stack.addWidget(self.welcome)
        self.counts = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.counts)
        self.dock = None
        self.toolbar = None
        self._panel_owner = None
        self._build_ui()
        if path:
            QtCore.QTimer.singleShot(0, lambda: self.open(path))

    def _action(self, text, slot, shortcut=None, checkable=False, enabled=True):
        action = QAction(text, self)
        action.triggered.connect(lambda *_: slot())
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
            action.setShortcutContext(Qt.WindowShortcut)
            action.setToolTip(f"{text} ({shortcut})")
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
        open_ = self._action(t("open"), self.open_dialog, "Ctrl+O")
        save = self._action(t("save"), self.save, "Ctrl+S", enabled=editor is not None)
        file_menu.addAction(self._action(t("new_voxel"), self.new_voxel_map, "Ctrl+N"))
        file_menu.addAction(self._action(t("new_grid"), self.new_grid, "Ctrl+Shift+N"))
        file_menu.addActions([open_, save, self._action(t("save_as"), self.save_as, "Ctrl+Shift+S", enabled=editor is not None)])
        file_menu.addSeparator()
        self.backup_action = self._action(t("backup"), self._toggle_backup, checkable=True)
        self.backup_action.setChecked(self.settings.value("backup", "true") in (True, "true"))
        file_menu.addAction(self.backup_action)
        file_menu.addAction(self._action(t("screenshot"), self.save_screenshot, enabled=editor is not None))
        file_menu.addSeparator()
        file_menu.addAction(self._action(t("quit"), self.close, "Ctrl+Q"))

        edit_menu = self.menuBar().addMenu(t("menu_edit"))
        undo = self._action(t("undo"), lambda: editor and editor.undo(), "Ctrl+Z", enabled=editor is not None)
        redo = self._action(t("redo"), lambda: editor and editor.redo(), "Ctrl+Y", enabled=editor is not None)
        edit_menu.addActions([undo, redo])
        selection = editor.selection_actions() if editor else {}
        if selection:
            edit_menu.addSeparator()
            for key, label, shortcut in (("delete", "delete_selection", "Delete"), ("select_all", "select_all", "Ctrl+A"),
                                         ("invert", "invert_selection", "Ctrl+I"), ("clear", "clear_selection", "Escape")):
                edit_menu.addAction(self._action(t(label), selection[key], shortcut))
        extras = [self._action(label, slot, shortcut) for label, shortcut, slot in (editor.extra_actions() if editor else [])]
        if extras:
            edit_menu.addSeparator()
            edit_menu.addActions(extras)

        view_menu = self.menuBar().addMenu(t("menu_view"))
        view_actions = [self._action(label, slot) for label, slot in (editor.view_actions() if editor else [])]
        view_menu.addActions(view_actions)

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
        help_menu.addAction(self._action(t("controls"), self.show_controls, "F1"))
        help_menu.addAction(self._action(t("about"), lambda: QtWidgets.QMessageBox.about(
            self, "MapBarber", t("about_text", version=__version__))))

        self.toolbar = self.addToolBar("main")
        self.toolbar.setMovable(False)
        self.toolbar.addActions([open_, save, undo, redo])
        self.tool_actions = {}
        if editor:
            self.toolbar.addSeparator()
            tools = QActionGroup(self)
            for name, key in editor.tools:
                action = self._action(f"{key} {editor.tool_label(name)}", lambda n=name: self.set_tool(n), key, checkable=True)
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

    def _toggle_backup(self):
        self.settings.setValue("backup", "true" if self.backup_action.isChecked() else "false")

    def set_tool(self, name):
        if self.editor:
            self.editor.set_tool(name)
            self.tool_actions[name].setChecked(True)

    def show_controls(self):
        key = f"controls_{self.editor.kind}" if self.editor else "controls_general"
        QtWidgets.QMessageBox.information(self, self.tr_("controls"), self.tr_(key))

    def document_changed(self):
        editor = self.editor
        if editor is None:
            self.counts.setText("")
            self.setWindowTitle("MapBarber")
            return
        self.counts.setText(editor.summary())
        name = os.path.basename(editor.path) if editor.path else self.tr_("untitled")
        self.setWindowTitle(f"{'*' if editor.dirty else ''}{name} [{self.tr_('kind_' + editor.kind)}] — MapBarber")

    def _editor_for(self, kind):
        if kind not in self.editors:
            editor = EDITORS[kind](self)
            self.editors[kind] = editor
            self.stack.addWidget(editor.widget)
        return self.editors[kind]

    def show_document(self, kind, payload, path=None, fmt=None):
        editor = self._editor_for(kind)
        if path is None:
            editor.set_document(payload)
        self.editor = editor
        self.stack.setCurrentWidget(editor.widget)
        self._build_ui()
        editor.set_tool(editor.tool)
        editor.activate()
        self.document_changed()

    def open(self, path):
        """Detect what the file holds and open it in the matching editor; returns False on failure."""
        try:
            kind = formats.kind(path)
            editor = self._editor_for(kind)
            editor.load(path)
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, self.tr_("open_failed"), f"{path}\n\n{error}")
            return False
        editor.path = os.path.abspath(path)
        self.settings.setValue("directory", os.path.dirname(editor.path))
        self.show_document(kind, None, editor.path)
        self.statusBar().showMessage(self.tr_("status_opened", path=editor.path, kind=self.tr_("kind_" + kind)), 8000)
        return True

    def _directory(self):
        if self.editor and self.editor.path:
            return os.path.dirname(self.editor.path)
        return str(self.settings.value("directory") or os.getcwd())

    def open_dialog(self):
        if not self.confirm_discard():
            return
        t = self.tr_
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, t("open"), self._directory(), f"{t('filter_maps')} ({formats.OPEN_PATTERNS});;{t('filter_all')} (*)")
        if path:
            self.open(path)

    def new_voxel_map(self):
        if not self.confirm_discard():
            return
        answer = ask_numbers(self, self.tr_("new_voxel"), [(self.tr_("voxel_size_new"), 0.05, 1e-4, 1e3, 4)])
        if answer:
            self.show_document(VOXEL, (EMPTY, answer[0]))
            self.set_tool("add")

    def new_grid(self):
        if not self.confirm_discard():
            return
        t = self.tr_
        answer = ask_numbers(self, t("new_grid"), [(t("grid_width"), 200, 1, 20000, 0), (t("grid_height"), 200, 1, 20000, 0),
                                                   (t("resolution_label"), 0.05, 1e-4, 100.0, 4)])
        if answer:
            import numpy as np
            width, height, resolution = int(answer[0]), int(answer[1]), answer[2]
            self.show_document(GRID, GridMap(np.full((height, width), UNKNOWN, np.uint8), resolution))
            self.set_tool("pen")

    def convert(self, make):
        if not self.confirm_discard():
            return
        result = make()
        if result is None:
            return
        source = self.tr_("kind_" + self.editor.kind)
        kind, payload = result
        self.show_document(kind, payload)
        self.statusBar().showMessage(self.tr_("status_converted", source=source, kind=self.tr_("kind_" + kind)), 10000)

    def confirm_discard(self):
        if self.editor is None or not self.editor.dirty:
            return True
        answer = QtWidgets.QMessageBox.question(self, self.tr_("unsaved_title"), self.tr_("unsaved_text"))
        return answer == QtWidgets.QMessageBox.Yes

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
        if self.confirm_discard():
            for editor in self.editors.values():
                if hasattr(editor, "viewport"):
                    editor.viewport.widget.Finalize()
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files and self.confirm_discard():
            self.open(files[0])


def launch(path=None, language=None):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["mapbarber"])
    app.setApplicationName("MapBarber")
    app.setWindowIcon(QtGui.QIcon(ICON))
    window = Workbench(path, language)
    window.show()
    return app, window


def main(path=None, language=None):
    app, _window = launch(path, language)
    return run(app)
