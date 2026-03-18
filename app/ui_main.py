from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .export import export_multi_weapon_config, repo_root, suggest_output_path
from .io_params import document_from_json, load_params, save_params, serialize_document
from .models import ParameterDocument, WeaponProfile
from .trajectory import apply_delta, cumulative_path, scale_factors, scale_rows, scaled_step_series, shot_numbers, smooth_rows


def make_spinbox(*, minimum: int = -1_000_000, maximum: int = 5_000_000) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(1)
    return box


GUIDE_TEXT = """快速上手

1. 左侧先选武器
   建议先从 AK 之类最常调的武器开始，不要一上来同时改很多把。

2. 看两张图
   上图“每发步进”：看第 N 发单独输出多少 X / Y。
   下图“累计轨迹”：看 30 发累加后的整体轨迹。

3. 怎么调 X
   X 负责左右补偿。
   选中几发后，用“X +1 / X -1”做小改。
   要整体加大或减小一段左右补偿，用“缩放 X”。

4. 怎么调 Y
   Y 负责纵向补偿。
   建议先调前 5 到 10 发，再调中后段。
   小改用“Y +1 / Y -1”，大改用“缩放 Y”。

5. 什么时候用平滑
   某一段忽高忽低、不够顺的时候，用“平滑 X / 平滑 Y”。
   平滑更适合处理中段和后段，不建议一开始就把全表都平滑。

6. 怎么拖轨迹点
   在下方“累计轨迹”里直接拖某一发的点。
   拖第 N 发，只会改第 N 发的 X / Y 步进，但后续累计轨迹会一起移动。
   这很适合做局部修正。

7. 基准和对比
   “设为基准”会记录当前状态。
   之后虚线是基准，实线是当前，方便比较改动前后差异。

8. 撤销和重做
   如果改崩了，直接点“撤销”。
   表格编辑、批量操作、倍率修改、拖轨迹点都支持撤销 / 重做。

9. 选择规则
   先选中表格中的几发，再点批量按钮，就只修改选中的发数。
   如果表格里没有选中任何行，批量操作会默认作用于全部 30 发。

10. 推荐调参顺序
   先“设为基准”
   先调 Y，再调 X
   先调前段，再调后段
   大改先用“缩放”，细调再用“+1/-1”或拖点

11. 导出
   调完先保存参数，再点“导出 JSON”。
   导出的文件可以继续导入 HID Remapper。
"""


class DraggablePathItem(pg.GraphItem):
    def __init__(self, on_commit) -> None:
        super().__init__()
        self._on_commit = on_commit
        self._data: dict[str, object] = {}
        self._base_positions: np.ndarray | None = None
        self._drag_index: int | None = None
        self._drag_offset: np.ndarray | None = None

    def set_path(
        self,
        positions: np.ndarray,
        *,
        brushes: list[pg.QtGui.QBrush],
        sizes: list[float],
    ) -> None:
        count = positions.shape[0]
        adjacency = (
            np.column_stack((np.arange(count - 1, dtype=int), np.arange(1, count, dtype=int)))
            if count > 1
            else np.empty((0, 2), dtype=int)
        )
        self._data = {
            "pos": positions.copy(),
            "adj": adjacency,
            "data": np.arange(count, dtype=int),
            "symbol": "o",
            "size": np.array(sizes, dtype=float),
            "pxMode": True,
            "pen": pg.mkPen("#57606a", width=2),
            "symbolPen": pg.mkPen("#1f2328", width=0.8),
            "symbolBrush": brushes,
        }
        self._apply_data()

    def _apply_data(self) -> None:
        pg.GraphItem.setData(self, **self._data)

    def mouseDragEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return

        if ev.isStart():
            points = self.scatter.pointsAt(ev.buttonDownPos())
            if not points:
                ev.ignore()
                return
            index = int(points[0].data())
            if index == 0:
                ev.ignore()
                return
            self._drag_index = index
            self._base_positions = np.array(self._data["pos"], copy=True)
            start_pos = ev.buttonDownPos()
            self._drag_offset = self._base_positions[index] - np.array([start_pos.x(), start_pos.y()], dtype=float)
        elif ev.isFinish():
            if self._drag_index is None or self._base_positions is None:
                ev.ignore()
                return
            final_positions = np.array(self._data["pos"], copy=True)
            delta = final_positions[self._drag_index] - self._base_positions[self._drag_index]
            shot_index = self._drag_index - 1
            self._drag_index = None
            self._drag_offset = None
            self._base_positions = None
            ev.accept()
            self._on_commit(shot_index, float(delta[0]), float(delta[1]))
            return
        else:
            if self._drag_index is None or self._base_positions is None or self._drag_offset is None:
                ev.ignore()
                return

        if self._drag_index is None or self._base_positions is None or self._drag_offset is None:
            ev.ignore()
            return

        cursor = ev.pos()
        new_position = np.array([cursor.x(), cursor.y()], dtype=float) + self._drag_offset
        delta = new_position - self._base_positions[self._drag_index]
        preview = np.array(self._base_positions, copy=True)
        preview[self._drag_index :] += delta
        self._data["pos"] = preview
        self._apply_data()
        ev.accept()


