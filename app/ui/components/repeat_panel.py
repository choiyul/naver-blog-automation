"""3개 섹션으로 구분된 로그 영역."""

import re
from datetime import datetime
from typing import Optional

from PyQt5 import QtCore, QtWidgets, QtGui


class RepeatPanel(QtWidgets.QWidget):
    # 정규식을 클래스 수준에서 미리 컴파일 (성능 최적화)
    _LOG_LEVEL_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - (INFO|DEBUG|ERROR|WARNING) - ')
    
    # 스크롤 업데이트 최소 간격 (밀리초)
    _SCROLL_UPDATE_INTERVAL_MS = 100

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        
        # 성능 최적화를 위한 스크롤 업데이트 제어
        self._last_scroll_update = 0
        self._scroll_timer = QtCore.QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._update_scroll_delayed)
        
        # 진행률 업데이트 캐시
        self._last_progress_value = 0
        self._last_step_text = ""
        
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # 1. 자동화 진행 상태 패널
        status_panel = QtWidgets.QGroupBox("자동화 진행 상태")
        status_layout = QtWidgets.QVBoxLayout(status_panel)
        status_layout.setSpacing(8)
        status_layout.setContentsMargins(12, 8, 12, 12)
        
        # 현재 단계 표시
        self.current_step_label = QtWidgets.QLabel("상태: 대기 중")
        self.current_step_label.setObjectName("statusLabel")
        status_layout.addWidget(self.current_step_label)
        
        # 진행률 바
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% (%v/%m)")
        status_layout.addWidget(self.progress_bar)
        
        # 진행 상세 정보
        self.status_view = QtWidgets.QPlainTextEdit()
        self.status_view.setReadOnly(True)
        self.status_view.setMaximumHeight(80)
        self.status_view.setPlainText("자동화를 시작하려면 시작 버튼을 클릭하세요.")
        self.status_view.setWordWrapMode(QtGui.QTextOption.WordWrap)
        status_layout.addWidget(self.status_view)
        
        layout.addWidget(status_panel, 1)

        # 2. 자동화 로그 패널
        log_panel = QtWidgets.QGroupBox("자동화 로그")
        log_layout = QtWidgets.QVBoxLayout(log_panel)
        log_layout.setSpacing(8)
        log_layout.setContentsMargins(12, 8, 12, 12)
        
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = self.log_view.font()
        font.setFamily("JetBrains Mono")
        font.setPointSize(10)
        self.log_view.setFont(font)
        log_layout.addWidget(self.log_view)
        
        layout.addWidget(log_panel, 2)

        # 3. 생성된 글 패널
        posts_panel = QtWidgets.QGroupBox("생성된 글")
        posts_layout = QtWidgets.QVBoxLayout(posts_panel)
        posts_layout.setSpacing(8)
        posts_layout.setContentsMargins(12, 8, 12, 12)
        
        self.history_list = QtWidgets.QListWidget()
        self.history_list.itemDoubleClicked.connect(self._on_post_double_clicked)
        posts_layout.addWidget(self.history_list)
        
        layout.addWidget(posts_panel, 1)

    def append_log(self, message: str) -> None:
        # 로그 메시지 형식 정리 (INFO 레벨 제거, 시간과 내용만 표시)
        formatted_message = self._format_log_message(message)
        self.log_view.appendPlainText(formatted_message)
        
        # 스크롤 업데이트 최적화 - 일정 간격으로만 실행
        self._schedule_scroll_update()
        
        # 로그 메시지에 따라 진행률 업데이트
        self._update_progress_from_log(message)

    def _format_log_message(self, message: str) -> str:
        """로그 메시지를 사용자 친화적 형식으로 변환합니다."""
        # 미리 컴파일된 정규식 사용 (성능 최적화)
        message = self._LOG_LEVEL_PATTERN.sub('', message)
        
        # 현재 시간 추가 (형식 단순화로 성능 최적화)
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # 아이콘 선택 최적화 - 조건 순서 조정
        if "완료" in message or "성공" in message:
            icon = "✅"
        elif "오류" in message or "실패" in message or "❌" in message:
            icon = "❌"
        elif "진행" in message:
            icon = "🔄"
        elif "시작" in message:
            icon = "🚀"
        else:
            icon = "📝"
            
        return f"[{current_time}] {icon} {message}"

    def update_status(self, status: str) -> None:
        """자동화 진행 상태를 업데이트합니다."""
        self.status_view.setPlainText(f"상태: {status}")
        # 상태 뷰는 짧은 텍스트이므로 스크롤 업데이트 최적화 생략

    def _update_progress_from_log(self, message: str) -> None:
        """로그 메시지를 분석하여 진행률을 업데이트합니다."""
        # 수동 모드 진행 단계 정의 (실제 로그에 맞춰 업데이트)
        manual_steps = {
            # 초기 준비 단계
            "브라우저 준비 (완료)": (5, "브라우저 초기화"),
            "네이버 홈 접속 (완료)": (8, "네이버 접속"),
            "로그인 상태 확인 (완료)": (10, "로그인 확인"),
            "블로그 메뉴 클릭 (완료)": (12, "블로그 이동"),
            "글쓰기 버튼 클릭 (완료)": (15, "글쓰기 페이지"),
            "글쓰기 탭 전환 (완료)": (18, "페이지 전환"),
            
            # 편집기 준비
            "편집기 iframe 전환 완료 (완료)": (22, "편집기 접속"),
            "편집기 로딩 완료 (완료)": (25, "편집기 준비"),
            "글쓰기 페이지 열기 (완료)": (30, "편집기 로딩"),
            
            # 콘텐츠 작성
            "제목 입력 완료 (완료)": (40, "제목 작성"),
            "이미지 클립보드 복사 완료 (완료)": (50, "이미지 준비"),
            "본문 입력 완료 (완료)": (65, "본문 작성"),
            "글 내용 작성 (완료)": (70, "내용 완성"),
            
            # 발행 준비
            "발행 준비 (완료)": (72, "발행 준비"),
            "발행 버튼 찾기 완료 (완료)": (75, "발행 버튼"),
            "발행 버튼 클릭 완료 (완료)": (78, "발행 시작"),
            
            # 발행 설정
            "태그 입력 완료 (완료)": (85, "태그 설정"),
            "예약 시간 설정 완료 (완료)": (92, "예약 설정"),
            "발행 완료 (완료)": (95, "발행 처리"),
            "예약 발행 완료 (완료)": (100, "발행 완료")
        }
        
        # AI 모드 진행 단계 (향후 구현용)
        ai_steps = {
            "API 연결 확인": (10, "API 연결 확인"),
            "콘텐츠 생성 시작": (30, "콘텐츠 생성 중"),
            "콘텐츠 생성 완료": (60, "콘텐츠 생성 완료"),
            "포스팅 시작": (70, "포스팅 준비"),
            "포스팅 완료": (100, "포스팅 완료")
        }
        
        # 현재는 수동 모드만 구현 - 진행률 업데이트 최적화
        for keyword, (progress, step_name) in manual_steps.items():
            if keyword in message:
                # 같은 진행률로 중복 업데이트 방지
                if progress != self._last_progress_value or step_name != self._last_step_text:
                    self.progress_bar.setValue(progress)
                    self.current_step_label.setText(f"현재 단계: {step_name}")
                    
                    # 진행률에 따른 추가 정보 표시
                    if progress == 100:
                        self.status_view.setPlainText("✅ 자동화가 성공적으로 완료되었습니다!")
                    else:
                        self.status_view.setPlainText(f"진행 중... {step_name} ({progress}%)")
                    
                    # 캐시 업데이트
                    self._last_progress_value = progress
                    self._last_step_text = step_name
                break

    def reset_progress(self) -> None:
        """진행률을 초기 상태로 리셋합니다."""
        self.progress_bar.setValue(0)
        self.current_step_label.setText("상태: 대기 중")
        self.status_view.setPlainText("자동화를 시작하려면 시작 버튼을 클릭하세요.")
        
        # 캐시 초기화
        self._last_progress_value = 0
        self._last_step_text = ""

    def set_error_state(self, error_message: str) -> None:
        """오류 상태로 설정합니다."""
        self.current_step_label.setText("상태: 오류 발생")
        self.status_view.setPlainText(f"❌ 오류: {error_message}")

    def add_post_to_history(self, title: str, url: str = None) -> None:
        """생성된 글 목록에 포스트를 추가합니다."""
        # URL 정보와 함께 저장 (향후 더블클릭으로 열기 위해)
        if url:
            item_text = f"{title}"
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.UserRole, url)  # URL을 UserRole로 저장
        else:
            item = QtWidgets.QListWidgetItem(title)
        
        self.history_list.addItem(item)

    def _schedule_scroll_update(self) -> None:
        """스크롤 업데이트를 예약합니다. (성능 최적화)"""
        if not self._scroll_timer.isActive():
            self._scroll_timer.start(self._SCROLL_UPDATE_INTERVAL_MS)
    
    def _update_scroll_delayed(self) -> None:
        """지연된 스크롤 업데이트를 실행합니다."""
        scrollbar = self.log_view.verticalScrollBar()
        if scrollbar.value() < scrollbar.maximum():
            scrollbar.setValue(scrollbar.maximum())

    def _on_post_double_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        """게시물 더블클릭 시 브라우저에서 열기"""
        import webbrowser
        
        url = item.data(QtCore.Qt.UserRole)
        if url:
            try:
                # 백그라운드에서 브라우저 열기 (비블로킹)
                QtCore.QTimer.singleShot(0, lambda: webbrowser.open(url))
                self.append_log(f"🌐 게시물 열기: {item.text()}")
            except Exception as e:
                self.append_log(f"❌ 게시물 열기 실패: {str(e)}")
        else:
            # URL이 없는 경우 알림
            self.append_log(f"⚠️ 게시물 URL이 없습니다: {item.text()}")




