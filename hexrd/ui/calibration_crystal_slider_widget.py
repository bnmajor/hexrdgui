from enum import Enum

from PySide2.QtCore import QObject, QSignalBlocker, Signal

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader

class WidgetMode(Enum):
    ORIENTATION = 1  # sliders update orientation
    POSITION = 2     # sliders update position


class CalibrationCrystalSliderWidget(QObject):
    changed = Signal(list, list)

    def __init__(self, parent=None):
        super(CalibrationCrystalSliderWidget, self).__init__(parent)
        self._mode = WidgetMode.ORIENTATION

        loader = UiLoader()
        self.ui = loader.load_file('calibration_crystal_slider_widget.ui', parent)

        self._orientation = [0.0] * 3
        self._position = [0.0] * 3
        self._orientation_suffix = ''

        self.setup_connections()

    @property
    def mode(self):
        index = self.ui.slider_mode.currentIndex()
        if index == 0:
            return WidgetMode.ORIENTATION
        elif index == 1:
            return WidgetMode.POSITION
        # (else)
        raise RuntimeError(f'Unexpected mode index ${index}')

    @property
    def orientation(self):
        return self._orientation

    @property
    def position(self):
        return self._position

    @property
    def spinbox_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'spinbox_{i}') for i in range(3)]

    def on_mode_changed(self):
        if self.mode == WidgetMode.ORIENTATION:
            data = self._orientation
            suffix = self._orientation_suffix
        else:
            data = self._position
            suffix = ''

        self.ui.slider_range.setSuffix(suffix)
        for i,w in enumerate(self.spinbox_widgets):
            blocker = QSignalBlocker(w)  # noqa: F841
            w.setSuffix(suffix)
            w.setValue(data[i])

    def on_spinbox_changed(self, value):
        sender_name = self.sender().objectName()
        index = int(sender_name[-1])
        if self.mode == WidgetMode.ORIENTATION:
            self._orientation[index] = value
        else:
            self._position[index] = value
        self.changed.emit(self._orientation, self._position)

    def set_orientation_suffix(self, suffix):
        self._orientation_suffix = suffix
        if self.mode == WidgetMode.ORIENTATION:
            self.ui.slider_range.setSuffix(suffix)
            for w in self.spinbox_widgets:
                w.setSuffix(suffix)

    def setup_connections(self):
        for w in self.spinbox_widgets:
            w.valueChanged.connect(self.on_spinbox_changed)
        self.ui.slider_mode.currentIndexChanged.connect(self.on_mode_changed)

    def update_gui(self, orientation, position):
        """Called by parent widget."""
        self._orientation = orientation
        self._position = position
        self.update_gui_from_config()

    def update_gui_from_config(self):
        """Called when widget becomes active tab."""
        data = self._orientation if self.mode == WidgetMode.ORIENTATION \
            else self._position
        for i, w in enumerate(self.spinbox_widgets):
            blocker = QSignalBlocker(w)  # noqa: F841
            w.setValue(data[i])
