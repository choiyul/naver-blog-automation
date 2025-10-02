"""계정 관리 패널."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt5 import QtCore, QtGui, QtWidgets

from ...core.models import AccountProfile


class _TableItemDelegate(QtWidgets.QStyledItemDelegate):
    """테이블 아이템 델리게이트 - 선택된 행에 통합 테두리 표시"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.accent_color = QtGui.QColor("#ffc857")  # 기본 액센트 색상
    
    def set_accent_color(self, color: str):
        """테마에 따라 액센트 색상 설정"""
        self.accent_color = QtGui.QColor(color)
    
    def paint(self, painter, option, index):
        # 기본 그리기
        super().paint(painter, option, index)
        
        # 선택된 행인 경우 행 전체를 감싸는 테두리 그리기
        if option.state & QtWidgets.QStyle.State_Selected:
            painter.save()
            
            # 테이블 위젯 가져오기
            table = self.parent()
            if isinstance(table, QtWidgets.QTableWidget):
                row = index.row()
                
                # 행 전체의 rect 계산
                first_col_rect = table.visualRect(table.model().index(row, 0))
                last_col_rect = table.visualRect(table.model().index(row, table.columnCount() - 1))
                
                # 행 전체를 감싸는 사각형
                full_rect = QtCore.QRect(
                    first_col_rect.left(),
                    first_col_rect.top(),
                    last_col_rect.right() - first_col_rect.left(),
                    first_col_rect.height()
                )
                
                # 테두리 그리기
                pen = QtGui.QPen(self.accent_color, 2)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.NoBrush)
                
                # 둥근 모서리 사각형 (약간 여백 조정)
                adjusted_rect = full_rect.adjusted(2, 2, -2, -2)
                painter.drawRoundedRect(adjusted_rect, 6, 6)
            
            painter.restore()


