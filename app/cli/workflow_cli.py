"""CLI 기반 워크플로우 실행."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.core.services.content_service import ContentGenerator, save_backup
from app.core.automation.naver_publisher import BlogPostContent, publish_blog_post
from app.core.constants import DEFAULT_MODEL


def run_cli(keyword: str, count: int) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler("naver_blog_automation.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )

    generator = ContentGenerator(model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    posts = generator.generate_posts(keyword, count)

    driver = None
    base_dir = Path.cwd()

    for idx, post in enumerate(posts, start=1):
        backup_path = save_backup(keyword, idx, post, base_dir)
        logging.info("백업 파일 저장: %s", backup_path)
        content = BlogPostContent(
            title=post.title,
            introduction=post.introduction,
            body=post.body,
            conclusion=post.conclusion,
            tags=post.tags,
        )
        driver = publish_blog_post(content, driver=driver, base_dir=base_dir)

    print("모든 발행을 완료했습니다. 브라우저 창을 직접 닫아주세요.")
    input("작업이 끝났습니다. 엔터 키를 누르면 종료합니다... ")


def main() -> int:
    keyword = input("키워드를 입력하세요: ").strip()
    while not keyword:
        keyword = input("키워드를 다시 입력하세요: ").strip()

    while True:
        raw = input("작성할 글 수 (1~5): ").strip()
        if not raw:
            count = 1
            break
        try:
            count = int(raw)
        except ValueError:
            print("숫자를 입력해주세요.")
            continue
        if 1 <= count <= 5:
            break
        print("1에서 5 사이로 입력해주세요.")

    run_cli(keyword, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
