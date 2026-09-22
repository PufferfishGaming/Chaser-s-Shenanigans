"""
Shared UI components for the suite.

`theme.py` owns colour and the stylesheet; this module owns *shape* - the
handful of composites every tool builds its panel out of, so that a control row
in Quick Edit is the same object as a control row in PhotoBorder rather than
the same idea implemented twice with different margins.

Three things here are worth knowing before adding to it.

**Icons are drawn, never shipped.** `icon()` renders from QPainter primitives
at request time and caches by (name, size, colour). The suite already ships
3.2 MB of fonts in a zip every user re-downloads on every update (see
CLAUDE.md); an icon set would be more of the same, and an icon *font* would put
the tool bar at the mercy of the same variable-font weight trap the captions
hit. Drawn icons also re-tint on a theme switch for free.

**The spacing scale is fixed and small.** SPACE_* below. Every margin and gap
in a rebuilt panel comes from it. The old GUIs used 24/20/14/8/6 in different
files and the tools visibly did not match each other when opened side by side.

**Live controls debounce, they do not throttle.** `Debouncer` waits for a pause
before firing. PhotoBorder's preview costs ~650ms with the palette on, so a
slider dragged across its range must not queue one render per step - and a
*throttle* (fire every N ms) still fires mid-drag, which is exactly the render
whose result is stale before it finishes. The drag path inside PreviewCanvas is
a different mechanism and stays as it is; this is for the ordinary controls.
"""
from PySide6 import QtCore, QtGui, QtWidgets

import theme

# ------------------------------------------------------------- spacing scale
#
# 4px base. Anything not on the scale is a mistake or needs a comment saying why.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 18
SPACE_XL = 26

PANEL_MARGIN = SPACE_LG
FIELD_HEIGHT = 32


# ------------------------------------------------------------------- icons

_icon_cache: dict = {}


