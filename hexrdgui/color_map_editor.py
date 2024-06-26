import copy

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from matplotlib import colormaps as cm
import matplotlib.colors

import numpy as np

from hexrdgui import constants
from hexrdgui.brightness_contrast_editor import BrightnessContrastEditor
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.scaling import SCALING_OPTIONS
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class ColorMapEditor:

    def __init__(self, image_object, parent=None):
        # The image_object can be any object with the following functions:
        # 1. set_cmap: a function to set the cmap on the image
        # 2. set_norm: a function to set the norm on the image
        # 3. set_scaling: a function to set the scaling on the image
        # 4. scaled_image_data: a property to get the scaled image data

        self.image_object = image_object

        loader = UiLoader()
        self.ui = loader.load_file('color_map_editor.ui', parent)

        self.bounds = (0, 16384)
        self._data = None

        self.bad_color = np.array([0, 0, 0, 0], dtype=float)

        self.bc_editor = None
        self.hide_overlays_during_bc_editing = False

        self._bc_previous_show_overlays = None

        self.load_cmaps()
        # Set the combobox to be the default
        self.ui.color_map.setCurrentText(HexrdConfig().default_cmap)
        self.setup_scaling_options()

        self.setup_connections()

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, v):
        self._data = v
        self.update_bc_enable_state()

        if self.bc_editor:
            self.bc_editor.data = v
            self.update_bc_editor()

    def load_cmaps(self):
        limited = HexrdConfig().limited_cmaps_list

        with block_signals(self.ui.color_map):
            old_selection = self.ui.color_map.currentText()
            self.ui.color_map.clear()
            self.ui.color_map.addItems(limited)

            if HexrdConfig().show_all_colormaps:
                cmaps = constants.ALL_CMAPS
                additional_cmaps = [c for c in cmaps if c not in limited]
                self.ui.color_map.insertSeparator(len(limited))
                self.ui.color_map.addItems(additional_cmaps)
                self.ui.color_map.setCurrentText(old_selection)
            else:
                if old_selection in limited:
                    self.ui.color_map.setCurrentText(old_selection)
                else:
                    # We're viewing the limited list but the color map that
                    # was selected is not in that list.
                    self.ui.color_map.setCurrentIndex(0)

                if self.ui.color_map.currentText():
                    self.update_cmap()

    def setup_scaling_options(self):
        options = list(SCALING_OPTIONS.keys())
        self.ui.scaling.addItems(options)

    def setup_connections(self):
        self.ui.bc_editor_button.pressed.connect(self.bc_editor_button_pressed)

        self.ui.minimum.valueChanged.connect(self.range_edited)
        self.ui.maximum.valueChanged.connect(self.range_edited)

        self.ui.color_map.currentIndexChanged.connect(self.update_cmap)
        self.ui.reverse.toggled.connect(self.update_cmap)
        self.ui.show_under.toggled.connect(self.update_cmap)
        self.ui.show_over.toggled.connect(self.update_cmap)
        self.ui.show_invalid.toggled.connect(self.show_invalid_toggled)
        self.ui.scaling.currentIndexChanged.connect(self.update_scaling)

    def range_edited(self):
        self.update_bc_editor()
        self.update_mins_and_maxes()
        self.update_norm()

    def update_bc_enable_state(self):
        has_images = HexrdConfig().has_images
        has_data = self.data is not None
        self.ui.bc_editor_button.setEnabled(has_data and has_images)

    def bc_editor_button_pressed(self):
        if self.bc_editor:
            self.bc_editor.ui.reject()

        bc = self.bc_editor = BrightnessContrastEditor(self.ui)
        bc.data = self.data
        bc.edited.connect(self.bc_editor_modified)
        bc.reset.connect(self.reset_range)
        bc.ui.finished.connect(self.remove_bc_editor)

        # Hide overlays while the BC editor is open
        if self.hide_overlays_during_bc_editing:
            self._bc_previous_show_overlays = HexrdConfig().show_overlays
            if self._bc_previous_show_overlays:
                HexrdConfig().show_overlays = False
                HexrdConfig().active_material_modified.emit()

        self.update_bc_editor()

        self.bc_editor.ui.show()

    def update_bc_editor(self):
        if not self.bc_editor:
            return

        widgets = (self.ui.minimum, self.ui.maximum)
        new_range = [x.value() for x in widgets]
        with block_signals(self.bc_editor):
            self.bc_editor.ui_range = new_range

    def remove_bc_editor(self):
        self.bc_editor = None

        show_overlays = (
            self.hide_overlays_during_bc_editing and
            self._bc_previous_show_overlays and
            not HexrdConfig().show_overlays
        )
        if show_overlays:
            # Show the overlays again
            HexrdConfig().show_overlays = True
            HexrdConfig().active_material_modified.emit()

    def bc_editor_modified(self):
        with block_signals(self.ui.minimum, self.ui.maximum):
            # Round these values for a nicer display
            bc_min = round(self.bc_editor.ui_min, 2)
            bc_max = round(self.bc_editor.ui_max, 2)
            self.ui.minimum.setValue(bc_min)
            self.ui.maximum.setValue(bc_max)
            self.range_edited()

    def update_mins_and_maxes(self):
        # We can't do this in PySide6 for some reason:
        # self.ui.maximum.valueChanged.connect(self.ui.minimum.setMaximum)
        # self.ui.minimum.valueChanged.connect(self.ui.maximum.setMinimum)
        self.ui.maximum.setMinimum(self.ui.minimum.value())
        self.ui.minimum.setMaximum(self.ui.maximum.value())

    def block_updates(self, blocked):
        self.updates_blocked = blocked

    def update_bounds(self, data):
        if hasattr(self, 'updates_blocked') and self.updates_blocked:
            # We don't want to adjust the bounds
            return

        bounds = self.percentile_range(data)
        self.ui.minimum.setValue(bounds[0])
        self.ui.minimum.setToolTip('Min: ' + str(bounds[0]))
        self.ui.maximum.setValue(bounds[1])
        self.ui.maximum.setToolTip('Max: ' + str(bounds[1]))

        self.bounds = bounds
        self.data = data

    @staticmethod
    def percentile_range(data, low=69.0, high=99.9):
        if isinstance(data, dict):
            values = data.values()
        elif not isinstance(data, (list, tuple)):
            values = [data]

        l = min([np.nanpercentile(v, low) for v in values])
        h = min([np.nanpercentile(v, high) for v in values])

        if h - l < 5:
            h = l + 5

        # Round these to two decimal places
        l = round(l, 2)
        h = round(h, 2)

        return l, h

    def reset_range(self):
        if hasattr(self, 'updates_blocked') and self.updates_blocked:
            # We don't want to adjust the range
            return

        if self.ui.minimum.maximum() < self.bounds[0]:
            # Make sure we can actually set the value...
            self.ui.minimum.setMaximum(self.bounds[0])

        self.ui.minimum.setValue(self.bounds[0])
        self.ui.maximum.setValue(self.bounds[1])

    def show_invalid_toggled(self, b):
        if b:
            color = QColor.fromRgbF(*self.bad_color)
            title = 'Select Invalid Pixel Color'
            selected_color = QColorDialog.getColor(color, None, title)
            if selected_color.isValid():
                # User accepted
                self.bad_color = np.array(selected_color.getRgbF())
            else:
                # User rejected
                with block_signals(self.ui.show_invalid):
                    self.ui.show_invalid.setChecked(False)

        self.update_cmap()

    def update_cmap(self):
        # Get the Colormap object from the name
        cmap = cm.get_cmap(self.ui.color_map.currentText())

        if self.ui.reverse.isChecked():
            cmap = cmap.reversed()

        # For set_under() and set_over(), we don't want to edit the
        # original color map, so make a copy
        cmap = copy.copy(cmap)

        if self.ui.show_under.isChecked():
            cmap.set_under('b')

        if self.ui.show_over.isChecked():
            cmap.set_over('r')

        if self.ui.show_invalid.isChecked():
            cmap.set_bad(self.bad_color)

        self.image_object.set_cmap(cmap)

    def update_norm(self):
        min = self.ui.minimum.value()
        max = self.ui.maximum.value()
        norm = matplotlib.colors.Normalize(vmin=min, vmax=max)
        self.image_object.set_norm(norm)

    def update_scaling(self):
        new_scaling = SCALING_OPTIONS[self.ui.scaling.currentText()]
        self.image_object.set_scaling(new_scaling)

        # Reset the bounds, as the histogram could potentially have moved.
        # This will update the data too.
        self.update_bounds(self.image_object.scaled_image_data)