class AccountPanel(QtWidgets.QGroupBox):
    account_selected = QtCore.pyqtSignal(str)
    request_add_account = QtCore.pyqtSignal(str, str)
    request_remove_account = QtCore.pyqtSignal(str)
    request_remove_accounts = QtCore.pyqtSignal(list)  # 여러 계정 삭제용
    request_open_profile = QtCore.pyqtSignal(str)
    request_open_browser = QtCore.pyqtSignal(str)
    request_batch_login = QtCore.pyqtSignal(list)  # 일괄 로그인용

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("계정 관리", parent)
        self._profile_path_text = "-"
        self._current_theme = "dark"  # 기본 테마
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("accountPanel")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)  # 간격을 12에서 8로 줄임
        layout.setContentsMargins(16, 12, 16, 12)  # 상하 여백 축소

        form_layout = QtWidgets.QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(6)  # 8에서 6으로 줄임
        self.account_id_edit = QtWidgets.QLineEdit()
        self.account_pw_edit = QtWidgets.QLineEdit()
        self.account_pw_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form_layout.addRow("네이버 아이디", self.account_id_edit)
        form_layout.addRow("네이버 비밀번호", self.account_pw_edit)

        layout.addLayout(form_layout)

        # 첫 번째 줄: 계정 추가, 일괄 추가, 선택 삭제
        button_row1 = QtWidgets.QHBoxLayout()
        self.add_account_btn = QtWidgets.QPushButton("추가")
        self.add_account_btn.clicked.connect(self._on_add_clicked)
        self.bulk_add_btn = QtWidgets.QPushButton("일괄추가")
        self.bulk_add_btn.clicked.connect(self._on_bulk_add_clicked)
        self.remove_selected_btn = QtWidgets.QPushButton("삭제")
        self.remove_selected_btn.clicked.connect(self._on_remove_selected_clicked)

        button_row1.setSpacing(6)
        button_row1.addWidget(self.add_account_btn)
        button_row1.addWidget(self.bulk_add_btn)
        button_row1.addWidget(self.remove_selected_btn)

        layout.addLayout(button_row1)

        # 두 번째 줄: 프로필 열기, 브라우저 열기, 일괄 로그인
        button_row2 = QtWidgets.QHBoxLayout()
        self.export_account_btn = QtWidgets.QPushButton("프로필")
        self.export_account_btn.clicked.connect(self._on_open_profile_clicked)
        self.login_button = QtWidgets.QPushButton("로그인")
        self.login_button.clicked.connect(self._on_open_browser_clicked)
        self.batch_login_btn = QtWidgets.QPushButton("일괄로그인")
        self.batch_login_btn.clicked.connect(self._on_batch_login_clicked)
        self.batch_login_btn.setStyleSheet("font-weight: bold;")

        button_row2.setSpacing(6)
        button_row2.addWidget(self.export_account_btn)
        button_row2.addWidget(self.login_button)
        button_row2.addWidget(self.batch_login_btn)

        layout.addLayout(button_row2)

        # 계정 목록 라벨
        accounts_label = QtWidgets.QLabel("계정 목록")
        accounts_label.setStyleSheet("font-weight: bold; font-size: 13px; margin-top: 4px;")
        layout.addWidget(accounts_label)

        # 테이블 위젯 생성
        self.accounts_table = QtWidgets.QTableWidget()
        self.accounts_table.setColumnCount(3)
        self.accounts_table.setMinimumHeight(300)  # 최소 높이 설정으로 더 많은 계정 표시
        
        # 전체 선택 체크박스를 헤더에 추가
        self.select_all_checkbox = QtWidgets.QCheckBox()
        self.select_all_checkbox.stateChanged.connect(self._on_select_all_changed)
        # 초기 스타일 적용은 나중에 _apply_theme_colors에서 함
        
        # 헤더 설정
        self.accounts_table.setHorizontalHeaderLabels(["", "아이디", "상태"])
        
        # 헤더 텍스트 중앙 정렬
        for col in range(self.accounts_table.columnCount()):
            header_item = self.accounts_table.horizontalHeaderItem(col)
            if header_item:
                header_item.setTextAlignment(QtCore.Qt.AlignCenter)
        
        # 체크박스를 헤더에 표시하기 위한 커스텀 헤더 뷰
        class CheckBoxHeader(QtWidgets.QHeaderView):
            def __init__(self, orientation, parent=None):
                super().__init__(orientation, parent)
                self.isOn = False
                self.checkbox = None
                self.checkbox_border_color = QtGui.QColor("#94a3c4")
                self.checkbox_bg_color = QtGui.QColor("#161e30")
                self.accent_color = QtGui.QColor("#ffc857")
                
            def set_colors(self, border_color, bg_color, accent_color):
                """체크박스 색상 설정"""
                self.checkbox_border_color = QtGui.QColor(border_color)
                self.checkbox_bg_color = QtGui.QColor(bg_color)
                self.accent_color = QtGui.QColor(accent_color)
                self.updateSection(0)
                
            def paintSection(self, painter, rect, logicalIndex):
                painter.save()
                super().paintSection(painter, rect, logicalIndex)
                painter.restore()
                
                if logicalIndex == 0:
                    # 체크박스 그리기
                    checkbox_size = 18
                    checkbox_x = rect.x() + rect.width()//2 - checkbox_size//2
                    checkbox_y = rect.y() + rect.height()//2 - checkbox_size//2
                    checkbox_rect = QtCore.QRect(checkbox_x, checkbox_y, checkbox_size, checkbox_size)
                    
                    painter.save()
                    painter.setRenderHint(QtGui.QPainter.Antialiasing)
                    
                    # 배경과 테두리
                    if self.isOn:
                        painter.setBrush(self.accent_color)
                        painter.setPen(QtGui.QPen(self.accent_color, 2))
                    else:
                        painter.setBrush(self.checkbox_bg_color)
                        painter.setPen(QtGui.QPen(self.checkbox_border_color, 2))
                    
                    painter.drawRoundedRect(checkbox_rect, 4, 4)
                    
                    # 체크 표시
                    if self.isOn:
                        painter.setPen(QtGui.QPen(QtGui.QColor("white"), 2))
                        # 체크 마크 그리기
                        check_path = QtGui.QPainterPath()
                        check_path.moveTo(checkbox_x + 4, checkbox_y + 9)
                        check_path.lineTo(checkbox_x + 7, checkbox_y + 12)
                        check_path.lineTo(checkbox_x + 14, checkbox_y + 5)
                        painter.drawPath(check_path)
                    
                    painter.restore()
                    
            def mousePressEvent(self, event):
                if self.logicalIndexAt(event.pos()) == 0:
                    self.isOn = not self.isOn
                    self.updateSection(0)
                    if self.checkbox:
                        self.checkbox.setChecked(self.isOn)
                super().mousePressEvent(event)
        
        self._header = CheckBoxHeader(QtCore.Qt.Horizontal, self.accounts_table)
        self._header.checkbox = self.select_all_checkbox
        self.accounts_table.setHorizontalHeader(self._header)
        
        # 커스텀 헤더 설정 후 컬럼 너비 설정 (3개 컬럼만 사용)
        self._header.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self._header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self._header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self._header.setStretchLastSection(False)
        self.accounts_table.setColumnWidth(0, 60)
        self.accounts_table.setColumnWidth(2, 100)
        
        # 수평 스크롤바 제거
        self.accounts_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        
        # 행 높이 설정
        self.accounts_table.verticalHeader().setDefaultSectionSize(50)
        
        # 테이블 속성 설정
        self.accounts_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.accounts_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.accounts_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.setAlternatingRowColors(False)  # 교대 색상 비활성화
        self.accounts_table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.accounts_table.currentItemChanged.connect(self._on_item_changed)
        self.accounts_table.setShowGrid(False)  # 그리드 라인 숨김
        self.accounts_table.setFocusPolicy(QtCore.Qt.NoFocus)  # 포커스 테두리 제거
        
        # 커스텀 델리게이트 설정 (선택된 행 테두리 표시)
        self._item_delegate = _TableItemDelegate(self.accounts_table)
        self.accounts_table.setItemDelegate(self._item_delegate)
        
        # 초기 테마 적용
        self._apply_theme_colors()
        
        layout.addWidget(self.accounts_table)

        profile_layout = QtWidgets.QHBoxLayout()
        profile_layout.addWidget(QtWidgets.QLabel("프로필 경로:"))
        self.profile_label = QtWidgets.QLabel("-")
        self.profile_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.profile_label.setWordWrap(True)
        self.profile_label.installEventFilter(self)
        profile_layout.addWidget(self.profile_label, 1)
        layout.addLayout(profile_layout)

    def _apply_theme_colors(self) -> None:
        """현재 테마에 맞는 색상 적용"""
        if self._current_theme == "dark":
            text_color = "#e5edff"
            header_color = "#94a3c4"
            border_color = "#25314d"
            divider_color = "rgba(37, 49, 77, 0.5)"
            accent_color = "#ffc857"
            checkbox_border = "#94a3c4"
            checkbox_bg = "#161e30"
        else:  # light
            text_color = "#0f172a"
            header_color = "#475569"
            border_color = "#e2e8f0"
            divider_color = "rgba(226, 232, 240, 0.8)"
            accent_color = "#03c75a"
            checkbox_border = "#94a3b8"
            checkbox_bg = "#ffffff"
        
        # 델리게이트 색상 업데이트
        self._item_delegate.set_accent_color(accent_color)
        
        # 헤더 체크박스 색상 업데이트
        self._header.set_colors(checkbox_border, checkbox_bg, accent_color)
        
        # 전체 선택 체크박스 스타일 적용 (위젯)
        self._apply_checkbox_style(self.select_all_checkbox)
        
        # 테이블 스타일 적용
        self.accounts_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: transparent;
                selection-background-color: transparent;
                border: none;
                color: {text_color};
            }}
            QTableWidget::item {{
                border-bottom: 1px solid {divider_color};
                padding: 12px 8px;
                color: {text_color};
            }}
            QTableWidget::item:hover {{
                background-color: rgba(148, 163, 184, 0.08);
                color: {text_color};
            }}
            QTableWidget::item:selected {{
                background-color: transparent;
                color: {text_color};
            }}
            QTableWidget::item:selected:hover {{
                background-color: rgba(148, 163, 184, 0.08);
                color: {text_color};
            }}
            QTableWidget::item:focus {{
                background-color: transparent;
                outline: none;
                border-bottom: 1px solid {divider_color};
                color: {text_color};
            }}
            QHeaderView {{
                background-color: transparent;
            }}
            QHeaderView::section {{
                background-color: transparent;
                border: none;
                border-bottom: 1px solid {border_color};
                padding: 10px 8px;
                color: {header_color};
                font-weight: 600;
                font-size: 13px;
                text-align: center;
            }}
            QCheckBox {{
                spacing: 5px;
                color: {text_color};
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {checkbox_border};
                border-radius: 4px;
                background-color: {checkbox_bg};
            }}
            QCheckBox::indicator:checked {{
                background-color: {accent_color};
                border-color: {accent_color};
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTAiIHZpZXdCb3g9IjAgMCAxMiAxMCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEgNUw0LjUgOC41TDExIDEiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }}
            QCheckBox::indicator:hover {{
                border-color: {accent_color};
            }}
        """)
    
    def _apply_checkbox_style(self, checkbox: QtWidgets.QCheckBox) -> None:
        """개별 체크박스에 스타일 적용"""
        if self._current_theme == "dark":
            checkbox_border = "#94a3c4"
            checkbox_bg = "#161e30"
            accent_color = "#ffc857"
        else:  # light
            checkbox_border = "#94a3b8"
            checkbox_bg = "#ffffff"
            accent_color = "#03c75a"
        
        checkbox.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {checkbox_border};
                border-radius: 4px;
                background-color: {checkbox_bg};
            }}
            QCheckBox::indicator:checked {{
                background-color: {accent_color};
                border-color: {accent_color};
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTAiIHZpZXdCb3g9IjAgMCAxMiAxMCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEgNUw0LjUgOC41TDExIDEiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }}
            QCheckBox::indicator:hover {{
                border-color: {accent_color};
            }}
        """)
    
    def set_theme(self, theme: str) -> None:
        """테마 변경"""
        self._current_theme = theme
        self._apply_theme_colors()
        
        # 헤더 체크박스 스타일 업데이트
        self._apply_checkbox_style(self.select_all_checkbox)
        
        # 모든 행의 체크박스 스타일 업데이트
        for row in range(self.accounts_table.rowCount()):
            checkbox_widget = self.accounts_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QtWidgets.QCheckBox)
                if checkbox:
                    self._apply_checkbox_style(checkbox)

    def _on_add_clicked(self) -> None:
        account_id = self.account_id_edit.text().strip()
        account_pw = self.account_pw_edit.text().strip()
        if not account_id:
            QtWidgets.QMessageBox.warning(self, "입력 오류", "네이버 아이디를 입력해주세요.")
            return
        if not account_pw:
            QtWidgets.QMessageBox.warning(self, "입력 오류", "네이버 비밀번호를 입력해주세요.")
            return

        self.accounts_table.clearSelection()
        self.account_id_edit.clear()
        self.account_pw_edit.clear()
        self.request_add_account.emit(account_id, account_pw)
    
    def _on_bulk_add_clicked(self) -> None:
        """txt 파일에서 계정 일괄 추가"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "계정 목록 파일 선택",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            added_count = 0
            skipped_count = 0
            error_lines = []
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line:  # 빈 줄 건너뛰기
                    continue
                
                # 탭으로 구분 (아이디, 비밀번호, 이름, 전화번호)
                parts = line.split('\t')
                
                if len(parts) < 2:
                    error_lines.append(f"라인 {line_num}: 형식 오류 (탭으로 구분된 데이터가 부족)")
                    skipped_count += 1
                    continue
                
                account_id = parts[0].strip()
                account_pw = parts[1].strip()
                
                # 아이디와 비밀번호가 비어있는지 확인
                if not account_id or not account_pw:
                    error_lines.append(f"라인 {line_num}: 아이디 또는 비밀번호가 비어있음")
                    skipped_count += 1
                    continue
                
                # 전화번호 형식(하이픈 포함)이 아이디로 들어가는 것 방지
                if '-' in account_id and len(account_id.replace('-', '').replace(' ', '')) >= 10:
                    error_lines.append(f"라인 {line_num}: 아이디가 전화번호 형식으로 보임 ({account_id})")
                    skipped_count += 1
                    continue
                
                # 계정 추가 요청
                self.request_add_account.emit(account_id, account_pw)
                added_count += 1
            
            # 결과 메시지
            result_msg = f"총 {added_count}개의 계정이 추가되었습니다."
            if skipped_count > 0:
                result_msg += f"\n{skipped_count}개의 라인을 건너뛰었습니다."
            if error_lines:
                result_msg += "\n\n오류 내역:\n" + "\n".join(error_lines[:10])
                if len(error_lines) > 10:
                    result_msg += f"\n... 외 {len(error_lines) - 10}개"
            
            QtWidgets.QMessageBox.information(self, "일괄 추가 완료", result_msg)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "파일 읽기 오류", f"파일을 읽는 중 오류가 발생했습니다:\n{str(e)}")

    def _on_select_all_changed(self, state: int) -> None:
        """전체 선택 체크박스 상태 변경"""
        is_checked = state == QtCore.Qt.Checked
        for row in range(self.accounts_table.rowCount()):
            checkbox_widget = self.accounts_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QtWidgets.QCheckBox)
                if checkbox:
                    checkbox.setChecked(is_checked)
    
    def _on_remove_selected_clicked(self) -> None:
        selected_accounts = []
        for row in range(self.accounts_table.rowCount()):
            checkbox_widget = self.accounts_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QtWidgets.QCheckBox)
                if checkbox and checkbox.isChecked():
                    id_item = self.accounts_table.item(row, 1)
                    if id_item:
                        account = id_item.data(QtCore.Qt.UserRole)
                        if account:
                            selected_accounts.append(account.account_id)
        
        if not selected_accounts:
            QtWidgets.QMessageBox.warning(self, "선택 오류", "삭제할 계정을 선택해주세요.")
            return
        
        # 계정 목록 표시 (최대 5개까지만 미리보기)
        max_preview = 5
        if len(selected_accounts) <= max_preview:
            account_list = "\n".join(f"- {account_id}" for account_id in selected_accounts)
            message = f"{len(selected_accounts)}개의 계정을 삭제하시겠습니까?\n프로필 폴더는 삭제되지 않습니다.\n\n{account_list}"
        else:
            preview_list = "\n".join(f"- {account_id}" for account_id in selected_accounts[:max_preview])
            remaining_count = len(selected_accounts) - max_preview
            message = f"총 {len(selected_accounts)}개의 계정을 삭제하시겠습니까?\n프로필 폴더는 삭제되지 않습니다.\n\n{preview_list}\n... 외 {remaining_count}개"
        
        reply = QtWidgets.QMessageBox.question(
            self,
            "계정 삭제 확인",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            # 여러 계정을 한 번에 삭제 (새로운 신호 사용)
            self.request_remove_accounts.emit(selected_accounts)

    def _on_open_profile_clicked(self) -> None:
        account = self._current_account()
        if account:
            self.request_open_profile.emit(account.account_id)

    def _on_open_browser_clicked(self) -> None:
        account = self._current_account()
        if account:
            self.request_open_browser.emit(account.account_id)
    
    def _on_batch_login_clicked(self) -> None:
        """선택된 계정들에 대해 일괄 로그인을 요청합니다."""
        checked_accounts = self.get_checked_accounts()
        
        if not checked_accounts:
            QtWidgets.QMessageBox.warning(
                self, 
                "선택 오류", 
                "일괄 로그인할 계정을 선택해주세요.\n체크박스를 선택하여 계정을 지정할 수 있습니다."
            )
            return
        
        # 확인 대화상자
        max_preview = 10
        if len(checked_accounts) <= max_preview:
            account_list = "\n".join(f"- {account_id}" for account_id in checked_accounts)
            message = (
                f"{len(checked_accounts)}개의 계정에 대해 순차적으로 로그인을 진행합니다.\n\n"
                f"{account_list}\n\n"
                f"각 계정마다 브라우저가 열리고, 로그인을 완료하면 자동으로 다음 계정으로 넘어갑니다.\n"
                f"계속 진행하시겠습니까?"
            )
        else:
            preview_list = "\n".join(f"- {account_id}" for account_id in checked_accounts[:max_preview])
            remaining_count = len(checked_accounts) - max_preview
            message = (
                f"총 {len(checked_accounts)}개의 계정에 대해 순차적으로 로그인을 진행합니다.\n\n"
                f"{preview_list}\n... 외 {remaining_count}개\n\n"
                f"각 계정마다 브라우저가 열리고, 로그인을 완료하면 자동으로 다음 계정으로 넘어갑니다.\n"
                f"계속 진행하시겠습니까?"
            )
        
        reply = QtWidgets.QMessageBox.question(
            self,
            "일괄 로그인 확인",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.request_batch_login.emit(checked_accounts)
    
    def _confirm_reset(self) -> bool:
        reply = QtWidgets.QMessageBox.question(
            self,
            "프로필 초기화",
            "새 계정 프로필 디렉터리를 초기화하시겠습니까?\n이미 존재하는 파일은 삭제됩니다.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return reply == QtWidgets.QMessageBox.Yes

    # --- 외부 API ---

    def set_accounts(self, accounts: Iterable[AccountProfile], selected_id: str | None = None) -> None:
        # UI 업데이트 배치 처리 (성능 최적화)
        self.accounts_table.setUpdatesEnabled(False)
        try:
            self.accounts_table.setRowCount(0)
            self.select_all_checkbox.setCheckState(QtCore.Qt.Unchecked)
            
            for account in accounts:
                row = self.accounts_table.rowCount()
                self.accounts_table.insertRow(row)
                
                # 체크박스 - 위젯으로 중앙 정렬
                checkbox_widget = QtWidgets.QWidget()
                checkbox_layout = QtWidgets.QHBoxLayout(checkbox_widget)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setAlignment(QtCore.Qt.AlignCenter)
                
                checkbox = QtWidgets.QCheckBox()
                checkbox.setProperty('row', row)
                checkbox.setProperty('account_id', account.account_id)
                
                # 체크박스 스타일 적용
                self._apply_checkbox_style(checkbox)
                
                checkbox_layout.addWidget(checkbox)
                
                self.accounts_table.setCellWidget(row, 0, checkbox_widget)
                
                # 아이디
                id_item = QtWidgets.QTableWidgetItem(account.account_id)
                id_item.setData(QtCore.Qt.UserRole, account)
                id_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                id_item.setTextAlignment(QtCore.Qt.AlignCenter)  # 중앙 정렬
                self.accounts_table.setItem(row, 1, id_item)
                
                # 상태 - 로그인 실패, 성공, 미시도 표시
                if account.login_failed:
                    status_text = "❌ 사용불가"
                    if self._current_theme == "dark":
                        status_color = QtGui.QColor(239, 68, 68, 200)  # 빨간색
                    else:
                        status_color = QtGui.QColor(220, 38, 38)
                elif account.login_initialized:
                    status_text = "✅ 로그인됨"
                    if self._current_theme == "dark":
                        status_color = QtGui.QColor(34, 197, 94, 200)  # 초록색
                    else:
                        status_color = QtGui.QColor(22, 163, 74)
                else:
                    status_text = "로그인 필요"
                    if self._current_theme == "dark":
                        status_color = QtGui.QColor(148, 163, 196, 200)  # 회색
                    else:
                        status_color = QtGui.QColor(100, 116, 139)
                
                status_item = QtWidgets.QTableWidgetItem(status_text)
                status_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                status_item.setForeground(status_color)
                status_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.accounts_table.setItem(row, 2, status_item)
            
            if self.accounts_table.rowCount() > 0:
                self.select_account(selected_id)
            else:
                self.profile_label.setText("-")
        finally:
            # UI 업데이트 재개 (배치 처리 완료)
            self.accounts_table.setUpdatesEnabled(True)

    def select_account(self, account_id: str | None) -> None:
        if account_id is None:
            if self.accounts_table.rowCount() > 0:
                self.accounts_table.selectRow(0)
            return
        for row in range(self.accounts_table.rowCount()):
            id_item = self.accounts_table.item(row, 1)
            if id_item:
                account = id_item.data(QtCore.Qt.UserRole)
                if account and account.account_id == account_id:
                    self.accounts_table.selectRow(row)
                    return
        if self.accounts_table.rowCount() > 0:
            self.accounts_table.selectRow(0)

    def _on_item_changed(self, current: QtWidgets.QTableWidgetItem | None, previous: QtWidgets.QTableWidgetItem | None) -> None:
        if current:
            row = current.row()
            id_item = self.accounts_table.item(row, 1)
            if id_item:
                account: AccountProfile = id_item.data(QtCore.Qt.UserRole)
                if account:
                    self.profile_label.setText(str(account.profile_dir))
                    self.account_selected.emit(account.account_id)

    def update_profile_path(self, path: Path | None) -> None:
        self._profile_path_text = str(path) if path else "-"
        self._refresh_profile_label()

    def enable_controls(self, enabled: bool) -> None:
        controls = [
            self.account_id_edit,
            self.account_pw_edit,
            self.add_account_btn,
            self.bulk_add_btn,
            self.remove_selected_btn,
            self.export_account_btn,
            self.login_button,
            self.batch_login_btn,
            self.accounts_table,
            self.select_all_checkbox,
        ]
        for widget in controls:
            widget.setEnabled(enabled)

    def _current_account(self) -> AccountProfile | None:
        current_row = self.accounts_table.currentRow()
        if current_row < 0:
            return None
        id_item = self.accounts_table.item(current_row, 1)
        if not id_item:
            return None
        return id_item.data(QtCore.Qt.UserRole)
    
    def get_checked_accounts(self) -> list[str]:
        """체크된 계정 ID 목록을 반환합니다."""
        checked_accounts = []
        for row in range(self.accounts_table.rowCount()):
            checkbox_widget = self.accounts_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QtWidgets.QCheckBox)
                if checkbox and checkbox.isChecked():
                    id_item = self.accounts_table.item(row, 1)
                    if id_item:
                        account = id_item.data(QtCore.Qt.UserRole)
                        if account:
                            checked_accounts.append(account.account_id)
        return checked_accounts

    def _refresh_profile_label(self) -> None:
        available_width = self.profile_label.width()
        if available_width <= 0:
            self.profile_label.setText(self._profile_path_text)
            return
        metrics = self.profile_label.fontMetrics()
        elided = metrics.elidedText(self._profile_path_text, QtCore.Qt.ElideMiddle, available_width)
        self.profile_label.setText(elided)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if obj is self.profile_label and event.type() == QtCore.QEvent.Resize:
            self._refresh_profile_label()
        return super().eventFilter(obj, event)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self.minimumWidth() == 0 and self.width() > 0:
            self.setMinimumWidth(self.width())


