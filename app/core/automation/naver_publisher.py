"""네이버 블로그 자동 발행 서비스."""

from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import pytz

from selenium.webdriver.remote.webelement import WebElement

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import platform
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

LOGGER = logging.getLogger("naver_blog")
NAVER_HOME_URL = "https://www.naver.com/"
LOGIN_LINK_SELECTOR = "a.MyView-module__link_login___HpHMW"
BLOG_SPAN_XPATH = "//span[contains(@class,'MyView-module__item_text') and text()='블로그']"
BLOG_WRITE_LINK_SELECTOR = "a.MyView-module__link_tool___tAoH1.MyView-module__type_write___l9FOk"
BLOG_WRITE_FRAME_ID = "mainFrame"
BLOG_POPUP_CANCEL_XPATH = "//span[contains(@class,'se-popup-button-text') and text()='취소']"
TITLE_FIELD_SELECTORS = [
    (By.CSS_SELECTOR, "div.se-component.se-documentTitle[data-a11y-title='제목'] .se-text-paragraph"),
    (By.CSS_SELECTOR, "div.se-component.se-documentTitle[data-a11y-title='제목'] .se-module.se-title-text"),
    (By.CSS_SELECTOR, "div.se-component.se-documentTitle[data-a11y-title='제목']"),
]
BODY_FIELD_SELECTORS = [
    (By.CSS_SELECTOR, "div.se-component.se-text[data-compid] .se-text-paragraph"),
    (By.CSS_SELECTOR, "div.se-component.se-text[data-compid] .se-section-text"),
    (By.CSS_SELECTOR, "div.se-component.se-text[data-compid]"),
]
FAST_TYPING_DELAY_SECONDS = 0.01
TYPING_DELAY_SECONDS = 0.05
PUBLISH_DELAY_SECONDS = 2.0


class AccountProtectionException(Exception):
    """계정이 보호조치 상태일 때 발생하는 예외"""
    pass


@dataclass
class BlogPostContent:
    title: str
    introduction: str
    body: str
    conclusion: str
    tags: list[str]


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _cmd_key():
    return Keys.CONTROL if _is_windows() else Keys.COMMAND


def _cleanup_chrome_processes() -> None:
    """Chrome 프로세스를 완전히 정리합니다."""
    try:
        if _is_windows():
            # Windows에서 Chrome 프로세스 종료
            subprocess.run(['taskkill', '/f', '/im', 'chrome.exe'], 
                         capture_output=True, text=True, timeout=10)
            subprocess.run(['taskkill', '/f', '/im', 'chromedriver.exe'], 
                         capture_output=True, text=True, timeout=10)
        else:
            # macOS/Linux에서 Chrome 프로세스 종료
            subprocess.run(['pkill', '-f', 'Google Chrome'], 
                         capture_output=True, text=True, timeout=10)
            subprocess.run(['pkill', '-f', 'chromedriver'], 
                         capture_output=True, text=True, timeout=10)
        time.sleep(1)  # 프로세스 종료 대기
    except Exception as e:
        LOGGER.debug(f"Chrome 프로세스 정리 중 오류 (무시됨): {e}")

def _cleanup_profile_locks(user_data_dir: Path) -> None:
    """프로필 디렉토리의 모든 락 파일들을 정리합니다."""
    try:
        if not user_data_dir.exists():
            return
            
        # 알려진 락 파일들 정리
        lock_patterns = [
            "Singleton*", ".*lock*", ".*Lock*", "*Cookie*", 
            "Local State", "Preferences.tmp", "*.tmp"
        ]
        
        # 디렉토리와 파일 모두 확인
        for pattern in lock_patterns:
            for item in user_data_dir.glob(pattern):
                try:
                    if item.is_file():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                except Exception:
                    pass  # 락 파일 삭제 실패는 무시
                    
        # Default 프로필 내부도 정리
        default_profile = user_data_dir / "Default"
        if default_profile.exists():
            for pattern in ["*Lock*", "*lock*", "*.tmp"]:
                for item in default_profile.glob(pattern):
                    try:
                        if item.is_file():
                            item.unlink(missing_ok=True)
                    except Exception:
                        pass
                        
    except Exception as e:
        LOGGER.debug(f"프로필 락 파일 정리 중 오류 (무시됨): {e}")

def create_chrome_driver(user_data_dir: Path, retry_count: int = 3) -> webdriver.Chrome:
    """Chrome 드라이버를 생성합니다. 실패 시 재시도합니다."""
    
    for attempt in range(retry_count):
        try:
            # 1단계: Chrome 프로세스 정리 (첫 번째 시도에서만)
            if attempt == 0:
                _cleanup_chrome_processes()
            
            # 2단계: 프로필 락 파일 정리
            _cleanup_profile_locks(user_data_dir)
            
            # 3단계: Chrome 옵션 설정
            chrome_options = Options()
            chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
            chrome_options.add_argument("--profile-directory=Default")
            
            # 세션 충돌 방지 옵션 추가
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--lang=ko-KR")
            chrome_options.add_argument("--no-first-run")
            chrome_options.add_argument("--disable-default-apps")
            chrome_options.add_argument("--disable-popup-blocking")
            
            # 재시도 시에는 더 강력한 옵션 추가
            if attempt > 0:
                chrome_options.add_argument("--force-device-scale-factor=1")
                chrome_options.add_argument("--disable-gpu-sandbox")
                
            # 최소한의 안정성 설정
            chrome_options.add_argument("--ignore-certificate-errors-spki-list")
            chrome_options.add_argument("--ignore-ssl-errors-spki-list")
    
            # OS에 맞춘 User-Agent 적용
            if _is_windows():
                chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            else:
                chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            # 기본 페이지 설정
            chrome_options.add_experimental_option("prefs", {
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_settings.popups": 0,
                "download.default_directory": str(user_data_dir / "Downloads"),
                "disk-cache-size": 0
            })
            
            # 드라이버 생성 시도
            LOGGER.info(f"Chrome 브라우저 생성 시도 {attempt + 1}/{retry_count}")
            driver = webdriver.Chrome(options=chrome_options)
            
            # 페이지 로딩 설정
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(10)
            
            # 자동화 탐지 방지
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            })
            
            LOGGER.info("✅ Chrome 브라우저 생성 성공")
            return driver
            
        except Exception as exc:
            LOGGER.warning(f"Chrome 브라우저 생성 실패 (시도 {attempt + 1}/{retry_count}): {exc}")
            
            if attempt < retry_count - 1:
                # 재시도 전 추가 대기 및 정리
                time.sleep(2 + attempt)  # 점진적 대기 시간 증가
                _cleanup_chrome_processes()  # 다시 정리
                continue
            else:
                # 모든 시도 실패 - 사용자 친화적 오류 메시지
                raise RuntimeError(
                    f"❌ Chrome 브라우저를 시작할 수 없습니다.\n\n"
                    f"오류 내용: {exc}\n\n"
                    f"💡 해결 방법:\n"
                    f"1. Chrome 브라우저를 완전히 종료하고 다시 시도해주세요\n"
                    f"2. 작업 관리자에서 chrome.exe 프로세스를 모두 종료해주세요\n"
                    f"3. 컴퓨터를 재시작한 후 다시 시도해주세요\n"
                    f"4. 다른 Chrome 창이나 브라우저를 모두 닫고 시도해주세요"
                ) from exc


def configure_user_data_dir(base_dir: Path, account_id: Optional[str] = None) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    target = base_dir / (re.sub(r"[^a-zA-Z0-9_-]", "_", account_id) if account_id else "default")
    target.mkdir(parents=True, exist_ok=True)
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_path = target / lock_name
        lock_path.unlink(missing_ok=True)
    return target


def publish_blog_post(
    content: BlogPostContent,
    *,
    driver: Optional[webdriver.Chrome] = None,
    base_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
    stop_callback: Optional[Callable[[], bool]] = None,
    image_file_path: Optional[str] = None,
    fast_mode: bool = False,
    schedule_minutes: int = 5,
    post_index: int = 0,
    account_id: Optional[str] = None,
    profile_dir: Optional[str] = None,
) -> tuple[webdriver.Chrome, Optional[str]]:
    """블로그 글을 발행합니다.
    
    Returns:
        tuple[webdriver.Chrome, Optional[str]]: (드라이버, 블로그 URL)
    """
    base_dir = base_dir or Path.cwd()
    user_data_dir = Path(profile_dir) if profile_dir else configure_user_data_dir(base_dir, account_id)
    if driver is None:
        driver = create_chrome_driver(user_data_dir)
        _report(progress_callback, "브라우저 준비", True)

    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 글쓰기 페이지 열기 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")
    
    _open_blog_write_page(driver, progress_callback, stop_callback)
    _report(progress_callback, "글쓰기 페이지 열기", True)
    
    # 글쓰기 페이지가 완전히 열린 후 시점 기록 (예약 시간 계산용)
    page_open_time = datetime.now()
    LOGGER.info(f"글쓰기 페이지 열림 완료 시간: {page_open_time.strftime('%H:%M:%S')}")
    
    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 글 내용 작성 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")
    
    _write_blog_post(
        driver,
        content,
        progress_callback=progress_callback,
        stop_callback=stop_callback,
        image_file_path=image_file_path,
        fast_mode=fast_mode,
    )
    _report(progress_callback, "글 내용 작성", True)

    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 발행 준비 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")

    if PUBLISH_DELAY_SECONDS > 0:
        LOGGER.info("발행 준비 중...")
        time.sleep(PUBLISH_DELAY_SECONDS)
    _report(progress_callback, "발행 준비", True)

    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 발행 버튼 클릭 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")

    _publish_post(driver, progress_callback=progress_callback, stop_callback=stop_callback)
    _report(progress_callback, "발행 버튼 클릭", True)
    
    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 발행 팝업 처리 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")
    
    blog_url = _handle_publish_popup(
        driver,
        content.tags,
        progress_callback=progress_callback,
        stop_callback=stop_callback,
        schedule_minutes=schedule_minutes,
        post_index=post_index,
        page_open_time=page_open_time,  # 글쓰기 페이지 열린 시점 전달
    )
    _report(progress_callback, "예약 발행 완료", True)
    
    # 블로그 URL 정보 추가 (로깅용)
    if blog_url:
        LOGGER.info(f"🔗 발행 완료된 게시물: {blog_url}")
    
    return driver, blog_url


