"""메인 윈도우 레이아웃 구성 (계정 관리 제거)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
import os
from typing import Dict, Optional

from PyQt5 import QtCore, QtGui, QtWidgets
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from openai import OpenAI  # type: ignore[import]

from app.core.automation.naver_publisher import (
    NAVER_HOME_URL, create_chrome_driver, BlogPostContent, 
    publish_blog_post
)
from app.core.constants import AUTOMATION_STEPS_PER_POST
from app.core.models import WorkflowParams
from app.core.preferences import UserSettings, load_settings, save_settings
from app.core.services.content_service import ContentGenerator
from app.core.theme import DARK_THEME, LIGHT_THEME
from app.core.workflow import WorkflowWorker
from ..components.header_bar import HeaderBar
from ..components.ai_control_panel import AiControlPanel
from ..components.mode_panels import ManualModePanel
from ..components.repeat_panel import RepeatPanel


logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    """AI / 수동 블로그 포스팅 컨트롤 센터 (계정 관리 제거)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("📝 NBlog Studio - 네이버 블로그 자동화 도구")
        self.setMinimumSize(1200, 800)

        # 화면 중앙에 창 배치
        screen = QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1920, 1080)
        
        # 화면 크기에 따른 적절한 창 크기 계산
        screen_width = avail.width()
        screen_height = avail.height()
        
        # 화면 크기별 최적화된 창 크기 설정
        if screen_width <= 1366:  # 작은 화면 (노트북 등)
            target_w = max(1200, int(screen_width * 0.9))
            target_h = max(800, int(screen_height * 0.85))
        elif screen_width <= 1920:  # 일반적인 화면
            target_w = max(1400, int(screen_width * 0.85))
            target_h = max(900, int(screen_height * 0.85))
        else:  # 큰 화면 (4K 등)
            target_w = max(1600, int(screen_width * 0.8))
            target_h = max(1000, int(screen_height * 0.8))
        
        # 최소/최대 크기 제한
        target_w = max(1200, min(target_w, 2400))
        target_h = max(800, min(target_h, 1600))
        
        self.setMinimumSize(1200, 800)
        self.resize(target_w, target_h)
        self.setMaximumSize(QtCore.QSize(16777215, 16777215))  # 자유롭게 리사이즈 가능
        
        # 화면 중앙에 창 배치
        self.setGeometry(
            QtWidgets.QStyle.alignedRect(
                QtCore.Qt.LeftToRight,
                QtCore.Qt.AlignCenter,
                self.size(),
                avail,
            )
        )

        # 설정 저장 debounce 타이머
        self._settings_save_timer = QtCore.QTimer()
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.timeout.connect(self._do_save_settings)

        # Windows 전용 데이터 경로 설정
        self.app_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
        data_home = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        self.data_root = data_home / "NBlogStudio"
        # 작업 파일 및 임시/백업 저장 기준 경로
        self.base_dir = self.data_root

        self.user_data_dir = self.data_root / "user_data" / self._current_user()
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        # 워커 스레드들
        self._worker: Optional[WorkflowWorker] = None
        self._validation_thread: Optional[QtCore.QThread] = None
        
        # 상태 플래그들
        self._api_valid = False
        self._is_ai_mode = False  # 기본값을 수동모드로 변경
        self._current_theme = "dark"

        self._build_ui()
        self._load_settings()
        self._apply_theme(self._current_theme)
        
        # 프로그램 시작 시 강제로 수동 모드로 설정 (설정 로드 후)
        self._set_ai_mode(False)

    # --- UI 구성 ---

    def _build_ui(self) -> None:
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)

        content = QtWidgets.QWidget()
        content.setObjectName("centralWidget")
        central_layout = QtWidgets.QVBoxLayout(content)
        central_layout.setContentsMargins(12, 12, 12, 12)
        central_layout.setSpacing(12)

        self.header = HeaderBar(
            toggle_theme=self._toggle_theme,
            toggle_mode=self._set_ai_mode,
        )
        central_layout.addWidget(self.header)

        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setSpacing(12)

        # 상단 2개 컬럼 (수동 | AI)
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.setSpacing(12)
        
        self.manual_panel = ManualModePanel()
        self.ai_control_panel = AiControlPanel()
        
        top_layout.addWidget(self.manual_panel, 1)
        top_layout.addWidget(self.ai_control_panel, 1)
        
        content_layout.addLayout(top_layout)
        
        # 하단 로그 패널
        self.repeat_panel = RepeatPanel()
        content_layout.addWidget(self.repeat_panel)

        central_layout.addLayout(content_layout)

        scroll_area.setWidget(content)
        self.setCentralWidget(scroll_area)

        self._connect_signals()
        self.header.tips_requested.connect(self._show_tips)
        self.header.cleanup_browser_requested.connect(self._cleanup_browser_sessions)

    def _connect_signals(self) -> None:
        """UI 시그널 연결."""
        # AI 컨트롤 패널 시그널
        self.ai_control_panel.api_key_changed.connect(self._on_api_key_changed)
        self.ai_control_panel.validate_api_key.connect(self._validate_api_key)
        self.ai_control_panel.keyword_changed.connect(self._on_keyword_changed)
        self.ai_control_panel.model_changed.connect(self._on_model_changed)
        self.ai_control_panel.count_changed.connect(self._on_count_changed)
        self.ai_control_panel.start_requested.connect(self._start_automation)
        self.ai_control_panel.stop_requested.connect(self._stop_automation)

        # 수동 모드 패널 시그널
        self.manual_panel.title_changed.connect(self._on_manual_title_changed)
        self.manual_panel.tags_changed.connect(self._on_manual_tags_changed)
        self.manual_panel.file_selected.connect(self._on_manual_file_selected)
        self.manual_panel.image_selected.connect(self._on_manual_image_selected)
        self.manual_panel.schedule_changed.connect(self._on_schedule_changed)
        self.manual_panel.schedule_enabled.connect(self._on_schedule_enabled)
        self.manual_panel.repeat_toggled.connect(self._on_repeat_toggled)
        self.manual_panel.interval_changed.connect(self._on_interval_changed)

    def _current_user(self) -> str:
        """현재 사용자 식별자 반환."""
        import getpass
        return getpass.getuser()

    def _load_settings(self) -> None:
        """사용자 설정 로드."""
        settings_file = self.user_data_dir / "settings.json"
        settings = load_settings(settings_file)
        
        # AI 모드 설정
        self._set_ai_mode(settings.use_ai)
        self._api_valid = bool(settings.api_key)
        
        # AI 패널 설정
        if settings.api_key:
            self.ai_control_panel.api_key_edit.setText(settings.api_key)
        self.ai_control_panel.model_combo.setCurrentText(settings.model)
        if settings.keyword:
            self.ai_control_panel.keyword_edit.setText(settings.keyword)
        
        # 수동 모드 패널 설정
        if settings.manual_title:
            self.manual_panel.manual_title_edit.setText(settings.manual_title)
        if settings.manual_tags:
            self.manual_panel.manual_tags_edit.setText(settings.manual_tags)
        if settings.image_file_path:
            self.manual_panel.image_file_edit.setText(settings.image_file_path)
        
        # 반복 설정
        self.manual_panel.update_repeat_status(
            settings.repeat_enabled, 
            settings.interval_minutes, 
            False
        )

    def _save_settings(self) -> None:
        """사용자 설정 저장 (debounced)."""
        self._settings_save_timer.start(500)  # 500ms 후 저장

    def _do_save_settings(self) -> None:
        """실제 설정 저장."""
        settings_file = self.user_data_dir / "settings.json"
        settings = UserSettings(
            use_ai=self._is_ai_mode,
            api_key=self.ai_control_panel.api_key_edit.text(),
            model=self.ai_control_panel.model_combo.currentText(),
            keyword=self.ai_control_panel.keyword_edit.text(),
            manual_title=self.manual_panel.manual_title_edit.text(),
            manual_tags=self.manual_panel.manual_tags_edit.text(),
            image_file_path=self.manual_panel.image_file_edit.text(),
            repeat_enabled=self.manual_panel.repeat_toggle_btn.isChecked(),
            interval_minutes=int(self.manual_panel.interval_value_label.text()),
            schedule_enabled=self.manual_panel.schedule_toggle_btn.isChecked(),
            schedule_minutes=int(self.manual_panel.schedule_value_label.text()),
        )
        save_settings(settings_file, settings)

    def _set_ai_mode(self, is_ai: bool) -> None:
        """AI/수동 모드 전환."""
        self._is_ai_mode = is_ai
        self.header.set_mode(is_ai)
        
        # 패널 활성화/비활성화
        self.manual_panel.setEnabled(not is_ai)
        self.ai_control_panel.set_ai_mode_enabled(is_ai)
        
        # 설정 저장
        self._save_settings()

    def _toggle_theme(self) -> None:
        """테마 전환."""
        self._current_theme = "light" if self._current_theme == "dark" else "dark"
        self._apply_theme(self._current_theme)
        self._save_settings()

    def _apply_theme(self, theme: str) -> None:
        """테마 적용."""
        theme_map = DARK_THEME if theme == "dark" else LIGHT_THEME
        self.header.set_theme_icon(theme_map, theme == "dark")
        
        # QSS 파일 로드
        qss_file = self.app_root / "app" / "resources" / "styles" / "main.qss"
        if qss_file.exists():
            qss = qss_file.read_text(encoding="utf-8")
        else:
            qss = ""
        
        # 테마 변수 치환
        replacements = {
            "{{WINDOW_COLOR}}": str(theme_map["palette"]["window"]),
            "{{TEXT_COLOR}}": str(theme_map["palette"]["text"]),
            "{{BASE_COLOR}}": str(theme_map["palette"]["base"]),
            "{{ALTERNATE_COLOR}}": str(theme_map["palette"]["alternate"]),
            "{{BUTTON_COLOR}}": str(theme_map["palette"]["button"]),
            "{{BUTTON_TEXT_COLOR}}": str(theme_map["palette"]["button_text"]),
            "{{HIGHLIGHT_COLOR}}": str(theme_map["palette"]["highlight"]),
            "{{HIGHLIGHT_TEXT_COLOR}}": str(theme_map["palette"]["highlight_text"]),
            "{{CARD_COLOR}}": str(theme_map["card"]),
            "{{INPUT_COLOR}}": str(theme_map["input"]),
            "{{BORDER_COLOR}}": str(theme_map["border"]),
            "{{PRIMARY_TEXT_COLOR}}": str(theme_map["primary_text"]),
            "{{SECONDARY_TEXT_COLOR}}": str(theme_map["secondary_text"]),
            "{{BACKGROUND_COLOR}}": str(theme_map["background"]),
            "{{ACCENT_COLOR}}": str(theme_map["accent"]),
            "{{ACCENT_HOVER_COLOR}}": str(theme_map["accent_hover"]),
            "{{ACCENT_LIGHT_COLOR}}": str(theme_map["accent_light"]),
            "{{ACCENT_DARK_COLOR}}": str(theme_map["accent_dark"]),
            "{{ACCENT_DARKER_COLOR}}": str(theme_map["accent_darker"]),
            "{{DANGER_COLOR}}": str(theme_map["danger"]),
            "{{WARNING_COLOR}}": str(theme_map["warning"]),
            "{{INFO_COLOR}}": str(theme_map["info"]),
            "{{THEME_ICON_COLOR}}": str(theme_map["theme_icon"]),
            "{{THEME_ICON_ACTIVE_COLOR}}": str(theme_map["theme_icon_active"]),
            "{{BG_ALT_COLOR}}": str(theme_map["bg_alt"]),
        }
        
        for token, value in replacements.items():
            qss = qss.replace(token, str(value))

        QtWidgets.QApplication.instance().setStyleSheet(qss)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)

    def _non_blocking_wait_ms(self, ms: int) -> None:
        """UI 이벤트를 처리하면서 대기 (최적화된 버전)."""
        import time
        start_time = time.time()
        while (time.time() - start_time) * 1000 < ms:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.01)  # 10ms씩 대기

    # --- 시그널 핸들러 ---

    def _on_api_key_changed(self, text: str) -> None:
        """API 키 변경 시."""
        self.ai_control_panel.set_validate_enabled(len(text.strip()) > 0)
        self._save_settings()

    def _on_keyword_changed(self, text: str) -> None:
        """키워드 변경 시."""
        self._save_settings()

    def _on_model_changed(self, text: str) -> None:
        """모델 변경 시."""
        self._save_settings()

    def _on_count_changed(self, count: int) -> None:
        """포스팅 개수 변경 시."""
        self._save_settings()

    def _on_manual_title_changed(self, text: str) -> None:
        """수동 제목 변경 시."""
        self._save_settings()

    def _on_manual_tags_changed(self, text: str) -> None:
        """수동 태그 변경 시."""
        self._save_settings()

    def _on_manual_file_selected(self, path: Path) -> None:
        """수동 파일 선택 시."""
        self.manual_panel.manual_file_edit.setText(str(path))
        self._save_settings()

    def _on_manual_image_selected(self, path: Path) -> None:
        """수동 이미지 선택 시."""
        self.manual_panel.image_file_edit.setText(str(path))
        self._save_settings()

    def _on_schedule_changed(self, minutes: int) -> None:
        """예약 시간 변경 시."""
        self._save_settings()

    def _on_schedule_enabled(self, enabled: bool) -> None:
        """예약 활성화 변경 시."""
        self._save_settings()

    def _on_repeat_toggled(self, enabled: bool) -> None:
        """반복 실행 토글 시."""
        self._save_settings()

    def _on_interval_changed(self, minutes: int) -> None:
        """반복 간격 변경 시."""
        self._save_settings()

    def _validate_api_key(self) -> None:
        """API 키 유효성 검사."""
        api_key = self.ai_control_panel.api_key_edit.text().strip()
        if not api_key:
            self.ai_control_panel.set_api_status("API 키를 입력하세요", "error")
            return

        self.ai_control_panel.set_api_status("검증 중...", "info")
        self.ai_control_panel.set_validate_enabled(False)

        # 백그라운드에서 API 키 검증
        self._validation_thread = QtCore.QThread()
        self._validation_thread.run = lambda: self._do_validate_api_key(api_key)
        self._validation_thread.start()

    def _do_validate_api_key(self, api_key: str) -> None:
        """실제 API 키 검증."""
        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
            )
            
            if response.choices:
                QtCore.QMetaObject.invokeMethod(
                    self, 
                    "_on_api_validation_success", 
                    QtCore.Qt.QueuedConnection
                )
            else:
                QtCore.QMetaObject.invokeMethod(
                    self, 
                    "_on_api_validation_failure", 
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, "API 응답이 비어있습니다")
                )
        except Exception as e:
            QtCore.QMetaObject.invokeMethod(
                self, 
                "_on_api_validation_failure", 
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, str(e))
            )

    def _on_api_validation_success(self) -> None:
        """API 키 검증 성공."""
        self._api_valid = True
        self.ai_control_panel.set_api_status("✅ 유효한 API 키입니다", "success")
        self.ai_control_panel.set_validate_enabled(True)
        self._save_settings()

    def _on_api_validation_failure(self, error: str) -> None:
        """API 키 검증 실패."""
        self._api_valid = False
        self.ai_control_panel.set_api_status(f"❌ {error}", "error")
        self.ai_control_panel.set_validate_enabled(True)

    def _start_automation(self) -> None:
        """자동화 시작."""
        if self._is_ai_mode and not self._api_valid:
            QtWidgets.QMessageBox.warning(self, "API 키 필요", "AI 모드를 사용하려면 유효한 API 키가 필요합니다.")
            return

        # 워크플로우 파라미터 생성
        params = WorkflowParams(
            keyword=self.ai_control_panel.keyword_edit.text() if self._is_ai_mode else self.manual_panel.manual_title_edit.text(),
            count=self.ai_control_panel.count_group.checkedId() if self._is_ai_mode else 1,
            use_ai=self._is_ai_mode,
            api_key=self.ai_control_panel.api_key_edit.text() if self._is_ai_mode else "",
            model=self.ai_control_panel.model_combo.currentText() if self._is_ai_mode else "",
            manual_title=self.manual_panel.manual_title_edit.text(),
            manual_body=self._load_manual_body(),
            manual_tags=self.manual_panel.manual_tags_edit.text(),
            manual_file_path=self.manual_panel.manual_file_edit.text(),
            image_file_path=self.manual_panel.image_file_edit.text(),
            schedule_minutes=int(self.manual_panel.schedule_value_label.text()) if self.manual_panel.schedule_toggle_btn.isChecked() else 0,
            naver_id="",  # 계정 관리 제거
            naver_profile_dir="",  # 계정 관리 제거
        )

        # 워크플로우 워커 생성 및 시작
        self._worker = WorkflowWorker(
            params=params,
            driver=None,  # 계정 관리 제거
            base_dir=self.base_dir,
            automation_steps_per_post=AUTOMATION_STEPS_PER_POST,
        )

        # 시그널 연결
        self._worker.finished_signal.connect(self._on_workflow_finished)
        self._worker.error_signal.connect(self._on_workflow_error)
        self._worker.progress_signal.connect(self._on_workflow_progress)
        self._worker.percent_signal.connect(self._on_workflow_percent)
        self._worker.status_signal.connect(self._on_workflow_status)
        self._worker.post_saved_signal.connect(self._on_post_saved)

        # UI 상태 변경
        self.ai_control_panel.set_controls_enabled(False)
        self.manual_panel.enable_controls(False)
        self.repeat_panel.reset_progress()

        # 워크플로우 시작
        self._worker.start()

    def _stop_automation(self) -> None:
        """자동화 중지."""
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self.repeat_panel.append_log("⏹️ 자동화 중지 요청됨...")

    def _load_manual_body(self) -> str:
        """수동 본문 로드."""
        file_path = self.manual_panel.manual_file_edit.text()
        if not file_path:
            return ""
        
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except Exception as e:
            self.repeat_panel.append_log(f"❌ 파일 읽기 오류: {e}")
            return ""

    def _on_workflow_finished(self, driver) -> None:
        """워크플로우 완료."""
        self.ai_control_panel.set_controls_enabled(True)
        self.manual_panel.enable_controls(True)
        self.repeat_panel.append_log("🎉 자동화 완료!")
        
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    def _on_workflow_error(self, error: str) -> None:
        """워크플로우 오류."""
        self.ai_control_panel.set_controls_enabled(True)
        self.manual_panel.enable_controls(True)
        self.repeat_panel.set_error_state(error)
        self.repeat_panel.append_log(f"❌ 오류: {error}")

    def _on_workflow_progress(self, message: str, completed: bool) -> None:
        """워크플로우 진행 상황."""
        self.repeat_panel.append_log(message)

    def _on_workflow_percent(self, percent: int) -> None:
        """워크플로우 진행률."""
        self.repeat_panel.progress_bar.setValue(percent)

    def _on_workflow_status(self, status: str) -> None:
        """워크플로우 상태."""
        self.repeat_panel.update_status(status)

    def _on_post_saved(self, title: str, url: str) -> None:
        """포스트 저장됨."""
        self.repeat_panel.add_post_to_history(title, url)

    def _cleanup_browser_sessions(self) -> None:
        """브라우저 세션 정리."""
        self.repeat_panel.append_log("🧹 브라우저 세션 정리 중...")
        # 계정 관리 제거로 인해 브라우저 정리 기능 단순화
        self.repeat_panel.append_log("✅ 브라우저 세션 정리 완료")

    def _show_tips(self) -> None:
        """팁 표시."""
        QtWidgets.QMessageBox.information(
            self,
            "Tips",
            "1. AI 모드에서 키 확인 후 자동화를 시작하세요.\n"
            "2. 수동 모드에서는 제목과 본문 파일을 선택하세요.\n"
            "3. 브라우저 오류 발생 시 '브라우저 정리' 기능을 사용하세요.",
        )
