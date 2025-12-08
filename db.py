# db.py  ─ ARPG 봇용 SQLite 래퍼

import aiosqlite
from pathlib import Path

# DB 경로
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "arpg.db"


async def init_db():
    """모든 테이블 생성 + 컬럼/테이블 없으면 추가."""
    async with aiosqlite.connect(DB_PATH) as db:
        # -------------------------------------------------
        # 길드별 설정
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id            INTEGER PRIMARY KEY,
                attend_channel_id   INTEGER,
                shop_channel_id     INTEGER,
                fishing_channel_id  INTEGER,
                attend_currency_id  INTEGER,
                main_currency_id    INTEGER
            )
            """
        )
        # 기존 DB에 fishing_channel_id 없으면 추가
        try:
            cursor = await db.execute("PRAGMA table_info(guild_settings)")
            cols = await cursor.fetchall()
            await cursor.close()
            col_names = {c[1] for c in cols}
            if "fishing_channel_id" not in col_names:
                await db.execute(
                    "ALTER TABLE guild_settings ADD COLUMN fishing_channel_id INTEGER"
                )
        except Exception:
            pass

        # -------------------------------------------------
        # 재화
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS currencies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                code        TEXT NOT NULL,
                is_main     INTEGER NOT NULL DEFAULT 0,
                is_active   INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        # -------------------------------------------------
        # 유저
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id             INTEGER NOT NULL,
                user_id              INTEGER NOT NULL,
                last_attend_date     TEXT
            )
            """
        )

        # ✅ 새로 추가: 보너스 출석 날짜 컬럼
        # 이미 컬럼이 있는 상태에서 다시 실행되면 에러가 나기 때문에
        # try/except 로 한 번만 추가되도록 감싸준다.
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN last_bonus_attend_date TEXT"
            )
        except Exception:
            # 이미 컬럼이 있으면 여기로 들어오므로 그냥 무시
            pass

        # -------------------------------------------------
        # 잔액
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS balances (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                currency_id INTEGER NOT NULL,
                amount      INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # -------------------------------------------------
        # 상점 아이템 (stock + is_shop 포함)
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                price       INTEGER NOT NULL,
                description TEXT,
                currency_id INTEGER NOT NULL,
                stock       INTEGER,
                is_shop     INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        # 기존 DB에 stock / is_shop 없으면 추가
        try:
            cursor = await db.execute("PRAGMA table_info(items)")
            cols = await cursor.fetchall()
            await cursor.close()
            col_names = {c[1] for c in cols}
            if "stock" not in col_names:
                await db.execute("ALTER TABLE items ADD COLUMN stock INTEGER")
            if "is_shop" not in col_names:
                await db.execute(
                    "ALTER TABLE items ADD COLUMN is_shop INTEGER NOT NULL DEFAULT 1"
                )
        except Exception:
            pass

        # -------------------------------------------------
        # 인벤토리
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS inventories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                item_id     INTEGER NOT NULL,
                quantity    INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # -------------------------------------------------
        # 판매 상점 테이블
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sell_shop_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                item_id     INTEGER NOT NULL,
                price       INTEGER NOT NULL,
                currency_id INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sell_shop_unique
            ON sell_shop_items (guild_id, item_id)
            """
        )
        # -------------------------------------------------
        # 낚시 일일 제한 테이블 (유저당 KST 기준 하루 3회)
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS fishing_limits (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,   -- users.id (내부 유저 ID)
                date        TEXT NOT NULL,      -- 'YYYY-MM-DD' (KST 기준)
                count       INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fishing_limits_unique
            ON fishing_limits (guild_id, user_id, date)
            """
        )

        # -------------------------------------------------
        # 낚시 확률 테이블
        # chance 는 REAL 로, 소수 확률 허용
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS fishing_loot (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                item_id     INTEGER NOT NULL,
                chance      REAL NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fishing_loot_unique
            ON fishing_loot (guild_id, item_id)
            """
        )

        # -------------------------------------------------
        # 펫 도감 테이블
        # -------------------------------------------------
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS pets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                description TEXT,
                UNIQUE(guild_id, name)
            )
            """
        )
        await db.commit()