def _report(callback: Optional[Callable[[str, bool], None]], message: str, completed: bool = True) -> None:
    """UI 콜백에 상세한 진행 정보를 전달합니다."""
    if callback:
        try:
            callback(message, completed)
        except Exception:  # pragma: no cover - UI 콜백 실패는 무시
            LOGGER.debug("Progress callback failed", exc_info=True)


def _check_account_protection(driver: webdriver.Chrome, progress_callback: Optional[Callable[[str, bool], None]] = None) -> None:
    """계정 보호조치 여부를 확인합니다."""
    try:
        # 보호조치 버튼 감지
        protection_buttons = driver.find_elements(
            By.XPATH, 
            "//a[contains(@onclick, 'mainSubmit') and contains(@class, 'btn') and contains(text(), '보호조치')]"
        )
        
        if protection_buttons:
            LOGGER.warning("⚠️ 계정이 보호조치 상태입니다. 이 계정을 건너뜁니다.")
            _report(progress_callback, "계정 보호조치 감지 - 다음 계정으로 넘어갑니다", True)
            raise AccountProtectionException("계정이 보호조치 상태입니다.")
    except AccountProtectionException:
        raise  # AccountProtectionException은 그대로 전파
    except Exception as e:
        # 다른 예외는 무시 (보호조치 확인 실패는 치명적이지 않음)
        LOGGER.debug(f"보호조치 확인 중 오류 (무시): {e}")
        pass


def _countdown_sleep(
    seconds: int, 
    message: str,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
    stop_callback: Optional[Callable[[], bool]] = None,
) -> None:
    """카운트다운과 함께 대기합니다."""
    if seconds <= 0:
        return
        
    for remaining in range(seconds, 0, -1):
        # 중단 요청 확인
        if stop_callback and stop_callback():
            LOGGER.info("카운트다운 중단 요청")
            return
            
        countdown_msg = f"{message} ({remaining}초 남음...)"
        _report(progress_callback, countdown_msg, False)
        LOGGER.info(countdown_msg)
        time.sleep(1)
    
    # 완료 메시지
    final_msg = f"{message} (완료)"
    _report(progress_callback, final_msg, True)
    LOGGER.info(final_msg)


def _open_blog_write_page(
    driver: webdriver.Chrome,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
    stop_callback: Optional[Callable[[], bool]] = None,
) -> None:
    driver.get(NAVER_HOME_URL)
    _report(progress_callback, "네이버 홈 접속", True)

    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 로그인 상태 확인 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")

    need_login = False
    login_link = None
    try:
        login_link = driver.find_element(By.CSS_SELECTOR, "a.MyView-module__link_login___HpHMW")
        need_login = login_link.is_displayed()
    except NoSuchElementException:
        need_login = False

    if need_login:
        # 중단 요청 확인
        if stop_callback and stop_callback():
            LOGGER.info("작업 중단 요청 - 로그인 페이지 이동 전")
            raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")
            
        _report(progress_callback, "로그인 페이지 이동", False)
        login_link.click()
        _report(progress_callback, "사용자 로그인 입력 대기", False)
        try:
            WebDriverWait(driver, 300).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//span[contains(@class,'MyView-module__item_text') and text()='블로그']")
                )
            )
        except TimeoutException as exc:
            _report(progress_callback, "로그인 대기 시간이 초과되었습니다.", False)
            raise exc
        _report(progress_callback, "로그인 완료 확인", True)
    else:
        _report(progress_callback, "로그인 상태 확인", True)

    # 보호조치 여부 확인
    _check_account_protection(driver, progress_callback)

    try:
        blog_span = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(
                (By.XPATH, "//span[contains(@class,'MyView-module__item_text') and text()='블로그']")
            )
        )
    except TimeoutException as exc:
        _report(progress_callback, "블로그 메뉴를 찾지 못했습니다.", False)
        raise exc

    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 블로그 메뉴 클릭 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")

    try:
        blog_link = blog_span.find_element(By.XPATH, "./ancestor::a[1]")
    except NoSuchElementException:
        blog_span.click()
    else:
        blog_link.click()
    _report(progress_callback, "블로그 메뉴 클릭", True)

    try:
        write_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "a.MyView-module__link_tool___tAoH1.MyView-module__type_write___l9FOk")
            )
        )
    except TimeoutException as exc:
        _report(progress_callback, "글쓰기 버튼을 찾지 못했습니다.", False)
        raise exc

    # 중단 요청 확인
    if stop_callback and stop_callback():
        LOGGER.info("작업 중단 요청 - 글쓰기 버튼 클릭 전")
        raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")

    handles_before = list(driver.window_handles)
    write_button.click()
    _report(progress_callback, "글쓰기 버튼 클릭", True)

    try:
        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > len(handles_before))
    except TimeoutException:
        _report(progress_callback, "새 글쓰기 창을 열지 못했습니다.", False)
        raise

    driver.switch_to.window(driver.window_handles[-1])
    _report(progress_callback, "글쓰기 탭 전환", True)

    driver.switch_to.default_content()
    _handle_editor_entry_popup(driver, progress_callback)

    # mainFrame 전환 (편집기 iframe으로 이동)
    _report(progress_callback, "편집기 iframe 전환 중", False)
    
    try:
        # ID로 바로 전환 (이전 테스트에서 성공한 방법)
        WebDriverWait(driver, 10).until(EC.frame_to_be_available_and_switch_to_it("mainFrame"))
        LOGGER.info("mainFrame 전환 성공")
        _report(progress_callback, "편집기 iframe 전환 완료", True)
        
    except TimeoutException:
        try:
            # CSS selector로 대안 시도
            _report(progress_callback, "대안 방법으로 iframe 전환 시도", False)
            frame_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#mainFrame"))
            )
            driver.switch_to.frame(frame_element)
            LOGGER.info("대안 방법으로 mainFrame 전환 성공")
            _report(progress_callback, "편집기 iframe 전환 완료 (대안 방법)", True)
            
        except TimeoutException:
            _report(progress_callback, "편집기 iframe 전환 실패", False)
            raise TimeoutException("편집기 iframe 전환 실패")
    
    # iframe 전환 후 편집기 로딩 대기 (5초)
    _countdown_sleep(5, "편집기 로딩 대기", progress_callback, stop_callback)

    # 편집기 로딩 확인 (성공한 방법 우선 사용)
    try:
        # 이전 테스트에서 성공한 selector로 바로 확인
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-documentTitle"))
        )
        LOGGER.info("편집기 로딩 확인 완료")
        _report(progress_callback, "편집기 로딩 완료", True)
        
    except TimeoutException:
        # 대안 방법들 시도
        _report(progress_callback, "대안 방법으로 편집기 로딩 확인 중", False)
        alternative_selectors = [".se-section-documentTitle", "[data-a11y-title='제목']"]
        
        editor_loaded = False
        for selector in alternative_selectors:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                LOGGER.info(f"편집기 로딩 확인됨 (대안: {selector})")
                editor_loaded = True
                break
            except TimeoutException:
                continue
        
        if not editor_loaded:
            _report(progress_callback, "편집기 로딩 확인 실패", False)
            driver.switch_to.default_content()
            raise TimeoutException("편집기 로딩 실패")
        
        driver.switch_to.default_content()
        _report(progress_callback, "편집기 로딩 완료 (대안 방법)", True)