def _paint_icon(name: str, size: int, color: str) -> QtGui.QPixmap:
    """Draw one icon into a transparent pixmap at 3x for DPI headroom.

    Everything is expressed as a fraction of `s` so a single definition serves
    the 14px inline mark and the 28px card icon. Stroke width is a fraction too;
    a constant one goes spidery at 28px and blocks up at 14px.
    """
    scale = 3
    s = size * scale
    pm = QtGui.QPixmap(s, s)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    col = QtGui.QColor(color)
    pen = QtGui.QPen(col, s * 0.085)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)

    def rect(x, y, w, h, r=0.0):
        rr = QtCore.QRectF(s * x, s * y, s * w, s * h)
        if r:
            p.drawRoundedRect(rr, s * r, s * r)
        else:
            p.drawRect(rr)

    def line(x1, y1, x2, y2):
        p.drawLine(QtCore.QPointF(s * x1, s * y1), QtCore.QPointF(s * x2, s * y2))

    def circle(cx, cy, r, fill=False):
        rr = QtCore.QRectF(s * (cx - r), s * (cy - r), s * r * 2, s * r * 2)
        if fill:
            p.setBrush(col)
            p.drawEllipse(rr)
            p.setBrush(QtCore.Qt.NoBrush)
        else:
            p.drawEllipse(rr)

    # --- tool marks (used on the launcher cards) -----------------------------
    if name == "border":                       # a frame with a wide lower band
        rect(0.14, 0.16, 0.72, 0.68, 0.06)
        rect(0.24, 0.26, 0.52, 0.34, 0.03)
        line(0.28, 0.70, 0.60, 0.70)
    elif name == "convert":                    # two arrows, opposite directions
        line(0.20, 0.36, 0.76, 0.36)
        line(0.62, 0.22, 0.78, 0.36)
        line(0.62, 0.50, 0.78, 0.36)
        line(0.80, 0.66, 0.24, 0.66)
        line(0.38, 0.52, 0.22, 0.66)
        line(0.38, 0.80, 0.22, 0.66)
    elif name == "tag":                        # metadata
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.50, s * 0.16)
        pth.lineTo(s * 0.84, s * 0.50)
        pth.lineTo(s * 0.52, s * 0.82)
        pth.lineTo(s * 0.18, s * 0.48)
        pth.lineTo(s * 0.18, s * 0.16)
        pth.closeSubpath()
        p.drawPath(pth)
        circle(0.33, 0.33, 0.055, fill=True)
    elif name == "stars":                      # astro stacker: sky over a horizon
        for cx, cy, r in ((0.28, 0.26, 0.055), (0.62, 0.20, 0.042),
                          (0.78, 0.44, 0.05), (0.42, 0.48, 0.038)):
            circle(cx, cy, r, fill=True)
        # The horizon sat at 0.86 and the round cap on a 0.085-wide stroke put
        # its outer edge past the pixmap edge, so it was clipped away entirely.
        line(0.16, 0.76, 0.84, 0.76)
    elif name == "wand":                       # quick edit
        line(0.24, 0.78, 0.68, 0.34)
        line(0.60, 0.26, 0.76, 0.42)
        line(0.24, 0.22, 0.24, 0.36)
        line(0.17, 0.29, 0.31, 0.29)
    # --- action marks --------------------------------------------------------
    elif name == "folder":
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.14, s * 0.76)
        pth.lineTo(s * 0.14, s * 0.26)
        pth.lineTo(s * 0.42, s * 0.26)
        pth.lineTo(s * 0.50, s * 0.38)
        pth.lineTo(s * 0.86, s * 0.38)
        pth.lineTo(s * 0.86, s * 0.76)
        pth.closeSubpath()
        p.drawPath(pth)
    elif name == "file":
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.26, s * 0.14)
        pth.lineTo(s * 0.60, s * 0.14)
        pth.lineTo(s * 0.76, s * 0.32)
        pth.lineTo(s * 0.76, s * 0.86)
        pth.lineTo(s * 0.26, s * 0.86)
        pth.closeSubpath()
        p.drawPath(pth)
        line(0.60, 0.14, 0.60, 0.32)
        line(0.60, 0.32, 0.76, 0.32)
    elif name == "image":
        rect(0.14, 0.20, 0.72, 0.60, 0.06)
        circle(0.35, 0.38, 0.065)
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.20, s * 0.72)
        pth.lineTo(s * 0.42, s * 0.50)
        pth.lineTo(s * 0.58, s * 0.64)
        pth.lineTo(s * 0.68, s * 0.55)
        pth.lineTo(s * 0.80, s * 0.72)
        p.drawPath(pth)
    elif name == "export":
        line(0.50, 0.16, 0.50, 0.58)
        line(0.34, 0.32, 0.50, 0.16)
        line(0.66, 0.32, 0.50, 0.16)
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.20, s * 0.56)
        pth.lineTo(s * 0.20, s * 0.84)
        pth.lineTo(s * 0.80, s * 0.84)
        pth.lineTo(s * 0.80, s * 0.56)
        p.drawPath(pth)
    elif name == "reset":                      # circular arrow
        rr = QtCore.QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.60)
        p.drawArc(rr, 60 * 16, 280 * 16)
        line(0.50, 0.12, 0.66, 0.24)
        line(0.50, 0.34, 0.66, 0.24)
    elif name == "sun":
        circle(0.5, 0.5, 0.20)
        for i in range(8):
            import math
            a = math.radians(i * 45)
            line(0.5 + 0.30 * math.cos(a), 0.5 + 0.30 * math.sin(a),
                 0.5 + 0.40 * math.cos(a), 0.5 + 0.40 * math.sin(a))
    elif name == "moon":
        pth = QtGui.QPainterPath()
        pth.addEllipse(QtCore.QRectF(s * 0.20, s * 0.18, s * 0.58, s * 0.58))
        bite = QtGui.QPainterPath()
        bite.addEllipse(QtCore.QRectF(s * 0.38, s * 0.10, s * 0.56, s * 0.56))
        p.drawPath(pth.subtracted(bite))
    elif name == "download":
        line(0.50, 0.16, 0.50, 0.60)
        line(0.34, 0.44, 0.50, 0.60)
        line(0.66, 0.44, 0.50, 0.60)
        line(0.22, 0.80, 0.78, 0.80)
    elif name == "info":
        circle(0.5, 0.5, 0.34)
        circle(0.5, 0.33, 0.045, fill=True)
        line(0.50, 0.46, 0.50, 0.68)
    elif name == "warning":
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.50, s * 0.16)
        pth.lineTo(s * 0.88, s * 0.82)
        pth.lineTo(s * 0.12, s * 0.82)
        pth.closeSubpath()
        p.drawPath(pth)
        line(0.50, 0.42, 0.50, 0.60)
        circle(0.50, 0.71, 0.038, fill=True)
    elif name == "check":
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.20, s * 0.52)
        pth.lineTo(s * 0.42, s * 0.74)
        pth.lineTo(s * 0.80, s * 0.26)
        p.drawPath(pth)
    elif name == "close":
        line(0.26, 0.26, 0.74, 0.74)
        line(0.74, 0.26, 0.26, 0.74)
    elif name == "palette":
        circle(0.5, 0.5, 0.34)
        for cx, cy in ((0.38, 0.34), (0.62, 0.34), (0.70, 0.55)):
            circle(cx, cy, 0.055, fill=True)
    elif name == "type":                       # typography
        line(0.20, 0.26, 0.80, 0.26)
        line(0.50, 0.26, 0.50, 0.80)
        line(0.36, 0.80, 0.64, 0.80)
    elif name == "layers":
        for dy in (0.0, 0.16, 0.32):
            pth = QtGui.QPainterPath()
            pth.moveTo(s * 0.50, s * (0.20 + dy))
            pth.lineTo(s * 0.84, s * (0.36 + dy))
            pth.lineTo(s * 0.50, s * (0.52 + dy))
            pth.lineTo(s * 0.16, s * (0.36 + dy))
            pth.closeSubpath()
            p.drawPath(pth)
    elif name == "rotate":                     # a frame plus a quarter-turn arrow
        rect(0.20, 0.36, 0.44, 0.44, 0.05)
        rr = QtCore.QRectF(s * 0.34, s * 0.16, s * 0.48, s * 0.48)
        p.drawArc(rr, 0, 110 * 16)             # top-right quadrant only
        line(0.82, 0.40, 0.82, 0.24)           # arrow head on the arc's end
        line(0.82, 0.40, 0.68, 0.40)
    elif name in ("chevron_down", "chevron_right"):
        pth = QtGui.QPainterPath()
        pth.moveTo(s * 0.30, s * 0.40)
        pth.lineTo(s * 0.50, s * 0.60)
        pth.lineTo(s * 0.70, s * 0.40)
        p.save()
        p.translate(s / 2.0, s / 2.0)
        p.rotate(0 if name == "chevron_down" else -90)
        p.translate(-s / 2.0, -s / 2.0)
        p.drawPath(pth)
        p.restore()
    elif name == "sliders":
        for y, kx in ((0.30, 0.64), (0.50, 0.36), (0.70, 0.56)):
            line(0.16, y, 0.84, y)
            circle(kx, y, 0.075, fill=True)
    p.end()
    # Declare the 3x oversampling so Qt lays the pixmap out at `size` logical
    # pixels while drawing from the high-resolution bitmap. Without this a
    # QLabel shows the pixmap at its full 3x device size, which inside a
    # size-constrained label crops it - the launcher's card marks came through
    # as a corner of each icon rather than as the icon.
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, size: int = 16, color: str = None) -> QtGui.QIcon:
    """A themed QIcon, cached. `color` defaults to the theme's glyph colour."""
    color = color or theme.palette_color("GLYPH")
    key = (name, size, color)
    hit = _icon_cache.get(key)
    if hit is None:
        hit = QtGui.QIcon(_paint_icon(name, size, color))
        _icon_cache[key] = hit
    return hit


