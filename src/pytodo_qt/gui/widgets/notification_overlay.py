"""In-app notification overlay: frameless banner widgets stacked vertically
in the top-right of the primary screen.

Provides cross-platform notification rendering without depending on OS
notification centers. Each `NotificationOverlay` is an independent
top-level window painted directly by the application, so the banner
renders identically on macOS, Linux, and Windows without permission
prompts, bundle-identity constraints, or distribution signing.

`NotificationManager` owns the placement math, the visible-count cap,
and the overflow queue. It is idempotent against main-window hide/show
cycles because each overlay is its own top-level window with the
WindowStaysOnTopHint flag.

Public API is minimal: `NotificationManager.show(title, body, timeout)`
enqueues or displays a banner; the manager handles the rest.
"""

from __future__ import annotations

import logging
from collections import deque

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_log = logging.getLogger(__name__)

_MIN_WIDTH = 360
_MAX_WIDTH = 420
# Banners size to content within these bounds. _MIN_HEIGHT preserves the
# visual baseline that short single-line bodies always landed at; _MAX_HEIGHT
# caps growth so a pathologically long body can't take over the screen.
# Bodies past the cap are scrollable inside the body's QScrollArea wrap
# rather than clipped — short and medium bodies render in a fully-expanded
# banner with no scroll bar; only pathological lengths trigger one.
_MIN_HEIGHT = 88
_MAX_HEIGHT = 240
_HORIZONTAL_MARGIN = 16
_TOP_MARGIN = 16
_STACK_SPACING = 10
_CORNER_RADIUS = 10
_ANIMATION_DURATION_MS = 240
_DEFAULT_TIMEOUT_MS = 5000
_MAX_VISIBLE_DEFAULT = 4


