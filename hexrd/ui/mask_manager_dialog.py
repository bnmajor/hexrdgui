import os
import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import (
    QCheckBox, QFileDialog, QMenu, QPushButton, QTableWidgetItem)
from PySide2.QtGui import QCursor

from hexrd.ui import enter_key_filter

from hexrd.ui.utils import create_unique_name
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.constants import ViewType


class MaskManagerDialog(QObject):

    # Emitted when masks are removed or visibility is toggled
    update_masks = Signal()

    def __init__(self, parent=None):
        super(MaskManagerDialog, self).__init__(parent)
        self.parent = parent

        loader = UiLoader()
        self.ui = loader.load_file('mask_manager_dialog.ui', parent)
        self.ui.installEventFilter(enter_key_filter)
        self.create_masks_list()
        self.threshold = False
        self.image_mode = ViewType.raw

        self.setup_connections()

    def show(self):
        self.setup_table()
        self.ui.show()

    def create_masks_list(self):
        self.masks = {}
        polar_data = HexrdConfig().polar_masks_line_data
        raw_data = HexrdConfig().raw_masks_line_data

        for i, (key, val) in enumerate(polar_data.items()):
            if not any(np.array_equal(m, val) for m in self.masks.values()):
                self.masks[key] = ('polar', val)
        for i, (key, val) in enumerate(raw_data.items()):
            if not any(np.array_equal(m, val) for m in self.masks.values()):
                self.masks[key] = val
        if HexrdConfig().threshold_mask_status:
            self.threshold = True
            self.masks['threshold'] = (
                'threshold', HexrdConfig().threshold_mask)
        HexrdConfig().visible_masks = list(self.masks.keys())

    def update_masks_list(self, mask_type):
        if mask_type == 'polar':
            if not HexrdConfig().polar_masks_line_data:
                return
            for name, data in HexrdConfig().polar_masks_line_data.items():
                vals = self.masks.values()
                for val in data:
                    if any(np.array_equal(val, m) for t, m in vals):
                        continue
                    self.masks[name] = (mask_type, val)
        elif mask_type == 'raw':
            if not HexrdConfig().raw_masks_line_data:
                return
            for name, (det, val) in HexrdConfig().raw_masks_line_data.items():
                vals = self.masks.values()
                if any(np.array_equal(val, m) for t, m in vals):
                    continue
                self.masks[name] = (det, val)
        elif not self.threshold:
            name = create_unique_name(self.masks, 'threshold')
            self.masks[name] = ('threshold', HexrdConfig().threshold_mask)
            HexrdConfig().visible_masks.append(name)
            self.threshold = True
        self.setup_table()

    def setup_connections(self):
        self.ui.masks_table.cellDoubleClicked.connect(self.get_old_name)
        self.ui.masks_table.cellChanged.connect(self.update_mask_name)
        self.ui.masks_table.customContextMenuRequested.connect(
            self.context_menu_event)
        self.ui.export_masks.clicked.connect(self.export_visible_masks)
        HexrdConfig().mode_threshold_mask_changed.connect(
            self.update_masks_list)

    def setup_table(self, status=True):
        self.ui.masks_table.setRowCount(0)
        for i, key in enumerate(self.masks.keys()):
            # Add label
            self.ui.masks_table.insertRow(i)
            self.ui.masks_table.setItem(i, 0, QTableWidgetItem(key))

            # Add checkbox to toggle visibility
            cb = QCheckBox()
            status = key in HexrdConfig().visible_masks
            cb.setChecked(status)
            cb.setStyleSheet('margin-left:50%; margin-right:50%;')
            cb.toggled.connect(self.toggle_visibility)
            self.ui.masks_table.setCellWidget(i, 1, cb)

            # Add push button to remove mask
            pb = QPushButton('Remove Mask')
            pb.clicked.connect(self.remove_mask)
            self.ui.masks_table.setCellWidget(i, 2, pb)

            # Connect manager to raw image mode tab settings
            # for threshold mask
            mtype, data = self.masks[key]
            if mtype == 'threshold':
                self.setup_threshold_connections(cb, pb)

    def setup_threshold_connections(self, checkbox, pushbutton):
        HexrdConfig().mode_threshold_mask_changed.connect(checkbox.setChecked)
        checkbox.toggled.connect(self.threshold_toggled)

    def image_mode_changed(self, mode):
        self.image_mode = mode

    def threshold_toggled(self, v):
        HexrdConfig().set_threshold_mask_status(v, set_by_mgr=True)

    def toggle_visibility(self, checked):
        if self.ui.masks_table.currentRow() < 0:
            return

        row = self.ui.masks_table.currentRow()
        name = self.ui.masks_table.item(row, 0).text()
        mtype, data = self.masks[name]

        if checked and name and name not in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.append(name)
        elif not checked and name in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.remove(name)

        if self.image_mode == ViewType.polar:
            HexrdConfig().polar_masks_changed.emit()
        elif self.image_mode == ViewType.raw:
            HexrdConfig().raw_masks_changed.emit()

    def reset_threshold(self):
        self.threshold = False
        HexrdConfig().set_threshold_comparison(0)
        HexrdConfig().set_threshold_value(0.0)
        HexrdConfig().set_threshold_mask(None)
        HexrdConfig().set_threshold_mask_status(False)

    def remove_mask(self):
        row = self.ui.masks_table.currentRow()
        name = self.ui.masks_table.item(row, 0).text()
        mtype, data = self.masks[name]

        del self.masks[name]
        if name in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.remove(name)
        HexrdConfig().polar_masks_line_data.pop(name, None)
        HexrdConfig().polar_masks.pop(name, None)
        HexrdConfig().raw_masks_line_data.pop(name, None)
        HexrdConfig().raw_masks.pop(name, None)
        if mtype == 'threshold':
            self.reset_threshold()

        self.ui.masks_table.removeRow(row)

        if self.image_mode == ViewType.polar:
            HexrdConfig().polar_masks_changed.emit()
        elif self.image_mode == ViewType.raw:
            HexrdConfig().raw_masks_changed.emit()

    def get_old_name(self, row, column):
        if column != 0:
            return

        self.old_name = self.ui.masks_table.item(row, 0).text()

    def update_mask_name(self, row, column):
        if not hasattr(self, 'old_name') or self.old_name is None:
            return

        new_name = self.ui.masks_table.item(row, 0).text()
        if self.old_name != new_name:
            if new_name in self.masks.keys():
                self.ui.masks_table.item(row, 0).setText(self.old_name)
                return

            self.masks[new_name] = self.masks.pop(self.old_name)
            mtype, data = self.masks[new_name]
            if mtype == 'polar':
                value = HexrdConfig().polar_masks_line_data.pop(self.old_name)
                HexrdConfig().polar_masks[new_name] = value
            elif mtype != 'threshold':
                value = HexrdConfig().raw_masks_line_data.pop(self.old_name)
                HexrdConfig().raw_masks[new_name] = value

            if self.old_name in HexrdConfig().polar_masks.keys():
                value = HexrdConfig().polar_masks.pop(self.old_name)
                HexrdConfig().polar_masks[new_name] = value
            if self.old_name in HexrdConfig().raw_masks.keys():
                value = HexrdConfig().raw_masks.pop(self.old_name)
                HexrdConfig().raw_masks[new_name] = value

            if self.old_name in self.visible:
                self.visible.append(new_name)
                self.visible.remove(self.old_name)
        self.old_name = None

    def context_menu_event(self, event):
        index = self.ui.masks_table.indexAt(event)
        menu = QMenu(self.ui.masks_table)
        export = menu.addAction('Export Mask')
        action = menu.exec_(QCursor.pos())
        if action == export:
            selection = self.ui.masks_table.item(index.row(), 0).text()
            mtype, data = self.masks[selection]
            self.export_masks({selection: data})

    def export_masks(self, data):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'NPZ files (*.npz);; NPY files (*.npy)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            path, ext = os.path.splitext(selected_file)

            if ext.lower() == '.npz':
                np.savez(selected_file, **data)
            elif ext.lower() == '.npy':
                np.save(selected_file, list(data.values())[0])

    def export_visible_masks(self):
        d = {}
        for mask in HexrdConfig().visible_masks:
            mtype, data = self.masks[mask]
            d[mask] = data
        self.export_masks(d)