def pixmap(name: str, size: int = 16, color: str = None) -> QtGui.QPixmap:
    color = color or theme.palette_color("GLYPH")
    return _paint_icon(name, size, color)


# --------------------------------------------------------------- reactivity

class Debouncer(QtCore.QObject):
    """Collapse a burst of change signals into one call after a quiet period.

    Deliberately a debounce and not a throttle: a throttle fires *during* the
    drag, and for a control whose result takes ~650ms to compute the in-flight
    render is already answering a question the user has moved on from. Waiting
    for the pause costs one interval of latency and saves every intermediate
    render.
    """

    def __init__(self, callback, interval: int = 180, parent=None):
        super().__init__(parent)
        self._callback = callback
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._fire)

    def poke(self, *_args) -> None:
        """Restart the quiet period. Safe to connect straight to a signal."""
        self._timer.start()

    def flush(self) -> None:
        """Fire now if something is pending (e.g. on a slider's release)."""
        if self._timer.isActive():
            self._timer.stop()
            self._fire()

    def cancel(self) -> None:
        self._timer.stop()

    def _fire(self) -> None:
        self._callback()


# ------------------------------------------------------------ small widgets

def section(text: str) -> QtWidgets.QLabel:
    """A small-caps section heading."""
    lab = QtWidgets.QLabel(text.upper())
    lab.setObjectName("section")
    return lab


