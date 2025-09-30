"""애플리케이션 전역 로깅 설정."""

import logging
from pathlib import Path


def setup_logging() -> None:
    base_dir = Path(__file__).resolve().parents[2]
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            # 윈도우에서 콘솔이 뜨지 않도록 파일 로그만 유지
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
        ],
    )