class EditablePathPlot(pg.PlotWidget):
    def __init__(self, *, on_commit) -> None:
        super().__init__()
        self._baseline_curve = pg.PlotCurveItem(pen=pg.mkPen("#8b949e", width=1.5, style=Qt.PenStyle.DashLine))
        self.addItem(self._baseline_curve)
        self._path_item = DraggablePathItem(on_commit=on_commit)
        self.addItem(self._path_item)
        self.setLabel("bottom", "累计 X")
        self.setLabel("left", "累计 Y")
        self.showGrid(x=True, y=True, alpha=0.2)
        self.getPlotItem().invertY(True)
        self.setToolTip("拖动某一发的轨迹点，可以直接调整这一发的 X/Y 步进。")

    def set_path_data(self, path_x: list[float], path_y: list[float], *, highlighted_rows: list[int]) -> None:
        if not path_x or not path_y or len(path_x) != len(path_y):
            self.clear_path()
            return

        positions = np.column_stack((np.array(path_x, dtype=float), np.array(path_y, dtype=float)))
        brushes: list[pg.QtGui.QBrush] = []
        sizes: list[float] = []
        highlighted = set(highlighted_rows)
        for index in range(len(positions)):
            if index == 0:
                brushes.append(pg.mkBrush("#cf222e"))
                sizes.append(10.0)
            elif (index - 1) in highlighted:
                brushes.append(pg.mkBrush("#1f6feb"))
                sizes.append(11.0)
            else:
                brushes.append(pg.mkBrush("#2da44e"))
                sizes.append(8.0)

        self._path_item.set_path(positions, brushes=brushes, sizes=sizes)
        self.enableAutoRange(axis="xy", enable=True)

    def clear_path(self) -> None:
        self._path_item.set_path(np.empty((0, 2), dtype=float), brushes=[], sizes=[])

    def set_baseline_path(self, path_x: list[float], path_y: list[float]) -> None:
        self._baseline_curve.setData(path_x, path_y)

    def clear_baseline(self) -> None:
        self._baseline_curve.setData([], [])