def _write_blog_post(
    driver: webdriver.Chrome,
    content: BlogPostContent,
    *,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
    stop_callback: Optional[Callable[[], bool]] = None,
    image_file_path: Optional[str] = None,
    fast_mode: bool = False,
) -> None:
    _dismiss_resume_popup(driver, progress_callback)

    title_element = _focus_title_area(driver)
    _type_text(title_element, content.title)
    _report(progress_callback, "제목 입력 완료", True)
    time.sleep(0.5)  # 제목 입력 후 안정화 대기 (최적화)

    # 이미지가 있는 경우 무조건 본문 작성 전에 먼저 삽입
    if image_file_path:
        _report(progress_callback, "이미지 삽입 중 (본문 상단)", False)
        _insert_image(driver, image_file_path, progress_callback, stop_callback)
        time.sleep(1)  # 이미지 삽입 후 안정화 대기 (최적화)

    body_element = _focus_body_area(driver)
    body_text = _combine_body(content)
    _type_text(body_element, body_text, fast_mode)
    _report(progress_callback, "본문 입력 완료", True)
    time.sleep(0.5)  # 본문 입력 후 안정화 대기 (최적화)


def _insert_image(
    driver: webdriver.Chrome,
    image_file_path: str,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
    stop_callback: Optional[Callable[[], bool]] = None,
) -> None:
    """복사-붙여넣기 방식으로 본문 상단에 이미지를 삽입합니다."""
    try:
        # 이미지 파일 경로 확인
        if not Path(image_file_path).is_file():
            LOGGER.error("이미지 파일이 존재하지 않습니다: %s", image_file_path)
            _report(progress_callback, "이미지 파일을 찾을 수 없습니다.", False)
            return
        
        LOGGER.info("복사-붙여넣기 방식으로 이미지 삽입 시작: %s", image_file_path)
        _report(progress_callback, "이미지를 클립보드에 복사 중", False)
        
        # 1. 본문 영역 찾기
        try:
            # 본문 편집 가능한 영역 찾기
            body_area = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-text .se-text-paragraph"))
            )
            LOGGER.info("본문 편집 영역 찾기 성공")
        except TimeoutException:
            # 대안: 제목 다음에 새로운 영역 생성
            try:
                title_area = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-documentTitle"))
                )
                title_area.click()
                ActionChains(driver).send_keys(Keys.END).send_keys(Keys.ENTER).perform()
                time.sleep(1)
                
                body_area = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-text .se-text-paragraph"))
                )
                LOGGER.info("새 본문 영역 생성 성공")
            except TimeoutException:
                LOGGER.error("본문 영역을 찾거나 생성할 수 없습니다")
                _report(progress_callback, "본문 영역을 찾을 수 없습니다", False)
                return
        
        # 2. 이미지를 클립보드에 복사 (JavaScript 사용)
        try:
            # 이미지 파일을 Base64로 읽기
            with open(image_file_path, 'rb') as img_file:
                img_data = base64.b64encode(img_file.read()).decode('utf-8')
            
            # 파일 확장자에 따른 MIME 타입 결정
            file_ext = Path(image_file_path).suffix.lower()
            if file_ext in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif file_ext == '.png':
                mime_type = 'image/png'
            elif file_ext == '.gif':
                mime_type = 'image/gif'
            elif file_ext == '.webp':
                mime_type = 'image/webp'
            else:
                mime_type = 'image/png'  # 기본값
            
            # JavaScript로 이미지를 클립보드에 복사
            script = f"""
            async function copyImageToClipboard() {{
                try {{
                    const base64Data = '{img_data}';
                    const mimeType = '{mime_type}';
                    
                    // Base64를 Blob으로 변환
                    const byteCharacters = atob(base64Data);
                    const byteNumbers = new Array(byteCharacters.length);
                    for (let i = 0; i < byteCharacters.length; i++) {{
                        byteNumbers[i] = byteCharacters.charCodeAt(i);
                    }}
                    const byteArray = new Uint8Array(byteNumbers);
                    const blob = new Blob([byteArray], {{type: mimeType}});
                    
                    // 클립보드에 복사
                    const clipboardItem = new ClipboardItem({{[mimeType]: blob}});
                    await navigator.clipboard.write([clipboardItem]);
                    
                    return true;
                }} catch (error) {{
                    console.error('클립보드 복사 실패:', error);
                    return false;
                }}
            }}
            return copyImageToClipboard();
            """
            
            result = driver.execute_script(script)
            if result:
                LOGGER.info("이미지 클립보드 복사 성공")
                _report(progress_callback, "이미지 클립보드 복사 완료", True)
            else:
                raise Exception("JavaScript 클립보드 복사 실패")
                
        except Exception as e:
            LOGGER.warning(f"JavaScript 클립보드 복사 실패: {e}")
            # 대안: OS별 네이티브 클립보드
            try:
                if _is_windows():
                    import win32clipboard  # type: ignore
                    import win32con  # type: ignore
                    from PIL import Image  # type: ignore
                    img = Image.open(image_file_path).convert('RGB')
                    import io
                    output = io.BytesIO()
                    img.save(output, format='BMP')
                    data = output.getvalue()[14:]
                    output.close()
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_DIB, data)
                    win32clipboard.CloseClipboard()
                    LOGGER.info("시스템 클립보드 복사 성공 (Windows)")
                else:
                    subprocess.run(['osascript', '-e', f'set the clipboard to (read file POSIX file "{image_file_path}" as JPEG picture)'], check=True)
                    LOGGER.info("시스템 클립보드 복사 성공 (macOS)")
                _report(progress_callback, "시스템 클립보드 복사 완료", True)
            except Exception as e2:
                LOGGER.error(f"모든 클립보드 복사 방법 실패: {e2}")
                _report(progress_callback, "클립보드 복사 실패", False)
                return

        # 3. 본문 영역에 포커스하고 이미지 붙여넣기
        try:
            _report(progress_callback, "본문 영역에 이미지 붙여넣기 중", False)
            
            # 본문 영역의 맨 처음으로 커서 이동
            body_area.click()
            time.sleep(0.5)
            
            # 커서를 맨 앞으로 이동
            meta = _cmd_key()
            ActionChains(driver).key_down(meta).send_keys(Keys.HOME).key_up(meta).perform()
            time.sleep(0.3)
            
            # 이미지 붙여넣기
            meta = _cmd_key()
            ActionChains(driver).key_down(meta).send_keys('v').key_up(meta).perform()
            time.sleep(3)  # 이미지 처리 대기
            
            # 이미지 다음에 줄바꿈 추가 (본문과 분리)
            ActionChains(driver).send_keys(Keys.END).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
            time.sleep(0.5)
            
            LOGGER.info("이미지 붙여넣기 및 줄바꿈 완료")
            _report(progress_callback, "이미지 삽입 완료 (본문 상단)", True)
            
        except Exception as e:
            LOGGER.error(f"이미지 붙여넣기 실패: {e}")
            _report(progress_callback, "이미지 붙여넣기 실패", False)
        
    except Exception as exc:
        LOGGER.error("이미지 삽입 전체 실패: %s", exc)
        _report(progress_callback, "이미지 삽입 실패", False)


def _publish_post(
    driver: webdriver.Chrome,
    *,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
    stop_callback: Optional[Callable[[], bool]] = None,
) -> None:
    """발행 버튼을 찾아 클릭합니다."""
    _report(progress_callback, "발행 버튼 찾는 중", False)
    
    # 이전 테스트에서 성공한 방법 우선 시도
    try:
        # 성공한 XPath로 바로 시도
        publish_button = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(@class,'text__d09H7') and text()='발행']"))
        )
        LOGGER.info("발행 버튼 찾기 성공")
        _report(progress_callback, "발행 버튼 찾기 완료", True)
        
    except TimeoutException:
        # 대안 방법들 시도
        _report(progress_callback, "대안 방법으로 발행 버튼 찾는 중", False)
        
        alternative_xpaths = [
            "//button[contains(text(),'발행')]",
            "//span[text()='발행']", 
            "//*[text()='발행']"
        ]
        
        publish_button = None
        for xpath in alternative_xpaths:
            try:
                publish_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                LOGGER.info(f"발행 버튼 찾음 (대안: {xpath})")
                break
            except TimeoutException:
                continue
        
        if not publish_button:
            # CSS selector로 최후 시도
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, "span.text__d09H7")
                for element in elements:
                    if element.text and "발행" in element.text:
                        publish_button = element
                        LOGGER.info("발행 버튼 찾음 (CSS)")
                        break
            except Exception:
                pass
        
        if not publish_button:
            _report(progress_callback, "발행 버튼을 찾을 수 없습니다", False)
            raise NoSuchElementException("발행 버튼을 찾을 수 없습니다")
        
        _report(progress_callback, "발행 버튼 찾기 완료 (대안 방법)", True)
    
    # 발행 버튼 클릭 (2초 대기 후)
    _countdown_sleep(2, "발행 버튼 클릭 준비", progress_callback, stop_callback)
    
    try:
        # 화면에 보이도록 스크롤
        driver.execute_script("arguments[0].scrollIntoView(true);", publish_button)
        time.sleep(0.5)
        
        # 클릭 시도
        publish_button.click()
        LOGGER.info("발행 버튼 클릭 성공")
        _report(progress_callback, "발행 버튼 클릭 완료", True)
        
    except ElementClickInterceptedException:
        # JavaScript로 클릭 시도
        _report(progress_callback, "JavaScript로 발행 버튼 클릭 시도", False)
        driver.execute_script("arguments[0].click();", publish_button)
        _report(progress_callback, "발행 버튼 클릭 완료 (JS)", True)
        
    except Exception as e:
        _report(progress_callback, "발행 버튼 클릭 실패", False)
        LOGGER.error("발행 버튼 클릭 실패: %s", e)
        raise


