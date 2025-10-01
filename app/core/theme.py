"""라이트/다크 테마 팔레트 정의."""

from __future__ import annotations


DARK_THEME: dict[str, object] = {
    "palette": {
        "window": "#10141f",
        "text": "#e5edff",
        "base": "#151b2c",
        "alternate": "#1d2336",
        "button": "#5285ff",
        "button_text": "#0b1120",
        "highlight": "#ffc857",
        "highlight_text": "#0b1120",
    },
    "card": "#161e30",
    "input": "#121a24",
    "border": "#25314d",
    "primary_text": "#e5edff",
    "secondary_text": "#94a3c4",
    "background": "#0c111c",
    "accent": "#ffc857",
    "accent_hover": "#ffd676",
    "accent_light": "rgba(255, 200, 87, 0.2)",
    "accent_dark": "#e6b34f",  # 추가
    "accent_darker": "#d4a03b",  # 추가
    "danger": "#ff6b6b",
    "warning": "#fbbf24",
    "info": "#38bdf8",
    "theme_icon": "#ffc857",
    "theme_icon_active": "#ffc857",
    "bg_alt": "#1d2336",
}


LIGHT_THEME: dict[str, object] = {
    "palette": {
        "window": "#f5f7fb",
        "text": "#0f172a",
        "base": "#ffffff",
        "alternate": "#f1f5f9",
        "button": "#03c75a",
        "button_text": "#0b1120",
        "highlight": "#38bdf8",
        "highlight_text": "#ffffff",
    },
    "card": "#ffffff",
    "input": "#f2f5fb",
    "border": "#e2e8f0",
    "primary_text": "#0f172a",
    "secondary_text": "#475569",
    "background": "#f8fafc",
    "accent": "#03c75a",
    "accent_hover": "#09d866",
    "accent_light": "rgba(3, 199, 90, 0.1)",
    "accent_dark": "#02b350",  # 추가
    "accent_darker": "#029f46",  # 추가
    "danger": "#ef4444",
    "warning": "#f59e0b",
    "info": "#0284c7",
    "theme_icon": "#0f172a",
    "theme_icon_active": "#ffffff",
    "bg_alt": "#f1f5f9",
}


