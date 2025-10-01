"""메인 윈도우 레이아웃 구성."""

from __future__ import annotations

import logging
from pathlib import Path
import os
import sys
import platform
from typing import Dict, Optional

from PyQt5 import QtCore, QtGui, QtWidgets
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from openai import OpenAI  # type: ignore[import]

from app.core.accounts import ensure_profile_dir, load_accounts, save_accounts
from app.core.automation.naver_publisher import NAVER_HOME_URL, create_chrome_driver
from app.core.constants import AUTOMATION_STEPS_PER_POST
from app.core.models import AccountProfile, WorkflowParams
from app.core.preferences import UserSettings, load_settings, save_settings
from app.core.services.content_service import ContentGenerator
from app.core.theme import DARK_THEME, LIGHT_THEME
from app.core.workflow import WorkflowWorker
from app.core.automation.naver_publisher import BlogPostContent, publish_blog_post, create_chrome_driver, AccountProtectionException
from ..components.account_panel import AccountPanel
from ..components.header_bar import HeaderBar
from ..components.ai_control_panel import AiControlPanel
from ..components.mode_panels import ManualModePanel
from ..components.repeat_panel import RepeatPanel


logger = logging.getLogger(__name__)


class _ApiKeyValidator(QtCore.QObject):
    finished = QtCore.pyqtSignal(bool, str)

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self._api_key = api_key

    def run(self) -> None:
        try:
            client = OpenAI(api_key=self._api_key)
            client.models.retrieve("gpt-4o-mini")
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(False, str(exc))
        else:
            self.finished.emit(True, "")