class WrapLabel(QtWidgets.QLabel):
    """A word-wrapping label that does NOT drive the width of its column.

    A QLabel with `setWordWrap(True)` still reports the width of its text on ONE
    line as its size hint, and only wraps once it is given less. In a fixed-width
    control column measured from its content - which is how every panel in this
    suite is sized - that is circular: the panel measures the unwrapped
    paragraph, so one sentence of help text under a control widened PhotoBorder's
    panel from 564px to 902px and pushed it into the 760px cap, where the cap
    then clipped the real controls.

    Reporting a minimal width instead is correct here because these labels are
    always laid out in a vertical column and get the full column width whatever
    they ask for.
    """

    def __init__(self, text: str = "", object_name: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        if object_name:
            self.setObjectName(object_name)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                           QtWidgets.QSizePolicy.Minimum)

    def sizeHint(self):
        return QtCore.QSize(0, super().sizeHint().height())

    def minimumSizeHint(self):
        return QtCore.QSize(0, super().minimumSizeHint().height())


def wrap_label(text: str = "", object_name: str = "") -> "WrapLabel":
    """Shorthand for a WrapLabel."""
    return WrapLabel(text, object_name)


def field_label(text: str) -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text)
    lab.setObjectName("fieldlabel")
    return lab


def divider() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QtWidgets.QFrame.NoFrame)
    line.setFixedHeight(1)
    return line


def primary_button(text: str, icon_name: str = None) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    b.setObjectName("primary")
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setMinimumHeight(FIELD_HEIGHT + 4)
    if icon_name:
        b.setIcon(icon(icon_name, 15, theme.palette_color("ACCENT_TEXT")))
    return b


def button(text: str, icon_name: str = None) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setMinimumHeight(FIELD_HEIGHT)
    if icon_name:
        b.setIcon(icon(icon_name, 15))
    return b


def ghost_button(text: str, icon_name: str = None) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    b.setObjectName("ghost")
    b.setCursor(QtCore.Qt.PointingHandCursor)
    if icon_name:
        b.setIcon(icon(icon_name, 15))
    return b


def icon_button(icon_name: str, tooltip: str = "", size: int = 30) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton()
    b.setObjectName("ghost")
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setFixedSize(size, size)
    b.setIcon(icon(icon_name, 16))
    b.setProperty("iconName", icon_name)
    if tooltip:
        b.setToolTip(tooltip)
    return b


