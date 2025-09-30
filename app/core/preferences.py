"""사용자 설정 저장/로드 헬퍼."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional


@dataclass
class UserSettings:
    keyword: str = ""
    use_ai: bool = False  # 기본값을 수동모드로 변경
    api_key: str = ""
    model: str = "gpt-4o-mini"
    manual_title: str = ""
    manual_tags: str = ""
    repeat_enabled: bool = False
    interval_minutes: int = 60
    image_file_path: str = ""
    schedule_minutes: int = 5


def load_settings(file_path: Path) -> UserSettings:
    if not file_path.exists():
        return UserSettings()

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return UserSettings()

    result = UserSettings()
    field_names = {field.name for field in fields(UserSettings)}
    for key, value in data.items():
        if key in field_names:
            setattr(result, key, value)
    return result


def save_settings(file_path: Path, settings: UserSettings) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


