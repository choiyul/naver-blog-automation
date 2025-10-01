"""애플리케이션 전역 로깅 설정."""

import logging
from pathlib import Path


def setup_logging() -> None:
    base_dir = Path(__file__).resolve().parents[2]
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 파일 핸들러 - 버퍼링으로 I/O 최적화
    file_handler = logging.FileHandler(
        log_dir / "app.log", 
        encoding="utf-8",
        delay=True  # 첫 로그까지 파일 열기 지연
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler],
        force=True,
    )