class TrajectoryWorkbench(QMainWindow):
    def __init__(self, *, initial_path: Path | None = None) -> None:
        super().__init__()
        self.document: ParameterDocument | None = None
        self.current_weapon_index = -1
        self._loading_ui = False
        self._dirty = False
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._saved_snapshot: str | None = None
        self._baseline_snapshot: str | None = None

        self.setWindowTitle("压枪轨迹工作台")
        self.resize(1680, 980)

        self._build_actions()
        self._build_ui()
        self._wire_signals()
        self._load_initial_document(initial_path)

    def _build_actions(self) -> None:
        toolbar = self.addToolBar("主工具栏")
        toolbar.setMovable(False)

        self.open_action = QAction("打开", self)
        self.undo_action = QAction("撤销", self)
        self.redo_action = QAction("重做", self)
        self.set_baseline_action = QAction("设为基准", self)
        self.clear_baseline_action = QAction("清除基准", self)
        self.guide_action = QAction("使用说明", self)
        self.save_action = QAction("保存", self)
        self.save_as_action = QAction("另存为", self)
        self.export_action = QAction("导出 JSON", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)

        toolbar.addAction(self.open_action)
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.guide_action)
        toolbar.addSeparator()
        toolbar.addAction(self.set_baseline_action)
        toolbar.addAction(self.clear_baseline_action)
        toolbar.addSeparator()
        toolbar.addAction(self.save_action)
        toolbar.addAction(self.save_as_action)
        toolbar.addSeparator()
        toolbar.addAction(self.export_action)
        self._update_history_actions()
        self._update_baseline_actions()

    def _build_ui(self) -> None:
        self.file_label = QLabel("尚未打开参数文件")
        self.file_label.setWordWrap(True)

        self.weapon_list = QListWidget()

        self.base_mult_box = make_spinbox(minimum=0)
        self.fov_comp_box = make_spinbox(minimum=0)
        self.tune_mult_x_box = make_spinbox(minimum=0)
        self.tune_mult_y_box = make_spinbox(minimum=0)

        global_group = QGroupBox("全局预览")
        global_form = QFormLayout(global_group)
        global_form.addRow("基础倍率", self.base_mult_box)
        global_form.addRow("FOV 补偿", self.fov_comp_box)
        global_form.addRow("X 微调倍率", self.tune_mult_x_box)
        global_form.addRow("Y 微调倍率", self.tune_mult_y_box)

        self.scope_mode_combo = QComboBox()
        self.scope_mode_combo.addItem("1倍镜", "1x")
        self.scope_mode_combo.addItem("8倍镜", "8x")
        self.stance_mode_combo = QComboBox()
        self.stance_mode_combo.addItem("站立", "stand")
        self.stance_mode_combo.addItem("蹲下", "crouch")

        preview_group = QGroupBox("预览条件")
        preview_form = QFormLayout(preview_group)
        preview_form.addRow("镜倍", self.scope_mode_combo)
        preview_form.addRow("姿态", self.stance_mode_combo)

        guide_group = QGroupBox("快速上手")
        guide_layout = QVBoxLayout(guide_group)
        self.guide_text = QPlainTextEdit()
        self.guide_text.setReadOnly(True)
        self.guide_text.setPlainText(GUIDE_TEXT)
        self.guide_text.setMinimumHeight(220)
        self.guide_text.setMaximumHeight(280)
        guide_layout.addWidget(self.guide_text)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self.file_label)
        left_layout.addWidget(QLabel("武器列表"))
        left_layout.addWidget(self.weapon_list, 1)
        left_layout.addWidget(global_group)
        left_layout.addWidget(preview_group)
        left_layout.addWidget(guide_group)

        self.delta_plot = pg.PlotWidget()
        self.delta_plot.setLabel("bottom", "第几发")
        self.delta_plot.setLabel("left", "步进值")
        self.delta_plot.showGrid(x=True, y=True, alpha=0.2)

        self.path_plot = EditablePathPlot(on_commit=self._commit_path_drag)

        plots_splitter = QSplitter(Qt.Orientation.Vertical)
        plots_splitter.addWidget(self.delta_plot)
        plots_splitter.addWidget(self.path_plot)
        plots_splitter.setStretchFactor(0, 1)
        plots_splitter.setStretchFactor(1, 1)

        self.weapon_name_edit = QLineEdit()
        self.weapon_id_box = make_spinbox(minimum=1, maximum=999)
        self.select_usage_edit = QLineEdit()
        self.select_usage_edit.setReadOnly(True)
        self.shot_interval_box = make_spinbox(minimum=1)
        self.start_delay_box = make_spinbox(minimum=0)
        self.attack_box = make_spinbox(minimum=1)
        self.scope_1x_box = make_spinbox(minimum=0)
        self.scope_8x_box = make_spinbox(minimum=0)
        self.stand_mult_box = make_spinbox(minimum=0)
        self.crouch_mult_box = make_spinbox(minimum=0)

        weapon_group = QGroupBox("武器参数")
        weapon_form = QFormLayout(weapon_group)
        weapon_form.addRow("名称", self.weapon_name_edit)
        weapon_form.addRow("ID", self.weapon_id_box)
        weapon_form.addRow("选择键 Usage", self.select_usage_edit)
        weapon_form.addRow("射击间隔", self.shot_interval_box)
        weapon_form.addRow("起始延迟", self.start_delay_box)
        weapon_form.addRow("攻击窗口", self.attack_box)
        weapon_form.addRow("1倍镜倍率", self.scope_1x_box)
        weapon_form.addRow("8倍镜倍率", self.scope_8x_box)
        weapon_form.addRow("站立倍率", self.stand_mult_box)
        weapon_form.addRow("蹲下倍率", self.crouch_mult_box)

        self.step_table = QTableWidget(30, 3)
        self.step_table.setHorizontalHeaderLabels(["第几发", "X", "Y"])
        self.step_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.step_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.step_table.verticalHeader().setVisible(False)
        self.step_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.step_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.step_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.x_plus_button = QPushButton("X +1")
        self.x_minus_button = QPushButton("X -1")
        self.y_plus_button = QPushButton("Y +1")
        self.y_minus_button = QPushButton("Y -1")
        self.smooth_x_button = QPushButton("平滑 X")
        self.smooth_y_button = QPushButton("平滑 Y")
        self.scale_x_button = QPushButton("缩放 X")
        self.scale_y_button = QPushButton("缩放 Y")

        batch_group = QGroupBox("批量操作")
        batch_layout = QGridLayout(batch_group)
        batch_layout.addWidget(self.x_plus_button, 0, 0)
        batch_layout.addWidget(self.x_minus_button, 0, 1)
        batch_layout.addWidget(self.y_plus_button, 1, 0)
        batch_layout.addWidget(self.y_minus_button, 1, 1)
        batch_layout.addWidget(self.smooth_x_button, 2, 0)
        batch_layout.addWidget(self.smooth_y_button, 2, 1)
        batch_layout.addWidget(self.scale_x_button, 3, 0)
        batch_layout.addWidget(self.scale_y_button, 3, 1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(weapon_group)
        right_layout.addWidget(QLabel("30 发参数表"))
        right_layout.addWidget(self.step_table, 1)
        right_layout.addWidget(batch_group)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(plots_splitter)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 1)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(main_splitter)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())

    def _wire_signals(self) -> None:
        self.open_action.triggered.connect(self.open_document)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.guide_action.triggered.connect(self.show_usage_guide)
        self.set_baseline_action.triggered.connect(self.set_baseline)
        self.clear_baseline_action.triggered.connect(self.clear_baseline)
        self.save_action.triggered.connect(self.save_document)
        self.save_as_action.triggered.connect(self.save_document_as)
        self.export_action.triggered.connect(self.export_document)

        self.weapon_list.currentRowChanged.connect(self._set_current_weapon)
        self.step_table.itemChanged.connect(self._on_step_item_changed)
        self.step_table.itemSelectionChanged.connect(self.refresh_plots)

        for widget in (
            self.base_mult_box,
            self.fov_comp_box,
            self.tune_mult_x_box,
            self.tune_mult_y_box,
        ):
            widget.valueChanged.connect(self._update_global_from_ui)

        self.scope_mode_combo.currentTextChanged.connect(self.refresh_plots)
        self.stance_mode_combo.currentTextChanged.connect(self.refresh_plots)

        self.weapon_name_edit.editingFinished.connect(self._update_weapon_from_ui)
        for widget in (
            self.weapon_id_box,
            self.shot_interval_box,
            self.start_delay_box,
            self.attack_box,
            self.scope_1x_box,
            self.scope_8x_box,
            self.stand_mult_box,
            self.crouch_mult_box,
        ):
            widget.valueChanged.connect(self._update_weapon_from_ui)

        self.x_plus_button.clicked.connect(lambda: self._adjust_axis("x", 1))
        self.x_minus_button.clicked.connect(lambda: self._adjust_axis("x", -1))
        self.y_plus_button.clicked.connect(lambda: self._adjust_axis("y", 1))
        self.y_minus_button.clicked.connect(lambda: self._adjust_axis("y", -1))
        self.smooth_x_button.clicked.connect(lambda: self._smooth_axis("x"))
        self.smooth_y_button.clicked.connect(lambda: self._smooth_axis("y"))
        self.scale_x_button.clicked.connect(lambda: self._scale_axis("x"))
        self.scale_y_button.clicked.connect(lambda: self._scale_axis("y"))

    def _load_initial_document(self, initial_path: Path | None) -> None:
        default_path = repo_root() / "data" / "params" / "wk.json"
        target = initial_path or (default_path if default_path.exists() else None)
        if target is not None:
            self.load_document(target)

    def current_weapon(self) -> WeaponProfile | None:
        if self.document is None:
            return None
        if self.current_weapon_index < 0 or self.current_weapon_index >= len(self.document.weapons):
            return None
        return self.document.weapons[self.current_weapon_index]

    def selected_rows(self) -> list[int]:
        rows = sorted({index.row() for index in self.step_table.selectionModel().selectedRows()})
        if not rows:
            return list(range(30))
        return rows

    def highlighted_rows(self) -> list[int]:
        return sorted({index.row() for index in self.step_table.selectionModel().selectedRows()})

    def mark_dirty(self) -> None:
        self._sync_dirty_state()

    def clear_dirty(self) -> None:
        self._dirty = False
        self._refresh_title()

    def _snapshot_string(self) -> str | None:
        if self.document is None:
            return None
        return serialize_document(self.document)

    def _sync_dirty_state(self) -> None:
        current = self._snapshot_string()
        self._dirty = bool(current is not None and self._saved_snapshot is not None and current != self._saved_snapshot)
        self._refresh_title()

    def _update_history_actions(self) -> None:
        self.undo_action.setEnabled(bool(self._undo_stack))
        self.redo_action.setEnabled(bool(self._redo_stack))

    def _update_baseline_actions(self) -> None:
        has_document = self.document is not None
        self.set_baseline_action.setEnabled(has_document)
        self.clear_baseline_action.setEnabled(self._baseline_snapshot is not None)

    def _record_history_state(self) -> None:
        snapshot = self._snapshot_string()
        if snapshot is None:
            return
        if self._undo_stack and self._undo_stack[-1] == snapshot:
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > 200:
            self._undo_stack = self._undo_stack[-200:]
        self._redo_stack.clear()
        self._update_history_actions()

    def _reset_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._saved_snapshot = self._snapshot_string()
        self.clear_dirty()
        self._update_history_actions()

    def set_baseline(self) -> None:
        snapshot = self._snapshot_string()
        if snapshot is None:
            return
        self._baseline_snapshot = snapshot
        self._update_baseline_actions()
        self.refresh_plots()
        self.statusBar().showMessage("已记录当前基准轨迹。", 3000)

    def show_usage_guide(self) -> None:
        QMessageBox.information(self, "使用说明", GUIDE_TEXT)

    def clear_baseline(self) -> None:
        self._baseline_snapshot = None
        self._update_baseline_actions()
        self.refresh_plots()
        self.statusBar().showMessage("已清除基准轨迹。", 3000)

    def current_scope_mode(self) -> str:
        return str(self.scope_mode_combo.currentData() or "1x")

    def current_stance_mode(self) -> str:
        return str(self.stance_mode_combo.currentData() or "stand")

    def _apply_document_to_ui(self, document: ParameterDocument, *, preferred_index: int | None = None) -> None:
        self.document = document
        target_index = preferred_index if preferred_index is not None else self.current_weapon_index
        self.current_weapon_index = -1
        self._loading_ui = True
        self.weapon_list.clear()
        for weapon in document.weapons:
            self.weapon_list.addItem(f"{weapon.weapon_id}. {weapon.name}")
        self.base_mult_box.setValue(document.global_config.base_mult)
        self.fov_comp_box.setValue(document.global_config.fov_comp)
        self.tune_mult_x_box.setValue(document.global_config.tune_mult_x)
        self.tune_mult_y_box.setValue(document.global_config.tune_mult_y)
        self.file_label.setText(str(document.path) if document.path else "未保存的参数文件")
        self._loading_ui = False

        if document.weapons:
            safe_index = min(max(target_index if target_index is not None else 0, 0), len(document.weapons) - 1)
            self.weapon_list.setCurrentRow(safe_index)
        else:
            self.refresh_plots()

    def _restore_snapshot(self, snapshot: str) -> None:
        current_path = self.document.path if self.document else None
        restored = document_from_json(snapshot, path=current_path)
        current_index = self.current_weapon_index
        self._apply_document_to_ui(restored, preferred_index=current_index)
        self._sync_dirty_state()
        self._update_history_actions()

    def undo(self) -> None:
        if self.document is None or not self._undo_stack:
            return
        current = self._snapshot_string()
        if current is None:
            return
        self._redo_stack.append(current)
        snapshot = self._undo_stack.pop()
        self._restore_snapshot(snapshot)
        self.statusBar().showMessage("已撤销。", 2000)

    def redo(self) -> None:
        if self.document is None or not self._redo_stack:
            return
        current = self._snapshot_string()
        if current is None:
            return
        self._undo_stack.append(current)
        snapshot = self._redo_stack.pop()
        self._restore_snapshot(snapshot)
        self.statusBar().showMessage("已重做。", 2000)

    def _refresh_title(self) -> None:
        suffix = ""
        if self.document and self.document.path:
            suffix = f" - {self.document.path.name}"
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"压枪轨迹工作台{suffix}{dirty}")

    def load_document(self, path: Path) -> None:
        try:
            document = load_params(path)
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))
            return

        self._baseline_snapshot = None
        self._apply_document_to_ui(document, preferred_index=0)
        self._reset_history()
        self._update_baseline_actions()
        self.statusBar().showMessage(f"已加载：{path}", 4000)

    def open_document(self) -> None:
        start_dir = repo_root() / "data" / "params"
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "打开参数文件",
            str(start_dir),
            "JSON 文件 (*.json)",
        )
        if file_name:
            self.load_document(Path(file_name))

    def save_document(self) -> None:
        if self.document is None:
            return
        if self.document.path is None:
            self.save_document_as()
            return
        try:
            out_path = save_params(self.document)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.file_label.setText(str(out_path))
        self._saved_snapshot = self._snapshot_string()
        self._sync_dirty_state()
        self.statusBar().showMessage(f"已保存：{out_path}", 4000)

    def save_document_as(self) -> None:
        if self.document is None:
            return
        current_path = self.document.path or (repo_root() / "data" / "params" / "workbench.json")
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "参数另存为",
            str(current_path),
            "JSON 文件 (*.json)",
        )
        if not file_name:
            return
        try:
            out_path = save_params(self.document, Path(file_name))
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.file_label.setText(str(out_path))
        self._saved_snapshot = self._snapshot_string()
        self._sync_dirty_state()
        self.statusBar().showMessage(f"已保存：{out_path}", 4000)

    def export_document(self) -> None:
        if self.document is None:
            return
        if self.document.path is None:
            self.save_document_as()
            if self.document.path is None:
                return
        if self._dirty:
            self.save_document()
            if self._dirty:
                return

        suggested = suggest_output_path(self.document.path)
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "导出 HID 配置",
            str(suggested),
            "JSON 文件 (*.json)",
        )
        if not file_name:
            return

        result = export_multi_weapon_config(self.document.path, Path(file_name))
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "未知导出错误"
            QMessageBox.critical(self, "导出失败", detail)
            return

        detail = result.stdout.strip() or f"已写入：{file_name}"
        QMessageBox.information(self, "导出完成", detail)
        self.statusBar().showMessage(f"已导出：{file_name}", 4000)

    def _set_current_weapon(self, index: int) -> None:
        self.current_weapon_index = index
        weapon = self.current_weapon()
        self._loading_ui = True
        if weapon is None:
            self.weapon_name_edit.clear()
            self.weapon_id_box.setValue(1)
            self.select_usage_edit.clear()
            self.shot_interval_box.setValue(1)
            self.start_delay_box.setValue(0)
            self.attack_box.setValue(1)
            self.scope_1x_box.setValue(0)
            self.scope_8x_box.setValue(0)
            self.stand_mult_box.setValue(0)
            self.crouch_mult_box.setValue(0)
            for row in range(30):
                self.step_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
                self.step_table.setItem(row, 1, QTableWidgetItem("0"))
                self.step_table.setItem(row, 2, QTableWidgetItem("0"))
            self._loading_ui = False
            self.refresh_plots()
            return

        self.weapon_name_edit.setText(weapon.name)
        self.weapon_id_box.setValue(weapon.weapon_id)
        self.select_usage_edit.setText(str(weapon.select_usage))
        self.shot_interval_box.setValue(weapon.shot_interval_us)
        self.start_delay_box.setValue(weapon.start_delay_us)
        self.attack_box.setValue(weapon.attack_us)
        self.scope_1x_box.setValue(weapon.scope_1x_mult)
        self.scope_8x_box.setValue(weapon.scope_8x_mult)
        self.stand_mult_box.setValue(weapon.stand_mult)
        self.crouch_mult_box.setValue(weapon.crouch_mult)
        self._reload_step_table(weapon)
        self._loading_ui = False
        self.refresh_plots()

    def _reload_step_table(self, weapon: WeaponProfile) -> None:
        for row in range(30):
            shot_item = self.step_table.item(row, 0) or QTableWidgetItem()
            shot_item.setText(str(row + 1))
            shot_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.step_table.setItem(row, 0, shot_item)

            x_item = self.step_table.item(row, 1) or QTableWidgetItem()
            x_item.setText(str(weapon.x_steps[row]))
            self.step_table.setItem(row, 1, x_item)

            y_item = self.step_table.item(row, 2) or QTableWidgetItem()
            y_item.setText(str(weapon.y_steps[row]))
            self.step_table.setItem(row, 2, y_item)

    def _on_step_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_ui:
            return
        weapon = self.current_weapon()
        if weapon is None:
            return
        if item.column() not in (1, 2):
            return
        target = weapon.x_steps if item.column() == 1 else weapon.y_steps
        try:
            value = int(item.text(), 0)
        except ValueError:
            self._loading_ui = True
            item.setText(str(target[item.row()]))
            self._loading_ui = False
            return
        if target[item.row()] == value:
            return
        self._record_history_state()
        target[item.row()] = value
        self.mark_dirty()
        self.refresh_plots()

    def _update_global_from_ui(self) -> None:
        if self._loading_ui or self.document is None:
            return
        changed = (
            self.document.global_config.base_mult != self.base_mult_box.value()
            or self.document.global_config.fov_comp != self.fov_comp_box.value()
            or self.document.global_config.tune_mult_x != self.tune_mult_x_box.value()
            or self.document.global_config.tune_mult_y != self.tune_mult_y_box.value()
        )
        if not changed:
            return
        self._record_history_state()
        self.document.global_config.base_mult = self.base_mult_box.value()
        self.document.global_config.fov_comp = self.fov_comp_box.value()
        self.document.global_config.tune_mult_x = self.tune_mult_x_box.value()
        self.document.global_config.tune_mult_y = self.tune_mult_y_box.value()
        self.mark_dirty()
        self.refresh_plots()

    def _update_weapon_from_ui(self) -> None:
        if self._loading_ui:
            return
        weapon = self.current_weapon()
        if weapon is None:
            return
        new_name = self.weapon_name_edit.text().strip() or weapon.name
        changed = (
            weapon.name != new_name
            or weapon.weapon_id != self.weapon_id_box.value()
            or weapon.shot_interval_us != self.shot_interval_box.value()
            or weapon.start_delay_us != self.start_delay_box.value()
            or weapon.attack_us != self.attack_box.value()
            or weapon.scope_1x_mult != self.scope_1x_box.value()
            or weapon.scope_8x_mult != self.scope_8x_box.value()
            or weapon.stand_mult != self.stand_mult_box.value()
            or weapon.crouch_mult != self.crouch_mult_box.value()
        )
        if not changed:
            return
        self._record_history_state()
        weapon.name = new_name
        weapon.weapon_id = self.weapon_id_box.value()
        weapon.shot_interval_us = self.shot_interval_box.value()
        weapon.start_delay_us = self.start_delay_box.value()
        weapon.attack_us = self.attack_box.value()
        weapon.scope_1x_mult = self.scope_1x_box.value()
        weapon.scope_8x_mult = self.scope_8x_box.value()
        weapon.stand_mult = self.stand_mult_box.value()
        weapon.crouch_mult = self.crouch_mult_box.value()
        self.weapon_list.item(self.current_weapon_index).setText(f"{weapon.weapon_id}. {weapon.name}")
        self.mark_dirty()
        self.refresh_plots()

    def _adjust_axis(self, axis: str, delta: int) -> None:
        weapon = self.current_weapon()
        if weapon is None:
            return
        rows = self.selected_rows()
        self._record_history_state()
        if axis == "x":
            weapon.x_steps = apply_delta(weapon.x_steps, rows, delta)
        else:
            weapon.y_steps = apply_delta(weapon.y_steps, rows, delta)
        self._loading_ui = True
        self._reload_step_table(weapon)
        self._loading_ui = False
        self.mark_dirty()
        self.refresh_plots()

    def _smooth_axis(self, axis: str) -> None:
        weapon = self.current_weapon()
        if weapon is None:
            return
        rows = self.selected_rows()
        self._record_history_state()
        if axis == "x":
            weapon.x_steps = smooth_rows(weapon.x_steps, rows)
        else:
            weapon.y_steps = smooth_rows(weapon.y_steps, rows)
        self._loading_ui = True
        self._reload_step_table(weapon)
        self._loading_ui = False
        self.mark_dirty()
        self.refresh_plots()

    def _scale_axis(self, axis: str) -> None:
        weapon = self.current_weapon()
        if weapon is None:
            return
        factor, ok = QInputDialog.getDouble(
            self,
            f"缩放 {axis.upper()}",
            "倍率",
            1.1,
            -10.0,
            10.0,
            2,
        )
        if not ok:
            return
        rows = self.selected_rows()
        self._record_history_state()
        if axis == "x":
            weapon.x_steps = scale_rows(weapon.x_steps, rows, factor)
        else:
            weapon.y_steps = scale_rows(weapon.y_steps, rows, factor)
        self._loading_ui = True
        self._reload_step_table(weapon)
        self._loading_ui = False
        self.mark_dirty()
        self.refresh_plots()

    def _commit_path_drag(self, shot_index: int, delta_x: float, delta_y: float) -> None:
        weapon = self.current_weapon()
        if weapon is None or self.document is None:
            return

        x_scale, y_scale = scale_factors(
            self.document.global_config,
            weapon,
            scope_mode=self.current_scope_mode(),
            stance_mode=self.current_stance_mode(),
        )

        x_delta_steps = int(round(delta_x / x_scale)) if abs(x_scale) > 1e-9 else 0
        y_delta_steps = int(round(delta_y / y_scale)) if abs(y_scale) > 1e-9 else 0

        if x_delta_steps == 0 and y_delta_steps == 0:
            self.refresh_plots()
            self.statusBar().showMessage("拖动幅度太小，没有形成有效修改。", 3000)
            return

        self._record_history_state()
        weapon.x_steps[shot_index] += x_delta_steps
        weapon.y_steps[shot_index] += y_delta_steps

        self._loading_ui = True
        self._reload_step_table(weapon)
        self.step_table.clearSelection()
        self.step_table.selectRow(shot_index)
        self._loading_ui = False

        self.mark_dirty()
        self.refresh_plots()
        self.statusBar().showMessage(
            f"第 {shot_index + 1} 发：X {x_delta_steps:+d}，Y {y_delta_steps:+d}",
            4000,
        )

    def refresh_plots(self) -> None:
        weapon = self.current_weapon()
        self.delta_plot.clear()
        if weapon is None or self.document is None:
            self.path_plot.clear_path()
            self.path_plot.clear_baseline()
            return

        shots = shot_numbers(30)
        selected_rows = self.highlighted_rows()
        selected_shots = [row + 1 for row in selected_rows]
        baseline_weapon: WeaponProfile | None = None
        baseline_doc: ParameterDocument | None = None
        if self._baseline_snapshot is not None and self.document is not None:
            try:
                baseline_doc = document_from_json(self._baseline_snapshot, path=self.document.path)
            except Exception:
                baseline_doc = None
            if baseline_doc is not None and 0 <= self.current_weapon_index < len(baseline_doc.weapons):
                baseline_weapon = baseline_doc.weapons[self.current_weapon_index]

        if baseline_weapon is not None:
            self.delta_plot.plot(
                shots,
                baseline_weapon.x_steps,
                pen=pg.mkPen("#8b949e", width=1.5, style=Qt.PenStyle.DashLine),
            )
            self.delta_plot.plot(
                shots,
                baseline_weapon.y_steps,
                pen=pg.mkPen("#bf8700", width=1.5, style=Qt.PenStyle.DashLine),
            )

        self.delta_plot.plot(
            shots,
            weapon.x_steps,
            pen=pg.mkPen("#1f6feb", width=2),
            symbol="o",
            symbolSize=6,
            symbolBrush="#1f6feb",
        )
        self.delta_plot.plot(
            shots,
            weapon.y_steps,
            pen=pg.mkPen("#d29922", width=2),
            symbol="o",
            symbolSize=6,
            symbolBrush="#d29922",
        )

        if selected_rows:
            self.delta_plot.plot(
                selected_shots,
                [weapon.x_steps[row] for row in selected_rows],
                pen=None,
                symbol="o",
                symbolSize=10,
                symbolBrush="#005cc5",
            )
            self.delta_plot.plot(
                selected_shots,
                [weapon.y_steps[row] for row in selected_rows],
                pen=None,
                symbol="o",
                symbolSize=10,
                symbolBrush="#b08800",
            )

        scaled_x, scaled_y = scaled_step_series(
            self.document.global_config,
            weapon,
            scope_mode=self.current_scope_mode(),
            stance_mode=self.current_stance_mode(),
        )
        path_x, path_y = cumulative_path(scaled_x, scaled_y)
        if baseline_weapon is not None and baseline_doc is not None:
            baseline_scaled_x, baseline_scaled_y = scaled_step_series(
                baseline_doc.global_config,
                baseline_weapon,
                scope_mode=self.current_scope_mode(),
                stance_mode=self.current_stance_mode(),
            )
            baseline_path_x, baseline_path_y = cumulative_path(baseline_scaled_x, baseline_scaled_y)
            self.path_plot.set_baseline_path(baseline_path_x, baseline_path_y)
        else:
            self.path_plot.clear_baseline()
        self.path_plot.set_path_data(path_x, path_y, highlighted_rows=selected_rows)
