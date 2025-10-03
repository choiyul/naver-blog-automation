"""PyInstaller 런타임 훅 - 발생 가능한 오류 사전 대비."""

import sys
import os

# 1. SSL 모듈 사전 로드 (DLL 오류 방지)
try:
    import ssl
    import _ssl
    import _hashlib
except ImportError as e:
    print(f"SSL 모듈 로드 실패: {e}")
    sys.exit(1)

# 2. certifi 인증서 경로 설정
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except Exception as e:
    print(f"인증서 설정 실패: {e}")

# 3. PyQt5 플러그인 경로 설정
try:
    from PyQt5 import QtCore
    # PyInstaller 환경에서 Qt 플러그인 경로 자동 설정
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        qt_plugin_path = os.path.join(meipass, 'PyQt5', 'Qt5', 'plugins')
        if os.path.exists(qt_plugin_path):
            os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
except Exception as e:
    print(f"PyQt5 설정 실패: {e}")

# 4. 인코딩 설정 (한글 처리)
if sys.platform.startswith('win'):
    try:
        # Windows에서 한글 출력 오류 방지
        import locale
        locale.setlocale(locale.LC_ALL, '')
    except Exception:
        pass

# 5. DLL 로드 경로 추가 (Windows)
if sys.platform.startswith('win'):
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        # PyInstaller가 압축 해제한 임시 폴더를 DLL 검색 경로에 추가
        try:
            os.add_dll_directory(meipass)
        except (AttributeError, OSError):
            # Python 3.7 이하 또는 권한 문제
            pass

print("런타임 초기화 완료")

