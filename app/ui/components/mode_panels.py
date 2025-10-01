"""AI/수동 모드 입력 패널."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from ...core.constants import MAX_POST_COUNT


class DisabledOverlay(QtWidgets.QWidget):
    """패널 비활성화 시 표시할 오버레이."""

    def __init__(self, message: str = "수동 모드가 비활성화입니다", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("disabledOverlay")
        self._message = message
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)  # 마진을 늘려서 패널 경계 내에 확실히 위치
        layout.setAlignment(QtCore.Qt.AlignCenter)

        # 중앙 메시지 컨테이너 - 패널 크기에 맞게 조정
        message_container = QtWidgets.QFrame()
        message_container.setObjectName("disabledMessageContainer")
        message_container.setMaximumWidth(280)  # 최대 너비 제한으로 오버플로우 방지
        message_container.setMinimumSize(260, 100)
        sp = message_container.sizePolicy()
        sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Maximum)  # 최대 크기로 제한
        sp.setVerticalPolicy(QtWidgets.QSizePolicy.Preferred)
        message_container.setSizePolicy(sp)
        
        container_layout = QtWidgets.QVBoxLayout(message_container)
        container_layout.setContentsMargins(22, 18, 22, 18)  # 패딩을 더 넉넉히
        container_layout.setAlignment(QtCore.Qt.AlignCenter)
        container_layout.setSpacing(8)  # 아이콘과 메시지 간격도 조금 늘림

        # 아이콘
        icon_label = QtWidgets.QLabel("🚫")
        icon_label.setAlignment(QtCore.Qt.AlignCenter)
        icon_label.setObjectName("disabledIcon")
        container_layout.addWidget(icon_label)

        # 메시지
        message_label = QtWidgets.QLabel(self._message)
        message_label.setAlignment(QtCore.Qt.AlignCenter)
        message_label.setObjectName("disabledMessage")
        message_label.setWordWrap(True)
        container_layout.addWidget(message_label)

        layout.addWidget(message_container)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """반투명 배경을 둥근 모서리로 그리기."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        # 둥근 모서리 사각형 생성
        rect = self.rect()
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(rect), 10, 10)  # 10px 둥근 모서리
        
        # 반투명 검정으로 채우기
        painter.fillPath(path, QtGui.QColor(0, 0, 0, 120))


