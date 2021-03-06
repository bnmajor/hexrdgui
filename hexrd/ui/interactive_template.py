import numpy as np

from matplotlib import patches
from matplotlib.path import Path
from matplotlib.transforms import Affine2D

from skimage.draw import polygon

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui import resource_loader


class InteractiveTemplate:
    def __init__(self, img, parent=None):
        self.parent = parent.image_tab_widget.image_canvases[0]
        self.ax = self.parent.axes_images[0]
        self.raw_axes = self.parent.raw_axes[0]
        self.panels = self.parent.iviewer.instr.detectors
        self.img = img
        self.shape = None
        self.press = None
        self.total_rotation = 0

    def update_image(self, img):
        self.img = img

    def rotate_shape(self, angle):
        angle = np.radians(angle)
        self.rotate_template(self.shape.xy, angle)
        self.redraw()

    def create_shape(self, module, file_name, det):
        with resource_loader.resource_path(module, file_name) as f:
            data = np.loadtxt(f)
        verts = self.panels[det].cartToPixel(data)
        verts[:, [0, 1]] = verts[:, [1, 0]]
        self.shape = patches.Polygon(verts, fill=False, lw=1)
        self.center = self.get_midpoint()
        self.connect_translate()
        self.raw_axes.add_patch(self.shape)
        self.redraw()

    @property
    def template(self):
        return self.shape

    @property
    def masked_image(self):
        self.mask()
        return self.img

    @property
    def bounds(self):
        l, r, b, t = self.ax.get_extent()
        x0, y0 = np.nanmin(self.shape.xy, axis=0)
        x1, y1 = np.nanmax(self.shape.xy, axis=0)
        return np.array([max(np.floor(y0), t),
                         min(np.ceil(y1), b),
                         max(np.floor(x0), l),
                         min(np.ceil(x1), r)]).astype(int)

    @property
    def cropped_image(self):
        y0, y1, x0, x1 = self.bounds
        self.img = self.img[y0:y1, x0:x1]
        self.shape.set_xy(self.shape.xy - np.array([x0, y0]))
        return self.img

    @property
    def rotation(self):
        return self.total_rotation

    def clear(self):
        self.raw_axes.patches.remove(self.shape)
        self.redraw()

    def mask(self):
        col, row = self.shape.xy.T
        col_nans = np.where(np.isnan(col))[0]
        row_nans = np.where(np.isnan(row))[0]
        cols = np.split(col, col_nans)
        rows = np.split(row, row_nans)
        master_mask = np.zeros(self.img.shape, dtype=bool)
        for c, r in zip(cols, rows):
            c = c[~np.isnan(c)]
            r = r[~np.isnan(r)]
            rr, cc = polygon(r, c, shape=self.img.shape)
            mask = np.zeros(self.img.shape, dtype=bool)
            mask[rr, cc] = True
            master_mask = np.logical_xor(master_mask, mask)
        self.img[~master_mask] = 0

    def get_paths(self):
        all_paths = []
        points = []
        codes = []
        for coords in self.shape.get_path().vertices[:-1]:
            if np.isnan(coords).any():
                codes[0] = Path.MOVETO
                all_paths.append(Path(points, codes))
                codes = []
                points = []
            else:
                codes.append(Path.LINETO)
                points.append(coords)
        codes[0] = Path.MOVETO
        all_paths.append(Path(points, codes))

        return all_paths

    def redraw(self):
        self.parent.draw()

    def scale_template(self, sx=1, sy=1):
        xy = self.shape.xy
        # Scale the shape
        scaled_xy = Affine2D().scale(sx, sy).transform(xy)
        self.shape.set_xy(scaled_xy)

        # Translate the shape back to where it was
        diff = np.array(self.center) - np.array(self.get_midpoint())
        new_xy = scaled_xy + diff
        self.shape.set_xy(new_xy)
        self.redraw()

    def connect_translate(self):
        self.button_press_cid = self.parent.mpl_connect(
            'button_press_event', self.on_press_translate)
        self.button_release_cid = self.parent.mpl_connect(
            'button_release_event', self.on_release)
        self.motion_cid = self.parent.mpl_connect(
            'motion_notify_event', self.on_translate)

    def on_press_translate(self, event):
        if event.inaxes != self.shape.axes:
            return

        contains, info = self.shape.contains(event)
        if not contains:
            return
        self.press = self.shape.xy, event.xdata, event.ydata

    def on_translate(self, event):
        if self.press is None or event.inaxes != self.shape.axes:
            return

        xy, xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.center = self.get_midpoint()
        self.shape.set_xy(xy + np.array([dx, dy]))
        self.redraw()

    def on_release(self, event):
        if self.press is None:
            return

        xy, xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.shape.set_xy(xy + np.array([dx, dy]))
        self.press = None
        self.redraw()

    def disconnect_translate(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
        self.parent.mpl_disconnect(self.motion_cid)

    def connect_rotate(self):
        self.button_press_cid = self.parent.mpl_connect(
            'button_press_event', self.on_press_rotate)
        self.button_drag_cid = self.parent.mpl_connect(
            'motion_notify_event', self.on_rotate)
        self.button_release_cid = self.parent.mpl_connect(
            'button_release_event', self.on_rotate_release)

    def on_press_rotate(self, event):
        if event.inaxes != self.shape.axes:
            return

        contains, info = self.shape.contains(event)
        if not contains:
            return
        self.center = self.get_midpoint()
        self.shape.set_transform(self.ax.axes.transData)
        self.press = self.shape.xy, event.xdata, event.ydata

    def rotate_template(self, points, angle):
        x = [np.cos(angle), np.sin(angle)]
        y = [-np.sin(angle), np.cos(angle)]
        verts = np.dot(points - self.center, np.array([x, y])) + self.center
        self.shape.set_xy(verts)

    def on_rotate(self, event):
        if self.press is None:
            return

        x, y = self.center
        xy, xpress, ypress = self.press
        angle = self.get_angle(event)
        self.rotate_template(xy, angle)
        self.redraw()

    def get_midpoint(self):
        x0, y0 = np.nanmin(self.shape.xy, axis=0)
        x1, y1 = np.nanmax(self.shape.xy, axis=0)
        return [(x1 + x0)/2, (y1 + y0)/2]

    def mouse_position(self, e):
        xmin, xmax, ymin, ymax = self.ax.get_extent()
        x, y = self.get_midpoint()
        xdata = e.xdata
        ydata = e.ydata
        if xdata is None:
            if e.x < x:
                xdata = 0
            else:
                xdata = xmax
        if ydata is None:
            if e.y < y:
                ydata = 0
            else:
                ydata = ymax
        return xdata, ydata

    def get_angle(self, e):
        xy, xdata, ydata = self.press
        v0 = np.array([xdata, ydata]) - np.array(self.center)
        v1 = np.array(self.mouse_position(e)) - np.array(self.center)
        v0_u = v0/np.linalg.norm(v0)
        v1_u = v1/np.linalg.norm(v1)
        angle = np.arctan2(np.linalg.det([v0_u, v1_u]), np.dot(v0_u, v1_u))
        return angle

    def on_rotate_release(self, event):
        if self.press is None:
            return

        angle = self.get_angle(event)
        self.total_rotation += angle
        y, x = self.center
        xy, xpress, ypress = self.press
        self.press = None
        self.rotate_template(xy, angle)
        self.redraw()

    def disconnect_rotate(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_drag_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
