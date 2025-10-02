# -*- mode: python ; coding: utf-8 -*-
# Windows용 PyInstaller 빌드 스펙 (최적화)

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/resources/styles/main.qss', 'app/resources/styles'),
    ],
    hiddenimports=[
        'PyQt5.QtCore',
        'PyQt5.QtGui', 
        'PyQt5.QtWidgets',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.common.by',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.expected_conditions',
        'selenium.common.exceptions',
        'openai',
        'requests',
        'dotenv',
        'sqlite3',
        # SSL 관련 모듈 추가
        'ssl',
        '_ssl',
        '_hashlib',
        'certifi',
        'urllib3',
        'http.client',
        'http.cookiejar',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook.py'],
    excludes=[
        # 과학 계산 라이브러리 (불필요)
        'matplotlib', 'numpy', 'pandas', 'scipy', 'sympy',
        # GUI 라이브러리 (불필요)
        'tkinter', 'turtle', 'wx', 'gtk',
        # 테스트 관련
        'test', 'tests', 'testing', 'unittest', 'doctest', 'pytest', 'nose',
        # 문서화 도구
        'sphinx', 'docutils', 'jinja2',
        # 개발 도구
        'setuptools', 'distutils', 'pkg_resources',
        # 데이터베이스 (sqlite3만 사용)
        'psycopg2', 'pymongo', 'MySQLdb', 'mysql',
        # 이미지 처리 (Pillow만 사용)
        'cv2', 'skimage',
        # 네트워크/서버 (불필요)
        'tornado', 'twisted', 'flask', 'django',
        # 기타 대형 라이브러리
        'IPython', 'jupyter', 'notebook',
        # XML/HTML 파서 (selenium 내장 사용)
        'lxml', 'bs4', 'beautifulsoup4',
        # 압축 라이브러리 (내장만 사용)
        'bz2file', 'lzma',
        # 암호화 (내장만 사용)
        'cryptography', 'pycryptodome',
        # 기타
        'pydoc', 'pdb', 'profile', 'cProfile',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NaverBlog',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # SSL DLL 문제 방지를 위해 strip 비활성화
    upx=False,    # SSL DLL 문제 방지를 위해 UPX 압축 비활성화
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 모드 (콘솔 창 숨김)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version_file=None,
)