class MainWindow(QtWidgets.QMainWindow):
    """AI / 수동 블로그 포스팅 컨트롤 센터."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("네이버 블로그 자동화 스튜디오")
        
        # 화면 해상도에 따른 창 크기 자동 조절
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

        # UI 스케일링 상태
        self._ui_scale: float = 1.0
        self._theme_map_cache: Optional[Dict[str, object]] = None
        
        # 리사이즈 이벤트 최적화용 타이머
        self._resize_timer = QtCore.QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._apply_resize_changes)
        
        # 설정 저장 debounce 타이머 (성능 최적화)
        self._settings_save_timer = QtCore.QTimer()
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.timeout.connect(self._do_save_settings)
        
        # 계정 저장 debounce 타이머 (성능 최적화)
        self._accounts_save_timer = QtCore.QTimer()
        self._accounts_save_timer.setSingleShot(True)
        self._accounts_save_timer.timeout.connect(self._do_save_accounts)
        
        # 스타일시트 캐시
        self._original_qss: Optional[str] = None

        # 애플리케이션 리소스 경로(고정)와 사용자 데이터 경로(가변)를 분리
        self.app_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
        if platform.system() == "Windows":
            data_home = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        elif platform.system() == "Darwin":
            data_home = Path.home() / "Library" / "Application Support"
        else:
            data_home = Path.home() / ".local" / "share"
        self.data_root = data_home / "NBlogStudio"
        # 작업 파일 및 임시/백업 저장 기준 경로
        self.base_dir = self.data_root

        self.user_data_dir = self.data_root / "user_data" / self._current_user()
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_dir = self.data_root / "storage" / "accounts"
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = self.accounts_dir / "accounts.db"
        self.profiles_root = self.accounts_dir / "profiles"
        self.profiles_root.mkdir(parents=True, exist_ok=True)

        self._driver: Optional[object] = None
        self._worker: Optional[WorkflowWorker] = None
        self._accounts: Dict[str, AccountProfile] = {}
        self._selected_account_id: Optional[str] = None
        self._api_valid = False
        self._is_ai_mode = False  # 기본값을 수동모드로 변경
        self._current_theme = "dark"
        self._validation_thread: Optional[QtCore.QThread] = None
        self._pending_login_checks: dict[str, bool] = {}

        self._build_ui()
        self._load_settings()
        self._load_accounts()
        self._apply_theme(self._current_theme)
        
        # 프로그램 시작 시 강제로 수동 모드로 설정 (설정 로드 후)
        self._set_ai_mode(False)
        print(f"DEBUG: 초기 모드 설정 후 _is_ai_mode = {self._is_ai_mode}")  # 디버깅용

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

        # 상단 3개 컬럼 (수동 | 계정 | AI)
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.setSpacing(12)
        
        self.manual_panel = ManualModePanel()
        self.account_panel = AccountPanel()
        self.ai_control_panel = AiControlPanel()
        
        top_layout.addWidget(self.manual_panel, 1)
        top_layout.addWidget(self.account_panel, 1)
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
        self.ai_control_panel.api_key_changed.connect(self._on_api_key_changed)
        self.ai_control_panel.validate_api_key.connect(self._validate_api_key)
        self.ai_control_panel.keyword_changed.connect(lambda _: self._save_settings())
        self.ai_control_panel.model_changed.connect(lambda _: self._save_settings())
        self.ai_control_panel.count_changed.connect(lambda _: self._save_settings())
        self.ai_control_panel.start_requested.connect(self._start_workflow)
        self.ai_control_panel.stop_requested.connect(self._stop_workflow)

        self.manual_panel.title_changed.connect(lambda _: self._save_settings())
        self.manual_panel.tags_changed.connect(lambda _: self._save_settings())
        self.manual_panel.file_selected.connect(self._on_manual_file_selected)
        self.manual_panel.image_selected.connect(self._on_image_selected)
        self.manual_panel.schedule_changed.connect(self._on_schedule_changed)
        self.manual_panel.schedule_enabled.connect(self._on_schedule_enabled)
        self.manual_panel.repeat_toggled.connect(self._on_repeat_toggled)
        self.manual_panel.interval_changed.connect(self._on_interval_changed)

        self.account_panel.account_selected.connect(self._on_account_selected)
        self.account_panel.request_add_account.connect(self._on_add_account)
        self.account_panel.request_remove_account.connect(self._on_remove_account)
        self.account_panel.request_remove_accounts.connect(self._on_remove_accounts)
        self.account_panel.request_open_profile.connect(self._open_profile_dir)
        self.account_panel.request_open_browser.connect(self._open_browser_for_account)

    # --- 상태 관리 ---

    def _current_user(self) -> str:
        import getpass

        return getpass.getuser()

    def _settings_file(self) -> Path:
        return self.user_data_dir / "settings.json"

    def _accounts_file(self) -> Path:
        return self.database_path

    def _load_settings(self) -> None:
        settings = load_settings(self._settings_file())
        self.ai_control_panel.api_key_edit.setText(settings.api_key)
        self.ai_control_panel.keyword_edit.setText(settings.keyword)
        self.ai_control_panel.model_combo.setCurrentText(settings.model)
        # 모드 설정은 나중에 강제로 설정하므로 여기서는 로드하지 않음
        # self.header.set_mode(settings.use_ai)
        # self._is_ai_mode = settings.use_ai
        self.manual_panel._current_interval = settings.interval_minutes
        self.manual_panel.update_repeat_status(settings.repeat_enabled, settings.interval_minutes)
        self.manual_panel.manual_title_edit.setText(settings.manual_title)
        self.manual_panel.manual_tags_edit.setText(settings.manual_tags)
        self.manual_panel._current_schedule = settings.schedule_minutes
        self.manual_panel._schedule_enabled = settings.schedule_enabled
        self.manual_panel.schedule_toggle_btn.setChecked(settings.schedule_enabled)
        self.manual_panel.schedule_toggle_btn.setText("ON" if settings.schedule_enabled else "OFF")
        self.manual_panel.schedule_decrease_btn.setEnabled(settings.schedule_enabled)
        self.manual_panel.schedule_increase_btn.setEnabled(settings.schedule_enabled)
        self.manual_panel._update_schedule_display()
        if settings.image_file_path:
            self.manual_panel.image_file_edit.setText(settings.image_file_path)

    def _save_settings(self) -> None:
        """설정 저장을 debounce로 처리 (성능 최적화)"""
        # 타이머를 재시작하여 500ms 후에 실제 저장
        self._settings_save_timer.stop()
        self._settings_save_timer.start(500)
    
    def _do_save_settings(self) -> None:
        """실제 설정 저장 수행"""
        try:
            settings = UserSettings(
                keyword=self.ai_control_panel.keyword_edit.text(),
                use_ai=self._is_ai_mode,
                api_key=self.ai_control_panel.api_key_edit.text(),
                model=self.ai_control_panel.model_combo.currentText(),
                manual_title=self.manual_panel.manual_title_edit.text(),
                manual_tags=self.manual_panel.manual_tags_edit.text(),
                repeat_enabled=self.manual_panel.repeat_toggle_btn.isChecked(),
                interval_minutes=self.manual_panel._current_interval,
                image_file_path=self.manual_panel.image_file_edit.text(),
                schedule_minutes=self.manual_panel._current_schedule,
                schedule_enabled=self.manual_panel._schedule_enabled,
            )
            save_settings(self._settings_file(), settings)
        except Exception as e:
            logger.debug(f"설정 저장 중 오류 (무시됨): {e}")

    def _load_accounts(self) -> None:
        accounts_map = load_accounts(self._accounts_file(), self.profiles_root)
        self._accounts = accounts_map
        selected_id = self._selected_account_id if self._selected_account_id in accounts_map else None
        self._refresh_accounts_ui(selected_id)

    def _save_accounts(self) -> None:
        """계정 저장을 debounce로 처리 (성능 최적화)"""
        # 타이머를 재시작하여 300ms 후에 실제 저장
        self._accounts_save_timer.stop()
        self._accounts_save_timer.start(300)
    
    def _do_save_accounts(self) -> None:
        """실제 계정 저장 수행"""
        try:
            save_accounts(self._accounts_file(), self._accounts.values())
        except Exception as e:
            logger.debug(f"계정 저장 중 오류 (무시됨): {e}")

    def _refresh_accounts_ui(self, selected_id: str | None = None) -> None:
        self.account_panel.set_accounts(self._accounts.values(), selected_id)
        if not self._accounts:
            self._selected_account_id = None

    # --- 이벤트 핸들러 ---

    def _set_ai_mode(self, enabled: bool) -> None:
        """AI 모드와 수동 모드를 배타적으로 전환합니다."""
        self._is_ai_mode = enabled
        self.header.set_mode(enabled)
        
        if enabled:
            # AI 모드: AI 설정 활성화, 수동 패널 비활성화 (오버레이 표시)
            self.ai_control_panel.set_ai_mode_enabled(True)
            self.manual_panel.setEnabled(False)  # 수동 패널에 오버레이 표시
        else:
            # 수동 모드: 수동 패널 활성화, AI 설정 비활성화 (오버레이 표시)
            self.ai_control_panel.set_ai_mode_enabled(False)  # AI 설정에 오버레이 표시
            self.manual_panel.setEnabled(True)  # 수동 패널 활성화 (오버레이 숨김)
        
        self._save_settings()

    def _on_api_key_changed(self, value: str) -> None:
        self._api_valid = False
        value = value.strip()
        is_candidate = value.startswith("sk-") or value.startswith("sk-proj-")
        self.ai_control_panel.set_validate_enabled(is_candidate)
        if not value:
            self.ai_control_panel.set_api_status("상태: 미입력", state="default")
            return
        if is_candidate:
            self.ai_control_panel.set_api_status("상태: 미확인", state="default")
        else:
            self.ai_control_panel.set_api_status("상태: 키 형식 오류", state="error")
        self._save_settings()

    def _validate_api_key(self) -> None:
        api_key = self.ai_control_panel.api_key_edit.text().strip()
        if not api_key:
            QtWidgets.QMessageBox.warning(self, "검증 실패", "API 키를 입력해주세요.")
            return
        if not (api_key.startswith("sk-") or api_key.startswith("sk-proj-")):
            self.ai_control_panel.set_api_status("상태: 키 형식 오류", state="error")
            QtWidgets.QMessageBox.warning(self, "키 형식 오류", "OpenAI에서 발급된 키 형식이 아닙니다.")
            return

        if self._validation_thread and self._validation_thread.isRunning():
            return

        self.ai_control_panel.set_api_status("상태: 검증 중", state="loading")
        self.ai_control_panel.set_validate_enabled(False)

        worker = _ApiKeyValidator(api_key)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda success, message: self._on_api_validation_finished(success, message, worker, thread))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._validation_thread = thread
        thread.start()

    def _on_api_validation_finished(self, success: bool, message: str, worker: _ApiKeyValidator, thread: QtCore.QThread) -> None:
        del worker  # for type checkers
        self._validation_thread = None
        self.ai_control_panel.set_validate_enabled(True)
        if success:
            self._api_valid = True
            self.ai_control_panel.set_api_status("상태: 사용 가능", state="success")
            QtWidgets.QMessageBox.information(self, "검증 완료", "API 키가 정상적으로 확인되었습니다.")
            self._save_settings()
        else:
            self._api_valid = False
            self.ai_control_panel.set_api_status("상태: 검증 실패", state="error")
            QtWidgets.QMessageBox.warning(self, "검증 실패", "OpenAI API 키 확인에 실패했습니다. 키를 다시 확인해주세요.")

    def _on_manual_file_selected(self, path: Path) -> None:
        self._save_settings()

    def _on_image_selected(self, path: Path) -> None:
        self._save_settings()

    def _on_schedule_changed(self, minutes: int) -> None:
        self._save_settings()
    
    def _on_schedule_enabled(self, enabled: bool) -> None:
        self._save_settings()

    def _on_repeat_toggled(self, enabled: bool) -> None:
        self.manual_panel.update_repeat_status(enabled, self.manual_panel._current_interval)
        self._save_settings()

    def _on_interval_changed(self, value: int) -> None:
        if self.manual_panel.repeat_toggle_btn.isChecked():
            self.manual_panel.update_repeat_status(True, value)
        self._save_settings()

    def _on_account_selected(self, account_id: str) -> None:
        self._selected_account_id = account_id or None
        profile = self._accounts.get(account_id) if account_id else None
        self.account_panel.update_profile_path(profile.profile_dir if profile else None)

    def _on_add_account(self, account_id: str, password: str) -> None:
        account_id = account_id.strip()
        if not account_id:
            QtWidgets.QMessageBox.warning(self, "입력 오류", "네이버 아이디를 입력해주세요.")
            return

        profile_dir = ensure_profile_dir(self.profiles_root, account_id, reset=False)
        existing = self._accounts.get(account_id)
        if existing:
            existing.profile_dir = profile_dir
            if password:
                existing.password = password
            self._accounts[account_id] = existing
            message = f"'{account_id}' 계정 정보가 업데이트되었습니다."
        else:
            self._accounts[account_id] = AccountProfile(
                account_id=account_id,
                profile_dir=profile_dir,
                password=password,
                login_initialized=False,
            )
            message = f"'{account_id}' 계정이 추가되었습니다."

        self._selected_account_id = account_id
        self._save_accounts()
        self._refresh_accounts_ui(account_id)
        self._log(message)

    def _on_remove_account(self, account_id: str) -> None:
        if QtWidgets.QMessageBox.question(
            self,
            "삭제 확인",
            f"'{account_id}' 계정을 삭제하시겠습니까?\n프로필 폴더는 삭제되지 않습니다.",
        ) != QtWidgets.QMessageBox.Yes:
            return
        self._accounts.pop(account_id, None)
        self._save_accounts()
        next_id = next(iter(self._accounts)) if self._accounts else None
        self._refresh_accounts_ui(next_id)
    
    def _on_remove_accounts(self, account_ids: list[str]) -> None:
        """여러 계정을 한 번에 삭제 (이미 확인을 받았음)"""
        for account_id in account_ids:
            self._accounts.pop(account_id, None)
        self._save_accounts()
        next_id = next(iter(self._accounts)) if self._accounts else None
        self._refresh_accounts_ui(next_id)

    def _log(self, message: str) -> None:
        """로그 메시지를 출력합니다."""
        logger.info(message)
        self.repeat_panel.append_log(message)

    def _open_profile_dir(self, account_id: str) -> None:
        profile = self._accounts.get(account_id)
        if not profile:
            return
        path = profile.profile_dir
        if not path.exists():
            QtWidgets.QMessageBox.warning(self, "경로 없음", "프로필 폴더가 존재하지 않습니다.")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _open_browser_for_account(self, account_id: str) -> None:
        account = self._accounts.get(account_id)
        if not account:
            QtWidgets.QMessageBox.warning(self, "계정 없음", "선택된 계정이 없습니다.")
            return

        self._log(f"'{account_id}' 계정용 브라우저 준비 중...")

        try:
            driver = create_chrome_driver(account.profile_dir)
            self._log(f"'{account_id}' 계정용 브라우저가 성공적으로 생성되었습니다.")
        except WebDriverException as exc:
            error_msg = f"브라우저 초기화 실패: {exc}"
            QtWidgets.QMessageBox.critical(self, "브라우저 오류", error_msg)
            self._log(f"❌ {error_msg}")
            return
        except Exception as exc:
            error_msg = f"예상치 못한 오류: {exc}"
            QtWidgets.QMessageBox.critical(self, "초기화 오류", error_msg)
            self._log(f"❌ {error_msg}")
            return

        self._driver = driver
        
        # 브라우저 초기화 대기 (비차단)
        self._non_blocking_wait_ms(2000)
        self._log("브라우저 초기화 완료, 네이버 메인 페이지로 이동 중...")

        # 먼저 간단한 URL로 연결 테스트
        try:
            self._log("네트워크 연결 테스트 중...")
            driver.get("about:blank")
            self._non_blocking_wait_ms(1000)
            self._log("브라우저 네트워크 연결 확인 완료")
        except Exception as exc:
            error_msg = f"브라우저 네트워크 초기화 실패: {exc}"
            self._log(f"❌ {error_msg}")
            try:
                driver.quit()
            except Exception:
                pass
            self._driver = None
            return

        # 네이버 접속 시도 (여러 방법으로)
        naver_urls = [
            "https://www.naver.com/",
            "https://naver.com/",
            "https://m.naver.com/"  # 모바일 버전도 시도
        ]
        
        success = False
        last_error = None
        
        for i, url in enumerate(naver_urls):
            try:
                self._log(f"네이버 접속 시도 {i+1}/{len(naver_urls)}: {url}")
                driver.get(url)

                # 페이지 로딩 대기
                WebDriverWait(driver, 30).until(  # 15초 -> 30초 증가 (느린 인터넷)
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )

                # 페이지 완전 로딩 확인
                try:
                    WebDriverWait(driver, 20).until(  # 8초 -> 20초 증가
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    self._log(f"✅ 네이버 페이지 접속 성공: {url}")
                    success = True
                    break
                except Exception:
                    self._log(f"⚠️ {url} 부분적 로딩 성공, 다음 URL 시도")
                    continue
            except WebDriverException as exc:
                last_error = exc
                self._log(f"❌ {url} 접속 실패: {str(exc)[:100]}...")
                continue  # 다음 URL 시도
                
        # for 루프 완료 후 처리
        if not success:
            if last_error:
                error_msg = f"모든 네이버 URL 접속 실패. 마지막 오류: {last_error}"
                self._log(f"❌ {error_msg}")
                
                # DNS 문제인 경우 특별한 안내 메시지
                if "ERR_NAME_NOT_RESOLVED" in str(last_error):
                    dns_msg = ("DNS 해결 문제가 발생했습니다.\n\n"
                             "해결 방법:\n"
                             "1. 시스템 환경설정 > 네트워크 > 고급 > DNS에서\n"
                             "   DNS 서버를 8.8.8.8, 1.1.1.1로 변경\n"
                             "2. 터미널에서 'sudo dscacheutil -flushcache' 실행\n"
                             "3. VPN이나 방화벽 설정 확인\n"
                             "4. Wi-Fi 재연결 또는 이더넷 케이블 확인")
                    QtWidgets.QMessageBox.warning(self, "DNS 오류", dns_msg)
                else:
                    QtWidgets.QMessageBox.warning(self, "네이버 접속 오류", error_msg)
            else:
                self._log("❌ 모든 네이버 URL 접속 시도가 실패했습니다.")
            
            try:
                driver.quit()
            except:
                pass
            self._driver = None
            return

        # 로그인 상태 확인 (브라우저 연결 체크 포함)
        try:
            # 브라우저 연결 상태 확인
            driver.current_url  # 브라우저가 살아있는지 체크
            current_logged_in_account = self._check_current_logged_in_account(driver)
        except Exception as exc:
            self._log(f"❌ 브라우저 연결 오류: {exc}")
            self._log("브라우저 연결이 끊어졌습니다. 프로세스를 중단합니다.")
            try:
                driver.quit()
            except:
                pass
            self._driver = None
            return
        
        if current_logged_in_account is None:
            # 로그인되지 않은 상태 - 바로 로그인 프로세스 진행
            self._log("🔐 로그인되지 않은 상태입니다. 자동 로그인을 시작합니다.")
        elif current_logged_in_account == account_id:
            # 같은 계정이 이미 로그인되어 있음
            if self._mark_account_logged_in(account_id):
                self._log(f"✅ '{account_id}' 계정이 이미 로그인된 상태입니다.")
            return
        else:
            # 다른 계정이 로그인되어 있음 - 로그아웃 필요
            self._log(f"⚠️ 다른 계정 '{current_logged_in_account}'이 로그인되어 있습니다.")
            if self._logout_current_account(driver):
                self._log(f"✅ 기존 계정 로그아웃 완료. '{account_id}' 계정으로 로그인을 진행합니다.")
            else:
                self._log("❌ 기존 계정 로그아웃에 실패했습니다. 계속 진행합니다.")

        # 자동 로그인 프로세스 시작
        self._log("🔐 자동 로그인 프로세스를 시작합니다...")
        self._perform_automatic_login(driver, account, account_id)

    def _mark_account_logged_in(self, account_id: str) -> bool:
        account = self._accounts.get(account_id)
        if not account:
            return False
        if not account.login_initialized:
            account.login_initialized = True
            self._accounts[account_id] = account
            self._save_accounts()
            self._refresh_accounts_ui(account_id)
            self._log(f"'{account_id}' 계정을 로그인된 상태로 표시했습니다.")
            return True
        return False

    def _schedule_login_status_check(self, account_id: str, driver, attempts: int = 12) -> None:
        if account_id in self._pending_login_checks:
            return
        self._pending_login_checks[account_id] = True

        def check(remaining: int) -> None:
            if account_id not in self._pending_login_checks:
                return
            if not getattr(driver, "session_id", None):
                self._pending_login_checks.pop(account_id, None)
                return
            try:
                cookies = {cookie.get("name") for cookie in driver.get_cookies()}
            except WebDriverException:
                self._pending_login_checks.pop(account_id, None)
                return

            if {"NID_SES", "NID_AUT", "NID_JKL"}.intersection(cookies) or self._check_login_status(driver):
                self._pending_login_checks.pop(account_id, None)
                if self._mark_account_logged_in(account_id):
                    self._log(f"'{account_id}' 계정 로그인 상태를 확인했습니다.")
                return

            if remaining > 0:
                QtCore.QTimer.singleShot(4000, lambda: check(remaining - 1))
            else:
                self._pending_login_checks.pop(account_id, None)
                self._log("로그인 상태를 확인하지 못했습니다. 창이 열려 있는지 또는 추가 인증이 필요한지 확인해주세요.")

        QtCore.QTimer.singleShot(4000, lambda: check(attempts))

    def _check_login_status(self, driver) -> bool:
        """네이버 로그인 상태를 정확하게 확인합니다."""
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))  # 5초 -> 15초
        except Exception:
            return False

        # 1. 쿠키 확인 (가장 확실한 방법)
        try:
            cookies = {cookie.get("name") for cookie in driver.get_cookies()}
            if {"NID_SES", "NID_AUT", "NID_JKL"}.intersection(cookies):
                self._log("✅ 쿠키 확인: 로그인된 상태입니다.")
                return True
        except WebDriverException:
            pass

        # 2. 네이버 메인 페이지의 로그인 버튼 확인 (정확한 선택자 사용)
        try:
            login_button = driver.find_elements(By.CSS_SELECTOR, "a.MyView-module__link_login___HpHMW")
            if login_button and len(login_button) > 0:
                self._log("🔐 로그인 버튼 발견: 로그인이 필요합니다.")
                return False
        except Exception:
            pass

        # 3. 프로필 영역 또는 로그아웃 버튼 확인
        try:
            # 로그인된 상태에서 나타나는 요소들
            profile_elements = driver.find_elements(By.CSS_SELECTOR, 
                "a[data-clk*='logout'], .MyView-module__profile, .MyView-module__user_info")
            if profile_elements and len(profile_elements) > 0:
                self._log("✅ 프로필 영역 확인: 로그인된 상태입니다.")
            return True
        except Exception:
            pass

        # 4. 블로그 메뉴 접근 가능 여부 확인
        try:
            blog_menu = driver.find_elements(By.XPATH, 
                "//span[contains(@class,'MyView-module__item_text') and text()='블로그']")
            if blog_menu and len(blog_menu) > 0:
                self._log("✅ 블로그 메뉴 접근 가능: 로그인된 상태입니다.")
                return True
        except Exception:
            pass

        self._log("🔐 로그인 상태 확인 완료: 로그인이 필요합니다.")
        return False

    def _check_current_logged_in_account(self, driver) -> Optional[str]:
        """현재 로그인된 계정 ID를 확인합니다."""
        try:
            # 1단계: 먼저 페이지에서 실제 로그인 상태 확인
            try:
                # 로그인 버튼이 있으면 로그인되지 않은 상태
                login_buttons = driver.find_elements(By.CSS_SELECTOR, 
                    "a[href*='nidlogin'], .MyView-module__link_login, .login_link")
                
                if login_buttons:
                    for button in login_buttons:
                        if button.is_displayed() and ("로그인" in button.text or "LOGIN" in button.text.upper()):
                            self._log("로그인 버튼이 발견됨: 로그인되지 않은 상태입니다.")
                            return None
                
                # 로그아웃 버튼이 있으면 로그인된 상태
                logout_buttons = driver.find_elements(By.CSS_SELECTOR, 
                    "button.MyView-module__btn_logout___bsTOJ, a[href*='logout'], .logout")
                
                logged_in = False
                for button in logout_buttons:
                    if button.is_displayed() and "로그아웃" in button.text:
                        logged_in = True
                        break
                
                if not logged_in:
                    self._log("로그아웃 버튼이 없음: 로그인되지 않은 상태입니다.")
                    return None
                    
            except Exception:
                # 요소 찾기 실패 시 쿠키로 재확인
                pass
            
            # 2단계: 쿠키에서 로그인된 계정 정보 확인 (추가 검증)
            cookies = {cookie.get("name"): cookie.get("value") for cookie in driver.get_cookies()}
            if not {"NID_SES", "NID_AUT", "NID_JKL"}.intersection(cookies.keys()):
                self._log("네이버 로그인 쿠키가 없음: 로그인되지 않은 상태입니다.")
                return None  # 로그인되지 않음
            
            # 3단계: 페이지에서 로그인된 사용자 정보 찾기
            try:
                # 방법 1: 마이 메뉴에서 사용자 정보 확인
                profile_elements = driver.find_elements(By.CSS_SELECTOR, 
                    ".MyView-module__user_info, .gnb_my_name, .my_name")
                
                for element in profile_elements:
                    if element.text and element.text.strip():
                        # 텍스트에서 계정 ID 추출 시도
                        text = element.text.strip()
                        if "님" in text:
                            account_id = text.replace("님", "").strip()
                            if account_id:  # 빈 문자열이 아닌 경우만
                                self._log(f"현재 로그인된 계정: {account_id}")
                                return account_id
                
                # 방법 2: 로그아웃 버튼 근처에서 사용자 정보 확인
                for button in logout_buttons:
                    try:
                        # 로그아웃 버튼 주변의 텍스트에서 계정 정보 찾기
                        parent = button.find_element(By.XPATH, "..")
                        if parent.text and "님" in parent.text:
                            lines = parent.text.split('\n')
                            for line in lines:
                                if "님" in line and line.strip() != "로그아웃":
                                    account_id = line.replace("님", "").strip()
                                    if account_id:  # 빈 문자열이 아닌 경우만
                                        self._log(f"현재 로그인된 계정: {account_id}")
                                        return account_id
                    except Exception:
                        continue
                
                # 로그인은 되어 있지만 계정 ID를 확인할 수 없음
                self._log("로그인된 상태이지만 계정 ID를 확인할 수 없습니다.")
                return "unknown_account"
                
            except Exception:
                # 로그인된 상태이지만 계정 정보를 가져올 수 없음
                self._log("로그인 상태 확인 중 오류 발생, 'unknown_account'로 처리")
                return "unknown_account"
                
        except Exception as exc:
            self._log(f"로그인 상태 체크 중 오류: {exc}")
            return None

    def _logout_current_account(self, driver) -> bool:
        """현재 로그인된 계정을 로그아웃합니다."""
        
        try:
            self._log("기존 계정 로그아웃을 시도합니다...")
            
            # 로그아웃 버튼 찾기
            logout_selectors = [
                "button.MyView-module__btn_logout___bsTOJ",
                "a[href*='logout']",
                "button[data-clk*='logout']",
                ".btn_logout"
            ]
            
            logout_button = None
            for selector in logout_selectors:
                try:
                    logout_button = WebDriverWait(driver, 10).until(  # 5초 -> 10초
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    self._log(f"로그아웃 버튼 찾음: {selector}")
                    break
                except:
                    continue
            
            if not logout_button:
                self._log("❌ 로그아웃 버튼을 찾을 수 없습니다.")
                return False
            
            # 로그아웃 버튼 클릭
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", logout_button)
                self._non_blocking_wait_ms(500)
                logout_button.click()
                self._log("✅ 로그아웃 버튼 클릭 완료")
            except:
                # JavaScript 클릭 시도
                driver.execute_script("arguments[0].click();", logout_button)
                self._log("✅ 로그아웃 버튼 클릭 완료 (JS)")
            
            # 로그아웃 완료 대기
            self._non_blocking_wait_ms(3000)
            
            # 로그아웃 확인
            for _ in range(5):  # 5초간 확인
                try:
                    cookies = {cookie.get("name") for cookie in driver.get_cookies()}
                    if not {"NID_SES", "NID_AUT", "NID_JKL"}.intersection(cookies):
                        self._log("✅ 로그아웃이 완료되었습니다.")
                        return True
                    self._non_blocking_wait_ms(1000)
                except:
                    self._non_blocking_wait_ms(1000)
                    continue
            
            self._log("⚠️ 로그아웃이 완전히 완료되지 않았을 수 있습니다.")
            return True  # 버튼 클릭은 성공했으므로 True 반환
            
        except Exception as exc:
            self._log(f"❌ 로그아웃 실패: {exc}")
            return False

    def _perform_automatic_login(self, driver, account: AccountProfile, account_id: str) -> None:
        """네이버 자동 로그인을 수행합니다."""
        
        try:
            # 1단계: 네이버 메인 페이지에서 로그인 버튼 클릭
            self._log("1단계: 네이버 메인 페이지에서 로그인 버튼을 찾는 중...")
            
            try:
                # 로그인 버튼 찾기 및 클릭
                login_button = WebDriverWait(driver, 20).until(  # 10초 -> 20초
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "a.MyView-module__link_login___HpHMW"))
                )
                
                # 버튼이 화면에 보이도록 스크롤
                driver.execute_script("arguments[0].scrollIntoView(true);", login_button)
                self._non_blocking_wait_ms(1000)
                
                login_button.click()
                self._log("✅ 네이버 메인의 로그인 버튼을 클릭했습니다.")
                
                # 로그인 페이지 로딩 대기
                self._non_blocking_wait_ms(3000)
                
            except Exception as exc:
                self._log(f"⚠️ 메인 페이지 로그인 버튼 클릭 실패: {exc}")
                # 직접 로그인 페이지로 이동
                self._log("직접 로그인 페이지로 이동합니다...")
                driver.get("https://nid.naver.com/nidlogin.login")
                self._non_blocking_wait_ms(2000)

            # 2단계: 로그인 폼에 아이디/비밀번호 입력
            self._log("2단계: 로그인 폼에 정보를 입력 중...")
            
            if self._fill_login_form_auto(driver, account):
                self._log("✅ 아이디와 비밀번호를 성공적으로 입력했습니다.")
            else:
                self._log("⚠️ 일부 정보만 입력되었습니다. 수동 확인이 필요할 수 있습니다.")

            # 3단계: 사용자 수동 로그인 대기
            self._log("3단계: 로그인 정보 입력 및 로그인 상태 유지 설정이 완료되었습니다.")
            self._log("👆 수동으로 로그인 버튼을 클릭해주세요.")
            self._log("💡 로그인 버튼을 클릭하시면 자동으로 로그인 완료를 감지합니다.")
            
            # 4단계: 로그인 완료 대기 및 확인
            self._log("4단계: 사용자 로그인 완료를 기다리는 중...")
            self._wait_for_manual_login_completion(driver, account_id)
                
        except Exception as exc:
            error_msg = f"자동 로그인 프로세스 중 오류 발생: {exc}"
            self._log(f"❌ {error_msg}")
            QtWidgets.QMessageBox.warning(self, "자동 로그인 오류", error_msg)

    def _fill_login_form_auto(self, driver, account: AccountProfile) -> bool:
        """로그인 폼에 아이디와 비밀번호를 자동으로 입력합니다."""
        
        try:
            # ID 입력 필드 찾기 및 입력
            self._log("아이디 입력 중...")
            id_input = WebDriverWait(driver, 20).until(  # 10초 -> 20초
                EC.presence_of_element_located((By.CSS_SELECTOR, "input#id"))
            )
            
            # 기존 내용 지우고 아이디 입력
            id_input.clear()
            self._non_blocking_wait_ms(500)
            id_input.send_keys(account.account_id)
            self._non_blocking_wait_ms(1000)
            
            # 비밀번호 입력 필드 찾기 및 입력
            if account.password:
                self._log("비밀번호 입력 중...")
                pw_input = WebDriverWait(driver, 10).until(  # 5초 -> 10초
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input#pw"))
                )
                
                pw_input.clear()
                self._non_blocking_wait_ms(500)
                pw_input.send_keys(account.password)
                self._non_blocking_wait_ms(1000)
                
                self._log("✅ 아이디와 비밀번호 입력 완료")
            else:
                self._log("⚠️ 저장된 비밀번호가 없습니다. 아이디만 입력했습니다.")
            
            # 로그인 상태 유지 체크박스 클릭 (아이디만 있어도 실행)
            self._click_keep_login_checkbox(driver)
            
            return account.password is not None
                
        except Exception as exc:
            self._log(f"❌ 로그인 폼 입력 실패: {exc}")
            return False

    def _click_keep_login_checkbox(self, driver) -> None:
        """로그인 상태 유지 체크박스를 클릭합니다."""
        
        try:
            self._log("로그인 상태 유지 체크박스 클릭 중...")
            
            # 여러 선택자로 체크박스 찾기 시도
            checkbox_selectors = [
                '#keep',  # div 요소 (role="checkbox")
                '#nvlong',  # input 요소
                '.keep_check',  # div 클래스
                '.input_keep',  # input 클래스
                'div[role="checkbox"]',  # role 속성으로 찾기
                'input[name="nvlong"]'  # name 속성으로 찾기
            ]
            
            checkbox_element = None
            used_selector = None
            
            for selector in checkbox_selectors:
                try:
                    checkbox_element = WebDriverWait(driver, 10).until(  # 3초 -> 10초
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    used_selector = selector
                    self._log(f"로그인 상태 유지 체크박스 찾음: {selector}")
                    break
                except:
                    continue
            
            if not checkbox_element:
                self._log("⚠️ 로그인 상태 유지 체크박스를 찾을 수 없습니다.")
                return
            
            # 이미 체크되어 있는지 확인
            try:
                if used_selector == '#keep':
                    # div 요소의 경우 aria-checked 속성 확인
                    is_checked = checkbox_element.get_attribute('aria-checked') == 'true'
                elif used_selector == '#nvlong' or 'input' in used_selector:
                    # input 요소의 경우 checked 속성 확인
                    is_checked = checkbox_element.is_selected() or checkbox_element.get_attribute('checked')
                else:
                    # 기타 경우는 클릭 진행
                    is_checked = False
                
                if is_checked:
                    self._log("✅ 로그인 상태 유지가 이미 체크되어 있습니다.")
                    return
                    
            except Exception:
                # 체크 상태 확인 실패 시 그냥 클릭 진행
                pass
            
            # 체크박스 클릭
            try:
                # 화면에 보이도록 스크롤
                driver.execute_script("arguments[0].scrollIntoView(true);", checkbox_element)
                self._non_blocking_wait_ms(500)
                
                # 일반 클릭 시도
                checkbox_element.click()
                self._log("✅ 로그인 상태 유지 체크박스를 클릭했습니다.")
                
            except Exception as e:
                # JavaScript 클릭 시도
                try:
                    driver.execute_script("arguments[0].click();", checkbox_element)
                    self._log("✅ 로그인 상태 유지 체크박스를 클릭했습니다 (JS).")
                except Exception as e2:
                    self._log(f"⚠️ 로그인 상태 유지 체크박스 클릭 실패: {e2}")
            
            # 클릭 후 잠시 대기
            self._non_blocking_wait_ms(500)
            
        except Exception as exc:
            self._log(f"⚠️ 로그인 상태 유지 처리 중 오류: {exc}")

    # 이 메서드는 더 이상 사용하지 않음 (수동 로그인으로 변경)
    # def _click_login_button(self, driver) -> bool:
    #     """로그인 버튼을 클릭합니다."""
    #     # 수동 로그인으로 변경되어 사용하지 않음

    def _wait_for_manual_login_completion(self, driver, account_id: str) -> None:
        """사용자의 수동 로그인 완료를 기다리고 확인합니다."""
        
        self._log("🔍 사용자 로그인 완료를 실시간으로 감지하고 있습니다...")
        self._log("👆 브라우저에서 로그인 버튼을 클릭해주세요.")
        self._log("🔐 CAPTCHA나 2단계 인증이 나타날 수 있습니다.")
        self._log("✅ 로그인이 완료되면 자동으로 브라우저가 닫히고 계정에 'O' 표시됩니다.")
        
        # 로그인 완료를 기다림 (최대 300초 = 5분)
        captcha_check_interval = 10  # CAPTCHA 체크 간격 (10초)
        last_captcha_check = 0
        
        for i in range(300):
            self._non_blocking_wait_ms(1000)
            
            try:
                # 1. URL 변화 확인 (가장 확실한 방법)
                current_url = driver.current_url
                
                # 로그인이 완료되면 네이버 메인으로 리디렉트됨
                if "naver.com" in current_url and "nidlogin" not in current_url:
                    self._log("🔄 페이지 리디렉트 감지: 로그인 프로세스 진행 중...")
                    self._non_blocking_wait_ms(3000)  # 페이지 안정화 대기
                    
                    # 2. 쿠키 확인으로 로그인 상태 재확인
                    if self._verify_login_success(driver):
                        self._log("🎉 로그인 완료 감지!")
                        self._complete_login_process(driver, account_id)
                        return
                
                # 3. 페이지에서 로그인 성공 요소 확인 (URL이 바뀌지 않는 경우도 대비)
                # CAPTCHA 체크는 10초마다만 수행하여 성능 최적화
                if i - last_captcha_check >= captcha_check_interval:
                    if self._detect_login_success_elements(driver):
                        self._log("🎉 로그인 성공 요소 감지!")
                        self._non_blocking_wait_ms(2000)  # 안정화 대기
                        self._complete_login_process(driver, account_id)
                        return
                    last_captcha_check = i
                else:
                    # 간단한 URL 체크만 수행
                    if "nidlogin" not in current_url and "naver.com" in current_url:
                        self._log("🎉 로그인 완료! (URL 변화 감지)")
                        self._non_blocking_wait_ms(2000)
                        self._complete_login_process(driver, account_id)
                        return
                
                # 진행 상황 주기적 알림
                if i % 30 == 0 and i > 0:  # 30초마다
                    self._log(f"⏳ 로그인 대기 중... ({i//60}분 {i%60}초 경과)")
                    
            except Exception as e:
                # 브라우저가 닫힌 경우
                if "no such window" in str(e).lower():
                    self._log("❌ 브라우저가 닫혔습니다. 로그인을 완료하지 못했습니다.")
                    return
                continue
        
        # 5분 후에도 로그인이 완료되지 않았을 때 - 계정을 사용불가로 표시
        self._log("⏰ 로그인 대기 시간이 초과되었습니다 (5분).")
        self._log("❌ 해당 계정은 '사용불가'로 표시됩니다.")
        
        # 계정을 로그인 실패로 표시
        account = self._accounts.get(account_id)
        if account:
            account.login_failed = True
            self._accounts[account_id] = account
            self._save_accounts()
            self._refresh_accounts_ui(account_id)
            self._log(f"❌ '{account_id}' 계정이 사용불가로 표시되었습니다.")
        
        # 브라우저 닫기
        try:
            driver.quit()
            self._driver = None
        except Exception:
            pass

    def _verify_login_success(self, driver) -> bool:
        """쿠키를 확인하여 로그인 성공을 검증합니다."""
        try:
            cookies = {cookie.get("name") for cookie in driver.get_cookies()}
            login_cookies = {"NID_SES", "NID_AUT", "NID_JKL"}
            
            if login_cookies.intersection(cookies):
                self._log("✅ 로그인 쿠키 확인: 로그인이 성공적으로 완료되었습니다.")
                return True
            return False
        except Exception:
            return False

    def _detect_login_success_elements(self, driver) -> bool:
        """페이지 요소를 확인하여 로그인 성공을 감지합니다."""
        try:
            current_url = driver.current_url
            
            # CAPTCHA나 추가 보안 인증 감지
            captcha_elements = driver.find_elements(By.CSS_SELECTOR, 
                ".captcha_area, #captcha, [id*='captcha'], .captcha")
            
            if captcha_elements and len(captcha_elements) > 0:
                self._log("🔐 CAPTCHA 보안 인증이 감지되었습니다. 이미지의 숫자를 입력해주세요.")
                return False
            
            # 2단계 인증 감지
            auth_elements = driver.find_elements(By.CSS_SELECTOR, 
                "[id*='sms'], [id*='otp'], .auth, .verification")
            
            if auth_elements and len(auth_elements) > 0:
                self._log("📱 2단계 인증이 감지되었습니다. 인증을 완료해주세요.")
                return False
            
            # 로그인 페이지에서 벗어났는지 확인 (가장 확실한 방법)
            if "nidlogin" not in current_url and "naver.com" in current_url:
                self._log("✅ 로그인 페이지를 벗어났습니다: 로그인 완료!")
                return True
            
            # 로그아웃 버튼이나 프로필 영역이 나타나면 로그인 성공
            success_elements = driver.find_elements(By.CSS_SELECTOR, 
                "a[href*='logout'], .MyView-module__profile, .gnb_my")
            
            if success_elements and len(success_elements) > 0:
                self._log("✅ 로그인 성공 요소 발견: 프로필 영역이 나타났습니다.")
                return True
                
            # 로그인 버튼이 사라졌는지 확인 (마지막 체크)
            if "nidlogin" not in current_url:  # 로그인 페이지가 아닌 경우만
                login_buttons = driver.find_elements(By.CSS_SELECTOR, "a.MyView-module__link_login___HpHMW")
                if not login_buttons or len(login_buttons) == 0:
                    self._log("✅ 로그인 버튼 사라짐 확인: 로그인이 완료된 것 같습니다.")
                    return True
                
            return False
        except Exception:
            return False

    def _complete_login_process(self, driver, account_id: str) -> None:
        """로그인 완료 후 마무리 작업을 수행합니다."""
        
        try:
            # 1. 계정 상태 업데이트
            self._mark_account_logged_in(account_id)
            self._log(f"🎯 '{account_id}' 계정이 성공적으로 로그인되었습니다!")
            
            # 2. 세션/쿠키 안정화를 위한 대기
            self._log("💾 세션과 쿠키를 안정화하는 중...")
            self._non_blocking_wait_ms(3000)
            
            # 3. 네이버 메인 페이지로 이동하여 세션 확인
            try:
                driver.get("https://www.naver.com/")
                self._non_blocking_wait_ms(2000)
                self._log("✅ 네이버 메인 페이지에서 세션 안정화 완료")
            except:
                pass
            
            # 4. 브라우저 닫기
            self._log("🔐 로그인 정보가 저장되었습니다. 브라우저를 닫습니다...")
            self._non_blocking_wait_ms(1000)
            
            try:
                driver.quit()
                self._driver = None
                self._log("✅ 브라우저가 성공적으로 닫혔습니다.")
                self._log(f"🎉 '{account_id}' 계정 설정이 완료되었습니다!")
            except Exception as e:
                self._log(f"⚠️ 브라우저 닫기 중 오류: {e}")
                
        except Exception as e:
            self._log(f"❌ 로그인 완료 처리 중 오류: {e}")

    def _show_manual_login_message(self) -> None:
        """수동 로그인 안내 메시지를 표시합니다."""
        message = ("자동 로그인이 완료되지 않았습니다.\n\n"
                  "다음 사항을 확인해주세요:\n"
                  "1. 브라우저에서 추가 인증 (CAPTCHA, 2단계 인증 등)\n"
                  "2. 아이디/비밀번호가 정확한지 확인\n"
                  "3. 계정이 정상 상태인지 확인\n\n"
                  "수동으로 로그인을 완료하시면 자동으로 상태가 업데이트됩니다.")
        
        QtWidgets.QMessageBox.information(self, "수동 로그인 필요", message)
        self._log("ℹ️ 수동 로그인 완료 후 자동으로 상태가 업데이트됩니다.")

    def _auto_fill_login_form(self, driver, account: AccountProfile) -> bool:
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "input#id")))  # 10초 -> 20초
            id_input = driver.find_element(By.CSS_SELECTOR, "input#id")
            pw_input = driver.find_element(By.CSS_SELECTOR, "input#pw")
            id_input.clear()
            id_input.send_keys(account.account_id)
            pw_input.clear()
            if account.password:
                pw_input.send_keys(account.password)
                return True
            return False
        except NoSuchElementException:
            self._log("로그인 폼 요소를 찾지 못했습니다. 페이지 레이아웃이 변경되었을 수 있습니다.")
            return False

    # --- 워크플로우 ---

    def _collect_params(self) -> WorkflowParams:
        count = self.ai_control_panel.count_group.checkedId() or 1
        manual_body = None
        if not self._is_ai_mode:
            file_path = Path(self.manual_panel.manual_file_edit.text()) if self.manual_panel.manual_file_edit.text() else None
            if file_path and file_path.exists():
                manual_body = file_path.read_text(encoding="utf-8")
        # 예약 발행이 OFF이면 schedule_minutes를 0으로 설정 (즉시 발행)
        schedule_minutes = self.manual_panel._current_schedule if self.manual_panel._schedule_enabled else 0
        
        return WorkflowParams(
            keyword=self.ai_control_panel.keyword_edit.text().strip() or self.manual_panel.manual_title_edit.text().strip(),
            count=count,
            use_ai=self._is_ai_mode,
            api_key=self.ai_control_panel.api_key_edit.text().strip() or None,
            model=self.ai_control_panel.model_combo.currentText(),
            manual_title=self.manual_panel.manual_title_edit.text().strip(),
            manual_body=manual_body,
            manual_tags=self.manual_panel.manual_tags_edit.text().strip(),
            manual_file_path=self.manual_panel.manual_file_edit.text() or None,
            image_file_path=self.manual_panel.image_file_edit.text() or None,
            schedule_minutes=schedule_minutes,
            naver_id=self._selected_account_id,
            naver_profile_dir=str(self._accounts[self._selected_account_id].profile_dir) if self._selected_account_id else None,
        )

    def _start_workflow(self) -> None:
        if self._is_ai_mode and not self._api_valid:
            QtWidgets.QMessageBox.warning(self, "입력 오류", "OpenAI 키 확인을 먼저 완료해주세요.")
            return

        # 수동 모드에서는 본문 파일이 반드시 필요
        if not self._is_ai_mode:
            from pathlib import Path as _Path
            file_text = self.manual_panel.manual_file_edit.text().strip()
            if not file_text or not _Path(file_text).exists():
                QtWidgets.QMessageBox.warning(self, "입력 오류", "본문 파일을 선택해 주세요.")
                return

        # 체크된 계정 목록 확인
        checked_accounts = self.account_panel.get_checked_accounts()
        
        # 로그인된 계정 목록 확인
        logged_in_accounts = [account_id for account_id, account in self._accounts.items() 
                            if account.login_initialized]
        
        # 체크된 계정이 있으면 우선 사용, 없으면 로그인된 모든 계정 사용
        if checked_accounts:
            # 체크된 계정 중 로그인된 계정만 필터링
            target_accounts = [acc_id for acc_id in checked_accounts if acc_id in logged_in_accounts]
            if not target_accounts:
                QtWidgets.QMessageBox.warning(self, "계정 없음", 
                    "체크된 계정 중 로그인된 계정이 없습니다.\n먼저 로그인을 완료해주세요.")
                return
            self._log(f"✅ 체크된 {len(target_accounts)}개 계정을 순환하며 자동 발행합니다.")
        else:
            # 체크된 계정이 없으면 로그인된 모든 계정 사용
            target_accounts = logged_in_accounts
            if not target_accounts:
                QtWidgets.QMessageBox.warning(self, "계정 없음", 
                    "로그인된 계정이 없습니다.\n먼저 계정을 추가하고 로그인을 완료해주세요.")
                return
            
            # 다중 계정 처리 확인
            if len(target_accounts) > 1:
                reply = QtWidgets.QMessageBox.question(
                    self, "다중 계정 워크플로우", 
                    f"로그인된 {len(target_accounts)}개의 계정이 있습니다.\n"
                    f"모든 계정에서 순서대로 자동 발행하시겠습니까?\n\n"
                    f"계정 목록: {', '.join(target_accounts)}\n\n"
                    f"💡 팁: 특정 계정만 반복 실행하려면 계정 체크박스를 선택하세요.",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.Yes
                )
                
                if reply == QtWidgets.QMessageBox.No:
                    return
            
            self._log(f"📝 워크플로우 시작: {len(target_accounts)}개 계정에서 자동 발행을 시작합니다.")

        # 항상 무한 반복 모드
        use_infinite_loop = True
        self._log(f"🔄 무한 반복 모드: 마지막 계정 후 다시 첫 번째 계정부터 시작합니다.")
        self._log(f"🔗 계정 순서: {' → '.join(target_accounts)}")

        params = self._collect_params()
        self.repeat_panel.history_list.clear()
        self.repeat_panel.log_view.clear()
        
        # 진행률 초기화
        self.repeat_panel.reset_progress()

        # 다중 계정 워크플로우 워커 시작
        self._worker = MultiAccountWorkflowWorker(
            params,
            target_accounts,
            self._accounts,
            self._driver,
            base_dir=self.base_dir,
            automation_steps_per_post=AUTOMATION_STEPS_PER_POST,
            infinite_loop=use_infinite_loop,
        )
        self._worker.finished_signal.connect(self._on_workflow_finished)
        self._worker.error_signal.connect(self._on_workflow_error)
        self._worker.progress_signal.connect(self._on_progress_update)
        self._worker.post_saved_signal.connect(self._on_post_saved)
        self._worker.account_switch_signal.connect(self._on_account_switch)
        self._worker.start()
        self._set_controls_enabled(False)

    def _on_account_switch(self, current_account: str, total_accounts: int, current_index: int) -> None:
        """계정 전환 시 호출되는 메서드"""
        self._log(f"🔄 계정 전환: {current_account} ({current_index}/{total_accounts})")

    def _stop_workflow(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            # 작업 중단 알림 표시
            self.repeat_panel.append_log("🛑 사용자가 작업을 중단했습니다")
            QtWidgets.QMessageBox.information(self, "작업 중단", "작업을 멈췄습니다.")
            self._set_controls_enabled(True)

    def _on_progress_update(self, message: str, completed: bool) -> None:
        suffix = "완료" if completed else "진행 중"
        full_message = f"{message} ({suffix})"
        logger.info(full_message)
        self.repeat_panel.append_log(full_message)

    def _on_post_saved(self, display_text: str, url: str) -> None:
        # URL이 있으면 더블클릭으로 열 수 있도록 저장
        if url and url.startswith("http"):
            self.repeat_panel.add_post_to_history(display_text, url)
        else:
            # URL이 없는 경우 (실패)
            self.repeat_panel.add_post_to_history(display_text, None)

    def _on_workflow_finished(self, driver: object) -> None:
        self._driver = driver
        self._worker = None
        self.repeat_panel.append_log("🎉 모든 작업이 완료되었습니다!")
        self._set_controls_enabled(True)

    def _on_workflow_error(self, message: str) -> None:
        self._worker = None
        
        # 브라우저 닫힘 오류인지 확인하여 사용자 친화적 메시지 표시
        if "no such window" in message.lower() or "target window already closed" in message.lower():
            user_log_message = "브라우저가 닫혀 작업이 중단되었습니다"
            user_popup_message = "브라우저가 닫혀 작업이 중단되었습니다.\n\n브라우저를 닫지 말고 작업을 진행해주세요."
        else:
            user_log_message = message
            user_popup_message = message
        
        # 팝업창 표시 전에 모든 오버레이 일시적으로 숨기기 (AI 모드처럼)
        self._hide_all_overlays_temporarily()
        
        # 로그에 사용자 친화적 메시지 표시
        self.repeat_panel.append_log(f"❌ 오류 발생: {user_log_message}")
        # 진행률 패널에 오류 상태 설정
        self.repeat_panel.set_error_state(user_log_message)
            
        # 팝업창 표시
        QtWidgets.QMessageBox.critical(self, "작업 오류", user_popup_message)
        
        # 팝업창 닫힌 후 정상 상태로 복구
        self._set_controls_enabled(True)

    def _set_controls_enabled(self, enabled: bool) -> None:
        """작업 진행 중일 때 컨트롤 활성화/비활성화를 관리합니다."""
        # 자동화 제어 버튼 설정 (시작/정지 버튼)
        self.ai_control_panel.set_controls_enabled(enabled)
        
        if not enabled:
            # 작업 진행 중: 패널들 비활성화
            self.manual_panel.setEnabled(False)
            # AI 패널은 개별적으로 관리 (오버레이 유지)
            if not self._is_ai_mode:
                self.ai_control_panel.set_ai_mode_enabled(False)  # AI 설정 비활성화
        else:
            # 작업 완료 후: 패널들을 활성화하고 모드에 따라 오버레이 설정
            self.ai_control_panel.setEnabled(True)  # 전체 AI 패널 활성화
            if self._is_ai_mode:
                self.ai_control_panel.set_ai_mode_enabled(True)  # AI 설정 활성화
                self.manual_panel.setEnabled(False)  # 수동 패널에 오버레이 표시
            else:
                self.ai_control_panel.set_ai_mode_enabled(False)  # AI 설정에 오버레이 표시
                self.manual_panel.setEnabled(True)  # 수동 패널 활성화
        
        self.account_panel.enable_controls(enabled)

    def _hide_all_overlays_temporarily(self) -> None:
        """팝업창 표시 중 수동 모드 오버레이만 일시적으로 숨깁니다."""
        # 수동 패널 오버레이만 숨기기 (AI 모드 오버레이는 유지)
        if hasattr(self.manual_panel, 'disabled_overlay'):
            self.manual_panel.disabled_overlay.hide()
        
        # AI 패널 오버레이는 숨기지 않음 (수동 모드에서는 AI 패널이 비활성화되어야 함)

    # --- 테마 ---

    def _toggle_theme(self) -> None:
        theme = "light" if self._current_theme == "dark" else "dark"
        self._apply_theme(theme)

    def _apply_theme(self, theme: str) -> None:
        self._current_theme = theme
        theme_map = DARK_THEME if theme == "dark" else LIGHT_THEME
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(theme_map["palette"]["window"]))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(theme_map["palette"]["text"]))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(theme_map["palette"]["base"]))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor(theme_map["palette"]["text"]))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor(theme_map["palette"]["button"]))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(theme_map["palette"]["button_text"]))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(theme_map["palette"]["highlight"]))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(theme_map["palette"]["highlight_text"]))
        QtWidgets.QApplication.instance().setPalette(palette)
        self._load_stylesheet(theme_map)
        self.header.set_theme_icon(theme_map, theme == "dark")
        
        # 계정 패널 테마 적용
        self.account_panel.set_theme(theme)

    def _load_stylesheet(self, theme_map: Dict[str, object]) -> None:
        # 테마 맵 캐시 (리사이즈 시 재적용)
        self._theme_map_cache = theme_map
        style_path = self.app_root / "app" / "resources" / "styles" / "main.qss"
        if not style_path.exists():
            return

        # Cache original QSS so scaling does not accumulate
        if self._original_qss is None:
            self._original_qss = style_path.read_text(encoding="utf-8")
        qss = self._original_qss
        replacements = {
            "{{BACKGROUND}}": theme_map["background"],
            "{{CARD}}": theme_map["card"],
            "{{INPUT_BG}}": theme_map.get("input", theme_map["card"]),
            "{{BORDER}}": theme_map["border"],
            "{{PRIMARY}}": theme_map["primary_text"],
            "{{SECONDARY}}": theme_map["secondary_text"],
            "{{ACCENT}}": theme_map["accent"],
            "{{ACCENT_HOVER}}": theme_map["accent_hover"],
            "{{ACCENT_LIGHT}}": theme_map["accent_light"],
            "{{ACCENT_DARK}}": theme_map.get("accent_dark", theme_map["accent"]),
            "{{ACCENT_DARKER}}": theme_map.get("accent_darker", theme_map["accent"]),
            "{{DANGER}}": theme_map["danger"],
            "{{BG_ALT}}": theme_map.get("bg_alt", theme_map["card"]),
            "{{THEME_ICON}}": theme_map.get("theme_icon", theme_map["accent"]),
            "{{THEME_ICON_ACTIVE}}": theme_map.get("theme_icon_active", "#0b1120"),
        }

        for token, value in replacements.items():
            qss = qss.replace(token, str(value))

        # Apply dynamic font scaling by multiplying any 'font-size: Npx' values
        try:
            scale = getattr(self, "_ui_scale", 1.0)
            if abs(scale - 1.0) > 0.01:
                import re
                def _scale_font(match: "re.Match[str]") -> str:
                    size_px = int(match.group(1))
                    new_px = max(10, int(round(size_px * scale)))
                    return f"font-size: {new_px}px"
                qss = re.sub(r"font-size:\s*(\d+)px", _scale_font, qss)
        except Exception:
            # If scaling fails for any reason, fall back to unscaled qss
            pass

        QtWidgets.QApplication.instance().setStyleSheet(qss)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        # 리사이즈 이벤트 최적화 - 타이머로 지연 처리
        if not self._resize_timer.isActive():
            self._resize_timer.start(150)  # 150ms 지연
        super().resizeEvent(event)
    
    def _apply_resize_changes(self) -> None:
        """리사이즈 변경사항을 지연 적용 (성능 최적화)"""
        try:
            width = max(1, self.width())
            height = max(1, self.height())
            
            # 화면 크기에 따른 기준 크기 동적 조정 (캐시 활용)
            if not hasattr(self, '_base_size_cache'):
                screen = QtWidgets.QApplication.primaryScreen()
                if screen:
                    screen_width = screen.availableGeometry().width()
                    if screen_width <= 1366:
                        self._base_size_cache = (1200, 800)
                    elif screen_width <= 1920:
                        self._base_size_cache = (1400, 900)
                    else:
                        self._base_size_cache = (1600, 1000)
                else:
                    self._base_size_cache = (1400, 900)
            
            base_width, base_height = self._base_size_cache
            scale_w = width / base_width
            scale_h = height / base_height
            new_scale = max(0.8, min(1.5, min(scale_w, scale_h)))
            
            # 스케일 변화가 충분히 클 때만 업데이트
            if abs(new_scale - self._ui_scale) > 0.08:  # 임계값 증가로 빈도 감소
                self._ui_scale = new_scale
                if self._theme_map_cache:
                    self._load_stylesheet(self._theme_map_cache)
        except Exception:
            pass

    def _non_blocking_wait_ms(self, ms: int) -> None:
        # UI 이벤트를 처리하면서 대기 (성능 최적화)
        try:
            from PyQt5 import QtTest  # type: ignore
            # processEvents 호출을 최소화
            if ms > 100:
                QtWidgets.QApplication.processEvents()
            QtTest.QTest.qWait(max(0, int(ms)))
        except Exception:
            # fallback에서도 processEvents 호출 최소화
            if ms > 100:
                QtWidgets.QApplication.processEvents()

    def _cleanup_browser_sessions(self) -> None:
        """브라우저 세션 정리를 수행합니다 (로그인 세션 보존)."""
        from app.core.automation.naver_publisher import _cleanup_chrome_processes, _cleanup_profile_locks
        
        # 확인 메시지 표시
        reply = QtWidgets.QMessageBox.question(
            self,
            "브라우저 정리",
            "🔧 Chrome 프로세스와 락 파일을 정리합니다.\n\n"
            "✅ 로그인 세션과 쿠키는 보존됩니다!\n"
            "✅ 프로세스 락 파일만 삭제합니다.\n\n"
            "브라우저 오류 해결에 도움이 됩니다.\n"
            "계속하시겠습니까?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        self._log("🔧 브라우저 정리를 시작합니다...")
        
        try:
            # Chrome 프로세스 정리
            _cleanup_chrome_processes()
            self._log("✅ Chrome 프로세스 정리 완료")
            
            # 모든 계정의 프로필 락 파일 정리 (로그인 세션 보존)
            cleaned_profiles = 0
            for account in self._accounts.values():
                _cleanup_profile_locks(account.profile_dir)
                cleaned_profiles += 1
            
            self._log(f"✅ {cleaned_profiles}개 계정 프로필 락 파일 정리 완료")
            self._log("✅ 로그인 세션과 캐시는 보존되었습니다")
            
            QtWidgets.QMessageBox.information(
                self,
                "브라우저 정리 완료", 
                "✅ 브라우저 정리가 완료되었습니다!\n\n"
                "✔ Chrome 프로세스 종료\n"
                f"✔ {cleaned_profiles}개 계정 프로필 락 파일 정리\n"
                "✔ 로그인 세션 및 쿠키 보존\n\n"
                "이제 브라우저 오류 없이 계정을 사용할 수 있습니다."
            )
            
        except Exception as e:
            self._log(f"❌ 브라우저 정리 중 오류: {e}")
            QtWidgets.QMessageBox.warning(
                self,
                "브라우저 정리 오류",
                f"브라우저 정리 중 오류가 발생했습니다:\n{e}\n\n"
                "수동으로 Chrome을 완전히 종료한 후 다시 시도해주세요."
            )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        """프로그램 종료 시 리소스 정리 (메모리 누수 방지)"""
        try:
            # 모든 타이머 정지
            if hasattr(self, '_resize_timer'):
                self._resize_timer.stop()
            if hasattr(self, '_settings_save_timer'):
                # 저장 대기 중인 설정이 있으면 즉시 저장
                if self._settings_save_timer.isActive():
                    self._settings_save_timer.stop()
                    self._do_save_settings()
            if hasattr(self, '_accounts_save_timer'):
                # 저장 대기 중인 계정이 있으면 즉시 저장
                if self._accounts_save_timer.isActive():
                    self._accounts_save_timer.stop()
                    self._do_save_accounts()
            
            # 워커 스레드 정리
            if self._worker and self._worker.isRunning():
                self._worker.request_stop()
                self._worker.wait(3000)  # 최대 3초 대기
            
            # 브라우저 정리
            if self._driver:
                try:
                    self._driver.quit()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"프로그램 종료 시 리소스 정리 중 오류 (무시됨): {e}")
        
        super().closeEvent(event)

    def _show_tips(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Tips",
            "1. AI 모드에서 키 확인 후 자동화를 시작하세요.\n"
            "2. 수동 모드에서는 제목과 본문 파일을 선택하세요.\n"
            "3. 계정을 추가한 뒤 브라우저 열기를 통해 쿠키를 저장하면 좋습니다.\n"
            "4. 브라우저 오류 발생 시 '브라우저 정리' 기능을 사용하세요.",
        )


class MultiAccountWorkflowWorker(QtCore.QThread):
    """여러 계정을 순서대로 처리하는 워크플로우 워커"""
    finished_signal = QtCore.pyqtSignal(object)
    error_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(str, bool)
    percent_signal = QtCore.pyqtSignal(int)
    status_signal = QtCore.pyqtSignal(str)
    post_saved_signal = QtCore.pyqtSignal(str, str)
    account_switch_signal = QtCore.pyqtSignal(str, int, int)  # account_id, total, current_index

    def __init__(
        self,
        params: WorkflowParams,
        account_ids: list[str],
        accounts: dict[str, AccountProfile],
        driver: Optional[object],
        base_dir,
        automation_steps_per_post: int,
        infinite_loop: bool = False,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.params = params
        self.account_ids = account_ids
        self.accounts = accounts
        self.driver = driver
        self.base_dir = base_dir
        self.auto_steps_per_post = automation_steps_per_post
        self.infinite_loop = infinite_loop
        self._stop_requested = False
        self.total_accounts = len(account_ids)

    def request_stop(self) -> None:
        self._stop_requested = True

    def _should_stop(self) -> bool:
        return self._stop_requested

    def run(self) -> None:
        """여러 계정에서 순서대로 글을 발행합니다."""
        import time
        
        try:
            cycle_count = 0  # 순환 횟수
            
            while True:  # 무한 반복 또는 1회 실행
                cycle_count += 1
                
                if self.infinite_loop and cycle_count > 1:
                    self.progress_signal.emit(f"🔄 다음 순환 시작 (순환 {cycle_count}회차)", True)
                
                for index, account_id in enumerate(self.account_ids, 1):
                    if self._should_stop():
                        break
                    
                    # 계정 전환 신호 발생
                    self.account_switch_signal.emit(account_id, self.total_accounts, index)
                    
                    account = self.accounts[account_id]
                    if not account.login_initialized:
                        self.progress_signal.emit(f"❌ '{account_id}' 계정이 로그인되지 않았습니다. 건너뜁니다.", True)
                        continue

                    # 계정별 워크플로우 파라미터 업데이트
                    account_params = WorkflowParams(
                        keyword=self.params.keyword,
                        count=self.params.count,
                        use_ai=self.params.use_ai,
                        api_key=self.params.api_key,
                        model=self.params.model,
                        manual_title=self.params.manual_title,
                        manual_body=self.params.manual_body,
                        manual_tags=self.params.manual_tags,
                        manual_file_path=self.params.manual_file_path,
                        image_file_path=self.params.image_file_path,
                        schedule_minutes=self.params.schedule_minutes,
                        naver_id=account_id,
                        naver_profile_dir=str(account.profile_dir),
                    )

                    self.progress_signal.emit(f"🔐 '{account_id}' 계정으로 브라우저를 시작합니다...", False)
                    
                    # 기존 브라우저가 있으면 정리
                    if self.driver:
                        try:
                            self.driver.quit()
                            time.sleep(1.5)  # 2초 -> 1.5초 단축
                        except Exception:
                            pass
                        finally:
                            self.driver = None

                    # 새 브라우저 생성 (계정별 프로필 사용)
                    try:
                        self.driver = create_chrome_driver(account.profile_dir)
                        self.progress_signal.emit(f"✅ '{account_id}' 계정 브라우저 생성 완료", True)
                    except Exception as exc:
                        self.progress_signal.emit(f"❌ '{account_id}' 브라우저 생성 실패: {exc}", True)
                        continue

                    # 계정별 워크플로우 실행
                    worker = WorkflowWorker(
                        account_params,
                        self.driver,
                        base_dir=self.base_dir,
                        automation_steps_per_post=self.auto_steps_per_post,
                    )
                    
                    # 워크플로우 신호 연결
                    worker.progress_signal.connect(self.progress_signal)
                    worker.post_saved_signal.connect(self.post_saved_signal)
                    worker.status_signal.connect(self.status_signal)
                    
                    # 워크플로우 실행 (동기적으로) - 보호조치 예외 처리 추가
                    try:
                        self.progress_signal.emit(f"📝 '{account_id}' 계정에서 글 발행을 시작합니다...", False)
                        worker.run()  # start() 대신 run() 직접 호출로 동기 실행
                        self.progress_signal.emit(f"✅ '{account_id}' 계정 발행 완료!", True)
                    except AccountProtectionException as e:
                        self.progress_signal.emit(f"⚠️ '{account_id}' 계정 보호조치 감지 - 다음 계정으로 넘어갑니다", True)
                        logger.warning(f"계정 '{account_id}' 보호조치: {e}")
                        continue  # 다음 계정으로 넘어감
                    
                    # 계정 간 대기 시간 최적화 (안정성 유지)
                    if index < self.total_accounts:  # 마지막 계정이 아니면
                        self.progress_signal.emit("⏳ 다음 계정 전환 준비 중...", False)
                        time.sleep(2)  # 3초 -> 2초 단축
                
                # for 루프가 끝난 후 (모든 계정 처리 완료)
                # 무한 반복이 아니면 한 사이클만 실행하고 종료
                if not self.infinite_loop:
                    break
                
                # 무한 반복 모드에서 중단되었으면 종료
                if self._should_stop():
                    break
                
                # 다음 순환 전 대기 최적화
                if self.infinite_loop:
                    self.progress_signal.emit("⏳ 다음 순환 준비 중...", False)
                    time.sleep(3)  # 5초 -> 3초 단축

        except Exception as exc:
            self.error_signal.emit(f"다중 계정 워크플로우 오류: {exc}")
            return

        if self.infinite_loop:
            self.progress_signal.emit("🛑 무한 반복 모드가 중단되었습니다.", True)
        else:
            self.progress_signal.emit("🎉 모든 계정에서 발행이 완료되었습니다!", True)
        self.finished_signal.emit(self.driver)