def _handle_publish_popup(
    driver: webdriver.Chrome,
    tags: list[str],
    *,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
    stop_callback: Optional[Callable[[], bool]] = None,
    schedule_minutes: int = 5,
    post_index: int = 0,
    page_open_time: Optional[datetime] = None,
) -> Optional[str]:
    """발행 팝업에서 태그 입력과 예약 시간 설정 후 발행합니다.
    
    Returns:
        발행된 블로그 게시물의 URL (성공 시) 또는 None (실패 시)
    """
    LOGGER.info("발행 팝업 처리 시작 - post_index: %s", post_index)
    
    try:
        # 1. 태그 입력
        if tags:
            _report(progress_callback, f"태그 확인 중 ({len(tags)}개 준비됨)", False)
            _input_tags(driver, tags, progress_callback)
            time.sleep(0.5)  # 대기 시간 단축
        
        # 2. 예약 시간 설정 (schedule_minutes > 0인 경우)
        if schedule_minutes > 0:
            _report(progress_callback, f"예약 시간 설정 중 ({schedule_minutes}분 후)", False)
            _set_scheduled_time(driver, schedule_minutes, page_open_time, progress_callback)
            
            # 예약 시간 설정 후 DOM 안정화 대기 (중요!)
            time.sleep(2)
            LOGGER.info("예약 시간 설정 후 DOM 안정화 대기 완료")
        else:
            # 예약 설정 건너뛰기 (즉시 발행)
            LOGGER.info("예약 발행 OFF - 즉시 발행 모드")
            _report(progress_callback, "즉시 발행 모드", True)
            _report(progress_callback, "예약 시간 설정 완료", True)
        
        # 3. 최종 발행 버튼 클릭 (팝업 상태 재확인)
        _report(progress_callback, "최종 발행 버튼 클릭 중", False)
        
        # 팝업이 아직 열려있는지 확인
        try:
            popup_check = driver.find_elements(By.CSS_SELECTOR, ".publish_popup, .se-popup, [class*='popup']")
            if not popup_check:
                LOGGER.warning("발행 팝업이 닫혔습니다. 다시 발행 버튼을 클릭합니다.")
                # 첫 번째 발행 버튼 다시 클릭
                first_publish_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[contains(@class,'text__d09H7') and text()='발행']"))
                )
                first_publish_btn.click()
                time.sleep(2)
                LOGGER.info("발행 팝업 재오픈 완료")
        except Exception as e:
            LOGGER.info(f"팝업 상태 확인 중 오류 (무시): {e}")
        
        _click_final_publish_button(driver)
        time.sleep(1)
        _report(progress_callback, "발행 완료", True)
        
        # 4. 발행 완료 후 블로그 게시물 URL 가져오기
        _report(progress_callback, "게시물 URL 확인 중", False)
        blog_url = _get_published_blog_url(driver)
        if blog_url:
            LOGGER.info(f"📝 발행된 게시물 URL: {blog_url}")
            _report(progress_callback, f"게시물 URL: {blog_url}", True)
        else:
            LOGGER.warning("게시물 URL을 가져오지 못했습니다.")
            _report(progress_callback, "URL 확인 실패", True)
        
        LOGGER.info("발행 팝업 처리 완료")
        return blog_url  # 블로그 URL 반환
        
    except Exception as e:
        LOGGER.error("발행 팝업 처리 실패: %s", e)
        _report(progress_callback, "발행 팝업 처리 실패", False)
        raise


def _input_tags(driver: webdriver.Chrome, tags: list[str], progress_callback: Optional[Callable[[str, bool], None]] = None) -> None:
    """발행 팝업에서 태그를 입력합니다."""
    try:
        # 태그 입력 필드 찾기 (더 짧은 대기 시간)
        tag_input = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "tag-input"))
        )
        LOGGER.info("태그 입력 필드 찾기 성공")
        
        # 기존 태그가 있는지 확인 (본문에서 자동 추출된 태그)
        try:
            existing_tags = driver.execute_script("""
                // 태그 영역에서 기존 태그들 찾기
                var tagElements = document.querySelectorAll('.tag-item, .tag, [class*="tag"], .tag_area span');
                var existingTags = [];
                tagElements.forEach(function(element) {
                    var text = element.textContent || element.innerText;
                    if (text && text.trim().length > 0 && !text.includes('태그') && !text.includes('입력')) {
                        var cleanTag = text.trim().replace(/[#×]/g, '');
                        if (cleanTag.length > 0) {
                            existingTags.push(cleanTag);
                        }
                    }
                });
                
                // 태그 입력 필드의 값도 확인
                var tagInput = document.getElementById('tag-input');
                if (tagInput && tagInput.value && tagInput.value.trim()) {
                    var inputTags = tagInput.value.split(',').map(t => t.trim()).filter(t => t.length > 0);
                    existingTags = existingTags.concat(inputTags);
                }
                
                // 중복 제거
                return [...new Set(existingTags)];
            """)
            
            if existing_tags and len(existing_tags) > 0:
                LOGGER.info(f"✅ 기존 태그 발견 ({len(existing_tags)}개): {', '.join(existing_tags)}")
                LOGGER.info("📝 본문에서 자동으로 추출된 태그가 있어 태그 입력을 스킵합니다.")
                _report(progress_callback, f"기존 태그 사용 ({len(existing_tags)}개): {', '.join(existing_tags[:3])}{'...' if len(existing_tags) > 3 else ''}", True)
                return
            else:
                LOGGER.info("🏷️ 기존 태그가 없어 새 태그를 입력합니다.")
                _report(progress_callback, f"새 태그 입력 시작 ({len(tags)}개)", False)
                
        except Exception as e:
            LOGGER.debug(f"기존 태그 확인 실패, 새 태그 입력 진행: {e}")
            # 기존 태그 확인 실패 시에도 새 태그 입력 진행
        
        # overlapping 요소 처리를 위한 스크롤 및 대기
        try:
            # 페이지 상단으로 스크롤하여 헤더 문제 해결
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            
            # 태그 입력 필드가 보이도록 스크롤
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tag_input)
            time.sleep(0.5)
            
            # overlapping 요소들 숨기기 시도
            try:
                driver.execute_script("""
                    var headers = document.querySelectorAll('.se-help-header, header');
                    headers.forEach(function(header) {
                        if (header) header.style.display = 'none';
                    });
                """)
                time.sleep(0.3)
            except:
                pass
            
        except Exception:
            LOGGER.warning("스크롤 및 overlapping 요소 처리 실패")
        
        # 각 태그 입력
        for i, tag in enumerate(tags):
            if tag.strip():  # 빈 태그가 아닌 경우만
                try:
                    # 태그 입력 필드 재확인 (stale element 방지)
                    tag_input = driver.find_element(By.ID, "tag-input")
                    
                    # 태그 입력 필드 클릭 (여러 방법 시도)
                    try:
                        # 일반 클릭 시도
                        tag_input.click()
                    except Exception:
                        try:
                            # JavaScript 클릭 시도
                            driver.execute_script("arguments[0].click();", tag_input)
                            LOGGER.info("태그 입력 필드 클릭 (JS)")
                        except Exception:
                            # ActionChains 클릭 시도
                            ActionChains(driver).move_to_element(tag_input).click().perform()
                            LOGGER.info("태그 입력 필드 클릭 (ActionChains)")
                    
                    time.sleep(0.3)
                    
                    # 기존 입력값 모두 지우기
                    tag_input.clear()
                    time.sleep(0.2)
                    
                    # ActionChains로 태그 입력
                    actions = ActionChains(driver)
                    actions.send_keys(tag.strip())
                    actions.send_keys(Keys.ENTER)  # 엔터로 태그 완료
                    actions.perform()
                    
                    time.sleep(0.5)  # 대기 시간 단축
                    LOGGER.info(f"태그 '{tag}' 입력 완료 ({i+1}/{len(tags)})")
                    
                except Exception as tag_error:
                    LOGGER.warning(f"태그 '{tag}' 입력 실패: {tag_error}")
                    continue  # 실패한 태그는 건너뛰고 계속 진행
        
        # 마지막 태그 적용 대기 (시간 단축)
        time.sleep(0.8)
        completed_tags = [t for t in tags if t.strip()]
        LOGGER.info(f"모든 태그 입력 완료: {', '.join(completed_tags)}")
        _report(progress_callback, f"태그 입력 완료 ({len(completed_tags)}개)", True)
        
    except Exception as e:
        LOGGER.warning(f"태그 입력 실패: {e}")
        _report(progress_callback, "태그 입력 실패 (계속 진행)", True)
        # 태그 입력이 실패해도 계속 진행