class Chip(QtWidgets.QLabel):
    """A small accent-tinted count/status pill."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("chip")
        self.setAlignment(QtCore.Qt.AlignCenter)


# ------------------------------------------------------------------ layout

class Panel(QtWidgets.QWidget):
    """The control column every tool has on its left: scrolling body + fixed footer.

    Two parts, and the split is the point.

    The **body** scrolls. PhotoBorder's panel was already taller than the window
    it asked for (928px against a requested 760) before the Typography section
    pushed it to 1157 - past the usable height of a 1080p screen. Every tool gets
    the same treatment so they behave alike when the window is short, and so a
    future section is never a layout emergency.

    The **footer** does not scroll. Without it the primary action goes wherever
    the content happens to end: the Astro Stacker's Preview and Export buttons
    sat below the fold at 820px tall with no frames loaded, so the tool's two
    verbs were invisible in its initial state. Anything the user needs to reach
    regardless of scroll position - run, export, status - belongs there.

    The `#panel` background and right border live on this container, not on the
    inner widget. QSS specificity has bitten this codebase before, and applying
    `#panel` to both the scroll viewport and the inner widget double-draws that
    border.
    """

    def __init__(self, bordered: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("panel" if bordered else "panel_flat")
        shell = QtWidgets.QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        # AsNeeded rather than AlwaysOff: at a fixed width, Off means an
        # over-wide child is clipped with no indication at all.
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.body = QtWidgets.QWidget()
        self.body.setAutoFillBackground(False)
        self.vbox = QtWidgets.QVBoxLayout(self.body)
        self.vbox.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN,
                                     PANEL_MARGIN, PANEL_MARGIN)
        self.vbox.setSpacing(SPACE_MD)
        self.scroll.setWidget(self.body)
        shell.addWidget(self.scroll, 1)

        self._footer = QtWidgets.QWidget()
        self._footer.setAutoFillBackground(False)
        self.footer_box = QtWidgets.QVBoxLayout(self._footer)
        self.footer_box.setContentsMargins(PANEL_MARGIN, SPACE_MD,
                                           PANEL_MARGIN, PANEL_MARGIN)
        self.footer_box.setSpacing(SPACE_SM)
        self._footer.setVisible(False)
        self._footer_rule = divider()
        self._footer_rule.setVisible(False)
        shell.addWidget(self._footer_rule)
        shell.addWidget(self._footer)

        self.setMinimumWidth(320)

    # -- body content ------------------------------------------------------
    def add(self, widget, *args, **kwargs):
        self.vbox.addWidget(widget, *args, **kwargs)
        return widget

    def add_layout(self, layout):
        self.vbox.addLayout(layout)
        return layout

    def add_section(self, text: str, top_gap: int = SPACE_MD):
        if self.vbox.count():
            self.vbox.addSpacing(top_gap)
        return self.add(section(text))

    def add_stretch(self, n: int = 1):
        self.vbox.addStretch(n)

    # -- footer content ----------------------------------------------------
    def add_footer(self, widget):
        self.footer_box.addWidget(widget)
        self._show_footer()
        return widget

    def add_footer_layout(self, layout):
        self.footer_box.addLayout(layout)
        self._show_footer()
        return layout

    def _show_footer(self):
        self._footer.setVisible(True)
        self._footer_rule.setVisible(True)

    # -- sizing ------------------------------------------------------------
    def max_width_for_window(self, window: QtWidgets.QWidget = None,
                             floor: int = 560, fraction: float = 0.66) -> int:
        """The widest this column may get, expressed against the window.

        The cap exists so a pathological font or a very long combo entry cannot
        take the whole window - but a constant cannot express that, for the same
        reason the panel's own width could not be a constant. 760 was as
        arbitrary as the 380 and 440 that preceded it: on a 1400px window it
        needlessly clipped content that had room, and on a 900px window it was
        five sixths of the window and not a limit at all.

        Two thirds of the window, never below `floor`. That is the actual
        promise - the panel may not swallow the window - stated in terms of the
        window.
        """
        win = window or self.window()
        width = win.width() if win is not None else 0
        return max(floor, int(width * fraction)) if width else floor

    def fit_width(self, minimum: int = 320, maximum: int = None) -> int:
        """Size the column to what its contents actually need.

        The required width is not predictable from here: it depends on the
        system font, the stylesheet, the display scaling and the locale's
        decimal separator ("1,0 x" is wider than "1.0 x"). Two hardcoded values
        were each wrong on some machine, the second clipping the reset buttons
        and the right-hand end of every combo behind the preview area.

        `invalidate()` before `activate()` matters: the layout caches its size
        hint, so activate() alone re-reads a stale value and the column never
        grows when a control's content gets wider.

        The footer is measured too. It holds the primary action, which is often
        the widest thing in the column.

        `maximum` defaults to `max_width_for_window()` - see there for why the
        cap is a fraction of the window rather than a constant.
        """
        needed = 0
        for host in (self.body, self._footer):
            layout = host.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            host.updateGeometry()
            if host is self._footer and not self._footer.isVisible():
                continue
            needed = max(needed, host.sizeHint().width(),
                         host.minimumSizeHint().width())
        # Reserve the scrollbar unconditionally so the column does not change
        # width the moment the content gets tall enough to need one.
        needed += self.scroll.verticalScrollBar().sizeHint().width() + 4
        if maximum is None:
            maximum = self.max_width_for_window()
        width = max(minimum, min(maximum, needed))
        if self.width() != width:
            self.setFixedWidth(width)
        return width


class FormGrid(QtWidgets.QGridLayout):
    """Label-left / control-right rows with one aligned control column.

    The control column stretches and the label column does not, which is what
    stops the ragged right-hand edge the old panels had - every combo took its
    own natural width, so five combos in a column ended at five different x
    positions.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setHorizontalSpacing(SPACE_MD)
        self.setVerticalSpacing(SPACE_SM)
        self.setColumnStretch(0, 0)
        self.setColumnStretch(1, 1)
        self._row = 0

    def add_row(self, label: str, widget: QtWidgets.QWidget):
        lab = field_label(label)
        lab.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        self.addWidget(lab, self._row, 0)
        # A numeric stepper is capped rather than stretched. The control column
        # stretches so that combos and text fields line up on a common right
        # edge - which is right for them and absurd for a spin box: "Shift
        # capture time" rendered as a 1080px-wide field holding "0 min", with
        # its up/down arrows a screen away from the number they change.
        if isinstance(widget, QtWidgets.QAbstractSpinBox):
            widget.setMaximumWidth(max(120, widget.sizeHint().width() + 40))
        self.addWidget(widget, self._row, 1)
        self._row += 1
        return widget

    def add_full(self, widget: QtWidgets.QWidget):
        self.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1
        return widget


