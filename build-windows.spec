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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy',  # 불필요한 과학 계산 라이브러리
        'tkinter', 'turtle',  # 불필요한 GUI 라이브러리
        'test', 'tests', 'testing',  # 테스트 관련
        'unittest', 'doctest',  # 테스트 프레임워크
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
    name='NaverBlogAutomation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # 디버그 정보 제거로 크기 최적화
    upx=True,    # 압축으로 크기 최적화
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

