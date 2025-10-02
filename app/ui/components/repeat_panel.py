"""3개 섹션으로 구분된 로그 영역."""

from datetime import datetime
from typing import Optional

from PyQt5 import QtCore, QtWidgets, QtGui


class RepeatPanel(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
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
        # 로그 메시지 형식 정리
        formatted_message = self._format_log_message(message)
        self.log_view.appendPlainText(formatted_message)
        
        # 자동 스크롤
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        
        # 로그 메시지에 따라 진행률 업데이트
        self._update_progress_from_log(message)

    def _format_log_message(self, message: str) -> str:
        """로그 메시지를 사용자 친화적 형식으로 변환합니다."""
        # 로그 레벨 제거 (정규식 대신 간단한 문자열 처리)
        if ' - INFO - ' in message:
            message = message.split(' - INFO - ', 1)[-1]
        elif ' - DEBUG - ' in message:
            message = message.split(' - DEBUG - ', 1)[-1]
        elif ' - ERROR - ' in message:
            message = message.split(' - ERROR - ', 1)[-1]
        elif ' - WARNING - ' in message:
            message = message.split(' - WARNING - ', 1)[-1]
        
        # 현재 시간 추가
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # 아이콘 선택
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
        # 간단한 진행률 업데이트
        if "브라우저 준비" in message:
            self.progress_bar.setValue(10)
        elif "글쓰기 페이지" in message:
            self.progress_bar.setValue(30)
        elif "제목 입력" in message:
            self.progress_bar.setValue(50)
        elif "본문 입력" in message:
            self.progress_bar.setValue(70)
        elif "발행" in message:
            self.progress_bar.setValue(90)
        elif "완료" in message:
            self.progress_bar.setValue(100)

    def reset_progress(self) -> None:
        """진행률을 초기 상태로 리셋합니다."""
        self.progress_bar.setValue(0)
        self.current_step_label.setText("상태: 대기 중")
        self.status_view.setPlainText("자동화를 시작하려면 시작 버튼을 클릭하세요.")

    def set_error_state(self, error_message: str) -> None:
        """오류 상태로 설정합니다."""
        self.current_step_label.setText("상태: 오류 발생")
        self.status_view.setPlainText(f"❌ 오류: {error_message}")

    def add_post_to_history(self, title: str, url: str = None) -> None:
        """생성된 글 목록에 포스트를 추가합니다."""
        # URL 정보와 함께 저장 (향후 더블클릭으로 열기 위해)
        if url:
            item_text = f"{title} 🔗"
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.UserRole, url)  # URL을 UserRole로 저장
            item.setToolTip(f"더블클릭하여 열기\nURL: {url}")
        else:
            item = QtWidgets.QListWidgetItem(title)
            item.setToolTip("URL을 가져오지 못했습니다")
        
        self.history_list.addItem(item)


    def _on_post_double_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        """게시물 더블클릭 시 브라우저에서 열기"""
        import webbrowser
        
        url = item.data(QtCore.Qt.UserRole)
        if url:
            try:
                # 백그라운드에서 브라우저 열기 (비블로킹)
                QtCore.QTimer.singleShot(0, lambda: webbrowser.open(url))
                # 제목에서 🔗 아이콘 제거하여 로그에 표시
                clean_title = item.text().replace(" 🔗", "")
                self.append_log(f"🌐 게시물 열기: {clean_title}")
                self.append_log(f"🔗 URL: {url}")
            except Exception as e:
                self.append_log(f"❌ 게시물 열기 실패: {str(e)}")
        else:
            # URL이 없는 경우 알림
            clean_title = item.text().replace(" 🔗", "")
            self.append_log(f"⚠️ 게시물 URL이 없습니다: {clean_title}")




