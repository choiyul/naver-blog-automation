"""상단 헤더 영역 UI 컴포넌트."""

from __future__ import annotations

from typing import Callable, Dict

from PyQt5 import QtCore, QtGui, QtWidgets

from ...core.utils import show_notification


class HeaderBar(QtWidgets.QWidget):
    tips_requested = QtCore.pyqtSignal()
    cleanup_browser_requested = QtCore.pyqtSignal()  # 브라우저 정리 시그널

    def __init__(
        self,
        toggle_theme: Callable[[], None],
        toggle_mode: Callable[[bool], None],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._toggle_theme = toggle_theme
        self._toggle_mode = toggle_mode
        
        # 아이콘 캐시 (성능 최적화) - 최대 10개로 제한
        self._icon_cache: Dict[str, QtGui.QIcon] = {}
        self._max_cache_size = 10
        
        self._build_ui()  # UI 구성 호출

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        title_layout = QtWidgets.QVBoxLayout()
        title_layout.setSpacing(2)
        title = QtWidgets.QLabel("📝 NBlog Studio")
        title.setObjectName("appTitle")
        subtitle = QtWidgets.QLabel("네이버 블로그 AI & 수동 포스팅 허브")
        subtitle.setObjectName("appSubtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        controls_layout = QtWidgets.QHBoxLayout()
        controls_layout.setSpacing(8)
        controls_layout.setAlignment(QtCore.Qt.AlignVCenter)  # 수직 중앙 정렬

        # 브라우저 정리 버튼
        self.cleanup_button = QtWidgets.QPushButton("🔧")
        self.cleanup_button.setObjectName("themeToggleButton")
        self.cleanup_button.setToolTip("브라우저 정리 (로그인 세션 보존)")
        self.cleanup_button.setFixedSize(44, 34)
        self.cleanup_button.clicked.connect(self.cleanup_browser_requested.emit)
        controls_layout.addWidget(self.cleanup_button, 0, QtCore.Qt.AlignVCenter)

        # Tips 버튼
        self.tips_button = QtWidgets.QPushButton("✨ Tips")
        self.tips_button.setObjectName("accentButton")
        self.tips_button.setFixedHeight(34)
        self.tips_button.clicked.connect(self.tips_requested.emit)
        controls_layout.addWidget(self.tips_button, 0, QtCore.Qt.AlignVCenter)

        # 모드 전환 버튼
        self.mode_button = QtWidgets.QPushButton()
        self.mode_button.setObjectName("modeToggleButton")
        self.mode_button.setCheckable(True)
        self.mode_button.setChecked(False)
        self.mode_button.setFixedHeight(34)
        self.mode_button.clicked.connect(self._handle_mode_clicked)
        controls_layout.addWidget(self.mode_button, 0, QtCore.Qt.AlignVCenter)

        # 테마 버튼
        self.theme_button = QtWidgets.QPushButton()
        self.theme_button.setObjectName("themeToggleButton")
        self.theme_button.setCheckable(True)
        self.theme_button.setChecked(True)
        self.theme_button.setFixedSize(44, 34)
        self.theme_button.setIconSize(QtCore.QSize(24, 24))
        self.theme_button.clicked.connect(self._handle_theme_clicked)
        controls_layout.addWidget(self.theme_button, 0, QtCore.Qt.AlignVCenter)
        layout.addLayout(title_layout, 1)
        layout.addStretch(1)
        layout.addLayout(controls_layout)

    def _handle_mode_clicked(self, checked: bool) -> None:
        self._toggle_mode(checked)
        mode_name = "AI 모드" if checked else "수동 모드"
        show_notification(self, "✨", mode_name, "모드가 변경되었습니다.")

    def _handle_theme_clicked(self) -> None:
        self._toggle_theme()
        show_notification(self, "🌙", "테마 변경", "테마가 변경되었습니다.")


    def set_mode(self, is_ai: bool) -> None:
        self.mode_button.blockSignals(True)
        self.mode_button.setChecked(is_ai)
        self._update_mode_button_text(is_ai)
        self.mode_button.blockSignals(False)

    def set_theme_icon(self, theme_map: Dict[str, object], is_dark: bool) -> None:
        self.theme_button.blockSignals(True)
        self.theme_button.setChecked(is_dark)
        color_active = str(theme_map.get("theme_icon_active", "#0c111c"))
        color_inactive = str(theme_map.get("theme_icon", "#0f172a"))
        color = color_active if is_dark else color_inactive
        
        # 캐시된 아이콘 사용 (성능 최적화)
        icon_key = f"{'moon' if is_dark else 'sun'}_{color}"
        if icon_key not in self._icon_cache:
            # 캐시 크기 제한
            if len(self._icon_cache) >= self._max_cache_size:
                # 가장 오래된 항목 제거 (FIFO)
                oldest_key = next(iter(self._icon_cache))
                del self._icon_cache[oldest_key]
            
            self._icon_cache[icon_key] = (
                self._create_moon_icon(color) if is_dark else self._create_sun_icon(color)
            )
        
        self.theme_button.setIcon(self._icon_cache[icon_key])
        self.theme_button.setText("")
        self.theme_button.blockSignals(False)

    def _update_mode_button_text(self, is_ai: bool) -> None:
        self.mode_button.setText("AI 모드" if is_ai else "수동 모드")

    def _create_sun_icon(self, color: str) -> QtGui.QIcon:
        size = 28
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        sun_color = QtGui.QColor(color)
        center = QtCore.QPointF(size / 2, size / 2)

        painter.setPen(QtGui.QPen(sun_color, 2))
        painter.setBrush(QtGui.QBrush(sun_color.lighter(115)))
        painter.drawEllipse(center, size * 0.3, size * 0.3)

        painter.setPen(QtGui.QPen(sun_color, 2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        # 미리 계산된 8방향 좌표 (45도 간격)
        rays = [
            (0.28, 0.0), (0.198, 0.198), (0.0, 0.28), (-0.198, 0.198),
            (-0.28, 0.0), (-0.198, -0.198), (0.0, -0.28), (0.198, -0.198)
        ]
        for ray_x, ray_y in rays:
            start = QtCore.QPointF(center.x() + ray_x * size, center.y() + ray_y * size)
            end = QtCore.QPointF(center.x() + ray_x * size * 1.5, center.y() + ray_y * size * 1.5)
            painter.drawLine(start, end)

        painter.end()
        return QtGui.QIcon(pixmap)

    def _create_moon_icon(self, color: str) -> QtGui.QIcon:
        size = 24
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        moon_color = QtGui.QColor(color)

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(moon_color)
        painter.drawEllipse(QtCore.QRectF(4, 4, size - 8, size - 8))

        painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 0)))
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
        painter.drawEllipse(QtCore.QRectF(9, 4, size - 8, size - 8))
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        painter.setPen(QtGui.QPen(moon_color.darker(140), 1))
        painter.drawArc(QtCore.QRect(4, 4, size - 8, size - 8), 30 * 16, 300 * 16)
        painter.end()

        return QtGui.QIcon(pixmap)


