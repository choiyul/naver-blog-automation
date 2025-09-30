"""하단 진행 상태 표시 컴포넌트."""

from __future__ import annotations

from PyQt5 import QtWidgets


class StatusBar(QtWidgets.QGroupBox):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("자동화 진행 상태", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.stage_label = QtWidgets.QLabel("현재 작업: -")
        self.status_label = QtWidgets.QLabel("상태: 준비")
        self.percent_label = QtWidgets.QLabel("0%")

        progress_layout = QtWidgets.QHBoxLayout()
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.percent_label)

        layout.addLayout(progress_layout)
        layout.addWidget(self.stage_label)
        layout.addWidget(self.status_label)

    def reset(self) -> None:
        self.progress_bar.setValue(0)
        self.stage_label.setText("현재 작업: -")
        self.status_label.setText("상태: 준비")
        self.percent_label.setText("0%")


