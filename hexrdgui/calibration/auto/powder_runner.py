import copy
import traceback

import numpy as np

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QMessageBox

from hexrd.fitting.calibration import InstrumentCalibrator, PowderCalibrator
from hexrdgui.async_runner import AsyncRunner
from hexrdgui.constants import ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import instr_to_internal_dict, masks_applied_to_panel_buffers

from hexrdgui.calibration.auto import PowderCalibrationDialog


class PowderRunner(QObject):

    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.parent = parent
        self.async_runner = AsyncRunner(parent)

    def clear(self):
        self.remove_lines()

        if hasattr(self, '_ask_if_lines_are_acceptable_box'):
            # Remove the box if it is still there...
            self._ask_if_lines_are_acceptable_box.hide()
            del self._ask_if_lines_are_acceptable_box

    def run(self):
        try:
            self.validate()
            self._run()
        except Exception as e:
            QMessageBox.critical(self.parent, 'HEXRD', f'Error: {e}')
            traceback.print_exc()

    def validate(self):
        overlays = self.visible_powder_overlays
        if len(overlays) != 1:
            raise Exception('There must be exactly one visible powder overlay')

        if np.count_nonzero(self.refinement_flags) == 0:
            raise Exception('There are no refinable parameters')

    def _run(self):
        # First, have the user pick some options
        if not PowderCalibrationDialog(self.material, self.parent).exec():
            # User canceled...
            return

        # The options they chose are saved here
        options = HexrdConfig().config['calibration']['powder']
        self.instr = create_hedm_instrument()

        if options['auto_guess_initial_fwhm']:
            fwhm_estimate = None
        else:
            fwhm_estimate = options['initial_fwhm']

        # Get an intensity-corrected masked dict of the images
        img_dict = MaskManager().masked_images_dict

        statuses = self.refinement_flags_without_overlays
        self.cf = statuses
        self.instr.calibration_flags = statuses

        kwargs = {
            'instr': self.instr,
            'plane_data': self.material.planeData,
            'img_dict': img_dict,
            'flags': self.refinement_flags,
            'eta_tol': options['eta_tol'],
            'fwhm_estimate': fwhm_estimate,
            'pktype': options['pk_type'],
            'bgtype': options['bg_type'],
            'tth_distortion': self.active_overlay.tth_distortion_dict,
        }

        self.pc = PowderCalibrator(**kwargs)
        self.ic = InstrumentCalibrator(self.pc)
        self.extract_powder_lines()

    def extract_powder_lines(self):
        self.async_runner.progress_title = 'Auto picking points...'
        self.async_runner.success_callback = self.extract_powder_lines_finished
        self.async_runner.run(self.run_extract_powder_lines)

    def run_extract_powder_lines(self):
        options = HexrdConfig().config['calibration']['powder']
        kwargs = {
            'fit_tth_tol': options['fit_tth_tol'],
            'int_cutoff': options['int_cutoff'],
        }

        # Apply any masks to the panel buffer for our instrument.
        # This is done so that the auto picking will skip over masked regions.
        with masks_applied_to_panel_buffers(self.instr):
            # FIXME: currently coded to handle only a single material
            #        so grabbing first (only) element
            self.data_dict = self.ic.extract_points(**kwargs)[0]

        # Save the picks to the active overlay in case we need them later
        self.save_picks_to_overlay()

    def extract_powder_lines_finished(self):
        try:
            self.draw_lines()
            self.ask_if_lines_are_acceptable()
        except Exception:
            self.remove_lines()
            raise

    @property
    def data_xys(self):
        ret = {}
        for k, v in self.data_dict.items():
            if len(v) == 0:
                v = np.empty((0, 2))
            else:
                v = np.vstack(v)[:, :2]
            ret[k] = v
        return ret

    def show_lines(self, b):
        self.draw_lines() if b else self.remove_lines()

    def draw_lines(self):
        HexrdConfig().auto_picked_data = self.data_xys

    def remove_lines(self):
        HexrdConfig().auto_picked_data = None

    def ask_if_lines_are_acceptable(self):
        msg = 'Perform calibration with the points drawn?'
        standard_buttons = QMessageBox.StandardButton
        buttons = standard_buttons.Yes | standard_buttons.No
        box = QMessageBox(QMessageBox.Question, 'HEXRD', msg, buttons,
                          self.parent)
        box.setWindowFlags(box.windowFlags() | Qt.Tool)
        box.setWindowModality(Qt.NonModal)

        # Add a checkbox
        cb = QCheckBox('Show auto picks?')
        cb.setStyleSheet('margin-left:50%; margin-right:50%;')
        cb.setChecked(True)
        cb.toggled.connect(self.show_lines)

        box.setCheckBox(cb)

        # We must show() in the GUI thread, or on Mac, the dialog
        # will appear behind the main window...
        QTimer.singleShot(0, lambda: box.show())

        box.finished.connect(self.remove_lines)
        box.accepted.connect(self.lines_accepted)

        self._show_auto_picks_check_box = cb
        self._ask_if_lines_are_acceptable_box = box

    def lines_accepted(self):
        # If accepted, run it
        self.async_runner.progress_title = 'Running calibration...'
        self.async_runner.success_callback = self.update_config
        self.async_runner.run(self.run_calibration)

    def run_calibration(self):
        options = HexrdConfig().config['calibration']['powder']

        x0 = self.ic.reduced_params
        kwargs = {
            'conv_tol': options['conv_tol'],
            'fit_tth_tol': options['fit_tth_tol'],
            'int_cutoff': options['int_cutoff'],
            'max_iter': options['max_iter'],
            'use_robust_optimization': options['use_robust_optimization'],
        }
        x1 = self.ic.run_calibration(**kwargs)

        results_message = 'Calibration Results:\n'
        for params in np.vstack([x0, x1]).T:
            results_message += f'{params[0]:6.3e}--->{params[1]:6.3e}\n'

        print(results_message)

        self.results_message = results_message

    def update_config(self):
        msg = 'Optimization successful!'
        msg_box = QMessageBox(QMessageBox.Information, 'HEXRD', msg)
        msg_box.exec()

        output_dict = instr_to_internal_dict(self.instr)

        # Save the previous iconfig to restore the statuses
        prev_iconfig = HexrdConfig().config['instrument']

        # Update the config
        HexrdConfig().config['instrument'] = output_dict

        # This adds in any missing keys. In particular, it is going to
        # add in any "None" detector distortions
        HexrdConfig().set_detector_defaults_if_missing()

        # Add status values
        HexrdConfig().add_status(output_dict)

        # Set the previous statuses to be the current statuses
        HexrdConfig().set_statuses_from_prev_iconfig(prev_iconfig)

        # the other parameters
        if np.any(self.ic.flags[self.ic.npi:]):
            # this means we asked to refine lattice parameters
            # FIXME: currently, there is only 1 phase/calibrator allowed, so
            #        this array is the reduce lattice parameter set.
            refined_lattice_params = self.ic.full_params[self.ic.npi:]
            self.material.latticeParameters = refined_lattice_params
            HexrdConfig().material_modified.emit(self.material.name)

        # Tell GUI that the overlays need to be re-computed
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)

        # redraw updated overlays
        HexrdConfig().overlay_config_changed.emit()

        self.finished.emit()

    @property
    def overlays(self):
        return HexrdConfig().overlays

    @property
    def visible_overlays(self):
        return [x for x in self.overlays if x.visible]

    @property
    def visible_powder_overlays(self):
        overlays = self.visible_overlays
        return [x for x in overlays if x.is_powder]

    @property
    def active_overlay(self):
        overlays = self.visible_powder_overlays
        return overlays[0] if overlays else None

    @property
    def material(self):
        overlay = self.active_overlay
        return overlay.material if overlay else None

    @property
    def refinement_flags_without_overlays(self):
        return HexrdConfig().get_statuses_instrument_format()

    @property
    def refinement_flags(self):
        return np.hstack([self.refinement_flags_without_overlays,
                          self.active_overlay.refinements])

    def save_picks_to_overlay(self):
        # Currently, we only have one active overlay
        save_picks_to_overlay(self.active_overlay, self.data_dict)


def save_picks_to_overlay(overlay, data_dict):
    instr = create_hedm_instrument()

    if overlay.display_mode == ViewType.cartesian:
        # Since this one has a fake instrument, we need to create an
        # overlay with a real instrument, update the data to generate
        # the hkls, and then take those hkls.
        overlay_copy = copy.deepcopy(overlay)
        overlay_copy.instrument = instr
        overlay_copy.display_mode = ViewType.raw
        overlay_copy.update_needed = True
        overlay_copy.data
        overlay_hkls = overlay_copy.hkls
    else:
        # These hkls should work fine
        overlay_hkls = overlay.hkls

    picks = {}
    for det_key, data in data_dict.items():
        picks[det_key] = []

        hkls = overlay_hkls[det_key]

        for hkl in hkls:
            hkl_picks = []
            for ringset in data:
                for row in ringset:
                    if np.array_equal(row[3:6], hkl):
                        hkl_picks.append(row[:2])

            picks[det_key].append(hkl_picks)

    overlay.calibration_picks = picks