# ---------------------------------------------------------
# guild_settings helpers
# ---------------------------------------------------------

async def get_or_create_guild_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return dict(row)

        # 없으면 기본 설정 생성
        await db.execute(
            """
            INSERT INTO guild_settings (
                guild_id,
                attend_channel_id,
                shop_channel_id,
                fishing_channel_id,
                attend_currency_id,
                main_currency_id
            )
            VALUES (?, NULL, NULL, NULL, NULL, NULL)
            """,
            (guild_id,),
        )
        await db.commit()

        # 기본 메인 재화 coin 생성
        cursor = await db.execute(
            """
            INSERT INTO currencies (guild_id, name, code, is_main, is_active)
            VALUES (?, '코인', 'coin', 1, 1)
            """,
            (guild_id,),
        )
        main_currency_id = cursor.lastrowid

        # guild_settings에 기본 메인/출석 재화 설정
        await db.execute(
            """
            UPDATE guild_settings
            SET attend_currency_id = ?, main_currency_id = ?
            WHERE guild_id = ?
            """,
            (main_currency_id, main_currency_id, guild_id),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row)


async def set_attend_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, attend_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET attend_channel_id = excluded.attend_channel_id
            """,
            (guild_id, channel_id),
        )
        await db.commit()


async def set_shop_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, shop_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET shop_channel_id = excluded.shop_channel_id
            """,
            (guild_id, channel_id),
        )
        await db.commit()


async def set_fishing_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, fishing_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET fishing_channel_id = excluded.fishing_channel_id
            """,
            (guild_id, channel_id),
        )
        await db.commit()


async def set_attend_currency(guild_id: int, currency_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE guild_settings
            SET attend_currency_id = ?
            WHERE guild_id = ?
            """,
            (currency_id, guild_id),
        )
        await db.commit()