class SliderField(QtWidgets.QWidget):
    """A labelled slider with a live numeric readout and an optional reset.

    The readout is the point. Every slider in the old suite except Quality was
    unlabelled, so "Temperature" and "Tint" could be moved but not *set* - and
    the one that did show its value put it in the label text, which made the
    label reflow and the row jump as the number changed width. Here the readout
    is right-aligned in a fixed-width cell.

    `valueChanged` carries the scaled float; `released` fires once on the
    mouse release, which is what an expensive live preview should listen to.
    """

    valueChanged = QtCore.Signal(float)
    released = QtCore.Signal()

    def __init__(self, label: str, minimum: float, maximum: float, value: float,
                 decimals: int = 0, suffix: str = "", step_scale: int = 1,
                 resettable: bool = True, parent=None):
        super().__init__(parent)
        self._decimals = decimals
        self._suffix = suffix
        self._scale = step_scale
        self._default = value

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_XS)

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACE_SM)
        self.label = field_label(label)
        head.addWidget(self.label)
        head.addStretch(1)
        self.readout = QtWidgets.QLabel()
        self.readout.setObjectName("value")
        self.readout.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        head.addWidget(self.readout)
        if resettable:
            self.reset_btn = icon_button("reset", "Reset to default", 22)
            self.reset_btn.clicked.connect(self.reset)
            head.addWidget(self.reset_btn)
        else:
            self.reset_btn = None
        root.addLayout(head)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(int(round(minimum * step_scale)),
                             int(round(maximum * step_scale)))
        self.slider.setValue(int(round(value * step_scale)))
        self.slider.valueChanged.connect(self._on_change)
        self.slider.sliderReleased.connect(self.released.emit)
        root.addWidget(self.slider)
        self._sync_readout()

    # -- value -------------------------------------------------------------
    def value(self) -> float:
        raw = self.slider.value() / float(self._scale)
        return raw if self._decimals else round(raw)

    def setValue(self, v: float) -> None:
        self.slider.setValue(int(round(v * self._scale)))

    def reset(self) -> None:
        self.setValue(self._default)
        self.released.emit()

    def set_default(self, v: float) -> None:
        self._default = v

    def _on_change(self, _raw) -> None:
        self._sync_readout()
        self.valueChanged.emit(self.value())

    def _sync_readout(self) -> None:
        v = self.value()
        txt = f"{v:.{self._decimals}f}" if self._decimals else f"{int(v)}"
        self.readout.setText(f"{txt}{self._suffix}")


