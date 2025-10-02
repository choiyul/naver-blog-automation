"""계정 프로필 관리 로직."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Iterable

from app.core.models import AccountProfile


def _initialise_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        # 테이블 생성
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                password TEXT DEFAULT '',
                login_initialized INTEGER DEFAULT 0,
                login_failed INTEGER DEFAULT 0
            )
            """
        )
        
        # 기존 테이블에 login_failed 컬럼 추가 (마이그레이션)
        try:
            # 테이블 정보 확인
            cursor = conn.execute("PRAGMA table_info(accounts)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # login_failed 컬럼이 없으면 추가
            if 'login_failed' not in columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN login_failed INTEGER DEFAULT 0")
                LOGGER.info("데이터베이스 마이그레이션: login_failed 컬럼 추가 완료")
        except sqlite3.Error as e:
            LOGGER.debug(f"마이그레이션 확인 중 오류 (무시됨): {e}")
        
        conn.commit()


LOGGER = logging.getLogger(__name__)


def _load_legacy_accounts(file_path: Path, profiles_root: Path) -> dict[str, AccountProfile]:
    accounts: dict[str, AccountProfile] = {}

    if not file_path.exists():
        return accounts

    try:
        for line in file_path.read_text(encoding="utf-8").splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            profile_dir = profiles_root / sanitize_account_id(cleaned)
            accounts[cleaned] = AccountProfile(
                account_id=cleaned,
                profile_dir=profile_dir,
                password="",
                login_initialized=False,
                login_failed=False,
            )
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("계정 정보를 불러오지 못했습니다: %s", exc)
        return {}

    return accounts


def load_accounts(db_path: Path, profiles_root: Path) -> dict[str, AccountProfile]:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    accounts: dict[str, AccountProfile] = {}

    if not db_path.exists():
        # migrate legacy list if available
        legacy_file = db_path.with_suffix(".txt")
        legacy_accounts = _load_legacy_accounts(legacy_file, profiles_root)
        if legacy_accounts:
            save_accounts(db_path, legacy_accounts.values())
            legacy_file.unlink(missing_ok=True)
            return legacy_accounts
        _initialise_db(db_path)
        return {}

    _initialise_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT account_id, password, login_initialized, login_failed FROM accounts"
            ).fetchall()
        except sqlite3.Error as exc:  # pragma: no cover
            LOGGER.warning("계정 정보를 불러오지 못했습니다(데이터베이스): %s", exc)
            return {}

    for row in rows:
        account_id = row["account_id"]
        profile_dir = profiles_root / sanitize_account_id(account_id)
        
        # sqlite3.Row는 get 메서드가 없으므로 try-except로 처리
        try:
            login_failed_value = row["login_failed"]
        except (KeyError, IndexError):
            login_failed_value = 0
        
        accounts[account_id] = AccountProfile(
            account_id=account_id,
            profile_dir=profile_dir,
            password=row["password"] or "",
            login_initialized=bool(row["login_initialized"]),
            login_failed=bool(login_failed_value),
        )

    return accounts


def save_accounts(db_path: Path, accounts: Iterable[AccountProfile]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _initialise_db(db_path)
    
    # 계정 리스트를 미리 생성 (성능 최적화)
    account_data = [
        (account.account_id, account.password, int(account.login_initialized), int(account.login_failed))
        for account in accounts
    ]

    with sqlite3.connect(db_path) as conn:
        # 트랜잭션 시작
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute("DELETE FROM accounts")
            if account_data:  # 빈 리스트 체크
                conn.executemany(
                    """
                    INSERT INTO accounts (account_id, password, login_initialized, login_failed)
                    VALUES (?, ?, ?, ?)
                    """,
                    account_data,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def sanitize_account_id(account_id: str) -> str:
    # 정규식 대신 간단한 문자열 처리
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in account_id)


def ensure_profile_dir(profiles_root: Path, account_id: str, reset: bool = False) -> Path:
    safe_id = sanitize_account_id(account_id)
    profile_dir = profiles_root / safe_id
    if reset and profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_path = profile_dir / lock_name
        lock_path.unlink(missing_ok=True)
    return profile_dir


