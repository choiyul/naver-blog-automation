"""AI 기반 블로그 콘텐츠 생성 서비스."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from dotenv import load_dotenv
from openai import OpenAI  # type: ignore[import]
from openai import RateLimitError as OpenAIRateLimitError
from openai import APIError as OpenAIAPIError

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TEMPERATURE = 0.7
MAX_POST_COUNT = 5
LOG_FILE_NAME = "naver_blog_automation.log"


@dataclass
class SectionSpec:
    name: str
    instruction_builder: Callable[[str, int], str]


@dataclass
class GeneratedPost:
    title: str
    introduction: str
    body: str
    conclusion: str
    tags: list[str]


SECTION_SPECS: tuple[SectionSpec, ...] = (
    SectionSpec("제목", lambda keyword, index: _build_title_prompt(keyword, index)),
    SectionSpec("서론", lambda keyword, index: _build_intro_prompt(keyword, index)),
    SectionSpec("본론", lambda keyword, index: _build_body_prompt(keyword, index)),
    SectionSpec("결론", lambda keyword, index: _build_conclusion_prompt(keyword, index)),
    SectionSpec("태그", lambda keyword, index: _build_tags_prompt(keyword, index)),
)


class ContentGenerator:
    """OpenAI를 사용해 블로그 콘텐츠를 생성하는 서비스."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        load_dotenv()
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        self.client = OpenAI(api_key=key)
        self.model = model or DEFAULT_MODEL

    def generate_posts(
        self,
        keyword: str,
        count: int,
        progress: Optional[Callable[[str, bool], None]] = None,
        stop_callback: Optional[Callable[[], bool]] = None,
    ) -> list[GeneratedPost]:
        posts: list[GeneratedPost] = []
        for index in range(1, count + 1):
            if stop_callback and stop_callback():
                raise RuntimeError("사용자에 의해 작업이 중단되었습니다.")
            parts: dict[str, str] = {}
            for spec in SECTION_SPECS:
                status = f"{index}번째 글 - {spec.name} 생성 중"
                if progress:
                    progress(status, False)
                prompt = spec.instruction_builder(keyword, index)
                raw = self._request_response(prompt)
                parts[spec.name] = _normalize_text(raw)
                if progress:
                    progress(f"{spec.name} 생성 완료", True)
            posts.append(self._build_post(keyword, parts))
        return posts

    def _request_response(self, prompt: str) -> str:
        try:
            response = self.client.responses.create(
                model=self.model,
                temperature=TEMPERATURE,
                input=prompt,
            )
        except OpenAIRateLimitError as exc:
            raise RuntimeError(
                "OpenAI 호출 한도를 초과했습니다. OpenAI 대시보드에서 사용량을 확인하거나 청구 정보를 업데이트한 뒤 다시 시도해주세요."
            ) from exc
        except OpenAIAPIError as exc:
            raise RuntimeError(f"OpenAI API 오류가 발생했습니다: {exc}") from exc
        return response.output_text.strip()

    def _build_post(self, keyword: str, parts: dict[str, str]) -> GeneratedPost:
        tags_line = parts["태그"].replace(",", " ")
        tags = self._normalize_tags(keyword, tags_line)
        return GeneratedPost(
            title=parts["제목"],
            introduction=parts["서론"],
            body=parts["본론"],
            conclusion=parts["결론"],
            tags=tags,
        )

    def _normalize_tags(self, keyword: str, tags_line: str) -> list[str]:
        tags: list[str] = []
        for token in tags_line.split():
            tag = token.strip()
            if not tag:
                continue
            if not tag.startswith("#"):
                tag = f"#{tag.lstrip('#')}"
            if tag not in tags:
                tags.append(tag)
        if len(tags) < 5:
            fallback = [_safe_tag(word) for word in re.findall(r"[가-힣A-Za-z0-9]{2,}", keyword)]
            for tag in fallback:
                if tag not in tags:
                    tags.append(tag)
                if len(tags) >= 10:
                    break
        while len(tags) < 5:
            tags.append(f"#블로그{len(tags) + 1}")
        return tags[:10]


