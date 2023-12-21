import math
import os
import numpy as np
import h5py

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QMenu,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout
)
from PySide6.QtGui import QCursor

from hexrd.instrument import unwrap_h5_to_dict
from hexrdgui.masking.constants import MaskType

from hexrdgui.utils import block_signals
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url

import matplotlib.pyplot as plt


class MaskManagerDialog(QObject):

    # Emitted when masks are removed or visibility is toggled
    update_masks = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        loader = UiLoader()
        self.ui = loader.load_file('mask_manager_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        add_help_url(self.ui.button_box,
                     'configuration/masking/#managing-masks')

        self.setup_connections()

    def show(self):
        self.setup_table()
        self.ui.show()

    def setup_connections(self):
        self.ui.masks_table.cellDoubleClicked.connect(self.get_old_name)
        self.ui.masks_table.cellChanged.connect(self.update_mask_name)
        self.ui.masks_table.customContextMenuRequested.connect(
            self.context_menu_event)
        self.ui.export_masks.clicked.connect(MaskManager().write_all_masks)
        self.ui.import_masks.clicked.connect(self.import_masks)
        self.ui.panel_buffer.clicked.connect(self.masks_to_panel_buffer)
        self.ui.view_masks.clicked.connect(self.show_masks)
        self.ui.hide_all_masks.clicked.connect(self.hide_all_masks)
        self.ui.show_all_masks.clicked.connect(self.show_all_masks)
        MaskManager().mask_mgr_dialog_update.connect(self.setup_table)
        MaskManager().export_masks_to_file.connect(self.export_masks_to_file)

    def setup_table(self):
        with block_signals(self.ui.masks_table):
            self.ui.masks_table.setRowCount(0)
            for i, key in enumerate(MaskManager().mask_names):
                # Add label
                self.ui.masks_table.insertRow(i)
                self.ui.masks_table.setItem(i, 0, QTableWidgetItem(key))

                # Add checkbox to toggle visibility
                vis_cb = QCheckBox()
                status = key in MaskManager().visible_masks
                vis_cb.setChecked(status)
                vis_cb.setStyleSheet('margin-left:50%; margin-right:50%;')
                self.ui.masks_table.setCellWidget(i, 1, vis_cb)
                vis_cb.toggled.connect(
                    lambda c, k=key: self.toggle_mask_visibility(c, k))

                # Add checkbox to toggle visibility
                border_cb = QCheckBox()
                status = (MaskManager().masks[key].type == MaskType.region)
                border_cb.setChecked(status)
                border_cb.setStyleSheet('margin-left:50%; margin-right:50%;')
                self.ui.masks_table.setCellWidget(i, 2, border_cb)
                border_cb.toggled.connect(
                    lambda c, k=key: self.toggle_border_visibility(c, k))

                # Add push button to remove mask
                pb = QPushButton('Remove Mask')
                self.ui.masks_table.setCellWidget(i, 3, pb)
                pb.clicked.connect(lambda i=i, k=key: self.remove_mask(i, k))

    def toggle_mask_visibility(self, checked, name):
        MaskManager().update_mask_visibility(name, checked)
        MaskManager().masks_changed()

    def toggle_border_visibility(self, checked, name):
        MaskManager().update_border_visibility(name, checked)
        # TODO: Signal to update if borders are drawn
        # MaskManager().masks_changed()

    def remove_mask(self, row, name):
        MaskManager().remove_mask(name)
        self.ui.masks_table.removeRow(row)
        self.setup_table()
        MaskManager().masks_changed()

    def get_old_name(self, row, column):
        if column != 0:
            return

        self.old_name = self.ui.masks_table.item(row, 0).text()

    def update_mask_name(self, row):
        if not hasattr(self, 'old_name') or self.old_name is None:
            return

        new_name = self.ui.masks_table.item(row, 0).text()
        if self.old_name != new_name:
            if new_name in MaskManager().mask_names:
                self.ui.masks_table.item(row, 0).setText(self.old_name)
                return
            MaskManager().update_name(self.old_name, new_name)

        self.old_name = None
        self.setup_table()

    def context_menu_event(self, event):
        index = self.ui.masks_table.indexAt(event)
        if index.row() >= 0:
            menu = QMenu(self.ui.masks_table)
            export = menu.addAction('Export Mask')
            action = menu.exec(QCursor.pos())
            if action == export:
                selection = self.ui.masks_table.item(index.row(), 0).text()
                MaskManager().write_single_mask(selection)

    def export_masks_to_file(self, data):
        output_file, _ = QFileDialog.getSaveFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not output_file:
            return

        HexrdConfig().working_dir = os.path.dirname(output_file)
        # write to hdf5
        with h5py.File(output_file, 'w') as f:
            h5py_group = f.create_group('masks')
            MaskManager().write_masks_to_group(data, h5py_group)

    def import_masks(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            return

        HexrdConfig().working_dir = os.path.dirname(selected_file)
        # Unwrap the h5 file to a dict
        masks_dict = {}
        with h5py.File(selected_file, 'r') as f:
            unwrap_h5_to_dict(f, masks_dict)
        MaskManager().load_masks(masks_dict['masks'])

    def masks_to_panel_buffer(self):
        show_dialog = False
        selection = 'Replace buffer'
        for det in HexrdConfig().detectors.values():
            buff_val = det.get('buffer', {}).get('value', None)
            if isinstance(buff_val, np.ndarray) and buff_val.ndim == 2:
                show_dialog = True
                break

        if show_dialog:
            dialog = QDialog(self.ui)
            layout = QVBoxLayout()
            dialog.setLayout(layout)

            options = QComboBox(dialog)
            options.addItem('Replace buffer')
            options.addItem('Logical AND with buffer')
            options.addItem('Logical OR with buffer')
            layout.addWidget(options)

            buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            button_box = QDialogButtonBox(buttons, dialog)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)

            if not dialog.exec():
                # canceled
                return

            selection = options.currentText()

        MaskManager().masks_to_panel_buffer(selection, buff_val)
        msg = 'Masks set as panel buffers.'
        QMessageBox.information(self.parent, 'HEXRD', msg)

    def show_masks(self):
        num_dets = len(HexrdConfig().detector_names)
        cols = 2 if num_dets > 1 else 1
        rows = math.ceil(num_dets / cols)

        fig = plt.figure()
        fig.canvas.manager.set_window_title('User Created Masks')
        for i, det in enumerate(HexrdConfig().detector_names):
            axis = fig.add_subplot(rows, cols, i + 1)
            axis.set_title(det)
            axis.imshow(MaskManager().raw_masks_dict[det])
        fig.canvas.draw_idle()
        fig.show()

    def update_visibility_checkboxes(self):
        with block_signals(self.ui.masks_table):
            for i, key in enumerate(MaskManager().mask_names):
                cb = self.ui.masks_table.cellWidget(i, 1)
                status = key in MaskManager().visible_masks
                cb.setChecked(status)
        MaskManager().masks_changed()

    def hide_all_masks(self):
        for name in MaskManager().mask_names:
            MaskManager().update_mask_visibility(name, False)
        self.update_visibility_checkboxes()

    def show_all_masks(self):
        for name in MaskManager().mask_names:
            MaskManager().update_mask_visibility(name, True)
        self.update_visibility_checkboxes()
