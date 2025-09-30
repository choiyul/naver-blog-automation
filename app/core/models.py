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

@dataclass
class AccountProfile:
    """네이버 계정과 연결된 브라우저 프로필 및 자격 증명 정보."""

    account_id: str
    profile_dir: Path
    password: str = ""
    login_initialized: bool = False


SettingsData = dict[str, Any]


