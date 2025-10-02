"""코어 데이터 모델 정의."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class WorkflowParams:
    keyword: str
    count: int
    use_ai: bool
    api_key: Optional[str]
    model: str
    manual_title: Optional[str]
    manual_body: Optional[str]
    manual_tags: Optional[str]
    manual_file_path: Optional[str]
    image_file_path: Optional[str]
    schedule_minutes: int
    naver_id: Optional[str]
    naver_profile_dir: Optional[str]



SettingsData = dict[str, Any]