class _BodyScrollArea(QScrollArea):
    """QScrollArea that delegates ``sizeHint`` and ``heightForWidth`` to its
    wrapped widget so the parent layout grows to fit body content naturally,
    capped only by the overlay's overall ``_MAX_HEIGHT``. Past the cap, the
    vertical scroll bar appears and the body scrolls inside the area rather
    than clipping at the overlay edge.

    Re-emits left mouse presses on the viewport as ``body_clicked`` so the
    overlay's existing click-to-dismiss behavior survives the wrap — the
    inner ``QLabel`` carries ``WA_TransparentForMouseEvents`` and clicks fall
    through the viewport to this widget instead of bubbling to the overlay.
    """

    body_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        viewport = self.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
        self.setStyleSheet("QScrollArea { background: transparent; border: 0; }")
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        sp.setVerticalPolicy(QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def sizeHint(self) -> QSize:  # noqa: N802
        widget = self.widget()
        if widget is None:
            return super().sizeHint()
        return widget.sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # Allow the layout to shrink the area below the inner widget's natural
        # height so the overall overlay can hit ``_MAX_HEIGHT``; the scroll
        # bar exposes the rest of the body once that happens.
        return QSize(0, 0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        widget = self.widget()
        return widget is not None and widget.hasHeightForWidth()

    def heightForWidth(self, a0: int) -> int:  # noqa: N802
        widget = self.widget()
        if widget is None or not widget.hasHeightForWidth():
            return super().heightForWidth(a0)
        # Reserve scroll-bar width unconditionally — over-allocates a few
        # pixels of vertical space when no bar appears, which is preferable
        # to under-allocating and clipping the last line.
        bar = self.verticalScrollBar()
        bar_width = bar.sizeHint().width() if bar is not None else 0
        return widget.heightForWidth(max(0, a0 - bar_width))

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.body_clicked.emit()
        super().mousePressEvent(a0)


class NotificationOverlay(QWidget):
    """Frameless banner window for a single notification.

    Renders a rounded-rectangle panel containing a bold title line, a
    body paragraph, and a close glyph in the corner. The widget is a
    top-level tool window so it floats above the application's own
    windows and remains visible when the main window is minimized or
    hidden to the system tray.

    Signals
    -------
    body_clicked : emitted when the user clicks anywhere on the body
        area (not on the close glyph). Consumers use this to route to
        an action (e.g. open a task detail).
    dismissed : emitted when the user clicks the close glyph OR when
        the auto-dismiss timer elapses. Either path triggers the
        slide-out animation and destruction.
    """

    body_clicked = pyqtSignal()
    dismissed = pyqtSignal()

    def __init__(
        self,
        title: str,
        body: str,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Size to content between min and max so long bodies don't clip;
        # short bodies still settle at the original 88 px visual baseline.
        self.setMinimumHeight(_MIN_HEIGHT)
        self.setMaximumHeight(_MAX_HEIGHT)
        self.setMinimumWidth(_MIN_WIDTH)
        self.setMaximumWidth(_MAX_WIDTH)

        self._title = title
        self._body = body
        self._dismissing = False
        self._paused = False

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

        self._build_layout()

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._start_dismiss)
        if timeout_ms > 0:
            self._timeout_timer.start(timeout_ms)
        self._timeout_ms = timeout_ms

        self._slide_anim: QPropertyAnimation | None = None

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 10, 12)
        outer.setSpacing(10)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(3)

        title_label = QLabel(self._title)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: palette(window-text);")
        title_label.setWordWrap(False)
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        body_label = QLabel(self._body)
        body_label.setStyleSheet("color: palette(window-text); background: transparent;")
        body_label.setWordWrap(True)
        body_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        body_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        body_scroll = _BodyScrollArea(self)
        body_scroll.setWidget(body_label)
        body_scroll.body_clicked.connect(self._on_body_area_clicked)

        text_column.addWidget(title_label)
        text_column.addWidget(body_scroll, 1)
        outer.addLayout(text_column, 1)

        close_btn = QPushButton("\u2715", self)
        close_btn.setFlat(True)
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { border: none; color: palette(mid); font-size: 14px; }"
            "QPushButton:hover { color: palette(window-text); }"
        )
        close_btn.clicked.connect(self._start_dismiss)

        close_column = QVBoxLayout()
        close_column.setContentsMargins(0, 0, 0, 0)
        close_column.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        close_column.addStretch(1)
        outer.addLayout(close_column)

        self._close_btn = close_btn
        self._body_label = body_label
        self._body_scroll = body_scroll

    def _on_body_area_clicked(self) -> None:
        # Body-click semantic preserved across the QScrollArea wrap: the
        # scroll area swallows clicks that the bare QLabel previously let
        # bubble up to the overlay's mousePressEvent. Re-emit and dismiss.
        if self._dismissing:
            return
        self.body_clicked.emit()
        self._start_dismiss()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, a0) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(
            float(rect.x()),
            float(rect.y()),
            float(rect.width()),
            float(rect.height()),
            _CORNER_RADIUS,
            _CORNER_RADIUS,
        )
        fill = self.palette().window().color()
        painter.fillPath(path, fill)
        border = self.palette().mid().color()
        pen = QPen(border)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        if a0.button() != Qt.MouseButton.LeftButton:
            return
        if self._close_btn.geometry().contains(a0.pos()):
            return
        self.body_clicked.emit()
        self._start_dismiss()

    def enterEvent(self, event) -> None:  # noqa: N802
        # Pause auto-dismiss while the cursor hovers — the user is
        # presumably reading. Timer restarts on leave.
        if self._timeout_timer.isActive():
            self._timeout_timer.stop()
            self._paused = True

    def leaveEvent(self, a0) -> None:  # noqa: N802
        if self._paused and not self._dismissing and self._timeout_ms > 0:
            self._timeout_timer.start(self._timeout_ms)
        self._paused = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def slide_in(self, target: QPoint) -> None:
        """Animate from off-screen right to the target position."""
        start_x = target.x() + self.width() + 40
        self.move(start_x, target.y())
        self.show()
        # Parent the animation to ``self`` so it stays alive as long as the
        # widget does. A bare-Python reference (no QObject parent) would be
        # GC'd the moment ``self._slide_anim`` is reassigned by a follow-up
        # ``slide_to`` or ``_start_dismiss``; the destructor calls ``stop()``
        # and the previous animation's ``finished`` connection never fires.
        # That race stranded multi-dismiss banners on screen pre-fix.
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(_ANIMATION_DURATION_MS)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._slide_anim = anim

    def slide_to(self, target: QPoint) -> None:
        """Animate from current position to a new target (e.g. when a
        banner above is dismissed and this one moves up)."""
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(_ANIMATION_DURATION_MS)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._slide_anim = anim

    def _start_dismiss(self) -> None:
        if self._dismissing:
            return
        self._dismissing = True
        self._timeout_timer.stop()
        current = self.pos()
        off_screen = QPoint(current.x() + self.width() + 60, current.y())
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(_ANIMATION_DURATION_MS)
        anim.setStartValue(current)
        anim.setEndValue(off_screen)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self._finalize_dismiss)
        anim.start()
        self._slide_anim = anim

    def _finalize_dismiss(self) -> None:
        self.dismissed.emit()
        self.hide()
        self.deleteLater()