def save_backup(keyword: str, index: int, post: GeneratedPost, base_dir: Optional[Path] = None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", keyword).strip("_") or "keyword"
    filename = f"blog_{safe}_{index}_{timestamp}.txt"
    folder = base_dir or Path.cwd()
    folder.mkdir(parents=True, exist_ok=True)
    payload = [
        f"키워드: {keyword}",
        f"글 번호: {index}",
        "",
        "[제목]",
        post.title,
        "",
        "[서론]",
        post.introduction,
        "",
        "[본론]",
        post.body,
        "",
        "[결론]",
        post.conclusion,
        "",
        "[태그]",
        " ".join(post.tags),
    ]
    path = folder / filename
    path.write_text("\n".join(payload) + "\n", encoding="utf-8")
    return path


def build_manual_tags(keyword: str, manual_tags: Optional[str], body_text: str) -> list[str]:
    tags: list[str] = []
    raw = manual_tags or ""
    for token in re.split(r"[\s,]+", raw.strip()):
        if not token:
            continue
        if not token.startswith("#"):
            token = f"#{token.lstrip('#')}"
        if token not in tags:
            tags.append(token)
    if len(tags) < 5:
        candidates = re.findall(r"[가-힣A-Za-z0-9]{2,}", f"{keyword} {body_text}")
        for word in candidates:
            tag = f"#{word}"
            if tag not in tags:
                tags.append(tag)
            if len(tags) >= 10:
                break
    while len(tags) < 5:
        tags.append(f"#블로그{len(tags) + 1}")
    return tags[:10]


def _normalize_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\r\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    return cleaned


def _safe_tag(token: str) -> str:
    token = token.strip()
    return f"#{token}" if token and not token.startswith("#") else token


def _build_title_prompt(keyword: str, index: int) -> str:
    return (
        "당신은 네이버 블로그 마케터입니다. "
        "키워드를 자연스럽게 녹여 독자가 클릭하고 싶어지는 1개의 제목을 작성하세요.\n"
        f"- 키워드: {keyword}\n"
        f"- 글 번호: {index}\n"
        "- 제목 길이는 35자 이내, 숫자나 호기심을 유발하는 문구를 활용하세요.\n"
        "- 말투는 친절한 존댓말로 작성합니다."
    )


def _build_intro_prompt(keyword: str, index: int) -> str:
    return (
        "네이버 블로그 글의 서론을 작성합니다.\n"
        f"- 글 번호: {index}\n"
        f"- 키워드: {keyword}\n"
        "- 첫 문장은 독자의 관심을 끄는 질문이나 observation으로 시작하세요.\n"
        "- 3~4문장 분량으로 문제 제기 → 해결 의지 순서로 구성합니다."
    )


def _build_body_prompt(keyword: str, index: int) -> str:
    return (
        "네이버 블로그 본문을 3개의 소제목과 각 소제목당 2~3문단으로 작성합니다.\n"
        f"- 글 번호: {index}\n"
        f"- 키워드: {keyword}\n"
        "- 소제목은 ## 형태의 마크다운으로 작성하고, 각 문단은 2~3문장으로 구성합니다.\n"
        "- 실제 사용 팁, 단계별 가이드, 예시 등을 포함해 실용적인 정보를 제공합니다."
    )


def _build_conclusion_prompt(keyword: str, index: int) -> str:
    return (
        "블로그 글의 결론을 작성합니다.\n"
        f"- 글 번호: {index}\n"
        f"- 키워드: {keyword}\n"
        "- 핵심 요약 2문장과 독자의 행동을 유도하는 마무리 1문장을 작성하세요."
    )


def _build_tags_prompt(keyword: str, index: int) -> str:
    return (
        "네이버 블로그용 해시태그를 최대 10개 작성합니다.\n"
        f"- 글 번호: {index}\n"
        f"- 키워드: {keyword}\n"
        "- 태그는 '#' 기호로 시작하고, 공백으로 구분합니다.\n"
        "- 키워드와 관련된 장소, 상황, 타겟 독자를 다양하게 포함하세요."
    )