async def set_main_currency(guild_id: int, currency_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # 모든 재화의 is_main = 0
        await db.execute(
            "UPDATE currencies SET is_main = 0 WHERE guild_id = ?",
            (guild_id,),
        )
        # 해당 재화만 is_main = 1
        await db.execute(
            "UPDATE currencies SET is_main = 1 WHERE id = ?",
            (currency_id,),
        )
        # guild_settings 업데이트
        await db.execute(
            "UPDATE guild_settings SET main_currency_id = ? WHERE guild_id = ?",
            (currency_id, guild_id),
        )
        await db.commit()


# ---------------------------------------------------------
# currencies
# ---------------------------------------------------------

async def add_currency(
    guild_id: int,
    name: str,
    code: str,
    is_main: bool = False,
    is_active: bool = True,
):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO currencies (guild_id, name, code, is_main, is_active)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, name, code, int(is_main), int(is_active)),
        )
        await db.commit()

        cur_id = cursor.lastrowid
        cursor = await db.execute(
            "SELECT * FROM currencies WHERE id = ?",
            (cur_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row)


async def list_currencies(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM currencies WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(r) for r in rows]


async def get_currency_by_code(guild_id: int, code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM currencies
            WHERE guild_id = ? AND LOWER(code) = LOWER(?)
            """,
            (guild_id, code),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None


# ---------------------------------------------------------
# users / balances
# ---------------------------------------------------------

async def get_or_create_user(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return dict(row)

        await db.execute(
            "INSERT INTO users (guild_id, user_id, last_attend_date) VALUES (?, ?, NULL)",
            (guild_id, user_id),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row)


async def update_user_last_attend(db_user_id: int, date_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_attend_date = ? WHERE id = ?",
            (date_str, db_user_id),
        )
        await db.commit()


async def get_balance(db_user_id: int, currency_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT amount FROM balances
            WHERE user_id = ? AND currency_id = ?
            """,
            (db_user_id, currency_id),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return 0
        return row[0]


async def change_balance(db_user_id: int, currency_id: int, diff: int) -> int:
    """diff 만큼 증감 후 최종 amount 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, amount FROM balances
            WHERE user_id = ? AND currency_id = ?
            """,
            (db_user_id, currency_id),
        )
        row = await cursor.fetchone()

        if row:
            bal_id, amount = row
            new_amount = amount + diff
            if new_amount < 0:
                new_amount = 0
            await db.execute(
                "UPDATE balances SET amount = ? WHERE id = ?",
                (new_amount, bal_id),
            )
        else:
            new_amount = max(diff, 0)
            await db.execute(
                "INSERT INTO balances (user_id, currency_id, amount) VALUES (?, ?, ?)",
                (db_user_id, currency_id, new_amount),
            )
        await db.commit()
        await cursor.close()
        return new_amount


# ---------------------------------------------------------
# items / inventories  (stock + is_shop)
# ---------------------------------------------------------

async def add_item(
    guild_id: int,
    name: str,
    price: int,
    description: str,
    currency_id: int,
    stock: int | None,
    is_shop: int = 1,
):
    """
    is_shop = 1 : 상점에 표시되는 아이템
    is_shop = 0 : 상점에 표시되지 않는 아이템(낚시 전용 등)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO items (guild_id, name, price, description, currency_id, stock, is_shop)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, name, price, description, currency_id, stock, is_shop),
        )
        await db.commit()
        item_id = cursor.lastrowid
        await cursor.close()
        return item_id


async def delete_item(guild_id: int, item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM items WHERE guild_id = ? AND id = ?",
            (guild_id, item_id),
        )
        await db.commit()


async def get_items(guild_id: int):
    """
    상점에서 쓸 아이템 목록.
    is_shop = 1 인 아이템만 반환 (이전에 만든 DB는 NULL일 수도 있어서 NULL도 포함)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT i.*, c.name AS currency_name, c.code AS currency_code
            FROM items i
            JOIN currencies c ON i.currency_id = c.id
            WHERE i.guild_id = ?
              AND (i.is_shop = 1 OR i.is_shop IS NULL)
            ORDER BY i.id ASC
            """,
            (guild_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(r) for r in rows]


async def get_item_by_id(guild_id: int, item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT i.*, c.name AS currency_name, c.code AS currency_code
            FROM items i
            JOIN currencies c ON i.currency_id = c.id
            WHERE i.guild_id = ? AND i.id = ?
            """,
            (guild_id, item_id),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None


async def get_item_by_name(guild_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT i.*, c.name AS currency_name, c.code AS currency_code
            FROM items i
            JOIN currencies c ON i.currency_id = c.id
            WHERE i.guild_id = ? AND i.name = ?
            """,
            (guild_id, name),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None


async def get_inventory(db_user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT inv.quantity,
                   it.name,
                   it.description,
                   it.id AS item_id
            FROM inventories inv
            JOIN items it ON inv.item_id = it.id
            WHERE inv.user_id = ?
            ORDER BY it.id ASC
            """,
            (db_user_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(r) for r in rows]


# ---------------------------------------------------------
# 판매 상점(sell_shop_items) 헬퍼
# ---------------------------------------------------------

async def upsert_sell_item(
    guild_id: int,
    item_id: int,
    price: int,
    currency_id: int,
):
    """판매 상점에 아이템 등록/수정."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sell_shop_items (guild_id, item_id, price, currency_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, item_id)
            DO UPDATE SET price = excluded.price,
                          currency_id = excluded.currency_id
            """,
            (guild_id, item_id, price, currency_id),
        )
        await db.commit()


async def get_sell_items(guild_id: int):
    """판매 상점 전체 목록."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.item_id,
                   s.price,
                   s.currency_id,
                   i.name AS item_name,
                   i.description AS item_description,
                   c.name AS currency_name,
                   c.code AS currency_code
            FROM sell_shop_items s
            JOIN items i ON s.item_id = i.id
            JOIN currencies c ON s.currency_id = c.id
            WHERE s.guild_id = ?
            ORDER BY i.id ASC
            """,
            (guild_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(r) for r in rows]


async def get_sell_item_by_name(guild_id: int, item_name: str):
    """판매 상점에서 아이템 이름으로 1개 찾기."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.*,
                   i.name AS item_name,
                   i.description AS item_description,
                   c.name AS currency_name,
                   c.code AS currency_code
            FROM sell_shop_items s
            JOIN items i ON s.item_id = i.id
            JOIN currencies c ON s.currency_id = c.id
            WHERE s.guild_id = ? AND i.name = ?
            LIMIT 1
            """,
            (guild_id, item_name),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None

async def update_user_last_bonus_attend(user_pk: int, date_str: str):
    """보너스 출석을 한 날짜를 기록하는 함수"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_bonus_attend_date = ? WHERE id = ?",
            (date_str, user_pk),
        )
        await db.commit()

# ---------------------------------------------------------
# 낚시(fishing_loot) 헬퍼
# ---------------------------------------------------------

async def upsert_fishing_loot(
    guild_id: int,
    item_id: int,
    chance: float,
):
    """낚시 확률 테이블에 아이템 등록/수정."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO fishing_loot (guild_id, item_id, chance)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, item_id)
            DO UPDATE SET chance = excluded.chance
            """,
            (guild_id, item_id, chance),
        )
        await db.commit()
async def get_fishing_daily_count(guild_id: int, db_user_id: int, date_str: str) -> int:
    """
    해당 길드/유저/날짜(KST 기준)에 오늘 몇 번 낚시했는지 반환.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT count FROM fishing_limits
            WHERE guild_id = ? AND user_id = ? AND date = ?
            """,
            (guild_id, db_user_id, date_str),
        )
        row = await cursor.fetchone()
        await cursor.close()

    return row[0] if row else 0


async def increment_fishing_daily_count(guild_id: int, db_user_id: int, date_str: str) -> int:
    """
    오늘 낚시 횟수를 1 증가시키고, 증가 후 count 를 반환.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, count FROM fishing_limits
            WHERE guild_id = ? AND user_id = ? AND date = ?
            """,
            (guild_id, db_user_id, date_str),
        )
        row = await cursor.fetchone()

        if row:
            limit_id, cnt = row
            new_cnt = cnt + 1
            await db.execute(
                "UPDATE fishing_limits SET count = ? WHERE id = ?",
                (new_cnt, limit_id),
            )
        else:
            new_cnt = 1
            await db.execute(
                """
                INSERT INTO fishing_limits (guild_id, user_id, date, count)
                VALUES (?, ?, ?, ?)
                """,
                (guild_id, db_user_id, date_str, new_cnt),
            )

        await db.commit()
        await cursor.close()

    return new_cnt


async def get_or_create_fishing_item_id(guild_id: int, item_name: str):
    item_name = item_name.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 🔍 1) 동일한 이름의 아이템이 이미 있는지 확인
        cursor = await db.execute(
            "SELECT id FROM items WHERE guild_id = ? AND name = ?",
            (guild_id, item_name)
        )
        row = await cursor.fetchone()

        if row:
            # 이미 존재하는 아이템 → 새로 만들지 않고 기존 ID 반환
            return row["id"]

        # 🔥 2) 존재하지 않을 때만 새로 생성
        cursor = await db.execute(
            "INSERT INTO items (guild_id, name, description) VALUES (?, ?, ?)",
            (guild_id, item_name, f"{item_name} (낚시 전용 아이템)")
        )
        await db.commit()

        return cursor.lastrowid


async def get_fishing_loot(guild_id: int):
    """길드별 낚시 아이템 + 확률 목록."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT f.item_id,
                   f.chance,
                   i.name AS item_name,
                   i.description AS item_description
            FROM fishing_loot f
            JOIN items i ON f.item_id = i.id
            WHERE f.guild_id = ?
            ORDER BY i.id ASC
            """,
            (guild_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(r) for r in rows]
# ---------------------------------------------------------
# pets (펫 도감)
# ---------------------------------------------------------

async def add_or_update_pet(guild_id: int, name: str, description: str):
    """
    같은 (guild_id, name) 이 이미 있으면 설명만 수정,
    없으면 새로 추가.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO pets (guild_id, name, description)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, name)
            DO UPDATE SET description = excluded.description
            """,
            (guild_id, name, description),
        )
        await db.commit()


async def list_pets(guild_id: int):
    """길드의 펫 전체 목록을 리스트[dict] 로 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, name, description
            FROM pets
            WHERE guild_id = ?
            ORDER BY id ASC
            """,
            (guild_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(r) for r in rows]