"""애플리케이션 진입점."""

from __future__ import annotations

import logging
import sys

from PyQt5 import QtWidgets, QtGui

from app.ui.pages import MainWindow
from app.core.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    app = QtWidgets.QApplication(sys.argv)
    
    # 전역 예외 훅: 예기치 않은 오류로 프로세스가 종료되는 것을 방지
    def _handle_exception(exc_type, exc_value, exc_traceback):  # noqa: ANN001
        import traceback
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        try:
            from app.core.logging_setup import logging  # lazy import to avoid cycles
            logging.getLogger(__name__).exception("Unhandled exception:\n%s", tb_text)
        except Exception:
            pass
        QtWidgets.QMessageBox.critical(None, "예기치 않은 오류", "프로그램 오류가 발생했습니다.\n로그를 확인해주세요.\n\n" + str(exc_value))

    sys.excepthook = _handle_exception
    # 전역 폰트 크기 확대 (가독성 향상)
    font = QtGui.QFont()
    font.setFamily('Malgun Gothic')
    font.setPointSize(15)
    app.setFont(font)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())