class NotificationManager:
    """Owns the vertical stack of visible `NotificationOverlay` windows.

    The top-right corner of the primary screen is the anchor. New
    banners slide in at the top of the stack; existing banners slide
    down to make room. When a banner is dismissed, those below it
    slide up. Beyond `max_visible`, additional notifications are
    queued and promoted as slots free up.
    """

    def __init__(self, max_visible: int = _MAX_VISIBLE_DEFAULT) -> None:
        self._max_visible = max(1, max_visible)
        self._visible: list[NotificationOverlay] = []
        self._queue: deque[tuple[str, str, int]] = deque()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def show(
        self,
        title: str,
        body: str,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> NotificationOverlay | None:
        """Display a banner immediately if there is room; otherwise
        queue it for display once a slot frees up. Returns the
        overlay instance if shown immediately, None if queued."""
        if len(self._visible) >= self._max_visible:
            self._queue.append((title, body, timeout_ms))
            return None
        return self._spawn(title, body, timeout_ms)

    def dismiss_all(self) -> None:
        """Start dismissal on every visible banner. The queue is
        cleared so nothing new is promoted."""
        self._queue.clear()
        for banner in list(self._visible):
            banner._start_dismiss()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _spawn(self, title: str, body: str, timeout_ms: int) -> NotificationOverlay | None:
        app = QApplication.instance()
        if app is None:
            _log.warning("NotificationManager._spawn: no QApplication instance; skip")
            return None

        banner = NotificationOverlay(title, body, timeout_ms=timeout_ms)
        banner.dismissed.connect(lambda b=banner: self._on_dismissed(b))
        banner.adjustSize()

        # Survivor count, not total visible count — the new banner
        # belongs at the bottom of the non-dismissing stack so it
        # doesn't position itself over (or below) a sibling that's
        # currently sliding off-screen.
        survivor_count = sum(1 for b in self._visible if not b._dismissing)
        target = self._slot_position(survivor_count, banner.size())
        self._visible.append(banner)
        banner.slide_in(target)
        return banner

    def _on_dismissed(self, banner: NotificationOverlay) -> None:
        if banner in self._visible:
            self._visible.remove(banner)
        self._reflow()
        self._promote_queued()

    def _reflow(self) -> None:
        # Skip dismissing siblings: a banner mid-dismiss has its
        # ``_slide_anim`` set to its in-flight dismiss animation, with
        # ``finished`` connected to ``_finalize_dismiss``. Calling
        # ``slide_to`` here would overwrite that reference, drop the
        # dismiss animation's last Python ref, and (with the widget-
        # parented animation safety net in place to prevent GC) still
        # cancel the slide-out by replacing it with a slide-back-to-slot
        # animation. Either way the banner gets stranded with
        # ``_dismissing=True`` and no further close is possible.
        survivor_index = 0
        for banner in self._visible:
            if banner._dismissing:
                continue
            target = self._slot_position(survivor_index, banner.size())
            if banner.pos() != target:
                banner.slide_to(target)
            survivor_index += 1

    def _promote_queued(self) -> None:
        while self._queue and len(self._visible) < self._max_visible:
            title, body, timeout_ms = self._queue.popleft()
            self._spawn(title, body, timeout_ms)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    @staticmethod
    def _primary_screen_geometry() -> QRect:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            # Fallback to a reasonable default if no screen is available
            # (headless test environments can hit this path).
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    def _slot_position(self, index: int, size: QSize) -> QPoint:
        """Top-right corner position for a banner at the given survivor
        index — the position counting only non-dismissing visible banners.

        Walks through the actual heights of preceding non-dismissing
        banners rather than assuming a uniform height: banners now size
        to content between ``_MIN_HEIGHT`` and ``_MAX_HEIGHT`` so a flat
        ``index * height`` calculation would mis-stack mixed-size rows.
        Dismissing siblings are skipped so a survivor below a banner
        that just started sliding away collapses into the freed slot
        immediately, instead of holding the gap until the dismissing
        sibling finishes its animation and is removed from ``_visible``.
        """
        screen = self._primary_screen_geometry()
        x = screen.right() - size.width() - _HORIZONTAL_MARGIN
        y = screen.top() + _TOP_MARGIN
        survivors = [b for b in self._visible if not b._dismissing]
        for i in range(min(index, len(survivors))):
            y += survivors[i].height() + _STACK_SPACING
        # Indices beyond the survivor count (only happens for a freshly-
        # arrived banner that hasn't been appended yet, when every
        # current sibling is mid-dismiss) get a conservative min-height
        # contribution per slot. _MAX_VISIBLE is small enough that the
        # cumulative drift of a few _MIN_HEIGHT placeholders stays bounded.
        for _ in range(max(0, index - len(survivors))):
            y += _MIN_HEIGHT + _STACK_SPACING
        return QPoint(x, y)

    # ------------------------------------------------------------------
    # Introspection (testing)
    # ------------------------------------------------------------------

    @property
    def visible_count(self) -> int:
        return len(self._visible)

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    @property
    def visible(self) -> list[NotificationOverlay]:
        return list(self._visible)
