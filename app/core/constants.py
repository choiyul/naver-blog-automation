"""애플리케이션 전역에서 사용하는 상수 정의."""

from __future__ import annotations

import os


MAX_POST_COUNT = 5
GENERATION_STEPS_PER_POST = 5
AUTOMATION_STEPS_PER_POST = 8
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SCHEDULE_INTERVAL_HOURS = 3


