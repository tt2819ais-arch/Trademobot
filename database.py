"""
Модуль работы с базой данных SQLite.
Потокобезопасный доступ через threading.Lock.
"""

import sqlite3
import threading
import logging
from config import DB_PATH

logger = logging.getLogger(__name__)


class Database:
    """Обёртка над SQLite для хранения пользователей, дропов, фото."""

    def __init__(self, db_path: str = DB_PATH):
        # check_same_thread=False — разрешаем доступ из разных потоков
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # доступ к колонкам по имени
        self.lock = threading.Lock()
        self._create_tables()

    # ────────────────── Инициализация схемы ──────────────────

    def _create_tables(self):
        with self.lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT,
                    first_name  TEXT,
                    last_name   TEXT,
                    is_manager  INTEGER DEFAULT 0,
                    is_creator  INTEGER DEFAULT 0,
                    on_shift    INTEGER DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS drops (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    fio                 TEXT NOT NULL,
                    card_number         TEXT NOT NULL,
                    account_number      TEXT NOT NULL,
                    phone               TEXT NOT NULL,
                    drop_username       TEXT,
                    bank                TEXT NOT NULL,
                    chat_link           TEXT NOT NULL,
                    verified            TEXT NOT NULL,
                    creator_id          INTEGER NOT NULL,
                    group_message_id    INTEGER,
                    button_message_id   INTEGER,
                    is_taken            INTEGER DEFAULT 0,
                    taken_by_id         INTEGER,
                    taken_by_username   TEXT,
                    created_at          TEXT DEFAULT (datetime('now')),
                    taken_at            TEXT
                );

                CREATE TABLE IF NOT EXISTS drop_photos (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    drop_id  INTEGER NOT NULL,
                    file_id  TEXT    NOT NULL,
                    FOREIGN KEY (drop_id) REFERENCES drops(id)
                );
            """)
            self.conn.commit()

    # ────────────────── Пользователи ──────────────────

    def upsert_user(self, user_id: int, username: str = None,
                    first_name: str = None, last_name: str = None):
        """Создать пользователя или обновить его данные."""
        with self.lock:
            self.conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username   = COALESCE(excluded.username,   username),
                    first_name = COALESCE(excluded.first_name, first_name),
                    last_name  = COALESCE(excluded.last_name,  last_name)
            """, (user_id, username, first_name, last_name))
            self.conn.commit()

    def user_exists(self, user_id: int) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row is not None

    def get_user(self, user_id: int):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()

    def get_all_users(self) -> list:
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC"
            ).fetchall()

    def set_on_shift(self, user_id: int, on_shift: bool):
        with self.lock:
            self.conn.execute(
                "UPDATE users SET on_shift = ? WHERE user_id = ?",
                (1 if on_shift else 0, user_id))
            self.conn.commit()

    def get_on_shift_users(self) -> list:
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM users WHERE on_shift = 1"
            ).fetchall()

    def set_manager(self, user_id: int, value: bool):
        with self.lock:
            self.conn.execute(
                "UPDATE users SET is_manager = ? WHERE user_id = ?",
                (1 if value else 0, user_id))
            self.conn.commit()

    def set_creator(self, user_id: int, value: bool):
        with self.lock:
            self.conn.execute(
                "UPDATE users SET is_creator = ? WHERE user_id = ?",
                (1 if value else 0, user_id))
            self.conn.commit()

    def is_creator_in_db(self, user_id: int) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT is_creator FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row is not None and row["is_creator"] == 1

    # ────────────────── Дропы ──────────────────

    def create_drop(self, *, fio, card_number, account_number, phone,
                    drop_username, bank, chat_link, verified,
                    creator_id, photo_file_ids=None) -> int:
        """Создать запись о дропе. Вернуть его ID."""
        with self.lock:
            cur = self.conn.execute("""
                INSERT INTO drops
                    (fio, card_number, account_number, phone,
                     drop_username, bank, chat_link, verified, creator_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (fio, card_number, account_number, phone,
                  drop_username, bank, chat_link, verified, creator_id))
            drop_id = cur.lastrowid

            if photo_file_ids:
                for fid in photo_file_ids:
                    self.conn.execute(
                        "INSERT INTO drop_photos (drop_id, file_id) VALUES (?, ?)",
                        (drop_id, fid))
            self.conn.commit()
            return drop_id

    def set_drop_message_ids(self, drop_id: int,
                             group_msg_id: int, button_msg_id: int = None):
        with self.lock:
            self.conn.execute("""
                UPDATE drops
                SET group_message_id = ?, button_message_id = ?
                WHERE id = ?
            """, (group_msg_id, button_msg_id, drop_id))
            self.conn.commit()

    def take_drop(self, drop_id: int, user_id: int, username: str) -> bool:
        """
        Попытаться взять дроп.
        Возвращает True при успехе, False если уже взят.
        """
        with self.lock:
            row = self.conn.execute(
                "SELECT is_taken FROM drops WHERE id = ?", (drop_id,)
            ).fetchone()
            if row is None or row["is_taken"]:
                return False
            self.conn.execute("""
                UPDATE drops
                SET is_taken = 1, taken_by_id = ?,
                    taken_by_username = ?, taken_at = datetime('now')
                WHERE id = ?
            """, (user_id, username, drop_id))
            self.conn.commit()
            return True

    def get_drop(self, drop_id: int):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM drops WHERE id = ?", (drop_id,)
            ).fetchone()

    def get_drop_photos(self, drop_id: int) -> list[str]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT file_id FROM drop_photos WHERE drop_id = ?", (drop_id,)
            ).fetchall()
            return [r["file_id"] for r in rows]

    def get_active_drops(self) -> list:
        """Все незакрытые дропы (для восстановления после рестарта)."""
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM drops WHERE is_taken = 0"
            ).fetchall()

    def get_taken_drops(self, limit: int = 20) -> list:
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM drops WHERE is_taken = 1 "
                "ORDER BY taken_at DESC LIMIT ?", (limit,)
            ).fetchall()

    def get_stats(self) -> dict:
        with self.lock:
            total = self.conn.execute(
                "SELECT COUNT(*) AS c FROM drops"
            ).fetchone()["c"]
            taken = self.conn.execute(
                "SELECT COUNT(*) AS c FROM drops WHERE is_taken = 1"
            ).fetchone()["c"]
            active = self.conn.execute(
                "SELECT COUNT(*) AS c FROM drops WHERE is_taken = 0"
            ).fetchone()["c"]
            top = self.conn.execute("""
                SELECT taken_by_username, COUNT(*) AS cnt
                FROM drops
                WHERE is_taken = 1 AND taken_by_username IS NOT NULL
                GROUP BY taken_by_id
                ORDER BY cnt DESC
                LIMIT 5
            """).fetchall()
            return {"total": total, "taken": taken,
                    "active": active, "top_takers": top}