class Collapsible(QtWidgets.QWidget):
    """A section that can be folded away, remembering its state per tool.

    PhotoBorder's panel is 1157px of controls; on a 1080p screen the user
    cannot see the section they are working in and the one they are comparing
    it against at the same time. Folding the sections they are not using is the
    cheapest fix that does not remove anything.
    """

    toggled = QtCore.Signal(bool)

    def __init__(self, title: str, expanded: bool = True, icon_name: str = None,
                 parent=None):
        # `expanded` defaults to True and callers should leave it that way for a
        # first run. A control the user has never seen cannot be discovered, and
        # hiding half the panel by default trades one problem (a tall panel,
        # which now scrolls) for a worse one.
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_SM)

        self.header = QtWidgets.QPushButton()
        self.header.setObjectName("ghost")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setCursor(QtCore.Qt.PointingHandCursor)
        self.header.setText("  " + title.upper())
        self.header.setStyleSheet(
            "QPushButton { text-align: left; padding: 3px 2px; font-size: 10px;"
            " font-weight: 700; letter-spacing: 1px; }")
        self.header.clicked.connect(self._on_toggle)
        root.addWidget(self.header)

        self.content = QtWidgets.QWidget()
        self.box = QtWidgets.QVBoxLayout(self.content)
        self.box.setContentsMargins(0, 0, 0, SPACE_XS)
        self.box.setSpacing(SPACE_SM)
        root.addWidget(self.content)

        self._icon_name = icon_name
        self.content.setVisible(expanded)
        self._sync_icon()

    def add(self, widget):
        self.box.addWidget(widget)
        return widget

    def add_layout(self, layout):
        self.box.addLayout(layout)
        return layout

    def setExpanded(self, on: bool) -> None:
        self.header.setChecked(on)
        self.content.setVisible(on)
        self._sync_icon()

    def isExpanded(self) -> bool:
        return self.header.isChecked()

    def _on_toggle(self) -> None:
        on = self.header.isChecked()
        self.content.setVisible(on)
        self._sync_icon()
        self.toggled.emit(on)

    def _sync_icon(self) -> None:
        """Point the chevron down when open, right when folded.

        The disclosure mark has to be the icon rather than a leading character
        in the text: `setText` on a checkable QPushButton re-lays out the whole
        row, and with a section title of a different length the header visibly
        jumped on every toggle.
        """
        name = "chevron_down" if self.isExpanded() else "chevron_right"
        self.header.setIcon(icon(name, 12, theme.palette_color("SECTION")))
        if self._icon_name:
            self.header.setToolTip(self._icon_name)

    def retint(self) -> None:
        self._sync_icon()


class EmptyState(QtWidgets.QWidget):
    """What a preview area shows before there is anything to preview.

    Replaces the bare "No image loaded" string floating in the middle of a
    large empty rectangle. Carries the next action, because the answer to "what
    now" should be reachable from where the user is looking rather than from
    the far side of the window.
    """

    def __init__(self, icon_name: str, title: str, body: str = "",
                 action: str = "", parent=None):
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        root.setSpacing(SPACE_SM)
        root.setAlignment(QtCore.Qt.AlignCenter)

        self.glyph = QtWidgets.QLabel()
        self.glyph.setAlignment(QtCore.Qt.AlignCenter)
        self._icon_name = icon_name
        root.addWidget(self.glyph)
        root.addSpacing(SPACE_XS)

        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("empty_title")
        self.title.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(self.title)

        self.body = QtWidgets.QLabel(body)
        self.body.setObjectName("empty_body")
        self.body.setAlignment(QtCore.Qt.AlignCenter)
        self.body.setWordWrap(True)
        self.body.setVisible(bool(body))
        root.addWidget(self.body)

        self.action_btn = None
        if action:
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            self.action_btn = button(action, "file")
            row.addWidget(self.action_btn)
            row.addStretch(1)
            root.addSpacing(SPACE_SM)
            root.addLayout(row)

        self.retint()

    def retint(self) -> None:
        """Re-render the glyph for the current theme.

        A QLabel holding a pixmap does not follow a live theme switch - the
        pixmap was baked with the old colour - so this is called from the
        window's PaletteChange handler, the same way the Metadata tag browser
        recolours its staged rows.
        """
        self.glyph.setPixmap(pixmap(self._icon_name, 40,
                                    theme.palette_color("BORDER_STRONG")))


