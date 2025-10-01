"""계정 관리 패널."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt5 import QtCore, QtGui, QtWidgets

from ...core.models import AccountProfile


class _AccountItemDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        # 체크박스 영역
        checkbox_rect = QtCore.QRect(opt.rect.left() + 16, opt.rect.top() + 10, 20, 20)
        checkbox_opt = QtWidgets.QStyleOptionButton()
        checkbox_opt.rect = checkbox_rect
        checkbox_opt.state = QtWidgets.QStyle.State_Enabled
        if index.data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked:
            checkbox_opt.state |= QtWidgets.QStyle.State_On
        else:
            checkbox_opt.state |= QtWidgets.QStyle.State_Off
        style.drawControl(QtWidgets.QStyle.CE_CheckBox, checkbox_opt, painter, opt.widget)

        # 텍스트 영역 (체크박스 오른쪽부터 시작)
        rect = opt.rect.adjusted(48, 0, -16, 0)
        account_id = index.data(QtCore.Qt.DisplayRole) or ""
        is_logged_in = bool(index.data(QtCore.Qt.UserRole + 1))

        painter.save()
        # 테마에 맞는 색상 사용
        palette = opt.palette
        text_color = palette.color(QtGui.QPalette.Text)
        painter.setPen(text_color)
        painter.drawText(rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, account_id)

        # 상태 색상도 테마에 맞게 조정
        if is_logged_in:
            status_color = QtGui.QColor("#22c55e")  # 성공 색상
        else:
            status_color = QtGui.QColor("#ef4444")  # 실패 색상
        painter.setPen(status_color)
        status_rect = QtCore.QRect(rect)
        status_rect.setLeft(status_rect.right() - 20)
        painter.drawText(status_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, "O" if is_logged_in else "X")
        painter.restore()

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtCore.QSize:
        return QtCore.QSize(option.rect.width(), 40)
    
    def editorEvent(self, event: QtCore.QEvent, model: QtCore.QAbstractItemModel, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> bool:
        if event.type() == QtCore.QEvent.MouseButtonRelease:
            checkbox_rect = QtCore.QRect(option.rect.left() + 16, option.rect.top() + 10, 20, 20)
            if checkbox_rect.contains(event.pos()):
                current_state = index.data(QtCore.Qt.CheckStateRole)
                new_state = QtCore.Qt.Unchecked if current_state == QtCore.Qt.Checked else QtCore.Qt.Checked
                model.setData(index, new_state, QtCore.Qt.CheckStateRole)
                return True
        return super().editorEvent(event, model, option, index)


class AccountPanel(QtWidgets.QGroupBox):
    account_selected = QtCore.pyqtSignal(str)
    request_add_account = QtCore.pyqtSignal(str, str)
    request_remove_account = QtCore.pyqtSignal(str)
    request_open_profile = QtCore.pyqtSignal(str)
    request_open_browser = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("계정 관리", parent)
        self._profile_path_text = "-"
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("accountPanel")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form_layout = QtWidgets.QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(8)
        self.account_id_edit = QtWidgets.QLineEdit()
        self.account_pw_edit = QtWidgets.QLineEdit()
        self.account_pw_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form_layout.addRow("네이버 아이디", self.account_id_edit)
        form_layout.addRow("네이버 비밀번호", self.account_pw_edit)

        layout.addLayout(form_layout)

        button_row = QtWidgets.QHBoxLayout()
        self.add_account_btn = QtWidgets.QPushButton("계정 추가")
        self.add_account_btn.clicked.connect(self._on_add_clicked)
        self.remove_account_btn = QtWidgets.QPushButton("계정 삭제")
        self.remove_account_btn.clicked.connect(self._on_remove_clicked)
        self.remove_selected_btn = QtWidgets.QPushButton("선택 삭제")
        self.remove_selected_btn.clicked.connect(self._on_remove_selected_clicked)
        self.export_account_btn = QtWidgets.QPushButton("프로필 폴더 열기")
        self.export_account_btn.clicked.connect(self._on_open_profile_clicked)
        self.login_button = QtWidgets.QPushButton("브라우저 열기")
        self.login_button.clicked.connect(self._on_open_browser_clicked)

        button_row.setSpacing(12)
        button_row.addWidget(self.add_account_btn)
        button_row.addWidget(self.remove_account_btn)
        button_row.addWidget(self.remove_selected_btn)
        button_row.addWidget(self.export_account_btn)
        button_row.addWidget(self.login_button)

        layout.addLayout(button_row)

        self.accounts_list = QtWidgets.QListWidget()
        self.accounts_list.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.accounts_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.accounts_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.accounts_list.setUniformItemSizes(True)
        self.accounts_list.setSpacing(2)
        self.accounts_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.accounts_list.setItemDelegate(_AccountItemDelegate(self.accounts_list))
        self.accounts_list.setWordWrap(False)
        self.accounts_list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self.accounts_list)

        profile_layout = QtWidgets.QHBoxLayout()
        profile_layout.addWidget(QtWidgets.QLabel("프로필 경로:"))
        self.profile_label = QtWidgets.QLabel("-")
        self.profile_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.profile_label.setWordWrap(True)
        self.profile_label.installEventFilter(self)
        profile_layout.addWidget(self.profile_label, 1)
        layout.addLayout(profile_layout)

    def _on_add_clicked(self) -> None:
        account_id = self.account_id_edit.text().strip()
        account_pw = self.account_pw_edit.text().strip()
        if not account_id:
            QtWidgets.QMessageBox.warning(self, "입력 오류", "네이버 아이디를 입력해주세요.")
            return
        if not account_pw:
            QtWidgets.QMessageBox.warning(self, "입력 오류", "네이버 비밀번호를 입력해주세요.")
            return

        self.accounts_list.clearSelection()
        self.account_id_edit.clear()
        self.account_pw_edit.clear()
        self.request_add_account.emit(account_id, account_pw)

    def _on_remove_clicked(self) -> None:
        account = self._current_account()
        if account:
            self.request_remove_account.emit(account.account_id)
    
    def _on_remove_selected_clicked(self) -> None:
        selected_accounts = []
        for row in range(self.accounts_list.count()):
            item = self.accounts_list.item(row)
            if item.checkState() == QtCore.Qt.Checked:
                account = item.data(QtCore.Qt.UserRole)
                if account:
                    selected_accounts.append(account.account_id)
        
        if not selected_accounts:
            QtWidgets.QMessageBox.warning(self, "선택 오류", "삭제할 계정을 선택해주세요.")
            return
        
        reply = QtWidgets.QMessageBox.question(
            self,
            "계정 삭제 확인",
            f"{len(selected_accounts)}개의 계정을 삭제하시겠습니까?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            for account_id in selected_accounts:
                self.request_remove_account.emit(account_id)

    def _on_open_profile_clicked(self) -> None:
        account = self._current_account()
        if account:
            self.request_open_profile.emit(account.account_id)

    def _on_open_browser_clicked(self) -> None:
        account = self._current_account()
        if account:
            self.request_open_browser.emit(account.account_id)

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
        self.accounts_list.clear()
        for account in accounts:
            item = QtWidgets.QListWidgetItem(account.account_id)
            item.setData(QtCore.Qt.UserRole, account)
            item.setData(QtCore.Qt.UserRole + 1, account.login_initialized)
            item.setCheckState(QtCore.Qt.Unchecked)  # 체크박스 초기 상태 설정
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)  # 체크 가능하도록 설정
            self.accounts_list.addItem(item)
        if self.accounts_list.count() > 0:
            self.select_account(selected_id)
        else:
            self.profile_label.setText("-")

    def select_account(self, account_id: str | None) -> None:
        if account_id is None:
            if self.accounts_list.count() > 0:
                self.accounts_list.setCurrentRow(0)
            return
        for row in range(self.accounts_list.count()):
            item = self.accounts_list.item(row)
            account = item.data(QtCore.Qt.UserRole)
            if account and account.account_id == account_id:
                self.accounts_list.setCurrentRow(row)
                return
        if self.accounts_list.count() > 0:
            self.accounts_list.setCurrentRow(0)

    def _on_item_changed(self, current: QtWidgets.QListWidgetItem | None, previous: QtWidgets.QListWidgetItem | None) -> None:
        if current:
            account: AccountProfile = current.data(QtCore.Qt.UserRole)
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
            self.remove_account_btn,
            self.remove_selected_btn,
            self.export_account_btn,
            self.login_button,
            self.accounts_list,
        ]
        for widget in controls:
            widget.setEnabled(enabled)

    def _current_account(self) -> AccountProfile | None:
        item = self.accounts_list.currentItem()
        if not item:
            return None
        return item.data(QtCore.Qt.UserRole)

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


