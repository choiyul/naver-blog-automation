"""워크플로우 실행 스레드 및 이벤트 정의."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5 import QtCore

from app.core.services.content_service import ContentGenerator, GeneratedPost, save_backup
from app.core.automation.naver_publisher import BlogPostContent, publish_blog_post, AccountProtectionException
from .constants import GENERATION_STEPS_PER_POST
from .models import WorkflowParams


LOGGER = logging.getLogger(__name__)


class WorkflowWorker(QtCore.QThread):
    finished_signal = QtCore.pyqtSignal(object)
    error_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(str, bool)
    percent_signal = QtCore.pyqtSignal(int)
    status_signal = QtCore.pyqtSignal(str)
    post_saved_signal = QtCore.pyqtSignal(str, str)

    def __init__(
        self,
        params: WorkflowParams,
        driver: Optional[object],
        base_dir,
        automation_steps_per_post: int,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.params = params
        self.driver = driver
        self.base_dir = base_dir
        self.auto_steps_per_post = automation_steps_per_post
        self._stop_requested = False
        self._total_steps = max(
            (params.count * GENERATION_STEPS_PER_POST if params.use_ai else 0)
            + params.count * automation_steps_per_post,
            1,
        )
        self._completed_posts = 0
        self._current_post_steps = 0

    def request_stop(self) -> None:
        self._stop_requested = True
        try:
            # 드라이버 쪽 대기 루프를 깨우기 위해 가벼운 no-op 실행
            if self.driver:
                try:
                    self.driver.execute_script("void(0)")
                except Exception:
                    pass
        except Exception:
            pass

    def _should_stop(self) -> bool:
        return self._stop_requested

    def _emit_progress(self, message: str, completed: bool) -> None:
        self.progress_signal.emit(message, completed)
        if completed:
            self._current_post_steps = min(self._current_post_steps + 1, self.auto_steps_per_post)
            total = self._completed_posts * self.auto_steps_per_post + self._current_post_steps
            percent = int(total / self._total_steps * 100)
            self.percent_signal.emit(percent)

    def _emit_status(self, message: str) -> None:
        self.status_signal.emit(message)

    def run(self) -> None:  # noqa: C901
        self.percent_signal.emit(0)
        self.status_signal.emit("준비 중")

        posts: list[GeneratedPost] = []

        if self.params.use_ai:
            try:
                generator = ContentGenerator(self.params.api_key, self.params.model)
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("OpenAI 클라이언트 초기화 실패: %s", exc)
                self.error_signal.emit(str(exc))
                return

            try:
                posts = generator.generate_posts(
                    self.params.keyword,
                    self.params.count,
                    progress=self._emit_progress,
                    stop_callback=self._should_stop,
                )
                for idx, post in enumerate(posts, start=1):
                    path = save_backup(self.params.keyword, idx, post, self.base_dir)
                    self.post_saved_signal.emit(post.title, str(path))
                    self._emit_status(f"{idx}번째 글 생성 완료")
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("글 생성 중 오류 발생: %s", exc)
                self.error_signal.emit(str(exc))
                return
        else:
            manual_body = (self.params.manual_body or "").strip()
            if not manual_body:
                self.error_signal.emit("본문 파일이 비어 있습니다.")
                return
            manual_title = (self.params.manual_title or self.params.keyword or "수동 작성 글").strip()
            for idx in range(1, self.params.count + 1):
                if self._should_stop():
                    self.error_signal.emit("사용자 중지")
                    return
                self._emit_status(f"{idx}번째 글 준비 중")
                display_title = manual_title if self.params.count == 1 else f"{manual_title} ({idx})"
                self._emit_progress(f"{idx}번째 글 콘텐츠 준비", True)
                post = GeneratedPost(
                    title=display_title,
                    introduction="",
                    body=manual_body,
                    conclusion="",
                    tags=[],
                )
                posts.append(post)
                self.post_saved_signal.emit(display_title, "수동 작성")
                self._emit_status(f"{idx}번째 글 준비 완료")

        driver = self.driver
        try:
            for idx, post in enumerate(posts, start=1):
                if self._should_stop():
                    raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")

                self._current_post_steps = 0
                self._emit_status(f"{idx}번째 글 발행 준비")
                automation_content = BlogPostContent(
                    title=post.title,
                    introduction=post.introduction,
                    body=post.body,
                    conclusion=post.conclusion,
                    tags=post.tags,
                )
                driver, blog_url = publish_blog_post(
                    automation_content,
                    driver=driver,
                    base_dir=self.base_dir,
                    progress_callback=self._emit_progress,
                    stop_callback=self._should_stop,
                    image_file_path=self.params.image_file_path,
                    fast_mode=not self.params.use_ai,
                    schedule_minutes=self.params.schedule_minutes,
                    post_index=idx,
                    account_id=self.params.naver_id,
                    profile_dir=self.params.naver_profile_dir,
                )
                self._emit_status(f"{idx}번째 글 발행 완료")
                self._completed_posts = idx
                
                # 블로그 URL이 있으면 UI에 전달 (아이디 - 생성여부 - 제목 형식)
                account_id = self.params.naver_id or "알 수 없음"
                if blog_url:
                    display_text = f"{account_id} - ✅ 성공 - {post.title}"
                    self.post_saved_signal.emit(display_text, blog_url)
                    LOGGER.info(f"게시물 '{post.title}' URL 전달 완료: {blog_url}")
                else:
                    display_text = f"{account_id} - ❌ 실패 - {post.title}"
                    self.post_saved_signal.emit(display_text, "")
                    LOGGER.warning(f"게시물 '{post.title}' URL을 가져오지 못했습니다.")
        except AccountProtectionException as exc:
            # 보호조치는 상위로 전파하여 다음 계정으로 넘어가도록 함
            LOGGER.warning("계정 보호조치 감지: %s", exc)
            raise
        except RuntimeError as exc:
            LOGGER.warning("작업 중단: %s", exc)
            self.error_signal.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("발행 중 오류 발생: %s", exc)
            self.error_signal.emit(str(exc))
            return

        self._emit_status("모든 작업 완료")
        self.finished_signal.emit(driver)


