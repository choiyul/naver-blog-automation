"""AI 모드와 자동화 제어를 통합한 패널."""

from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .mode_panels import AiModePanel, DisabledOverlay


class AiControlPanel(QtWidgets.QWidget):
    """AI 설정과 자동화 제어를 통합한 패널."""

    # AI 패널 시그널들을 그대로 전달
    api_key_changed = QtCore.pyqtSignal(str)
    validate_api_key = QtCore.pyqtSignal()
    keyword_changed = QtCore.pyqtSignal(str)
    model_changed = QtCore.pyqtSignal(str)
    count_changed = QtCore.pyqtSignal(int)
    
    # 자동화 제어 시그널들
    start_requested = QtCore.pyqtSignal()
    stop_requested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._setup_overlay()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # AI 모드 패널
        self.ai_panel = AiModePanel()
        layout.addWidget(self.ai_panel)
        
        # 간격 추가
        layout.addSpacing(8)
        
        # 자동화 제어 패널 (다른 패널들과 동일한 QGroupBox 스타일)
        control_panel = QtWidgets.QGroupBox("자동화 제어")
        control_layout = QtWidgets.QVBoxLayout(control_panel)
        control_layout.setSpacing(12)
        control_layout.setContentsMargins(16, 16, 16, 16)
        
        # 시작/정지 버튼
        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.addStretch()
        
        self.start_button = QtWidgets.QPushButton("시작")
        self.start_button.setObjectName("primaryButton")
        sp_start = self.start_button.sizePolicy()
        sp_start.setHorizontalPolicy(QtWidgets.QSizePolicy.Preferred)
        sp_start.setVerticalPolicy(QtWidgets.QSizePolicy.Fixed)
        self.start_button.setSizePolicy(sp_start)
        self.start_button.setMinimumHeight(40)
        self.start_button.clicked.connect(self.start_requested.emit)
        buttons_layout.addWidget(self.start_button)
        
        buttons_layout.addSpacing(20)
        
        self.stop_button = QtWidgets.QPushButton("정지")
        self.stop_button.setObjectName("dangerButton")
        sp_stop = self.stop_button.sizePolicy()
        sp_stop.setHorizontalPolicy(QtWidgets.QSizePolicy.Preferred)
        sp_stop.setVerticalPolicy(QtWidgets.QSizePolicy.Fixed)
        self.stop_button.setSizePolicy(sp_stop)
        self.stop_button.setMinimumHeight(40)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        buttons_layout.addWidget(self.stop_button)
        
        buttons_layout.addStretch()
        control_layout.addLayout(buttons_layout)
        
        layout.addWidget(control_panel)
        
        # AI 패널 시그널 연결
        self._connect_ai_signals()

    def _setup_overlay(self) -> None:
        """비활성화 오버레이 설정 - AI 패널에만 적용."""
        self.disabled_overlay = DisabledOverlay("AI 모드가 비활성화입니다", self.ai_panel)
        self.disabled_overlay.hide()  # 초기에는 숨김
        
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """위젯 크기 변경 시 AI 패널 오버레이 크기도 조정."""
        super().resizeEvent(event)
        if hasattr(self, 'disabled_overlay') and hasattr(self, 'ai_panel'):
            # AI 패널 크기에 맞춰 오버레이 조정 - 패널 경계 내에 확실히 위치
            ai_panel_size = self.ai_panel.size()
            overlay_size = ai_panel_size
            overlay_size.setWidth(overlay_size.width() - 32)  # 좌우 16px씩 여백 유지
            overlay_size.setHeight(overlay_size.height() - 32)  # 상하 16px씩 여백으로 높이 줄임
            self.disabled_overlay.resize(overlay_size)
            self.disabled_overlay.move(16, 16)  # 좌우 16px, 상하 16px 여백으로 이동
    
    def set_ai_mode_enabled(self, enabled: bool) -> None:
        """AI 모드만 활성화/비활성화 (자동화 제어는 유지)."""
        if hasattr(self, 'disabled_overlay'):
            if enabled:
                self.disabled_overlay.hide()
                self.ai_panel.setEnabled(True)
            else:
                self.disabled_overlay.show()
                self.disabled_overlay.raise_()  # 맨 위로 올리기
                # AI 패널 자체는 비활성화하지 않음 (오버레이로만 차단)
    
    def setEnabled(self, enabled: bool) -> None:
        """전체 패널 활성화/비활성화 (작업 진행 중에만 사용)."""
        super().setEnabled(enabled)
        # 작업 진행 중일 때만 전체 비활성화, 모드 전환과는 별개

    def _connect_ai_signals(self) -> None:
        """AI 패널의 시그널들을 이 패널의 시그널로 전달."""
        self.ai_panel.api_key_changed.connect(self.api_key_changed.emit)
        self.ai_panel.validate_api_key.connect(self.validate_api_key.emit)
        self.ai_panel.keyword_changed.connect(self.keyword_changed.emit)
        self.ai_panel.model_changed.connect(self.model_changed.emit)
        self.ai_panel.count_changed.connect(self.count_changed.emit)

    # AI 패널 메소드들을 위임
    def set_api_status(self, text: str, state: str = "default") -> None:
        """AI 패널의 API 상태 설정."""
        self.ai_panel.set_api_status(text, state)

    def set_validate_enabled(self, enabled: bool) -> None:
        """AI 패널의 키 확인 버튼 활성화/비활성화."""
        self.ai_panel.set_validate_enabled(enabled)

    def set_controls_enabled(self, enabled: bool) -> None:
        """자동화 제어 버튼들의 활성화/비활성화.
        
        Args:
            enabled: True면 작업 대기 상태 (시작 버튼 활성화, 정지 버튼 비활성화)
                   False면 작업 진행 중 (시작 버튼 비활성화, 정지 버튼 활성화)
        """
        self.start_button.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)

    @property
    def api_key_edit(self):
        """AI 패널의 API 키 입력 필드."""
        return self.ai_panel.api_key_edit

    @property
    def keyword_edit(self):
        """AI 패널의 키워드 입력 필드."""
        return self.ai_panel.keyword_edit

    @property
    def model_combo(self):
        """AI 패널의 모델 선택 콤보박스."""
        return self.ai_panel.model_combo

    @property
    def count_group(self):
        """AI 패널의 포스팅 개수 라디오 버튼 그룹."""
        return self.ai_panel.count_group