def _set_scheduled_time(driver: webdriver.Chrome, schedule_minutes: int, page_open_time: Optional[datetime] = None, progress_callback: Optional[Callable[[str, bool], None]] = None) -> None:
    """발행 팝업에서 예약 시간을 설정합니다."""
    try:
        # 예약 라디오 버튼 클릭 (더 안정적으로, 시간 최적화)
        LOGGER.info("예약 라디오 버튼 찾는 중...")
        
        # 대기 시간 단축: 3번 시도, 각 2초씩
        schedule_radio = None
        selectors = [
            ("ID", "radio_time2"),
            ("CSS", "[data-testid='preTimeRadioBtn']"),
            ("XPATH", "//label[contains(text(),'예약')]")
        ]
        
        for selector_type, selector in selectors:
            try:
                if selector_type == "ID":
                    schedule_radio = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable((By.ID, selector))
                    )
                elif selector_type == "CSS":
                    schedule_radio = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                elif selector_type == "XPATH":
                    label = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    schedule_radio = driver.find_element(By.ID, label.get_attribute("for"))
                
                if schedule_radio:
                    LOGGER.info(f"예약 라디오 버튼 찾기 성공 ({selector_type})")
                    break
            except (TimeoutException, NoSuchElementException):
                continue
        
        if not schedule_radio:
            raise Exception("예약 라디오 버튼을 찾을 수 없습니다")
        
        # 라디오 버튼 클릭 (stale element 처리 포함, 시간 최적화)
        for attempt in range(2):  # 시도 횟수 감소
            try:
                # stale element 방지를 위해 요소 재검색
                if attempt > 0:
                    try:
                        # 첫 번째 방법으로 다시 찾기
                        schedule_radio = driver.find_element(By.ID, "radio_time2")
                    except NoSuchElementException:
                        try:
                            schedule_radio = driver.find_element(By.CSS_SELECTOR, "[data-testid='preTimeRadioBtn']")
                        except NoSuchElementException:
                            label = driver.find_element(By.XPATH, "//label[contains(text(),'예약')]")
                            schedule_radio = driver.find_element(By.ID, label.get_attribute("for"))
                
                # 클릭 시도 (JavaScript 우선)
                try:
                    driver.execute_script("arguments[0].click();", schedule_radio)
                    time.sleep(0.5)
                    LOGGER.info(f"예약 라디오 버튼 클릭 완료 (JS, 시도 {attempt + 1})")
                    break
                except Exception:
                    # 일반 클릭 시도
                    schedule_radio.click()
                    time.sleep(0.5)
                    LOGGER.info(f"예약 라디오 버튼 클릭 완료 (직접, 시도 {attempt + 1})")
                    break
            except Exception as e:
                if attempt == 2:  # 마지막 시도
                    LOGGER.warning(f"예약 라디오 버튼 클릭 실패: {e}")
                    raise
                time.sleep(0.5)
        
        # 시간 설정 UI가 나타날 때까지 대기 (시간 단축)
        time.sleep(1)
        
        # 한국 시간 기준으로 예약 시간 계산
        korea_tz = pytz.timezone('Asia/Seoul')
        
        # 기준 시간 결정 (항상 현재 시간 기준으로 정확한 계산) - timezone-aware로 변환
        current_time_naive = datetime.now()
        current_time = korea_tz.localize(current_time_naive)
        
        # 예약 시간이 과거가 되지 않도록 현재 시간을 기준으로 계산
        base_time = current_time
        
        # 정확한 시간 정보 로그
        if page_open_time:
            page_open_time_aware = korea_tz.localize(page_open_time) if page_open_time.tzinfo is None else page_open_time
            time_since_page_open = (current_time - page_open_time_aware).total_seconds()
            LOGGER.info(f"📄 글쓰기 페이지 열린 시간: {page_open_time.strftime('%H:%M:%S')}")
            LOGGER.info(f"🕐 현재 시간: {current_time.strftime('%H:%M:%S')} (페이지 열린 후 {time_since_page_open:.1f}초)")
            LOGGER.info(f"⏰ 예약 시간 계산 기준: 현재 시간 ({current_time.strftime('%H:%M:%S')})")
        else:
            LOGGER.info(f"⏰ 예약 시간 계산 기준: 현재 시간 ({current_time.strftime('%H:%M:%S')})")
        
        # 예약 시간 계산 및 검증
        target_time = base_time + timedelta(minutes=schedule_minutes)
        
        # 과거 시간 방지: 현재 시간보다 최소 2분 후로 설정
        min_future_time = current_time + timedelta(minutes=2)
        if target_time <= min_future_time:
            LOGGER.warning(f"⚠️ 계산된 예약 시간이 너무 가깝습니다: {target_time.strftime('%H:%M:%S')}")
            target_time = min_future_time
            LOGGER.info(f"🔄 예약 시간을 최소 미래 시간으로 조정: {target_time.strftime('%H:%M:%S')}")
        
        target_hour = target_time.hour
        target_minute = target_time.minute
        
        # 시간이 넘어가는 경우 처리
        if target_minute >= 60:
            target_minute = target_minute % 60
            target_hour = (target_hour + 1) % 24
        
        # 상세한 시간 정보 로그
        actual_delay = (target_time - current_time).total_seconds() / 60  # 분 단위
        LOGGER.info(f"📅 기준 시간: {base_time.strftime('%Y-%m-%d %H:%M %Z')}")
        LOGGER.info(f"🎯 목표 예약 시간: {target_hour:02d}:{target_minute:02d} (실제 {actual_delay:.1f}분 후)")
        LOGGER.info(f"⏰ 최종 예약 시간: {target_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        # UI에 정확한 예약 시간 정보 표시
        current_time_str = current_time.strftime('%H:%M:%S')
        target_time_str = f"{target_hour:02d}:{target_minute:02d}"
        _report(progress_callback, f"예약 시간: {current_time_str} → {target_time_str} ({actual_delay:.0f}분 후)", False)
        
        # 시간 선택 드롭다운 (대기 시간 단축)
        try:
            # 방법 1: 직접 select 요소 찾기 (대기 시간 단축)
            hour_select = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".hour_option__J_heO"))
            )
            
            # Select 객체 생성 후 값 선택
            select_hour = Select(hour_select)
            select_hour.select_by_value(f"{target_hour:02d}")
            time.sleep(1)
            LOGGER.info(f"시간 설정 완료: {target_hour:02d}시")
            
        except Exception as e:
            LOGGER.warning(f"Select 방법 실패, ActionChains 시도: {e}")
            # 방법 2: ActionChains로 드롭다운 조작
            try:
                hour_select = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".hour_option__J_heO"))
                )
                hour_select.click()
                time.sleep(0.5)
                
                # 원하는 시간 옵션 클릭
                hour_option = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, f"//option[@value='{target_hour:02d}']"))
                )
                hour_option.click()
                time.sleep(1)
                LOGGER.info(f"시간 설정 완료 (ActionChains): {target_hour:02d}시")
                
            except Exception as e2:
                LOGGER.warning(f"시간 설정 완전 실패: {e2}")
        
        # 분 설정 (정확한 값으로 수동 입력)
        try:
            # 방법 1: JavaScript로 직접 값 설정 (가장 정확함)
            minute_select = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".minute_option__Vb3xB"))
            )
            
            # JavaScript로 직접 분 값 설정
            driver.execute_script(f"""
                var minuteSelect = document.querySelector('.minute_option__Vb3xB');
                if (minuteSelect) {{
                    // 기존 옵션 중에 해당 값이 있는지 확인
                    var targetOption = minuteSelect.querySelector('option[value="{target_minute:02d}"]');
                    if (targetOption) {{
                        minuteSelect.value = '{target_minute:02d}';
                    }} else {{
                        // 해당 옵션이 없으면 새로 생성
                        var newOption = document.createElement('option');
                        newOption.value = '{target_minute:02d}';
                        newOption.text = '{target_minute:02d}';
                        minuteSelect.appendChild(newOption);
                        minuteSelect.value = '{target_minute:02d}';
                    }}
                    // change 이벤트 발생시켜 UI 업데이트
                    minuteSelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            """)
            time.sleep(1)
            LOGGER.info(f"분 설정 완료 (정확한 값): {target_minute:02d}분")
            
        except Exception as e:
            LOGGER.warning(f"JavaScript 분 설정 실패, 대안 방법 시도: {e}")
            # 방법 2: 기존 드롭다운 방식 (10분 단위로 근사치)
            try:
                minute_select = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".minute_option__Vb3xB"))
                )
                
                # 10분 단위로 가장 가까운 값 선택
                closest_minute = (target_minute // 10) * 10
                if target_minute % 10 >= 5:  # 5분 이상이면 다음 10분 단위로
                    closest_minute = min(50, closest_minute + 10)
                
                select_minute = Select(minute_select)
                select_minute.select_by_value(f"{closest_minute:02d}")
                time.sleep(1)
                LOGGER.info(f"분 설정 완료 (근사치): {closest_minute:02d}분 (목표: {target_minute:02d}분)")
                
            except Exception as e2:
                LOGGER.warning(f"분 설정 완전 실패: {e2}")
        
        # 최종 완료 메시지 (실제 지연 시간 표시)
        try:
            final_delay = (target_time - datetime.now()).total_seconds() / 60
            LOGGER.info(f"✅ 한국시간 예약 설정 완료: {target_hour:02d}:{target_minute:02d} (현재로부터 약 {final_delay:.0f}분 후)")
            _report(progress_callback, f"예약 설정 완료: {target_hour:02d}:{target_minute:02d} (약 {final_delay:.0f}분 후)", True)
        except NameError:
            # target_time이 정의되지 않은 경우 (에러 발생 시)
            LOGGER.info(f"✅ 한국시간 예약 설정 완료: {target_hour:02d}:{target_minute:02d}")
            _report(progress_callback, f"예약 설정 완료: {target_hour:02d}:{target_minute:02d}", True)
        
    except Exception as e:
        LOGGER.warning(f"예약 시간 설정 실패: {e}")
        # 예약 시간 설정이 실패해도 즉시 발행으로 진행


def _click_final_publish_button(driver: webdriver.Chrome) -> None:
    """발행 팝업의 최종 발행 버튼을 클릭합니다."""
    max_attempts = 3
    
    for attempt in range(max_attempts):
        try:
            LOGGER.info(f"최종 발행 버튼 찾기 시도 {attempt + 1}/{max_attempts}")
            
            # 올바른 발행 버튼 찾기: 가장 신뢰할 수 있는 선택자 우선
            publish_selectors = [
                # 최고 우선순위: data-testid 속성 (가장 정확하고 안정적)
                "[data-testid='seOnePublishBtn']",
                
                # 2순위: confirm_btn 클래스와 아이콘 조합
                "button.confirm_btn__WEaBq[data-click-area*='publish']",
                
                # 3순위: confirm_btn 클래스
                ".confirm_btn__WEaBq",
                
                # 4순위: XPath로 버튼과 span 조합 찾기
                "//button[contains(@class,'confirm_btn')]//span[contains(@class,'text__sraQE') and text()='발행']",
                
                # 5순위: span 요소 직접 찾기 (최후의 수단)
                "//span[contains(@class,'text__sraQE') and text()='발행']",
            ]
            
            publish_btn = None
            used_selector = None
            
            for selector in publish_selectors:
                try:
                    if selector.startswith("//"):
                        # XPath 선택자 (대기 시간 단축)
                        publish_btn = WebDriverWait(driver, 2).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                    else:
                        # CSS 선택자
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements:
                            if element.is_displayed() and element.is_enabled():
                                # data-testid나 confirm_btn 클래스는 텍스트 검증 없이 사용 (가장 정확)
                                if selector.startswith("[data-testid") or selector.startswith(".confirm_btn"):
                                    publish_btn = element
                                    break
                                # text__sraQE인 경우만 텍스트 검증
                                elif selector == ".text__sraQE":
                                    if "발행" in element.text and len(element.text.strip()) <= 10:  # 짧은 텍스트만
                                        publish_btn = element
                                        break
                        
                        if not publish_btn:
                            try:
                                publish_btn = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                                )
                                # 추가 검증: 찾은 버튼이 정말 발행 버튼인지 확인
                                if selector == ".text__sraQE" and publish_btn:
                                    if "발행" not in publish_btn.text or len(publish_btn.text.strip()) > 10:
                                        publish_btn = None  # 잘못된 버튼
                            except:
                                pass
                    
                    if publish_btn:
                        used_selector = selector
                        LOGGER.info(f"최종 발행 버튼 찾기 성공: {selector}")
                        break
                        
                except Exception:
                    continue
            
            if publish_btn:
                # 클릭 전 최종 검증
                try:
                    # data-testid나 confirm_btn 클래스인 경우 텍스트 검증 스킵 (신뢰할 수 있음)
                    if used_selector and (used_selector.startswith("[data-testid") or used_selector.startswith(".confirm_btn")):
                        LOGGER.info(f"신뢰할 수 있는 선택자 사용: {used_selector} - 텍스트 검증 스킵")
                    else:
                        # 다른 선택자인 경우에만 텍스트 검증
                        btn_text = publish_btn.text.strip()
                        
                        # span 내부의 "발행" 텍스트만 확인 (아이콘 제외)
                        try:
                            span_element = publish_btn.find_element(By.CSS_SELECTOR, "span.text__sraQE")
                            span_text = span_element.text.strip()
                            LOGGER.info(f"발행 버튼 span 텍스트 확인: '{span_text}'")
                            
                            if span_text != "발행":
                                LOGGER.warning(f"잘못된 span 텍스트: '{span_text}' - 다른 선택자 시도")
                                publish_btn = None
                        except:
                            # span 요소 없으면 전체 텍스트로 검증
                            LOGGER.info(f"발행 버튼 전체 텍스트 확인: '{btn_text}'")
                            
                            if "발행" not in btn_text:
                                LOGGER.warning(f"잘못된 버튼 감지: '{btn_text}' - 다른 선택자 시도")
                                publish_btn = None
                        
                except Exception:
                    LOGGER.warning("버튼 텍스트 확인 실패 - 그대로 진행")
                
                # 버튼이 유효한 경우에만 클릭
                if publish_btn:
                    # 버튼 클릭
                    try:
                        # 화면에 보이도록 스크롤
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", publish_btn)
                        time.sleep(0.5)
                        
                        # 방법 1: 일반 클릭
                        publish_btn.click()
                        LOGGER.info(f"최종 발행 버튼 클릭 완료 (선택자: {used_selector})")
                        return  # 성공 시 함수 종료
                        
                    except Exception as e:
                        LOGGER.warning(f"일반 클릭 실패: {e}")
                        # 방법 2: JavaScript 클릭 시도
                        try:
                            driver.execute_script("arguments[0].click();", publish_btn)
                            LOGGER.info(f"최종 발행 버튼 클릭 완료 (JS, 선택자: {used_selector})")
                            return  # 성공 시 함수 종료
                        except Exception as e2:
                            LOGGER.warning(f"JavaScript 클릭도 실패: {e2}")
                            
                            # 방법 3: ActionChains 클릭 시도
                            try:
                                from selenium.webdriver.common.action_chains import ActionChains
                                actions = ActionChains(driver)
                                actions.move_to_element(publish_btn).click().perform()
                                LOGGER.info(f"최종 발행 버튼 클릭 완료 (ActionChains, 선택자: {used_selector})")
                                return  # 성공 시 함수 종료
                            except Exception as e3:
                                LOGGER.warning(f"ActionChains 클릭도 실패: {e3}")
                        
                else:
                    LOGGER.warning("검증을 통과한 최종 발행 버튼을 찾을 수 없습니다.")
            else:
                LOGGER.warning("최종 발행 버튼을 찾을 수 없습니다.")
                
        except Exception as e:
            LOGGER.warning(f"발행 버튼 찾기 시도 {attempt + 1} 실패: {e}")
            
            # 디버깅을 위해 현재 페이지 상태 확인
            try:
                page_title = driver.title
                current_url = driver.current_url
                LOGGER.info(f"현재 페이지 정보 - 제목: {page_title}, URL: {current_url}")
                
                # 발행 관련 요소들 확인
                publish_elements = driver.find_elements(By.CSS_SELECTOR, "[data-testid], .confirm_btn, .text__sraQE")
                LOGGER.info(f"페이지에서 발견된 발행 관련 요소 수: {len(publish_elements)}")
                
                for i, element in enumerate(publish_elements[:5]):  # 최대 5개만 로그
                    try:
                        tag_name = element.tag_name
                        class_name = element.get_attribute("class") or "없음"
                        data_testid = element.get_attribute("data-testid") or "없음"
                        text = element.text.strip() if element.text else "없음"
                        LOGGER.info(f"요소 {i+1}: {tag_name}, class={class_name}, data-testid={data_testid}, text='{text}'")
                    except:
                        pass
            except Exception as debug_error:
                LOGGER.warning(f"페이지 상태 확인 실패: {debug_error}")
        
        # 발행 팝업이 닫혔을 가능성 - 다시 발행 버튼을 클릭해서 팝업 재오픈
        if attempt < max_attempts - 1:  # 마지막 시도가 아니면
            try:
                LOGGER.info("발행 팝업이 닫혔을 수 있습니다. 발행 버튼을 다시 클릭합니다.")
                
                # 첫 번째 발행 버튼 다시 클릭 (text__d09H7)
                first_publish_selectors = [
                    "//span[contains(@class,'text__d09H7') and text()='발행']",
                    "//button[contains(@class,'text__d09H7')]//span[text()='발행']",
                    ".text__d09H7"
                ]
                
                for selector in first_publish_selectors:
                    try:
                        if selector.startswith("//"):
                            first_btn = WebDriverWait(driver, 2).until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                        else:
                            elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            first_btn = None
                            for element in elements:
                                if element.is_displayed() and "발행" in element.text:
                                    first_btn = element
                                    break
                        
                        if first_btn:
                            first_btn.click()
                            LOGGER.info("첫 번째 발행 버튼 재클릭 완료")
                            time.sleep(1)  # 팝업이 열릴 시간 대기 (단축)
                            break
                            
                    except Exception:
                        continue
                        
            except Exception as e:
                LOGGER.warning(f"첫 번째 발행 버튼 재클릭 실패: {e}")
    
        # 모든 시도 실패
        LOGGER.error("❌ 최종 발행 버튼 클릭 완전 실패 - 모든 방법을 시도했지만 실패")
        raise Exception(f"최종 발행 버튼 클릭에 {max_attempts}번 모두 실패했습니다.")