class DropZone(QtWidgets.QFrame):
    """A dashed target that accepts dropped image files.

    Emits `dropped` with the list of local paths. The dashed border switches to
    the accent colour on drag-over via a dynamic property plus a style repolish;
    setting a stylesheet on the widget itself instead would override the
    app-level sheet and freeze this widget in whatever theme was current when it
    was built.
    """

    dropped = QtCore.Signal(list)
    clicked = QtCore.Signal()

    def __init__(self, text: str = "Drop images here", sub: str = "or click to browse",
                 parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setProperty("dragover", "false")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        root.setSpacing(2)
        root.setAlignment(QtCore.Qt.AlignCenter)
        self.main = QtWidgets.QLabel(text)
        self.main.setAlignment(QtCore.Qt.AlignCenter)
        self.sub = QtWidgets.QLabel(sub)
        self.sub.setObjectName("empty_body")
        self.sub.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(self.main)
        root.addWidget(self.sub)

    def setText(self, text: str, sub: str = None) -> None:
        self.main.setText(text)
        if sub is not None:
            self.sub.setText(sub)

    def _set_over(self, on: bool) -> None:
        self.setProperty("dragover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_over(True)

    def dragLeaveEvent(self, e):
        self._set_over(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._set_over(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)
            e.acceptProposedAction()


class StatusStrip(QtWidgets.QWidget):
    """One inline status line: an icon, a message, and an optional progress bar.

    Replaces the pattern of a bare QLabel plus a separate always-present
    QProgressBar, which is why several tools showed an empty progress trough at
    rest with nothing running.
    """

    LEVELS = {"info": ("info", "MUTED"), "busy": ("info", "ACCENT"),
              "ok": ("check", "ACCENT"), "warn": ("warning", "HINT"),
              "error": ("warning", "ERROR")}

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_XS)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_SM)
        self.glyph = QtWidgets.QLabel()
        self.glyph.setFixedWidth(16)
        row.addWidget(self.glyph)
        self.text = QtWidgets.QLabel("")
        self.text.setWordWrap(True)
        row.addWidget(self.text, 1)
        root.addLayout(row)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setObjectName("thin")
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        root.addWidget(self.bar)

        self._level = "info"
        self.clear()

    def clear(self) -> None:
        self.text.setText("")
        self.glyph.clear()
        self.bar.setVisible(False)
        self.setVisible(False)

    def show_message(self, message: str, level: str = "info") -> None:
        self._level = level if level in self.LEVELS else "info"
        name, token = self.LEVELS[self._level]
        colour = theme.palette_color(token)
        self.glyph.setPixmap(pixmap(name, 14, colour))
        self.text.setText(message)
        self.text.setStyleSheet(f"color: {colour};")
        self.setVisible(True)

    def show_progress(self, done: int, total: int, message: str = "") -> None:
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        self.bar.setVisible(True)
        self.show_message(message or f"{done} of {total}", "busy")

    def hide_progress(self) -> None:
        self.bar.setVisible(False)

    def retint(self) -> None:
        if self.text.text():
            self.show_message(self.text.text(), self._level)


class Card(QtWidgets.QFrame):
    """A clickable raised surface. Used by the launcher grid."""

    clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class FlowGrid(QtWidgets.QWidget):
    """A grid that re-columns itself to the width available.

    The launcher's five cards were laid out in one fixed row, so on a narrow
    window they were squeezed to unreadable columns and on a tall one they
    stretched to the full window height with a bar of dead space between the
    description and the button. Reflowing by width fixes both: the column count
    comes from the width, and the rows take their natural height.
    """

    def __init__(self, min_item_width: int = 250, spacing: int = SPACE_MD, parent=None):
        super().__init__(parent)
        self._min_w = min_item_width
        self._items: list = []
        self._cols = 0
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)

    def add_item(self, widget: QtWidgets.QWidget) -> None:
        self._items.append(widget)
        self._relayout(force=True)

    def _columns_for(self, width: int) -> int:
        if not self._items:
            return 1
        gap = self.grid.spacing()
        n = max(1, (width + gap) // (self._min_w + gap))
        return int(min(n, len(self._items)))

    def _relayout(self, force: bool = False) -> None:
        cols = self._columns_for(max(self.width(), self._min_w))
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, w in enumerate(self._items):
            self.grid.addWidget(w, i // cols, i % cols)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()


# ------------------------------------------------------------------ helpers

def hbox(*widgets, spacing: int = SPACE_SM, stretch_last: bool = False):
    """A horizontal row of widgets with the suite's standard gap."""
    lay = QtWidgets.QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QtWidgets.QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    if stretch_last:
        lay.addStretch(1)
    return lay


def equal_row(*widgets, spacing: int = SPACE_SM):
    """A row where every widget gets the same share of the width."""
    lay = QtWidgets.QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w, 1)
    return lay


def retint_tree(widget: QtWidgets.QWidget) -> None:
    """Re-render every drawn pixmap under `widget` after a theme change.

    Anything holding a baked pixmap (EmptyState, StatusStrip, an icon button)
    keeps the old theme's colour through a live switch, because the pixmap was
    painted once. Windows call this from their PaletteChange handler.
    """
    _icon_cache.clear()
    for child in widget.findChildren(QtWidgets.QWidget):
        fn = getattr(child, "retint", None)
        if callable(fn):
            fn()
            continue
        name = child.property("iconName")
        if name and isinstance(child, QtWidgets.QAbstractButton):
            child.setIcon(icon(str(name), 16))
