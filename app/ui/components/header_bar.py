"""상단 헤더 영역 UI 컴포넌트."""

from __future__ import annotations

from typing import Callable, Dict
import math

from PyQt5 import QtCore, QtGui, QtWidgets


class HeaderBar(QtWidgets.QWidget):
    tips_requested = QtCore.pyqtSignal()

    def __init__(
        self,
        toggle_theme: Callable[[], None],
        toggle_mode: Callable[[bool], None],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._toggle_theme = toggle_theme
        self._toggle_mode = toggle_mode
        
        # 아이콘 캐시 (성능 최적화)
        self._icon_cache: Dict[str, QtGui.QIcon] = {}
        
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
        controls_layout.setSpacing(12)

        self.tips_button = QtWidgets.QPushButton("✨ Tips")
        self.tips_button.setObjectName("accentButton")
        self.tips_button.clicked.connect(self.tips_requested.emit)
        controls_layout.addWidget(self.tips_button)

        self.mode_button = QtWidgets.QPushButton()
        self.mode_button.setObjectName("modeToggleButton")
        self.mode_button.setCheckable(True)
        self.mode_button.setChecked(False)  # 기본값을 수동모드(False)로 변경
        self.mode_button.clicked.connect(self._handle_mode_clicked)
        controls_layout.addWidget(self.mode_button)

        self.theme_button = QtWidgets.QPushButton()
        self.theme_button.setObjectName("themeToggleButton")
        self.theme_button.setCheckable(True)
        self.theme_button.setChecked(True)
        self.theme_button.setIconSize(QtCore.QSize(26, 26))
        self.theme_button.clicked.connect(self._handle_theme_clicked)
        controls_layout.addWidget(self.theme_button)
        layout.addLayout(title_layout, 1)
        layout.addStretch(1)
        layout.addLayout(controls_layout)

    def _handle_mode_clicked(self, checked: bool) -> None:
        self._toggle_mode(checked)
        mode_name = "AI 모드" if checked else "수동 모드"
        self._show_notification("✨", mode_name, "모드가 변경되었습니다.")

    def _handle_theme_clicked(self) -> None:
        self._toggle_theme()
        self._show_notification("🌙", "테마 변경", "테마가 변경되었습니다.")

    def _show_notification(self, icon: str, title: str, message: str) -> None:
        # 알림을 비동기적으로 표시 (성능 최적화)
        QtCore.QTimer.singleShot(0, lambda: self._show_notification_delayed(icon, title, message))
    
    def _show_notification_delayed(self, icon: str, title: str, message: str) -> None:
        """지연된 알림 표시 (UI 블로킹 방지)"""
        dialog = QtWidgets.QDialog(self.window())
        dialog.setWindowFlags(
            QtCore.Qt.Dialog
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowSystemMenuHint
        )
        dialog.setModal(True)
        dialog.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        outer_layout = QtWidgets.QVBoxLayout(dialog)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        container = QtWidgets.QFrame()
        container.setObjectName("notificationContainer")
        outer_layout.addWidget(container)

        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("notificationTitle")

        content_layout = QtWidgets.QHBoxLayout()
        content_layout.setSpacing(16)

        icon_label = QtWidgets.QLabel(icon)
        icon_label.setObjectName("notificationIcon")

        message_label = QtWidgets.QLabel(message)
        message_label.setObjectName("notificationMessage")
        message_label.setAlignment(QtCore.Qt.AlignCenter)

        content_layout.addWidget(icon_label, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        content_layout.addWidget(message_label, 1)

        button = QtWidgets.QPushButton("확인")
        button.setObjectName("notificationConfirmButton")
        button.clicked.connect(dialog.accept)

        layout.addWidget(title_label, 0, QtCore.Qt.AlignLeft)
        layout.addLayout(content_layout)
        layout.addWidget(button, 0, QtCore.Qt.AlignRight)

        dialog.adjustSize()
        parent_rect = self.window().geometry()
        center_x = parent_rect.center().x() - dialog.width() // 2
        center_y = parent_rect.center().y() - dialog.height() // 2
        dialog.move(center_x, center_y)
        dialog.exec_()

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
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            start = QtCore.QPointF(center.x() + math.cos(rad) * size * 0.28, center.y() + math.sin(rad) * size * 0.28)
            end = QtCore.QPointF(center.x() + math.cos(rad) * size * 0.42, center.y() + math.sin(rad) * size * 0.42)
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