def _get_published_blog_url(driver: webdriver.Chrome) -> Optional[str]:
    """발행 완료 후 블로그 게시물 URL을 가져옵니다."""
    try:
        LOGGER.info("발행된 게시물 URL 확인 중...")
        
        # 발행 완료 대기 (최대 10초)
        time.sleep(3)
        
        # 방법 1: 발행 완료 메시지에서 URL 찾기
        try:
            # 발행 완료 팝업이나 메시지에서 링크 찾기
            url_selectors = [
                # 발행 완료 팝업 내 링크
                "a[href*='blog.naver.com']",
                ".se-popup a[href*='naver.com']",
                ".publish-complete a[href*='blog']",
                # 일반적인 블로그 링크
                "a[href*='/PostView.naver']",
                "a[href*='/PostList.naver']",
            ]
            
            for selector in url_selectors:
                try:
                    links = driver.find_elements(By.CSS_SELECTOR, selector)
                    for link in links:
                        href = link.get_attribute("href")
                        if href and ("blog.naver.com" in href or "PostView.naver" in href):
                            LOGGER.info(f"발행 완료 팝업에서 URL 발견: {href}")
                            return href
                except Exception:
                    continue
                    
        except Exception as e:
            LOGGER.debug(f"발행 완료 팝업에서 URL 찾기 실패: {e}")
        
        # 방법 2: 현재 페이지 URL 확인
        try:
            current_url = driver.current_url
            LOGGER.info(f"현재 페이지 URL: {current_url}")
            
            # 글쓰기 페이지에서 발행 후 리다이렉트된 경우
            if "blog.naver.com" in current_url and ("PostView" in current_url or "logNo=" in current_url):
                LOGGER.info(f"현재 URL이 발행된 게시물 페이지: {current_url}")
                return current_url
                
        except Exception as e:
            LOGGER.debug(f"현재 URL 확인 실패: {e}")
        
        # 방법 3: JavaScript로 최신 포스트 URL 가져오기
        try:
            # 네이버 블로그 관리 페이지로 이동하여 최신 글 확인
            script = """
            // 최근 발행된 글 링크 찾기
            var links = document.querySelectorAll('a[href*="PostView"], a[href*="logNo="]');
            for (var i = 0; i < links.length; i++) {
                var href = links[i].href;
                if (href && href.includes('blog.naver.com')) {
                    return href;
                }
            }
            return null;
            """
            
            blog_url = driver.execute_script(script)
            if blog_url:
                LOGGER.info(f"JavaScript로 URL 발견: {blog_url}")
                return blog_url
                
        except Exception as e:
            LOGGER.debug(f"JavaScript로 URL 찾기 실패: {e}")
        
        # 방법 4: 페이지 소스에서 URL 패턴 찾기
        try:
            page_source = driver.page_source
            import re
            
            # 네이버 블로그 URL 패턴 찾기
            patterns = [
                r'https://blog\.naver\.com/[^/]+/\d+',
                r'https://[^"\']*PostView\.naver[^"\']*logNo=\d+[^"\']*',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, page_source)
                if matches:
                    blog_url = matches[0]
                    LOGGER.info(f"페이지 소스에서 URL 발견: {blog_url}")
                    return blog_url
                    
        except Exception as e:
            LOGGER.debug(f"페이지 소스에서 URL 찾기 실패: {e}")
        
        LOGGER.warning("모든 방법으로 블로그 URL을 찾지 못했습니다.")
        return None
        
    except Exception as e:
        LOGGER.error(f"블로그 URL 가져오기 실패: {e}")
        return None