class StyledComboBox(QtWidgets.QComboBox):
    """커스텀 화살표와 팝업 위치를 갖는 콤보박스."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover = False
        self.setView(QtWidgets.QListView())
        self.setMaxVisibleItems(6)
        self.setMinimumHeight(34)

    def enterEvent(self, event: QtCore.QEvent) -> None:  # noqa: D401, ANN401
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: D401, ANN401
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().window()
        if not popup:
            return
        popup_rect = popup.geometry()
        target_pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        popup_rect.moveTopLeft(target_pos)
        screen = QtWidgets.QApplication.screenAt(target_pos)
        if screen:
            screen_rect = screen.availableGeometry()
        else:
            screen_rect = QtWidgets.QApplication.desktop().availableGeometry(target_pos)
        if popup_rect.bottom() > screen_rect.bottom():
            popup_rect.setBottom(screen_rect.bottom())
        popup.setGeometry(popup_rect)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtWidgets.QStylePainter(self)
        option = QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        option.subControls &= ~QtWidgets.QStyle.SC_ComboBoxArrow
        painter.drawComplexControl(QtWidgets.QStyle.CC_ComboBox, option)
        painter.drawControl(QtWidgets.QStyle.CE_ComboBoxLabel, option)

        arrow_color = QtGui.QColor(self.palette().color(QtGui.QPalette.ButtonText))
        if self._hover or self.hasFocus():
            arrow_color = QtGui.QColor(self.palette().color(QtGui.QPalette.Highlight))

        arrow_width = 10
        arrow_height = 6
        center_x = self.width() - 18
        top_y = (self.height() - arrow_height) / 2

        path = QtGui.QPainterPath()
        path.moveTo(center_x - arrow_width / 2, top_y)
        path.lineTo(center_x + arrow_width / 2, top_y)
        path.lineTo(center_x, top_y + arrow_height)
        path.closeSubpath()

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(arrow_color))
        painter.drawPath(path)


class AiModePanel(QtWidgets.QGroupBox):
    api_key_changed = QtCore.pyqtSignal(str)
    validate_api_key = QtCore.pyqtSignal()
    keyword_changed = QtCore.pyqtSignal(str)
    model_changed = QtCore.pyqtSignal(str)
    count_changed = QtCore.pyqtSignal(int)
    ai_start_requested = QtCore.pyqtSignal()
    ai_stop_requested = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("AI 자동 생성", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 사용 절차 카드 (수동 모드와 동일한 스타일)
        guide_card = QtWidgets.QFrame()
        guide_card.setObjectName("infoCard")
        guide_layout = QtWidgets.QVBoxLayout(guide_card)
        guide_layout.setContentsMargins(14, 12, 14, 12)
        guide_layout.setSpacing(6)

        guide_title = QtWidgets.QLabel("사용 절차")
        guide_title.setObjectName("sectionLabel")
        guide_layout.addWidget(guide_title)

        ai_steps = [
            "1. OpenAI API 키를 입력하고 확인을 완료하세요.",
            "2. 모델과 키워드를 선택 후 포스팅 개수를 정합니다.",
            "3. 설정을 확인하고 하단의 '자동화 시작'을 눌러 실행하세요.",
        ]
        for step in ai_steps:
            label = QtWidgets.QLabel(step)
            label.setWordWrap(True)
            label.setObjectName("infoText")
            guide_layout.addWidget(label)

        layout.addWidget(guide_card)

        # API 키 입력 (2줄 레이아웃)
        api_layout = QtWidgets.QVBoxLayout()
        api_layout.setSpacing(8)
        
        # 첫 번째 줄: 좌측 "API 키" 우측 "상태"
        api_label_row = QtWidgets.QHBoxLayout()
        api_label_row.setSpacing(8)
        
        api_label = QtWidgets.QLabel("API 키:")
        api_label.setFixedHeight(22)
        api_label.setAlignment(QtCore.Qt.AlignVCenter)
        api_label_row.addWidget(api_label)
        
        api_label_row.addStretch()
        
        status_prefix = QtWidgets.QLabel("상태:")
        status_prefix.setFixedHeight(22)
        status_prefix.setAlignment(QtCore.Qt.AlignVCenter)
        api_label_row.addWidget(status_prefix)
        
        self.api_status_label = QtWidgets.QLabel("미확인")
        self.api_status_label.setObjectName("apiStatusLabel")
        self.api_status_label.setFixedHeight(22)
        self.api_status_label.setAlignment(QtCore.Qt.AlignVCenter)
        api_label_row.addWidget(self.api_status_label)
        
        api_layout.addLayout(api_label_row)
        
        # 두 번째 줄: 좌측 "키 입력칸" 우측 "키 확인 버튼"
        api_input_row = QtWidgets.QHBoxLayout()
        api_input_row.setSpacing(8)
        
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setObjectName("apiKeyInput")
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_key_edit.setMinimumHeight(38)
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.textChanged.connect(self.api_key_changed)
        api_input_row.addWidget(self.api_key_edit, 0, QtCore.Qt.AlignVCenter)
        
        self.validate_button = QtWidgets.QPushButton("키 확인")
        self.validate_button.setObjectName("outlineButton")
        sp_val = self.validate_button.sizePolicy()
        sp_val.setHorizontalPolicy(QtWidgets.QSizePolicy.Fixed)
        sp_val.setVerticalPolicy(QtWidgets.QSizePolicy.Fixed)
        self.validate_button.setSizePolicy(sp_val)
        self.validate_button.setMinimumSize(75, 38)
        self.validate_button.clicked.connect(self.validate_api_key.emit)
        self.validate_button.setEnabled(False)
        api_input_row.addWidget(self.validate_button, 0, QtCore.Qt.AlignVCenter)
        
        api_layout.addLayout(api_input_row)
        layout.addLayout(api_layout)

        # 모델 선택
        model_layout = QtWidgets.QVBoxLayout()
        model_layout.addWidget(QtWidgets.QLabel("모델:"))
        self.model_combo = StyledComboBox()
        self.model_combo.addItems([
            "gpt-4o-mini",
            "gpt-4o", 
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
        ])
        self.model_combo.currentTextChanged.connect(self.model_changed)
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)

        # 키워드 입력
        keyword_layout = QtWidgets.QVBoxLayout()
        keyword_layout.addWidget(QtWidgets.QLabel("키워드:"))
        self.keyword_edit = QtWidgets.QLineEdit()
        self.keyword_edit.setPlaceholderText("예: 네이버 블로그 카페 소개")
        self.keyword_edit.textChanged.connect(self.keyword_changed)
        keyword_layout.addWidget(self.keyword_edit)
        layout.addLayout(keyword_layout)

        # 포스팅 개수 설정
        count_layout = QtWidgets.QVBoxLayout()
        count_layout.setSpacing(8)
        count_layout.addWidget(QtWidgets.QLabel("포스팅 개수:"))
        self.count_group = QtWidgets.QButtonGroup(self)
        radio_row = QtWidgets.QHBoxLayout()
        for idx in range(1, MAX_POST_COUNT + 1):
            radio = QtWidgets.QRadioButton(f"{idx}개")
            if idx == 1:
                radio.setChecked(True)
            self.count_group.addButton(radio, idx)
            radio_row.addWidget(radio)
        radio_row.addStretch()
        self.count_group.buttonClicked[int].connect(self.count_changed)
        count_layout.addLayout(radio_row)
        layout.addLayout(count_layout)

        layout.addStretch()

    def set_api_status(self, text: str, state: str = "default") -> None:
        # "상태: " 부분 제거하고 상태값만 표시
        status_text = text.replace("상태: ", "")
        self.api_status_label.setText(status_text)
        self.api_status_label.setProperty("state", state)
        # 재적용을 위해 스타일 리셋
        self.api_status_label.style().unpolish(self.api_status_label)
        self.api_status_label.style().polish(self.api_status_label)
        self.api_status_label.update()

    def set_validate_enabled(self, enabled: bool) -> None:
        self.validate_button.setEnabled(enabled)


class ManualModePanel(QtWidgets.QGroupBox):
    title_changed = QtCore.pyqtSignal(str)
    tags_changed = QtCore.pyqtSignal(str)
    file_selected = QtCore.pyqtSignal(Path)
    image_selected = QtCore.pyqtSignal(Path)
    schedule_changed = QtCore.pyqtSignal(int)
    schedule_enabled = QtCore.pyqtSignal(bool)
    repeat_toggled = QtCore.pyqtSignal(bool)
    interval_changed = QtCore.pyqtSignal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("수동 포스팅", parent)
        self._build_ui()
        self._setup_overlay()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        guide_card = QtWidgets.QFrame()
        guide_card.setObjectName("infoCard")
        guide_layout = QtWidgets.QVBoxLayout(guide_card)
        guide_layout.setContentsMargins(14, 12, 14, 12)
        guide_layout.setSpacing(6)

        guide_title = QtWidgets.QLabel("사용 절차")
        guide_title.setObjectName("sectionLabel")
        guide_layout.addWidget(guide_title)

        manual_steps = [
            "1. 게시할 제목과 태그를 입력하고 필요한 파일을 선택하세요.",
            "2. 이미지가 있다면 파일을 선택하고 예약 간격을 설정하세요.",
            "3. 설정을 확인하고 하단의 '자동화 시작'을 눌러 실행하세요.",
        ]
        for step in manual_steps:
            label = QtWidgets.QLabel(step)
            label.setWordWrap(True)
            label.setObjectName("infoText")
            guide_layout.addWidget(label)

        layout.addWidget(guide_card)

        title_layout = QtWidgets.QVBoxLayout()
        title_layout.addWidget(QtWidgets.QLabel("제목:"))
        self.manual_title_edit = QtWidgets.QLineEdit()
        self.manual_title_edit.setPlaceholderText("예: 네이버 블로그 카페 리뷰")
        self.manual_title_edit.textChanged.connect(self.title_changed)
        title_layout.addWidget(self.manual_title_edit)
        layout.addLayout(title_layout)

        file_layout = QtWidgets.QVBoxLayout()
        file_layout.addWidget(QtWidgets.QLabel("본문 파일:"))
        file_row = QtWidgets.QHBoxLayout()
        self.manual_file_edit = QtWidgets.QLineEdit()
        self.manual_file_edit.setReadOnly(True)
        file_row.addWidget(self.manual_file_edit)
        self.manual_file_button = QtWidgets.QPushButton("파일 선택")
        self.manual_file_button.setObjectName("fileChooserButton")
        self.manual_file_button.clicked.connect(self._on_file_clicked)
        file_row.addWidget(self.manual_file_button)
        file_layout.addLayout(file_row)
        layout.addLayout(file_layout)

        tags_layout = QtWidgets.QVBoxLayout()
        tags_layout.addWidget(QtWidgets.QLabel("태그 (공백 구분):"))
        self.manual_tags_edit = QtWidgets.QLineEdit()
        self.manual_tags_edit.setPlaceholderText("예: #카페 #서울맛집 #브런치")
        self.manual_tags_edit.textChanged.connect(self.tags_changed)
        tags_layout.addWidget(self.manual_tags_edit)
        layout.addLayout(tags_layout)

        image_layout = QtWidgets.QVBoxLayout()
        image_layout.setSpacing(6)
        image_layout.addWidget(QtWidgets.QLabel("이미지 파일:"))
        image_row = QtWidgets.QHBoxLayout()
        self.image_file_edit = QtWidgets.QLineEdit()
        self.image_file_edit.setReadOnly(True)
        image_row.addWidget(self.image_file_edit)
        self.image_file_button = QtWidgets.QPushButton("이미지 선택")
        self.image_file_button.setObjectName("fileChooserButton")
        self.image_file_button.clicked.connect(self._on_image_clicked)
        image_row.addWidget(self.image_file_button)
        image_layout.addLayout(image_row)
        layout.addLayout(image_layout)

        # 예약 간격 설정 (완전히 한 줄로)
        schedule_container = QtWidgets.QHBoxLayout()
        schedule_container.setSpacing(8)
        
        schedule_label = QtWidgets.QLabel("예약 발행:")
        schedule_label.setMinimumSize(65, 26)
        schedule_label.setAlignment(QtCore.Qt.AlignVCenter)
        schedule_container.addWidget(schedule_label)
        
        # 예약 ON/OFF 버튼
        self.schedule_toggle_btn = QtWidgets.QPushButton("ON")
        self.schedule_toggle_btn.setObjectName("scheduleButton")
        self.schedule_toggle_btn.setMinimumSize(42, 26)
        self.schedule_toggle_btn.setCheckable(True)
        self.schedule_toggle_btn.setChecked(True)  # 기본값: ON
        self.schedule_toggle_btn.clicked.connect(self._toggle_schedule)
        schedule_container.addWidget(self.schedule_toggle_btn)
        
        # 현재 값 표시
        self.schedule_value_label = QtWidgets.QLabel("5")
        self.schedule_value_label.setAlignment(QtCore.Qt.AlignCenter)
        self.schedule_value_label.setObjectName("scheduleValue")
        self.schedule_value_label.setMinimumSize(35, 26)
        schedule_container.addWidget(self.schedule_value_label)
        
        # 감소 버튼 (-)
        self.schedule_decrease_btn = QtWidgets.QPushButton("-")
        self.schedule_decrease_btn.setObjectName("scheduleButton")
        self.schedule_decrease_btn.setMinimumSize(26, 26)
        self.schedule_decrease_btn.clicked.connect(self._decrease_schedule)
        schedule_container.addWidget(self.schedule_decrease_btn)
        
        # 증가 버튼 (+)
        self.schedule_increase_btn = QtWidgets.QPushButton("+")
        self.schedule_increase_btn.setObjectName("scheduleButton")
        self.schedule_increase_btn.setMinimumSize(26, 26)
        self.schedule_increase_btn.clicked.connect(self._increase_schedule)
        schedule_container.addWidget(self.schedule_increase_btn)
        
        unit_label1 = QtWidgets.QLabel("분")
        unit_label1.setMinimumHeight(26)
        unit_label1.setAlignment(QtCore.Qt.AlignVCenter)
        schedule_container.addWidget(unit_label1)
        
        # 미리보기 레이블
        self.schedule_preview_label = QtWidgets.QLabel("5분 후 발행")
        self.schedule_preview_label.setObjectName("schedulePreview")
        schedule_container.addWidget(self.schedule_preview_label, 1)
        
        layout.addLayout(schedule_container)
        
        # 반복 실행 설정 (완전히 한 줄로)
        repeat_container = QtWidgets.QHBoxLayout()
        repeat_container.setSpacing(8)
        
        repeat_label = QtWidgets.QLabel("반복 실행:")
        repeat_label.setMinimumSize(65, 26)
        repeat_label.setAlignment(QtCore.Qt.AlignVCenter)
        repeat_container.addWidget(repeat_label)
        
        # 반복 ON/OFF 버튼
        self.repeat_toggle_btn = QtWidgets.QPushButton("OFF")
        self.repeat_toggle_btn.setObjectName("scheduleButton")
        self.repeat_toggle_btn.setMinimumSize(42, 26)
        self.repeat_toggle_btn.setCheckable(True)
        self.repeat_toggle_btn.clicked.connect(self._toggle_repeat)
        repeat_container.addWidget(self.repeat_toggle_btn)
        
        # 간격 값 표시
        self.interval_value_label = QtWidgets.QLabel("60")
        self.interval_value_label.setAlignment(QtCore.Qt.AlignCenter)
        self.interval_value_label.setObjectName("scheduleValue")
        self.interval_value_label.setMinimumSize(35, 26)
        repeat_container.addWidget(self.interval_value_label)
        
        # 간격 감소 버튼
        self.interval_decrease_btn = QtWidgets.QPushButton("-")
        self.interval_decrease_btn.setObjectName("scheduleButton")
        self.interval_decrease_btn.setMinimumSize(26, 26)
        self.interval_decrease_btn.setEnabled(False)
        self.interval_decrease_btn.clicked.connect(self._decrease_interval)
        repeat_container.addWidget(self.interval_decrease_btn)
        
        # 간격 증가 버튼
        self.interval_increase_btn = QtWidgets.QPushButton("+")
        self.interval_increase_btn.setObjectName("scheduleButton")
        self.interval_increase_btn.setMinimumSize(26, 26)
        self.interval_increase_btn.setEnabled(False)
        self.interval_increase_btn.clicked.connect(self._increase_interval)
        repeat_container.addWidget(self.interval_increase_btn)
        
        unit_label2 = QtWidgets.QLabel("분")
        unit_label2.setMinimumHeight(26)
        unit_label2.setAlignment(QtCore.Qt.AlignVCenter)
        repeat_container.addWidget(unit_label2)
        
        # 상태 표시
        self.repeat_status_label = QtWidgets.QLabel("비활성화")
        self.repeat_status_label.setObjectName("schedulePreview")
        repeat_container.addWidget(self.repeat_status_label, 1)
        
        layout.addLayout(repeat_container)
        
        # 초기값 설정
        self._current_schedule = 5
        self._schedule_enabled = True  # 예약 발행 기본값: ON
        self._current_interval = 60

    def _on_file_clicked(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "본문 파일 선택",
            str(Path.home()),
            "텍스트 파일 (*.txt);;모든 파일 (*.*)",
        )
        if path:
            self.manual_file_edit.setText(path)
            self.file_selected.emit(Path(path))

    def _on_image_clicked(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "이미지 파일 선택",
            str(Path.home()),
            "이미지 파일 (*.jpg *.jpeg *.png *.gif *.bmp);;모든 파일 (*.*)",
        )
        if path:
            self.image_file_edit.setText(path)
            self.image_selected.emit(Path(path))
    
    def _decrease_schedule(self) -> None:
        """예약 시간을 1분 감소시킵니다."""
        if self._current_schedule > 1:
            self._current_schedule -= 1
            self._update_schedule_display()
    
    def _increase_schedule(self) -> None:
        """예약 시간을 1분 증가시킵니다."""
        if self._current_schedule < 180:
            self._current_schedule += 1
            self._update_schedule_display()
    
    def _update_schedule_display(self) -> None:
        """예약 시간 표시를 업데이트합니다."""
        self.schedule_value_label.setText(str(self._current_schedule))
        if self._schedule_enabled:
            self.schedule_preview_label.setText(f"{self._current_schedule}분 후 발행")
        else:
            self.schedule_preview_label.setText("즉시 발행")
        self.schedule_changed.emit(self._current_schedule)
    
    def _toggle_schedule(self) -> None:
        """예약 발행 ON/OFF 토글"""
        self._schedule_enabled = self.schedule_toggle_btn.isChecked()
        
        if self._schedule_enabled:
            self.schedule_toggle_btn.setText("ON")
            self.schedule_preview_label.setText(f"{self._current_schedule}분 후 발행")
        else:
            self.schedule_toggle_btn.setText("OFF")
            self.schedule_preview_label.setText("즉시 발행")
        
        # 시간 조절 버튼 활성화/비활성화
        self.schedule_decrease_btn.setEnabled(self._schedule_enabled)
        self.schedule_increase_btn.setEnabled(self._schedule_enabled)
        
        self.schedule_enabled.emit(self._schedule_enabled)
    
    def _toggle_repeat(self) -> None:
        """반복 실행 ON/OFF 토글"""
        enabled = self.repeat_toggle_btn.isChecked()
        
        if enabled:
            self.repeat_toggle_btn.setText("ON")
            self.repeat_status_label.setText(f"활성화 ({self._current_interval}분)")
        else:
            self.repeat_toggle_btn.setText("OFF")
            self.repeat_status_label.setText("비활성화")
        
        # 간격 조절 버튼 활성화/비활성화
        self.interval_decrease_btn.setEnabled(enabled)
        self.interval_increase_btn.setEnabled(enabled)
        
        self.repeat_toggled.emit(enabled)
    
    def _decrease_interval(self) -> None:
        """반복 간격을 5분 감소시킵니다."""
        if self._current_interval > 5:
            self._current_interval -= 5
            self._update_interval_display()
    
    def _increase_interval(self) -> None:
        """반복 간격을 5분 증가시킵니다."""
        if self._current_interval < 720:
            self._current_interval += 5
            self._update_interval_display()
    
    def _update_interval_display(self) -> None:
        """반복 간격 표시를 업데이트합니다."""
        self.interval_value_label.setText(str(self._current_interval))
        if self.repeat_toggle_btn.isChecked():
            self.repeat_status_label.setText(f"활성화 ({self._current_interval}분)")
        self.interval_changed.emit(self._current_interval)

    def update_repeat_status(self, enabled: bool, interval: int, is_running: bool = False) -> None:
        """반복 작업 상태를 업데이트합니다."""
        self._current_interval = interval
        self.interval_value_label.setText(str(interval))
        self.repeat_toggle_btn.setChecked(enabled)
        
        if enabled:
            self.repeat_toggle_btn.setText("ON")
            if is_running:
                self.repeat_status_label.setText(f"실행 중 ({interval}분)")
            else:
                self.repeat_status_label.setText(f"활성화 ({interval}분)")
        else:
            self.repeat_toggle_btn.setText("OFF")
            self.repeat_status_label.setText("비활성화")
        
        # 간격 조절 버튼 활성화/비활성화
        self.interval_decrease_btn.setEnabled(enabled and not is_running)
        self.interval_increase_btn.setEnabled(enabled and not is_running)
    
    def _setup_overlay(self) -> None:
        """비활성화 오버레이 설정."""
        self.disabled_overlay = DisabledOverlay("수동 모드가 비활성화입니다", self)
        self.disabled_overlay.hide()  # 초기에는 숨김
        
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """위젯 크기 변경 시 오버레이 크기도 조정."""
        super().resizeEvent(event)
        if hasattr(self, 'disabled_overlay'):
            # 패널 경계 내에 확실히 위치하도록 여백을 더 크게 설정
            overlay_size = self.size()
            overlay_size.setWidth(overlay_size.width() - 32)  # 좌우 16px씩 여백 유지
            overlay_size.setHeight(overlay_size.height() - 32)  # 상하 16px씩 여백으로 높이 줄임
            self.disabled_overlay.resize(overlay_size)
            self.disabled_overlay.move(16, 16)  # 좌우 16px, 상하 16px 여백으로 이동
    
    def setEnabled(self, enabled: bool) -> None:
        """위젯 활성화/비활성화 시 오버레이 표시/숨김."""
        super().setEnabled(enabled)
        if hasattr(self, 'disabled_overlay'):
            if enabled:
                self.disabled_overlay.hide()
            else:
                self.disabled_overlay.show()
                self.disabled_overlay.raise_()  # 맨 위로 올리기
    
    def enable_controls(self, enabled: bool) -> None:
        """컨트롤들을 활성화/비활성화합니다."""
        controls = [
            self.manual_title_edit,
            self.manual_file_edit,
            self.manual_file_button,
            self.manual_tags_edit,
            self.image_file_edit,
            self.image_file_button,
            self.schedule_toggle_btn,
            self.schedule_decrease_btn,
            self.schedule_increase_btn,
            self.repeat_toggle_btn,
            self.interval_decrease_btn,
            self.interval_increase_btn,
        ]
        for widget in controls:
            widget.setEnabled(enabled)


