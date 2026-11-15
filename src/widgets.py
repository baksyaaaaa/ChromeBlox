"""Shared UI bits: labels/cards, image helpers, background jobs."""
import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def scrub(text):
    """Never show your Windows username / folder paths on screen."""
    text = str(text).replace(str(Path.home()), "~")
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user and len(user) > 2:
        text = text.replace(user, "user")
    return text


def label(text, kind=None):
    l = QLabel(text)
    if kind == "muted":
        l.setProperty("muted", True)
        l.setWordWrap(True)
    elif kind:
        l.setProperty(kind, True)
    return l


def header(title, sub):
    box = QVBoxLayout()
    box.setSpacing(2)
    box.addWidget(label(title, "h1"))
    box.addWidget(label(sub, "muted"))
    return box


def card(margins=(22, 18, 22, 18), prop="card"):
    f = QFrame()
    f.setProperty(prop, True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(10)
    return f, lay


def ghost(btn):
    btn.setProperty("ghost", True)
    return btn


def row(*widgets, stretch=True):
    """Widgets in a row. Pass (widget, n) to give one a stretch factor, or an int for a spacer stretch."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for x in widgets:
        if isinstance(x, int):
            lay.addStretch(x)
        elif isinstance(x, tuple):
            lay.addWidget(x[0], x[1])
        else:
            lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


def clear_layout(lay):
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def dot_icon(color):
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    return QIcon(pm)


def app_icon(accent):
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(accent))
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 28)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "C")
    p.end()
    return QIcon(pm)


def pixmap_from(data):
    pm = QPixmap()
    if data:
        pm.loadFromData(data)
    return pm


def rounded(pm, w, h=None, radius=12):
    """Crop-fill pm into w×h with rounded corners (radius=None -> circle)."""
    h = h or w
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    if pm is None or pm.isNull():
        return out
    s = pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    r = min(w, h) / 2 if radius is None else radius
    path.addRoundedRect(0, 0, w, h, r, r)
    p.setClipPath(path)
    p.drawPixmap(-(s.width() - w) // 2, -(s.height() - h) // 2, s)
    p.end()
    return out


def stack_faces(pixmaps, size=34, overlap=12, ring="#26292f", backdrop="#3a3d44", total=0):
    """Overlapping round headshots, like the avatars row on Discord/Modrinth. Adds a '+N' bubble."""
    shown = pixmaps[:5]
    extra = max(0, total - len(shown))
    n = len(shown) + (1 if extra else 0)
    n = max(n, 1)
    width = size + (n - 1) * (size - overlap)
    out = QPixmap(width + 2, size + 2)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    x = 1
    for pm in shown:
        p.setPen(QPen(QColor(ring), 3))
        p.setBrush(QColor(backdrop))
        p.drawEllipse(x, 1, size, size)
        if pm is not None and not pm.isNull():
            p.drawPixmap(x, 1, rounded(pm, size, radius=None))
        x += size - overlap
    if extra:
        p.setPen(QPen(QColor(ring), 3))
        p.setBrush(QColor(backdrop))
        p.drawEllipse(x, 1, size, size)
        p.setPen(QColor("#ffffff"))
        f = QFont("Segoe UI", 9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(x, 1, size, size, Qt.AlignmentFlag.AlignCenter, f"+{extra}")
    if not shown and not extra:
        p.setPen(QPen(QColor(ring), 3))
        p.setBrush(QColor(backdrop))
        p.drawEllipse(1, 1, size, size)
    p.end()
    return out


# ---------------------------------------------------------------- background jobs
class _Sig(QObject):
    done = Signal(object, object)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.sig = _Sig()
        self.setAutoDelete(False)

    def run(self):
        try:
            r, e = self.fn(), None
        except Exception as ex:  # handed to the callback
            r, e = None, ex
        try:
            self.sig.done.emit(r, e)
        except RuntimeError:
            pass  # app closed while this was running


_alive = set()


def bg(fn, cb=None):
    """Run fn() on a worker thread, then cb(result, error) back on the UI thread."""
    job = _Job(fn)
    _alive.add(job)

    def finish(r, e):
        _alive.discard(job)
        if cb:
            try:
                cb(r, e)
            except RuntimeError:
                pass  # widget went away meanwhile

    job.sig.done.connect(finish)
    QThreadPool.globalInstance().start(job)


# ---------------------------------------------------------------- wrapping grid
from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QLayout  # noqa: E402


class FlowLayout(QLayout):
    """Lays tiles out left to right and wraps to the next row when there's no room."""

    def __init__(self, parent=None, spacing=10):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._sp
            if nx - self._sp > rect.right() + 1 and line > 0:
                x, y = rect.x(), y + line + self._sp
                nx, line = x + hint.width() + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x, line = nx, max(line, hint.height())
        return y + line - rect.y()