def _handle_editor_entry_popup(
    driver: webdriver.Chrome,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
) -> None:
    try:
        cancel = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button.se-popup-button.se-popup-button-cancel")
            )
        )
    except TimeoutException:
        return

    cancel.click()
    _report(progress_callback, "이전 작성 팝업 닫기", True)
    time.sleep(0.5)


def _dismiss_resume_popup(
    driver: webdriver.Chrome,
    progress_callback: Optional[Callable[[str, bool], None]] = None,
) -> None:
    try:
        cancel = WebDriverWait(driver, 2).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button.se-popup-button.se-popup-button-cancel")
            )
        )
    except TimeoutException:
        return
    cancel.click()
    _report(progress_callback, "이전 작성 팝업 닫기", True)
    time.sleep(0.3)


def _focus_title_area(driver: webdriver.Chrome) -> WebElement:
    """순수 Selenium으로 제목 입력 영역을 찾아 포커스를 설정합니다."""
    _report(None, "Selenium으로 제목 입력 영역 찾는 중", False)
    
    # 이전 테스트에서 성공한 방법 우선 시도
    try:
        # 1단계: 제목 섹션 찾기 (.se-component.se-documentTitle이 성공함)
        title_section = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-documentTitle"))
        )
        LOGGER.info("제목 섹션 찾기 성공")
        
        # 2단계: 편집 가능한 요소 찾기 (.se-text-paragraph가 성공함)
        editable = title_section.find_element(By.CSS_SELECTOR, ".se-text-paragraph")
        
        if editable.is_enabled() and editable.is_displayed():
            # 3단계: Selenium으로 포커스 설정 (3초 안정화 대기)
            _countdown_sleep(3, "제목 입력 영역 안정화 대기", None, None)
            
            # 순수 Selenium 방법으로 포커스 설정
            WebDriverWait(driver, 8).until(EC.element_to_be_clickable(editable))
            
            # 여러 번 클릭으로 확실한 포커스 설정
            editable.click()
            time.sleep(0.5)
            editable.click()
            time.sleep(0.5)
            
            # ActionChains로 포커스 재확인
            ActionChains(driver).move_to_element(editable).click().perform()
            time.sleep(0.5)
            
            _report(None, "제목 입력 영역 찾기 및 포커스 설정 완료", True)
            return editable
            
    except (TimeoutException, NoSuchElementException):
        LOGGER.warning("기본 방법으로 제목 영역 찾기 실패, 대안 방법 시도")
    
    # 대안 방법들
    alternative_selectors = [
        (".se-documentTitle", ".se-text-paragraph"),
        (".se-component.se-documentTitle", "[contenteditable='true']")
    ]
    
    for section_selector, editable_selector in alternative_selectors:
        try:
            _report(None, f"대안 방법으로 제목 영역 찾는 중", False)
            title_section = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, section_selector))
            )
            editable = title_section.find_element(By.CSS_SELECTOR, editable_selector)
            
            if editable.is_enabled() and editable.is_displayed():
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(editable))
                
                # Selenium으로 포커스 설정
                editable.click()
                time.sleep(0.5)
                ActionChains(driver).move_to_element(editable).click().perform()
                time.sleep(0.5)
                
                _report(None, "제목 입력 영역 찾기 완료 (대안 방법)", True)
                return editable
                
        except (TimeoutException, NoSuchElementException):
            continue
    
    _report(None, "제목 입력 영역을 찾을 수 없습니다", False)
    raise NoSuchElementException("제목 입력 영역을 찾을 수 없습니다")


