"""공통 유틸리티 함수들."""

from __future__ import annotations

from typing import Optional
from PyQt5 import QtCore, QtWidgets, QtGui


def show_notification(
    parent: QtWidgets.QWidget,
    icon: str,
    title: str,
    message: str,
    callback: Optional[callable] = None
) -> None:
    """알림을 비동기적으로 표시합니다."""
    QtCore.QTimer.singleShot(0, lambda: _show_notification_delayed(parent, icon, title, message, callback))


def _show_notification_delayed(
    parent: QtWidgets.QWidget,
    icon: str,
    title: str,
    message: str,
    callback: Optional[callable] = None
) -> None:
    """지연된 알림 표시 (UI 블로킹 방지)."""
    dialog = QtWidgets.QDialog(parent.window())
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
    if callback:
        button.clicked.connect(callback)

    layout.addWidget(title_label, 0, QtCore.Qt.AlignLeft)
    layout.addLayout(content_layout)
    layout.addWidget(button, 0, QtCore.Qt.AlignRight)

    dialog.adjustSize()
    parent_rect = parent.window().geometry()
    center_x = parent_rect.center().x() - dialog.width() // 2
    center_y = parent_rect.center().y() - dialog.height() // 2
    dialog.move(center_x, center_y)
    dialog.exec_()


def create_icon_cache() -> dict:
    """아이콘 캐시를 생성합니다."""
    return {}


def safe_disconnect(signal, slot) -> None:
    """안전하게 시그널-슬롯 연결을 해제합니다."""
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass  # 이미 연결이 해제되었거나 연결되지 않은 경우 무시