def _focus_body_area(driver: webdriver.Chrome) -> WebElement:
    """순수 Selenium으로 본문 입력 영역을 찾아 포커스를 설정합니다."""
    _report(None, "Selenium으로 본문 입력 영역 찾는 중", False)
    
    # 이전 테스트에서 성공한 방법 우선 시도
    try:
        # 1단계: 본문 섹션 찾기 (.se-component.se-text가 성공함)
        body_section = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-text"))
        )
        LOGGER.info("본문 섹션 찾기 성공")
        
        # 2단계: 편집 가능한 요소 찾기 (.se-text-paragraph가 성공함)
        editable = body_section.find_element(By.CSS_SELECTOR, ".se-text-paragraph")
        
        if editable.is_enabled() and editable.is_displayed():
            # 3단계: Selenium으로 포커스 설정 (3초 안정화 대기)
            _countdown_sleep(3, "본문 입력 영역 안정화 대기", None, None)
            
            # 순수 Selenium 방법으로 포커스 설정
            WebDriverWait(driver, 8).until(EC.element_to_be_clickable(editable))
            
            # 여러 번 클릭으로 확실한 포커스 설정
            editable.click()
            time.sleep(0.5)
            editable.click()
            time.sleep(0.5)
            
            # ActionChains로 포커스 재확인
            ActionChains(driver).move_to_element(editable).click().perform()
            time.sleep(0.5)
            
            _report(None, "본문 입력 영역 찾기 및 포커스 설정 완료", True)
            return editable
            
    except (TimeoutException, NoSuchElementException):
        LOGGER.warning("기본 방법으로 본문 영역 찾기 실패, 대안 방법 시도")
    
    # 대안 방법: 본문 영역 생성 시도 (Selenium ActionChains 사용)
    try:
        _report(None, "Selenium으로 본문 영역 생성 시도 중 (Enter 키)", False)
        ActionChains(driver).send_keys(Keys.ENTER).perform()
        time.sleep(2)
        
        # 생성된 본문 영역 찾기
        body_section = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-text"))
        )
        editable = body_section.find_element(By.CSS_SELECTOR, ".se-text-paragraph")
        
        if editable.is_enabled() and editable.is_displayed():
            WebDriverWait(driver, 5).until(EC.element_to_be_clickable(editable))
            
            # Selenium으로 포커스 설정
            editable.click()
            time.sleep(0.5)
            ActionChains(driver).move_to_element(editable).click().perform()
            time.sleep(0.5)
            
            _report(None, "본문 입력 영역 생성 및 찾기 완료", True)
            return editable
            
    except (TimeoutException, NoSuchElementException):
        pass
    
    # 최후 대안 방법들
    alternative_selectors = [
        (".se-section-text", ".se-text-paragraph"),
        (".se-component.se-text", "[contenteditable='true']")
    ]
    
    for section_selector, editable_selector in alternative_selectors:
        try:
            _report(None, f"최후 대안 방법으로 본문 영역 찾는 중", False)
            body_section = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, section_selector))
            )
            editable = body_section.find_element(By.CSS_SELECTOR, editable_selector)
            
            if editable.is_enabled() and editable.is_displayed():
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(editable))
                
                # Selenium으로 포커스 설정
                editable.click()
                time.sleep(0.5)
                ActionChains(driver).move_to_element(editable).click().perform()
                time.sleep(0.5)
                
                _report(None, "본문 입력 영역 찾기 완료 (최후 대안)", True)
                return editable
                
        except (TimeoutException, NoSuchElementException):
            continue
    
    _report(None, "본문 입력 영역을 찾을 수 없습니다", False)
    raise NoSuchElementException("본문 입력 영역을 찾을 수 없습니다")


def _type_text(
    target: WebElement,
    text: str,
    fast_mode: bool = False,
) -> None:
    """순수 Selenium ActionChains로 텍스트를 입력합니다."""
    LOGGER.info("ActionChains 텍스트 입력 시작 (길이: %d자)", len(text))
    driver = target._parent
    _report(None, f"ActionChains로 텍스트 입력 중 ({len(text)}자)", False)
    
    # 방법 1: ActionChains로 실제 타이핑 시뮬레이션 (가장 안정적)
    try:
        # 포커스 설정
        target.click()
        time.sleep(0.5)
        
        # ActionChains로 기존 내용 지우기
        actions = ActionChains(driver)
        actions.click(target)
        actions.pause(0.2)
        meta = _cmd_key()
        actions.key_down(meta).send_keys('a').key_up(meta)  # 전체 선택
        actions.pause(0.1)
        actions.send_keys(Keys.DELETE)  # 삭제
        actions.pause(0.3)
        
        # 텍스트 입력
        if fast_mode:
            actions.send_keys(text)
        else:
            # 줄 단위로 천천히 입력
            lines = text.split('\n')
            for i, line in enumerate(lines):
                if line.strip():
                    actions.send_keys(line)
                    actions.pause(0.1)
                
                if i < len(lines) - 1:
                    actions.key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT)
                    actions.pause(0.1)
        
        actions.perform()
        
        LOGGER.info("ActionChains 방법으로 텍스트 입력 완료")
        _report(None, f"텍스트 입력 완료 ({len(text)}자)", True)
        return
        
    except Exception as e:
        LOGGER.warning("ActionChains 방법 실패: %s", e)
    
    # 방법 2: 문자 단위로 천천히 입력 (백업 방법)
    try:
        _report(None, "문자 단위로 천천히 입력 시도", False)
        
        # 포커스 재설정
        target.click()
        time.sleep(0.5)
        
        # 기존 내용 지우기
        meta = _cmd_key()
        target.send_keys(meta + 'a')
        target.send_keys(Keys.DELETE)
        time.sleep(0.3)
        
        # 문자 하나씩 입력
        for char in text:
            if char == '\n':
                target.send_keys(Keys.SHIFT + Keys.ENTER)
            else:
                target.send_keys(char)
            time.sleep(0.02)  # 각 문자마다 20ms 대기
        
        LOGGER.info("문자 단위 입력 방법으로 텍스트 입력 완료")
        _report(None, f"텍스트 입력 완료 ({len(text)}자)", True)
        return
        
    except Exception as e:
        LOGGER.error("모든 Selenium 텍스트 입력 방법 실패: %s", e)
        _report(None, "텍스트 입력 실패", False)
        raise


def _extract_seo_keywords(text: str, max_keywords: int = 5) -> list[str]:
    """본문에서 SEO 최적화 키워드를 추출합니다."""
    # 한글, 영어, 숫자만 추출
    clean_text = re.sub(r'[^\w\s가-힣]', ' ', text)
    
    # 불용어 리스트 (SEO에 도움이 안 되는 단어들)
    stop_words = {
        '그리고', '하지만', '그러나', '또한', '이것', '그것', '저것', '이런', '그런', '저런',
        '입니다', '습니다', '합니다', '됩니다', '있습니다', '없습니다', '했습니다', '했다',
        '한다', '하다', '이다', '있다', '없다', '같다', '다른', '많다', '적다', '크다', '작다',
        '좋다', '나쁘다', '새로운', '오래된', '전체', '부분', '모든', '어떤', '일부', '대부분',
        '우리', '저희', '당신', '그들', '이들', '여러분', '모두', '각자', '서로', '함께',
        '위해', '위한', '통해', '으로', '로써', '에서', '에게', '에다', '부터', '까지',
        '아니다', '맞다', '틀리다', '분명', '확실', '아마', '정말', '진짜', '가짜', '대신',
        '보다', '더', '덜', '매우', '너무', '조금', '많이', '가장', '최고', '최대', '최소'
    }
    
    # 2-4글자 한글 단어 추출 (SEO에 효과적인 길이)
    korean_words = re.findall(r'[가-힣]{2,4}', clean_text)
    
    # 3-8글자 영어 단어 추출 
    english_words = re.findall(r'[a-zA-Z]{3,8}', clean_text)
    
    # 모든 단어를 소문자로 통일하고 불용어 제거
    all_words = []
    for word in korean_words + english_words:
        word_lower = word.lower()
        if word_lower not in stop_words and len(word.strip()) >= 2:
            all_words.append(word)
    
    # 빈도수 계산하여 상위 키워드 추출
    word_freq = Counter(all_words)
    
    # 빈도수가 높은 순서로 정렬하되, 최소 2번 이상 등장한 단어만
    frequent_words = [word for word, count in word_freq.items() if count >= 2]
    
    # 만약 빈도수 2 이상인 단어가 부족하면 1번 등장한 단어도 포함
    if len(frequent_words) < max_keywords:
        single_words = [word for word, count in word_freq.items() if count == 1]
        frequent_words.extend(single_words[:max_keywords - len(frequent_words)])
    
    # 최종 키워드 리스트 (빈도순 + 길이순)
    final_keywords = []
    for word, count in word_freq.most_common():
        if word in frequent_words and len(final_keywords) < max_keywords:
            final_keywords.append(word)
    
    LOGGER.info(f"SEO 키워드 추출 완료: {final_keywords}")
    return final_keywords


def _add_tags_to_body(body: str, tags: list[str]) -> str:
    """본문 끝에 SEO 태그들을 자연스럽게 추가합니다."""
    if not tags:
        return body
    
    # 본문이 비어있다면 태그만 반환
    if not body.strip():
        return f"#{' #'.join(tags)}"
    
    # 본문 끝에 태그 추가 (자연스러운 형태로)
    tag_section = f"\n\n🏷️ 관련 태그: #{' #'.join(tags)}"
    
    return body + tag_section


def _combine_body(content: BlogPostContent) -> str:
    """본문을 조합하고 SEO 키워드를 자동 추가합니다."""
    # 기본 본문 조합
    parts = [content.introduction, content.body, content.conclusion]
    combined_body = "\n\n".join(part for part in parts if part.strip())
    
    # 본문에서 SEO 키워드 추출
    if combined_body.strip():
        seo_keywords = _extract_seo_keywords(combined_body, max_keywords=5)
        
        # 기존 태그와 SEO 키워드 결합 (중복 제거)
        all_tags = list(content.tags)  # 기존 태그
        for keyword in seo_keywords:
            if keyword not in all_tags:
                all_tags.append(keyword)
        
        # 본문에 태그 추가
        combined_body = _add_tags_to_body(combined_body, all_tags)
        
        # 원본 content의 tags도 업데이트 (발행 팝업에서 사용)
        content.tags.extend([kw for kw in seo_keywords if kw not in content.tags])
        
        LOGGER.info(f"SEO 최적화 완료 - 기존 태그: {len(content.tags) - len(seo_keywords)}개, 추가된 SEO 키워드: {len(seo_keywords)}개")
    
    return combined_body

__all__ = [
    "NAVER_HOME_URL",
    "BlogPostContent",
    "create_chrome_driver",
    "publish_blog_post",
]
