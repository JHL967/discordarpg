# bot.py - 슬래시(/) 전용 ARPG 봇 + 재고 있는 상점 + 선물 + 판매 상점 + 낚시

import random
import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite

from settings import TOKEN
from db import (
    DB_PATH,
    init_db,
    get_or_create_guild_settings,
    set_attend_channel,
    set_shop_channel,
    set_attend_currency,
    set_main_currency,
    add_currency,
    list_currencies,
    get_currency_by_code,
    get_or_create_user,
    update_user_last_attend,
    update_user_last_bonus_attend,
    get_balance,
    change_balance,
    get_items,
    add_item,
    delete_item,
    get_item_by_id,
    get_inventory,
    get_item_by_name,
    upsert_sell_item,
    get_sell_items,
    get_sell_item_by_name,
    upsert_fishing_loot,
    get_fishing_loot,
    get_fishing_daily_count,       # ✅ 추가
    increment_fishing_daily_count, # ✅ 추가
)

# =========================================================
# 봇 기본 설정
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# on_ready 에서 여러번 sync되는 것 방지
synced = False


def get_today_kst_str() -> str:
    """한국 시간(KST) 기준 오늘 날짜를 YYYY-MM-DD 문자열로 반환"""
    return datetime.datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
# =========================================================
# 공통 유틸 (Interaction 기반)
# =========================================================

def is_guild_inter(inter: discord.Interaction) -> bool:
    return inter.guild is not None


async def send_reply(
    inter: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = True,
):
    """Interaction 응답 도우미

    - 이미 응답했으면 followup.send
    - 아직이면 response.send_message
    - Unknown Interaction(404) 이 떠도 봇이 죽지 않도록 예외 처리
    """
    try:
        if inter.response.is_done():
            await inter.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await inter.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    except discord.NotFound:
        # 보통 응답이 3초 이상 지연되거나, 인터렉션이 만료됐을 때 나는 에러
        print("[WARN] send_reply: Unknown interaction (404) – 이미 만료된 요청, 무시합니다.")
    except Exception as e:
        # 어떤 이유든 여기서 막아서 봇이 죽지 않게
        print(f"[ERROR] send_reply 중 예외 발생: {e!r}")



# ---- 관리자용 봇채널 테이블 (command_channels) ----

async def ensure_admin_channel_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS command_channels (
                guild_id    INTEGER PRIMARY KEY,
                channel_id  INTEGER NOT NULL
            )
            """
        )
        await db.commit()


async def set_admin_channel(guild_id: int, channel_id: int):
    await ensure_admin_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO command_channels (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
            """,
            (guild_id, channel_id),
        )
        await db.commit()


async def get_admin_channel_id(guild_id: int) -> int | None:
    await ensure_admin_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT channel_id FROM command_channels WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    return row[0] if row else None


# ---- 사용자용 봇채널 테이블 (user_command_channels) ----

async def ensure_user_channel_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_command_channels (
                guild_id    INTEGER PRIMARY KEY,
                channel_id  INTEGER NOT NULL
            )
            """
        )
        await db.commit()


async def set_user_channel(guild_id: int, channel_id: int):
    await ensure_user_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_command_channels (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
            """,
            (guild_id, channel_id),
        )
        await db.commit()


async def get_user_channel_id(guild_id: int) -> int | None:
    await ensure_user_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT channel_id FROM user_command_channels WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    return row[0] if row else None


# ---- 낚시 채널 테이블 (fishing_channels) ----

async def ensure_fishing_channel_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS fishing_channels (
                guild_id    INTEGER PRIMARY KEY,
                channel_id  INTEGER NOT NULL
            )
            """
        )
        await db.commit()


async def set_fishing_channel(guild_id: int, channel_id: int):
    await ensure_fishing_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO fishing_channels (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
            """,
            (guild_id, channel_id),
        )
        await db.commit()


async def get_fishing_channel_id(guild_id: int) -> int | None:
    await ensure_fishing_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT channel_id FROM fishing_channels WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    return row[0] if row else None
# ---- 거래 채널 테이블 (trade_channels) ----

async def ensure_trade_channel_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_channels (
                guild_id    INTEGER PRIMARY KEY,
                channel_id  INTEGER NOT NULL
            )
            """
        )
        await db.commit()


async def set_trade_channel(guild_id: int, channel_id: int):
    await ensure_trade_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO trade_channels (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
            """,
            (guild_id, channel_id),
        )
        await db.commit()


async def get_trade_channel_id(guild_id: int) -> int | None:
    await ensure_trade_channel_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT channel_id FROM trade_channels WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    return row[0] if row else None


# ---- 채널 체크 공통 (Interaction용) ----

async def ensure_channel_inter(inter: discord.Interaction, kind: str) -> bool:
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return False

    guild_id = inter.guild.id

    if kind in ("attend", "shop"):
        settings = await get_or_create_guild_settings(guild_id)
        if kind == "attend":
            channel_id = settings["attend_channel_id"]
            cmd_name = "/출석채널설정"
            not_set_msg = (
                "아직 이 서버의 출석 채널이 설정되지 않았어요.\n"
                f"서버 관리자가 `{cmd_name}` 명령으로 설정해야 합니다."
            )
            wrong_channel_msg = "이 명령어는 지정된 **출석 채널**에서만 사용할 수 있어요!"
        else:
            channel_id = settings["shop_channel_id"]
            cmd_name = "/상점채널설정"
            not_set_msg = (
                "아직 이 서버의 상점 채널이 설정되지 않았어요.\n"
                f"서버 관리자가 `{cmd_name}` 명령으로 설정해야 합니다."
            )
            wrong_channel_msg = "이 명령어는 지정된 **상점 채널**에서만 사용할 수 있어요!"

        if channel_id is None:
            await send_reply(inter, not_set_msg, ephemeral=True)
            return False

        if str(inter.channel.id) != str(channel_id):
            await send_reply(inter, wrong_channel_msg, ephemeral=True)
            return False

        return True

    if kind == "admin":
        channel_id = await get_admin_channel_id(guild_id)
        if channel_id is None:
            await send_reply(
                inter,
                "아직 이 서버의 **관리자용 봇채널**이 설정되지 않았어요.\n"
                "서버 관리자가 `/명령어채널설정` 명령으로 설정해야 합니다.",
                ephemeral=True,
            )
            return False

        if str(inter.channel.id) != str(channel_id):
            await send_reply(
                inter,
                "이 명령어는 지정된 **관리자용 봇채널**에서만 사용할 수 있어요!",
                ephemeral=True,
            )
            return False

        return True

    if kind == "user":
        channel_id = await get_user_channel_id(guild_id)
        if channel_id is None:
            await send_reply(
                inter,
                "아직 이 서버의 **사용자용 봇채널**이 설정되지 않았어요.\n"
                "서버 관리자가 `/사용자채널설정` 명령으로 설정해야 합니다.",
                ephemeral=True,
            )
            return False

        if str(inter.channel.id) != str(channel_id):
            await send_reply(
                inter,
                "이 명령어는 지정된 **사용자용 봇채널**에서만 사용할 수 있어요!",
                ephemeral=True,
            )
            return False

        return True
    if kind == "trade":
        channel_id = await get_trade_channel_id(guild_id)
        if channel_id is None:
            await send_reply(
                inter,
                "아직 이 서버의 **거래 채널**이 설정되지 않았어요.\n"
                "서버 관리자가 `/거래채널설정` 명령으로 설정해야 합니다.",
                ephemeral=True,
            )
            return False

        if str(inter.channel.id) != str(channel_id):
            await send_reply(
                inter,
                "이 명령어는 지정된 **거래 채널**에서만 사용할 수 있어요!",
                ephemeral=True,
            )
            return False

        return True

    if kind == "fish":
        channel_id = await get_fishing_channel_id(guild_id)
        if channel_id is None:
            await send_reply(
                inter,
                "아직 이 서버의 **낚시 채널**이 설정되지 않았어요.\n"
                "서버 관리자가 `/낚시채널설정` 명령으로 설정해야 합니다.",
                ephemeral=True,
            )
            return False

        if str(inter.channel.id) != str(channel_id):
            await send_reply(
                inter,
                "이 명령어는 지정된 **낚시 채널**에서만 사용할 수 있어요!",
                ephemeral=True,
            )
            return False

        return True

    return True


async def get_currency_by_identifier(guild_id: int, identifier: str):
    cur = await get_currency_by_code(guild_id, identifier)
    if cur:
        return cur

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM currencies
            WHERE guild_id = ?
              AND LOWER(name) = LOWER(?)
            """,
            (guild_id, identifier),
        )
        row = await cursor.fetchone()
        await cursor.close()
    return dict(row) if row else None


# =========================================================
# on_ready: DB + 길드별 슬래시 명령 동기화
# =========================================================

@bot.event
async def on_ready():
    global synced
    print(f"✅ 로그인 완료: {bot.user} (ID: {bot.user.id})")

    # DB / 채널 테이블 준비
    await init_db()
    await ensure_admin_channel_table()
    await ensure_user_channel_table()
    await ensure_fishing_channel_table()
    await ensure_trade_channel_table()

    # 글로벌 슬래시 명령 동기화
    if not synced:
        try:
            cmds = await bot.tree.sync()
            print(f"✅ 전역 슬래시 명령 동기화: {len(cmds)}개")
        except Exception as e:
            print(f"⚠️ 전역 슬래시 명령 동기화 실패: {e}")
        synced = True

    print(f"✅ DB 초기화 및 채널 테이블 준비 완료: {DB_PATH}")

# =========================================================
# 전역 에러 핸들러 (봇이 예외로 죽지 않도록)
# =========================================================

@bot.event
async def on_error(event_method, *args, **kwargs):
    import traceback
    print(f"[on_error] 이벤트 {event_method} 처리 중 예외 발생")
    traceback.print_exc()

@bot.tree.error
async def on_app_command_error(
    inter: discord.Interaction,
    error: app_commands.AppCommandError,
):
    import traceback
    print(f"[slash-error] /{getattr(inter.command, 'name', '?')} 실행 중 예외: {error!r}")
    traceback.print_exc()

    # 이미 send_reply에서 NotFound를 잡고 있지만, 혹시 빠져나온 경우 한 번 더 필터
    if isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.NotFound):
        # 유저 쪽 응답은 굳이 안 해도 되지만, 하고 싶으면:
        try:
            await send_reply(
                inter,
                "처리가 너무 늦어서 요청이 만료됐어요. 한 번만 다시 시도해 주세요!",
                ephemeral=True,
            )
        except Exception:
            pass
        return

    # 그 외 예외는 “알려만 주는” 메시지
    try:
        await send_reply(
            inter,
            "명령어 처리 중 오류가 발생했어요. 개발자에게 스크린 로그를 전달해 주세요.",
            ephemeral=True,
        )
    except Exception:
        # 여기서 또 죽으면 안 되니까 마지막 안전망
        pass


# =========================================================
# 0. 채널 설정 (관리자)
# =========================================================

@bot.tree.command(name="출석채널설정", description="출석 명령어를 사용할 채널을 설정합니다.")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_attend_channel(inter: discord.Interaction, channel: discord.TextChannel):
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return
    await set_attend_channel(inter.guild.id, channel.id)
    await send_reply(inter, f"✅ 출석 채널이 {channel.mention} 로 설정되었습니다.", ephemeral=True)


@bot.tree.command(name="상점채널설정", description="상점/구매 명령어를 사용할 채널을 설정합니다.")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_shop_channel(inter: discord.Interaction, channel: discord.TextChannel):
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return
    await set_shop_channel(inter.guild.id, channel.id)
    await send_reply(inter, f"✅ 상점 채널이 {channel.mention} 로 설정되었습니다.", ephemeral=True)


@bot.tree.command(name="명령어채널설정", description="관리자용 봇채널(재화관리/정산/확인)을 설정합니다.")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_admin_channel(inter: discord.Interaction, channel: discord.TextChannel):
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return
    await set_admin_channel(inter.guild.id, channel.id)
    await send_reply(inter, f"✅ 관리자용 봇채널이 {channel.mention} 로 설정되었습니다.", ephemeral=True)


@bot.tree.command(name="사용자채널설정", description="사용자용 봇채널(소지금/인벤토리/재화)을 설정합니다.")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_user_channel(inter: discord.Interaction, channel: discord.TextChannel):
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return
    await set_user_channel(inter.guild.id, channel.id)
    await send_reply(inter, f"✅ 사용자용 봇채널이 {channel.mention} 로 설정되었습니다.", ephemeral=True)


@bot.tree.command(name="낚시채널설정", description="낚시 명령어를 사용할 채널을 설정합니다.")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_fishing_channel(inter: discord.Interaction, channel: discord.TextChannel):
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return
    await set_fishing_channel(inter.guild.id, channel.id)
    await send_reply(inter, f"✅ 낚시 채널이 {channel.mention} 로 설정되었습니다.", ephemeral=True)

@bot.tree.command(name="거래채널설정", description="재화/아이템 선물 명령어를 사용할 거래 채널을 설정합니다.")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_trade_channel(inter: discord.Interaction, channel: discord.TextChannel):
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return
    await set_trade_channel(inter.guild.id, channel.id)
    await send_reply(inter, f"✅ 거래 채널이 {channel.mention} 로 설정되었습니다.", ephemeral=True)



# =========================================================
# 1. 재화 관리 + 재화 목록
# =========================================================

@bot.tree.command(name="재화추가", description="새로운 재화를 추가합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_add_currency(inter: discord.Interaction, name: str, code: str):
    if not await ensure_channel_inter(inter, "admin"):
        return

    code = code.lower()
    existing = await get_currency_by_code(inter.guild.id, code)
    if existing:
        await send_reply(
            inter,
            f"이미 이 서버에 `{code}` 코드의 재화가 존재합니다: {existing['name']}",
            ephemeral=True,
        )
        return

    cur = await add_currency(inter.guild.id, name, code, is_main=False, is_active=True)
    await send_reply(
        inter,
        f"✅ 새 재화 추가 완료!\n"
        f"- 이름: {cur['name']}\n"
        f"- 코드: `{cur['code']}`",
        ephemeral=True,
    )


@bot.tree.command(name="재화", description="이 서버에 등록된 재화 목록을 봅니다.")
async def slash_list_currencies(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "user"):
        return

    await get_or_create_guild_settings(inter.guild.id)
    currencies = await list_currencies(inter.guild.id)
    active_currencies = [cur for cur in currencies if cur["is_active"]]

    if not active_currencies:
        await send_reply(inter, "현재 이 서버에 활성화된 재화가 없습니다.", ephemeral=True)
        return

    lines = []
    for cur in active_currencies:
        tags = []
        if cur["is_main"]:
            tags.append("메인")
        tag_str = f" ({', '.join(tags)})" if tags else ""
        lines.append(f"- {cur['name']} [`{cur['code']}`]{tag_str}")

    msg = "\n".join(lines)
    await send_reply(inter, f"💰 이 서버의 재화 목록 (활성 재화만):\n{msg}", ephemeral=True)


@bot.tree.command(name="재화비활성", description="재화를 비활성화합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_deactivate_currency(inter: discord.Interaction, identifier: str):
    if not await ensure_channel_inter(inter, "admin"):
        return

    cur = await get_currency_by_identifier(inter.guild.id, identifier)
    if not cur:
        await send_reply(inter, f"`{identifier}` 에 해당하는 재화를 찾을 수 없습니다.", ephemeral=True)
        return

    if not cur["is_active"]:
        await send_reply(
            inter,
            f"`{cur['name']}` (`{cur['code']}`) 재화는 이미 비활성 상태입니다.",
            ephemeral=True,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE currencies SET is_active = 0 WHERE id = ?", (cur["id"],))
        await db.commit()

    await send_reply(
        inter,
        f"📴 재화 비활성 완료: {cur['name']} (`{cur['code']}`)",
        ephemeral=True,
    )


@bot.tree.command(name="재화활성", description="재화를 활성화합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_activate_currency(inter: discord.Interaction, identifier: str):
    if not await ensure_channel_inter(inter, "admin"):
        return

    cur = await get_currency_by_identifier(inter.guild.id, identifier)
    if not cur:
        await send_reply(inter, f"`{identifier}` 에 해당하는 재화를 찾을 수 없습니다.", ephemeral=True)
        return

    if cur["is_active"]:
        await send_reply(
            inter,
            f"`{cur['name']}` (`{cur['code']}`) 재화는 이미 활성 상태입니다.",
            ephemeral=True,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE currencies SET is_active = 1 WHERE id = ?", (cur["id"],))
        await db.commit()

    await send_reply(
        inter,
        f"✅ 재화 활성 완료: {cur['name']} (`{cur['code']}`)",
        ephemeral=True,
    )


@bot.tree.command(name="재화삭제", description="재화를 삭제합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_delete_currency(inter: discord.Interaction, identifier: str):
    if not await ensure_channel_inter(inter, "admin"):
        return

    cur = await get_currency_by_identifier(inter.guild.id, identifier)
    if not cur:
        await send_reply(inter, f"`{identifier}` 에 해당하는 재화를 찾을 수 없습니다.", ephemeral=True)
        return

    settings = await get_or_create_guild_settings(inter.guild.id)
    attend_id = settings["attend_currency_id"]
    main_id = settings["main_currency_id"]

    if attend_id == cur["id"] or main_id == cur["id"]:
        await send_reply(
            inter,
            "이 재화는 현재 출석 재화 또는 메인 재화로 사용 중이라 삭제할 수 없습니다.\n"
            "`/출석재화설정`, `/메인재화설정` 으로 다른 재화로 먼저 변경해주세요.",
            ephemeral=True,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM items WHERE guild_id = ? AND currency_id = ?",
            (inter.guild.id, cur["id"]),
        )
        row = await cursor.fetchone()
        await cursor.close()
        item_count = row[0] if row else 0

        if item_count > 0:
            await send_reply(
                inter,
                f"이 재화를 사용하는 상점/아이템이 {item_count}개 있어 삭제할 수 없습니다.\n"
                "먼저 해당 아이템들을 삭제하거나 다른 재화로 바꿔주세요.",
                ephemeral=True,
            )
            return

        await db.execute("DELETE FROM currencies WHERE id = ?", (cur["id"],))
        await db.commit()

    await send_reply(
        inter,
        f"🗑 재화 삭제 완료: {cur['name']} (`{cur['code']}`)",
        ephemeral=True,
    )


@bot.tree.command(name="출석재화설정", description="출석 보상으로 지급할 재화를 설정합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_attend_currency_cmd(inter: discord.Interaction, identifier: str):
    if not await ensure_channel_inter(inter, "admin"):
        return

    cur = await get_currency_by_identifier(inter.guild.id, identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
            ephemeral=True,
        )
        return

    await set_attend_currency(inter.guild.id, cur["id"])
    await send_reply(
        inter,
        f"✅ 앞으로 출석 보상은 **{cur['name']} (`{cur['code']}`)** 으로 지급됩니다.",
        ephemeral=True,
    )


@bot.tree.command(name="메인재화설정", description="이 서버의 메인 재화 이름을 변경합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_set_main_currency_name(inter: discord.Interaction, new_name: str):
    if not await ensure_channel_inter(inter, "admin"):
        return

    new_name = new_name.strip()
    if not new_name:
        await send_reply(
            inter,
            "메인 재화의 새 이름을 입력해주세요. 예: `/메인재화설정 여우코인`",
            ephemeral=True,
        )
        return

    settings = await get_or_create_guild_settings(inter.guild.id)
    main_currency_id = settings["main_currency_id"]

    # 🔹 메인 재화가 아직 하나도 지정되지 않은 경우: 자동으로 하나 지정해 주기
    if main_currency_id is None:
        currencies = await list_currencies(inter.guild.id)
        if not currencies:
            await send_reply(
                inter,
                "이 서버에 아직 재화가 하나도 없습니다. `/재화추가`로 먼저 재화를 만들어 주세요.",
                ephemeral=True,
            )
            return

        # 우선 is_main이 이미 찍혀 있는 재화가 있으면 그걸 메인으로,
        # 아니면 첫 번째 재화를 메인으로 지정
        main_cur = next((c for c in currencies if c["is_main"]), None)
        if main_cur is None:
            main_cur = currencies[0]

        main_currency_id = main_cur["id"]

        async with aiosqlite.connect(DB_PATH) as db:
            # guild 내 모든 재화에서 is_main 리셋 후, 선택한 것만 메인으로
            await db.execute(
                "UPDATE currencies SET is_main = 0 WHERE guild_id = ?",
                (inter.guild.id,),
            )
            await db.execute(
                "UPDATE currencies SET is_main = 1 WHERE id = ?",
                (main_currency_id,),
            )
            # guild_settings 테이블에도 메인 재화 id 저장
            await db.execute(
                "UPDATE guild_settings SET main_currency_id = ? WHERE guild_id = ?",
                (main_currency_id, inter.guild.id),
            )
            await db.commit()

    # 여기부터는 "이미 메인 재화 id는 있다"라고 보고 이름만 바꾸는 기존 로직
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT name, code FROM currencies WHERE id = ? AND guild_id = ?",
            (main_currency_id, inter.guild.id),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if not row:
            await send_reply(
                inter,
                "메인 재화 정보를 찾지 못했습니다. DB 설정에 문제가 있는 것 같아요. 개발자에게 문의해주세요.",
                ephemeral=True,
            )
            return

        old_name = row["name"]
        code = row["code"]

        await db.execute(
            "UPDATE currencies SET name = ? WHERE id = ?",
            (new_name, main_currency_id),
        )
        await db.commit()

    await send_reply(
        inter,
        "✅ 이 서버의 메인 재화 이름이 변경되었습니다.\n"
        f"- 이전 이름: **{old_name}**\n"
        f"- 새 이름: **{new_name}**\n"
        f"- 코드: `{code}` (코드는 그대로 유지됩니다)",
        ephemeral=True,
    )



# =========================================================
# 2. 출석
# =========================================================

@bot.tree.command(name="출석", description="출석하여 1d50 보상을 받습니다.")
async def slash_attend(inter: discord.Interaction):
    # ✅ 출석 채널에서만 사용
    if not await ensure_channel_inter(inter, "attend"):
        return

    # ✅ 출석 재화 ID 가져오기
    settings = await get_or_create_guild_settings(inter.guild.id)
    attend_currency_id = settings["attend_currency_id"]

    if attend_currency_id is None:
        await send_reply(
            inter,
            "이 서버에 아직 출석 보상으로 줄 재화가 설정되지 않았어요.\n"
            "관리자가 `/출석재화설정` 으로 먼저 설정해야 합니다.",
            ephemeral=True,
        )
        return

    # ✅ 유저 정보 + 한국 시간 기준 오늘 날짜
    user = await get_or_create_user(inter.guild.id, inter.user.id)
    today_str = get_today_kst_str()   # 한국 시간 기준 YYYY-MM-DD

    # 이미 오늘 출석했는지 체크
    if user["last_attend_date"] == today_str:
        await send_reply(
            inter,
            "오늘은 이미 출석하셨어요! 내일 다시 와주세요 😊",
            ephemeral=False,
        )
        return

    # 출석 재화 정보 조회
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name, code FROM currencies WHERE id = ?",
            (attend_currency_id,),
        )
        cur_row = await cursor.fetchone()
        await cursor.close()

    if not cur_row:
        await send_reply(
            inter,
            "출석 재화 설정에 문제가 있습니다. 관리자에게 문의해주세요.",
            ephemeral=False,
        )
        return

    cur_name, cur_code = cur_row

    # 1d50 굴려서 지급


@bot.tree.command(
    name="재출석",
    description="특정 행운 아이템을 사용해 오늘 한 번 더 출석 보상을 받습니다.",
)
async def slash_bonus_attend(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "attend"):
        return

    # 오늘 날짜 (기존 /출석과 동일하게 사용)
    today_str = get_today_kst_str()

    settings = await get_or_create_guild_settings(inter.guild.id)
    attend_currency_id = settings["attend_currency_id"]

    # 기본 유저 정보
    user = await get_or_create_user(inter.guild.id, inter.user.id)

    # 1) 오늘 아직 일반 출석을 안 했으면 /재출석 사용 불가
    if user["last_attend_date"] != today_str:
        await send_reply(
            inter,
            "아직 오늘 기본 출석을 하지 않았어요!\n"
            "`/출석` 으로 먼저 오늘 출석을 한 뒤에 `/재출석` 을 사용해 주세요.",
            ephemeral=True,
        )
        return

    # 2) 오늘 이미 재출석을 한 적이 있다면 또 못 쓰게
    if user.get("last_bonus_attend_date") == today_str:
        await send_reply(
            inter,
            "오늘은 이미 `/재출석` 을 사용했어요.\n내일 다시 사용해 주세요 😊",
            ephemeral=True,
        )
        return

    # 3) 인벤토리에서 '출석 주사위' 또는 '행운의 꼬리' 보유 여부 확인
    lucky_items = ["출석 주사위", "행운의 꼬리"]
    chosen_row = None

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT inv.id AS inv_id, inv.quantity, i.name
              FROM inventories AS inv
              JOIN items AS i ON inv.item_id = i.id
             WHERE inv.user_id = ?
               AND i.guild_id = ?
               AND i.name IN (?, ?)
            """,
            (user["id"], inter.guild.id, lucky_items[0], lucky_items[1]),
        )
        rows = await cursor.fetchall()
        await cursor.close()

    # rows 안에 두 아이템 중 어떤 것이든 있을 수 있으니 우선순위 정하기
    for name in lucky_items:
        for row in rows:
            if row["name"] == name:
                chosen_row = row
                break
        if chosen_row:
            break

    if not chosen_row:
        await send_reply(
            inter,
            "인벤토리에 **출석 주사위** 또는 **행운의 꼬리**가 있어야 `/재출석` 을 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    used_item_name = chosen_row["name"]
    inv_id = chosen_row["inv_id"]
    qty = chosen_row["quantity"]

    # 4) 아이템 1개 소모
    async with aiosqlite.connect(DB_PATH) as db:
        if qty > 1:
            await db.execute(
                "UPDATE inventories SET quantity = ? WHERE id = ?",
                (qty - 1, inv_id),
            )
        else:
            await db.execute(
                "DELETE FROM inventories WHERE id = ?",
                (inv_id,),
            )
        await db.commit()

    # 5) 출석 재화 정보 확인
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name, code FROM currencies WHERE id = ?",
            (attend_currency_id,),
        )
        cur_row = await cursor.fetchone()
        await cursor.close()

    if not cur_row:
        await send_reply(
            inter,
            "출석 재화 설정에 문제가 있습니다. 관리자에게 문의해주세요.",
            ephemeral=False,
        )
        return

    cur_name, cur_code = cur_row

    # 6) 1d50 다시 굴려서 추가 보상 지급
    roll = random.randint(1, 50)
    new_amount = await change_balance(user["id"], attend_currency_id, roll)

    # 7) 오늘 재출석 사용 날짜 기록 (기본 출석 날짜는 그대로 둠)
    await update_user_last_bonus_attend(user["id"], today_str)

    await send_reply(
        inter,
        f"🍀 **{used_item_name}** 을(를) 사용하여 추가 출석에 성공했습니다!\n"
        f"🎲 보너스 출석 1d50 → **{roll}**\n"
        f"획득 재화: **{cur_name}** (`{cur_code}`)\n"
        f"현재 소지금: **{new_amount} {cur_name}**",
        ephemeral=False,
    )


# =========================================================
# 3. 소지금 / 인벤토리
# =========================================================

@bot.tree.command(name="소지금", description="자신의 재화 소지금을 확인합니다.")
async def slash_balance(inter: discord.Interaction, identifier: str | None = None):
    if not await ensure_channel_inter(inter, "user"):
        return

    user = await get_or_create_user(inter.guild.id, inter.user.id)

    if identifier:
        cur = await get_currency_by_identifier(inter.guild.id, identifier)
        if not cur:
            await send_reply(
                inter,
                f"`{identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
                ephemeral=True,
            )
            return

        amount = await get_balance(user["id"], cur["id"])
        await send_reply(
            inter,
            f"💰 **{inter.user.display_name}** 님의 `{cur['name']}` (`{cur['code']}`) 소지금: **{amount}**",
            ephemeral=True,
        )
        return

    currencies = await list_currencies(inter.guild.id)
    if not currencies:
        await send_reply(inter, "이 서버에는 아직 재화가 없습니다.", ephemeral=True)
        return

    lines = []
    for cur in currencies:
        amount = await get_balance(user["id"], cur["id"])
        lines.append(f"- {cur['name']} (`{cur['code']}`): {amount}")

    msg = "\n".join(lines)
    await send_reply(
        inter,
        f"💰 **{inter.user.display_name}** 님의 소지금:\n{msg}",
        ephemeral=True,
    )


@bot.tree.command(name="인벤토리", description="자신의 인벤토리를 확인합니다.")
async def slash_inventory_cmd(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "user"):
        return

    user = await get_or_create_user(inter.guild.id, inter.user.id)
    inv = await get_inventory(user["id"])

    if not inv:
        await send_reply(
            inter,
            "인벤토리가 비어 있어요. 먼저 아이템을 얻어보세요! (상점 구매 / 낚시 / 선물 등)",
            ephemeral=True,
        )
        return

    lines = []
    for item in inv:
        line = f"- {item['name']} x {item['quantity']}개"
        if item["description"]:
            line += f" ({item['description']})"
        lines.append(line)

    msg = "\n".join(lines)
    await send_reply(
        inter,
        f"📦 **{inter.user.display_name}** 님의 인벤토리:\n{msg}",
        ephemeral=True,
    )


# =========================================================
# 3-1. 선물 기능 (재화 / 아이템) - 사용자용 봇채널
# =========================================================

@bot.tree.command(name="재화선물", description="자신의 재화를 다른 사용자에게 선물합니다.")
@app_commands.describe(
    member="선물을 받을 사용자",
    amount="보낼 재화의 양 (양수만 가능)",
    currency_identifier="재화 코드 또는 이름 (예: coin, hcoin, 여우코인)",
)
async def slash_gift_currency(
    inter: discord.Interaction,
    member: discord.Member,
    amount: int,
    currency_identifier: str,
):
    if not await ensure_channel_inter(inter, "trade"):
        return

    if member.id == inter.user.id:
        await send_reply(inter, "자기 자신에게는 재화를 선물할 수 없어요!", ephemeral=True)
        return

    if amount <= 0:
        await send_reply(inter, "선물할 양은 1 이상이어야 합니다.", ephemeral=True)
        return

    cur = await get_currency_by_identifier(inter.guild.id, currency_identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{currency_identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
            ephemeral=True,
        )
        return

    giver = await get_or_create_user(inter.guild.id, inter.user.id)
    receiver = await get_or_create_user(inter.guild.id, member.id)

    giver_balance = await get_balance(giver["id"], cur["id"])
    if giver_balance < amount:
        await send_reply(
            inter,
            f"재화가 부족해서 선물할 수 없어요.\n"
            f"- 보유: {giver_balance} {cur['name']} (`{cur['code']}`)\n"
            f"- 시도: {amount}",
            ephemeral=True,
        )
        return

    await change_balance(giver["id"], cur["id"], -amount)
    new_receiver_balance = await change_balance(receiver["id"], cur["id"], amount)

    await send_reply(
        inter,
        f"🎁 재화 선물 완료!\n"
        f"- 보낸 사람: {inter.user.mention}\n"
        f"- 받은 사람: {member.mention}\n"
        f"- 재화: {cur['name']} (`{cur['code']}`)\n"
        f"- 선물한 양: {amount}\n"
        f"- 받는 사람의 선물 후 소지금: {new_receiver_balance} {cur['name']}",
        ephemeral=False,
    )


@bot.tree.command(name="아이템선물", description="자신의 인벤토리 아이템을 다른 사용자에게 선물합니다.")
@app_commands.describe(
    member="선물을 받을 사용자",
    item_name="선물할 아이템 이름 (인벤토리 기준 이름)",
    quantity="선물할 개수 (양수)",
)
async def slash_gift_item(
    inter: discord.Interaction,
    member: discord.Member,
    item_name: str,
    quantity: int,
):
    if not await ensure_channel_inter(inter, "trade"):
        return

    if member.id == inter.user.id:
        await send_reply(inter, "자기 자신에게는 아이템을 선물할 수 없어요!", ephemeral=True)
        return

    name = item_name.strip()
    if quantity <= 0:
        await send_reply(inter, "선물할 개수는 1 이상이어야 합니다.", ephemeral=True)
        return

    item = await get_item_by_name(inter.guild.id, name)
    if not item:
        await send_reply(
            inter,
            f"`{name}` 이름의 아이템을 찾을 수 없어요.\n"
            "아이템 이름을 정확히 입력했는지 확인하고, `/인벤토리` 또는 `/상점`에서 다시 확인해 주세요.",
            ephemeral=True,
        )
        return

    giver = await get_or_create_user(inter.guild.id, inter.user.id)
    receiver = await get_or_create_user(inter.guild.id, member.id)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, quantity FROM inventories WHERE user_id = ? AND item_id = ?",
            (giver["id"], item["id"]),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if not row:
            await send_reply(
                inter,
                f"당신의 인벤토리에 **{item['name']}** 이(가) 없습니다.",
                ephemeral=True,
            )
            return

        giver_inv_id, giver_qty = row
        if giver_qty < quantity:
            await send_reply(
                inter,
                f"아이템 개수가 부족해서 선물할 수 없습니다.\n"
                f"- 보유: {giver_qty}개\n"
                f"- 시도: {quantity}개",
                ephemeral=True,
            )
            return

        new_giver_qty = giver_qty - quantity

        if new_giver_qty > 0:
            await db.execute(
                "UPDATE inventories SET quantity = ? WHERE id = ?",
                (new_giver_qty, giver_inv_id),
            )
        else:
            await db.execute(
                "DELETE FROM inventories WHERE id = ?",
                (giver_inv_id,),
            )

        cursor = await db.execute(
            "SELECT id, quantity FROM inventories WHERE user_id = ? AND item_id = ?",
            (receiver["id"], item["id"]),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            recv_inv_id, recv_qty = row
            await db.execute(
                "UPDATE inventories SET quantity = ? WHERE id = ?",
                (recv_qty + quantity, recv_inv_id),
            )
        else:
            await db.execute(
                "INSERT INTO inventories (user_id, item_id, quantity) VALUES (?, ?, ?)",
                (receiver["id"], item["id"], quantity),
            )

        await db.commit()

    await send_reply(
        inter,
        f"🎁 아이템 선물 완료!\n"
        f"- 보낸 사람: {inter.user.mention}\n"
        f"- 받은 사람: {member.mention}\n"
        f"- 아이템: {item['name']}\n"
        f"- 선물한 개수: {quantity}개",
        ephemeral=False,
    )


# =========================================================
# 4. 상점 (재고 표시)
# =========================================================

def format_stock_text(stock):
    if stock is None:
        return "제한없음"
    elif stock <= 0:
        return "품절"
    else:
        return f"{stock}개"


@bot.tree.command(name="상점", description="일반 상점(메인 재화 아이템)을 봅니다.")
async def slash_shop(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "shop"):
        return

    settings = await get_or_create_guild_settings(inter.guild.id)
    main_currency_id = settings["main_currency_id"]

    items = await get_items(inter.guild.id)

    normal_items = [
        item for item in items
        if main_currency_id is not None and item["currency_id"] == main_currency_id
    ]

    if not normal_items:
        await send_reply(inter, "현재 일반 상점(메인 재화) 아이템이 없습니다. 😢", ephemeral=True)
        return

    embed = discord.Embed(
        title="🛒 상점 (일반)",
        description="`/구매 아이템이름` 으로 아이템을 구매할 수 있어요.\n"
                    "여기에는 **메인 재화로 구매하는 아이템**만 표시됩니다.",
    )

    for item in normal_items:
        cur_name = item["currency_name"] or "알 수 없음"
        cur_code = item["currency_code"] or "?"
        stock_text = format_stock_text(item.get("stock"))
        name = f"{item['name']} - {item['price']} {cur_name} (`{cur_code}`) | 재고: {stock_text}"
        value = (item["description"] or "설명 없음") + f"\n(구매 예시: `/구매 {item['name']}`)"
        embed.add_field(name=name, value=value, inline=False)

    await send_reply(inter, embed=embed, ephemeral=True)


@bot.tree.command(name="이벤트상점", description="이벤트 상점(이벤트 재화 아이템)을 봅니다.")
async def slash_event_shop(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "shop"):
        return

    settings = await get_or_create_guild_settings(inter.guild.id)
    main_currency_id = settings["main_currency_id"]

    items = await get_items(inter.guild.id)

    event_items = [
        item for item in items
        if main_currency_id is not None and item["currency_id"] != main_currency_id
    ]

    if not event_items:
        await send_reply(inter, "현재 이벤트 상점 아이템이 없습니다. 🎃", ephemeral=True)
        return

    embed = discord.Embed(
        title="🎁 이벤트 상점",
        description="`/구매 아이템이름` 으로 이벤트 아이템을 구매할 수 있어요.\n"
                    "여기에는 **이벤트 재화로 구매하는 아이템**만 표시됩니다.",
    )

    for item in event_items:
        cur_name = item["currency_name"] or "알 수 없음"
        cur_code = item["currency_code"] or "?"
        stock_text = format_stock_text(item.get("stock"))
        name = f"{item['name']} - {item['price']} {cur_name} (`{cur_code}`) | 재고: {stock_text}"
        value = (item["description"] or "설명 없음") + f"\n(구매 예시: `/구매 {item['name']}`)"
        embed.add_field(name=name, value=value, inline=False)

    await send_reply(inter, embed=embed, ephemeral=True)


# =========================================================
# 5. 아이템 추가/삭제 (재고 포함, 상점용)
# =========================================================

@bot.tree.command(
    name="아이템추가",
    description="일반 상점 아이템을 추가합니다. (메인 재화 / 재고 포함)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    name="아이템 이름",
    price="아이템 가격",
    currency_identifier="재화 코드 또는 이름 (예: coin)",
    description="아이템 설명",
    stock="재고 수량 ( -1 입력 시 무제한 )",
)
async def slash_add_item_cmd(
    inter: discord.Interaction,
    name: str,
    price: int,
    currency_identifier: str,
    description: str,
    stock: int,
):

    """
    예시:
    /아이템추가 이름:포션 price:10 currency_identifier:coin description:"체력 10 회복" stock:50
    """
    if not await ensure_channel_inter(inter, "shop"):
        return

    settings = await get_or_create_guild_settings(inter.guild.id)
    main_currency_id = settings["main_currency_id"]

    if price < 0:
        await send_reply(inter, "가격은 0 이상이어야 합니다.", ephemeral=True)
        return

    # 재고 처리: -1 → 무제한(None), 0 이상 → 그 값, 그 외 음수 → 오류
    if stock == -1:
        stock_value = None  # DB에 NULL로 들어가서 무제한 취급
        stock_text = "제한없음"
    elif stock >= 0:
        stock_value = stock
        stock_text = f"{stock}개"
    else:
        await send_reply(
            inter,
            "재고는 0 이상이거나, 무제한으로 하고 싶다면 -1을 입력해 주세요.",
            ephemeral=True,
        )
        return


    cur = await get_currency_by_identifier(inter.guild.id, currency_identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{currency_identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
            ephemeral=True,
        )
        return

    if main_currency_id is None or cur["id"] != main_currency_id:
        await send_reply(
            inter,
            "이 명령어는 메인 재화로만 아이템을 추가할 수 있어요.\n"
            "이벤트 재화라면 `/이벤트아이템추가` 를 사용해주세요.",
            ephemeral=True,
        )
        return

    item_id = await add_item(
        inter.guild.id,
        name,
        price,
        description,
        cur["id"],
        stock_value,
        is_shop=True,  # 상점용
    )
    await send_reply(
        inter,
        f"✅ 일반 상점 아이템 추가 완료!\n"
        f"- ID: {item_id}\n"
        f"- 이름: {name}\n"
        f"- 가격: {price} {cur['name']} (`{cur['code']}`)\n"
        f"- 초기 재고: {stock_text}\n"
        f"- 설명: {description}",
        ephemeral=True,
    )



@bot.tree.command(
    name="이벤트아이템추가",
    description="이벤트 상점 아이템을 추가합니다. (이벤트 재화 / 재고 포함)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_add_event_item(
    inter: discord.Interaction,
    name: str,
    price: int,
    currency_identifier: str,
    description: str,
    stock: int,
):
    """
    예시:
    /이벤트아이템추가 이름:이벤트상자 price:3 currency_identifier:icoins description:"한정 상자" stock:100
    """
    if not await ensure_channel_inter(inter, "shop"):
        return

    settings = await get_or_create_guild_settings(inter.guild.id)
    main_currency_id = settings["main_currency_id"]

    if price < 0:
        await send_reply(inter, "가격은 0 이상이어야 합니다.", ephemeral=True)
        return

    # 🔹 여기부터 재고 처리 로직 변경 (-1 → 무제한)
    if stock == -1:
        stock_value = None   # DB에서 NULL = 무제한
        stock_text = "제한없음"
    elif stock >= 0:
        stock_value = stock
        stock_text = f"{stock}개"
    else:
        await send_reply(
            inter,
            "재고는 0 이상이거나, 무제한으로 하고 싶다면 -1을 입력해 주세요.",
            ephemeral=True,
        )
        return
    # 🔹 여기까지 추가

    cur = await get_currency_by_identifier(inter.guild.id, currency_identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{currency_identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
            ephemeral=True,
        )
        return

    if main_currency_id is not None and cur["id"] == main_currency_id:
        await send_reply(
            inter,
            "이 명령어는 메인 재화가 아닌 **이벤트 재화**로만 아이템을 추가할 수 있어요.\n"
            "`/아이템추가` 로 다시 시도해주세요.",
            ephemeral=True,
        )
        return

    item_id = await add_item(
        inter.guild.id,
        name,
        price,
        description,
        cur["id"],
        stock_value,      # 🔹 여기도 stock → stock_value 로 변경
        is_shop=True,     # 상점용
    )
    await send_reply(
        inter,
        f"✅ 이벤트 상점 아이템 추가 완료!\n"
        f"- ID: {item_id}\n"
        f"- 이름: {name}\n"
        f"- 가격: {price} {cur['name']} (`{cur['code']}`)\n"
        f"- 초기 재고: {stock_text}\n"   # 🔹 {stock}개 → {stock_text}
        f"- 설명: {description}",
        ephemeral=True,
    )



@bot.tree.command(
    name="아이템삭제",
    description="상점 목록에서 아이템을 제거합니다. (이미 가진 사람 인벤토리는 유지) (관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    item_name="삭제할 아이템 이름 (상점에 표시된 이름 그대로 입력)"
)
async def slash_delete_item_cmd(inter: discord.Interaction, item_name: str):
    # 상점 채널에서만 사용 가능
    if not await ensure_channel_inter(inter, "shop"):
        return

    name = item_name.strip()
    if not name:
        await send_reply(
            inter,
            "삭제할 아이템 이름을 입력해주세요.",
            ephemeral=True,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # 상점에 노출 중인 같은 이름 아이템들 모두 찾기
        cursor = await db.execute(
            """
            SELECT id, name
              FROM items
             WHERE guild_id = ?
               AND name = ?
               AND is_shop = 1
            """,
            (inter.guild.id, name),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        if not rows:
            await send_reply(
                inter,
                f"`{name}` 이름의 상점 아이템을 찾을 수 없습니다.\n"
                "`/상점` 또는 `/이벤트상점`으로 아이템 이름을 다시 확인해 주세요.",
                ephemeral=True,
            )
            return

        # 판매 상점에 등록된 것도 함께 제거
        item_ids = [r[0] for r in rows]
        await db.executemany(
            """
            DELETE FROM sell_shop_items
             WHERE guild_id = ?
               AND item_id = ?
            """,
            [(inter.guild.id, iid) for iid in item_ids],
        )

        # ❗ 실제로 삭제하지 않고, 상점에서만 숨김
        await db.execute(
            """
            UPDATE items
               SET is_shop = 0
             WHERE guild_id = ?
               AND name = ?
               AND is_shop = 1
            """,
            (inter.guild.id, name),
        )

        await db.commit()

    deleted_count = len(rows)
    await send_reply(
        inter,
        f"🗑 상점 목록에서 `{name}` 아이템 {deleted_count}개를 제거했습니다.\n"
        f"이미 플레이어가 보유한 아이템은 **인벤토리에 그대로 남습니다.**",
        ephemeral=True,
    )
@bot.tree.command(
    name="아이템제거",
    description="잘못 만든 아이템을 DB에서 완전히 삭제합니다. (인벤토리에서도 사라짐 / 관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    item_name="완전히 삭제할 아이템 이름 (상점/인벤토리 기준 이름 그대로 입력)"
)
async def slash_purge_item_cmd(inter: discord.Interaction, item_name: str):
    """
    ⚠ 매우 위험한 명령어입니다.
    - items 테이블의 아이템을 삭제하고
    - 그 아이템을 가지고 있던 모든 유저의 인벤토리 기록도 사라집니다.
    이미 배포된 아이템을 '완전 무효화'할 때만 사용하세요.
    """

    # 위험한 명령어니까 관리자용 채널에서만 사용하도록 제한
    if not await ensure_channel_inter(inter, "shop"):
        return

    name = item_name.strip()
    if not name:
        await send_reply(
            inter,
            "완전히 삭제할 아이템 이름을 입력해주세요.",
            ephemeral=True,
        )
        return

    # 이름으로 아이템 찾기
    item = await get_item_by_name(inter.guild.id, name)
    if not item:
        await send_reply(
            inter,
            f"`{name}` 이름의 아이템을 찾을 수 없습니다.\n"
            "`/상점`, `/이벤트상점`, `/인벤토리` 등에서 정확한 이름을 다시 확인해 주세요.",
            ephemeral=True,
        )
        return

    # 실제 삭제: delete_item 헬퍼 사용
    # (items 에서 삭제되면서, 해당 아이템을 가진 인벤토리도 함께 정리되는 동작)
    await delete_item(inter.guild.id, item["id"])

    await send_reply(
        inter,
        f"💣 **완전 삭제 완료!**\n"
        f"- 대상 아이템: [{item['id']}] {item['name']}\n"
        f"- 이 아이템을 보유하던 모든 유저의 인벤토리에서도 **모두 제거**되었습니다.\n\n"
        f"※ 잘못 만든 아이템을 없앨 때만 사용하세요. 되돌릴 수 없습니다.",
        ephemeral=True,
    )




# =========================================================
# 6. 아이템 구매: /구매 (재고 차감)
# =========================================================

@bot.tree.command(name="구매", description="아이템 이름으로 상점 아이템을 구매합니다.")
async def slash_buy_item(inter: discord.Interaction, item_name: str):
    if not await ensure_channel_inter(inter, "shop"):
        return

    name = item_name.strip()
    item = await get_item_by_name(inter.guild.id, name)

    # 상점에 노출되는 아이템만 구매 가능 (is_shop=1 인 것만 get_items에 나와 있으므로)
    if not item or item.get("is_shop") == 0:
        await send_reply(
            inter,
            f"`{name}` 이름의 아이템을 상점에서 찾을 수 없어요.\n"
            "철자와 띄어쓰기를 정확히 입력했는지 확인하고, `/상점` 또는 `/이벤트상점`으로 아이템 이름을 다시 확인해 주세요.",
            ephemeral=True,
        )
        return

    stock = item.get("stock")
    if stock is not None and stock <= 0:
        await send_reply(
            inter,
            f"❌ **{item['name']}** 은(는) 현재 **품절** 상태입니다.",
            ephemeral=True,
        )
        return

    user = await get_or_create_user(inter.guild.id, inter.user.id)

    price = item["price"]
    currency_id = item["currency_id"]
    cur_name = item["currency_name"] or "알 수 없음"
    cur_code = item["currency_code"] or "?"

    current_balance = await get_balance(user["id"], currency_id)
    if current_balance < price:
        await send_reply(
            inter,
            f"재화가 부족해요!\n"
            f"- 필요: {price} {cur_name} (`{cur_code}`)\n"
            f"- 보유: {current_balance} {cur_name}",
            ephemeral=True,
        )
        return

    new_balance = await change_balance(user["id"], currency_id, -price)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, quantity FROM inventories WHERE user_id = ? AND item_id = ?",
            (user["id"], item["id"]),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            inv_id, qty = row
            await db.execute(
                "UPDATE inventories SET quantity = ? WHERE id = ?",
                (qty + 1, inv_id),
            )
        else:
            await db.execute(
                "INSERT INTO inventories (user_id, item_id, quantity) VALUES (?, ?, ?)",
                (user["id"], item["id"], 1),
            )

        if stock is not None:
            await db.execute(
                "UPDATE items SET stock = stock - 1 WHERE id = ? AND stock IS NOT NULL",
                (item["id"],),
            )

        await db.commit()

    new_stock_value = None if stock is None else max(stock - 1, 0)
    new_stock_text = "무제한" if new_stock_value is None else f"{new_stock_value}개"

    await send_reply(
        inter,
        f"✅ **{item['name']}** 을(를) 구매했습니다!\n"
        f"- 지불: {price} {cur_name} (`{cur_code}`)\n"
        f"- 남은 소지금: {new_balance} {cur_name}\n"
        f"- 남은 재고: {new_stock_text}",
        ephemeral=False,
    )


# =========================================================
# 7. 판매 상점: /판매등록, /판매상점, /판매
# =========================================================

@bot.tree.command(
    name="판매등록",
    description="판매 상점에 아이템을 등록하거나 가격을 수정합니다. (관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    item_name="판매 허용할 아이템 이름 (items 기준)",
    price="아이템 1개당 판매 가격",
    currency_identifier="지급할 재화 코드 또는 이름",
)
async def slash_register_sell_item(
    inter: discord.Interaction,
    item_name: str,
    price: int,
    currency_identifier: str,
):
    if not await ensure_channel_inter(inter, "shop"):
        return

    if price < 0:
        await send_reply(inter, "판매 가격은 0 이상이어야 합니다.", ephemeral=True)
        return

    item = await get_item_by_name(inter.guild.id, item_name.strip())
    if not item:
        await send_reply(
            inter,
            f"`{item_name}` 이름의 아이템을 찾을 수 없습니다.\n"
            "`/아이템추가`, `/이벤트아이템추가`, `/낚시아이템추가` 등으로 먼저 아이템을 추가해주세요.",
            ephemeral=True,
        )
        return

    cur = await get_currency_by_identifier(inter.guild.id, currency_identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{currency_identifier}` 에 해당하는 재화를 찾을 수 없습니다.",
            ephemeral=True,
        )
        return

    await upsert_sell_item(inter.guild.id, item["id"], price, cur["id"])

    await send_reply(
        inter,
        f"✅ 판매 상점 등록/수정 완료!\n"
        f"- 아이템: {item['name']}\n"
        f"- 판매 가격: {price} {cur['name']} (`{cur['code']}`)",
        ephemeral=True,
    )


@bot.tree.command(name="판매상점", description="현재 판매 가능한 아이템 목록을 봅니다.")
async def slash_sell_shop(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "shop"):
        return

    sell_items = await get_sell_items(inter.guild.id)
    if not sell_items:
        await send_reply(
            inter,
            "현재 판매 상점에 등록된 아이템이 없습니다.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="💰 판매 상점",
        description="`/판매 아이템이름 개수` 로 판매할 수 있어요.",
    )

    for s in sell_items:
        name = f"{s['item_name']} - 1개당 {s['price']} {s['currency_name']} (`{s['currency_code']}`)"
        value = s["item_description"] or "설명 없음"
        embed.add_field(name=name, value=value, inline=False)

    await send_reply(inter, embed=embed, ephemeral=True)


@bot.tree.command(name="판매", description="인벤토리의 아이템을 판매 상점에 판매합니다. 한번에 한 종류의 상품만 판매가능합니다.")
@app_commands.describe(
    item_name="판매할 아이템 이름",
    quantity="판매할 개수 (양수)",
)
async def slash_sell(
    inter: discord.Interaction,
    item_name: str,
    quantity: int,
):
    if not await ensure_channel_inter(inter, "shop"):
        return

    if quantity <= 0:
        await send_reply(inter, "판매 개수는 1 이상이어야 합니다.", ephemeral=True)
        return

    sell_item = await get_sell_item_by_name(inter.guild.id, item_name.strip())
    if not sell_item:
        await send_reply(
            inter,
            f"`{item_name}` 은(는) 판매 상점에 등록되어 있지 않습니다.\n"
            "`/판매상점` 으로 판매 가능한 아이템을 확인해 주세요.",
            ephemeral=True,
        )
        return

    user = await get_or_create_user(inter.guild.id, inter.user.id)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, quantity FROM inventories WHERE user_id = ? AND item_id = ?",
            (user["id"], sell_item["item_id"]),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if not row:
            await send_reply(
                inter,
                f"인벤토리에 `{sell_item['item_name']}` 이(가) 없습니다.",
                ephemeral=True,
            )
            return

        inv_id, have_qty = row
        if have_qty < quantity:
            await send_reply(
                inter,
                f"개수가 부족하여 판매할 수 없습니다.\n"
                f"- 보유: {have_qty}개\n"
                f"- 시도: {quantity}개",
                ephemeral=True,
            )
            return

        new_qty = have_qty - quantity
        if new_qty > 0:
            await db.execute(
                "UPDATE inventories SET quantity = ? WHERE id = ?",
                (new_qty, inv_id),
            )
        else:
            await db.execute(
                "DELETE FROM inventories WHERE id = ?",
                (inv_id,),
            )

        await db.commit()

    total_price = sell_item["price"] * quantity
    new_balance = await change_balance(user["id"], sell_item["currency_id"], total_price)

    await send_reply(
        inter,
        f"✅ 판매 완료!\n"
        f"- 아이템: {sell_item['item_name']} x {quantity}개\n"
        f"- 얻은 재화: {total_price} {sell_item['currency_name']} (`{sell_item['currency_code']}`)\n"
        f"- 판매 후 소지금: {new_balance} {sell_item['currency_name']}",
        ephemeral=False,
    )
@bot.tree.command(
    name="판매제거",
    description="판매 상점에서 특정 아이템을 제거합니다. (관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    item_name="판매 상점에서 제거할 아이템 이름"
)
async def slash_remove_sell_item(
    inter: discord.Interaction,
    item_name: str,
):
    # 판매등록과 동일하게 상점 채널에서만 작동하도록
    if not await ensure_channel_inter(inter, "shop"):
        return

    name = item_name.strip()

    # items 테이블에서 해당 이름의 아이템 검색
    item = await get_item_by_name(inter.guild.id, name)
    if not item:
        await send_reply(
            inter,
            f"`{name}` 이름의 아이템을 찾을 수 없습니다.",
            ephemeral=True,
        )
        return

    # 판매 상점 등록 여부 확인
    sell_data = await get_sell_item_by_name(inter.guild.id, name)
    if not sell_data:
        await send_reply(
            inter,
            f"`{name}` 은(는) 현재 판매 상점에 등록되어 있지 않습니다.",
            ephemeral=True,
        )
        return

    # 삭제 실행
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM sell_shop_items WHERE guild_id = ? AND item_id = ?",
            (inter.guild.id, item["id"]),
        )
        await db.commit()

    await send_reply(
        inter,
        f"🗑️ 판매 상점에서 **{name}** 을(를) 성공적으로 제거했습니다!",
        ephemeral=True,
    )

@bot.tree.command(
    name="관리자아이템추가",
    description="상점에 보이지 않는 관리자 전용 아이템을 추가합니다. (재고 무제한)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    name="아이템 이름",
    description="아이템 설명 (선택, 비워두면 '관리자 전용 아이템')",
    currency_identifier="기준 재화 코드 또는 이름 (예: coin, 여우코인)",
)
async def slash_add_admin_item(
    inter: discord.Interaction,
    name: str,
    description: str | None,
    currency_identifier: str,
):
    # 관리자용 봇 채널에서만 사용
    if not await ensure_channel_inter(inter, "admin"):
        return

    desc = description or "관리자 전용 아이템"

    # 어떤 재화에 속한 아이템인지(나중에 정산/보상용으로 사용 가능)
    cur = await get_currency_by_identifier(inter.guild.id, currency_identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{currency_identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
            ephemeral=True,
        )
        return

    # 가격 = 0, 재고 = None(무제한), is_shop = False → 상점 목록에는 안 뜸
    item_id = await add_item(
        inter.guild.id,
        name,
        0,              # 가격 0
        desc,           # 설명
        cur["id"],      # 기준 재화
        stock=None,     # 무제한
        is_shop=False,  # 상점에는 보이지 않음
    )

    await send_reply(
        inter,
        f"✅ 관리자 전용 아이템 추가 완료!\n"
        f"- ID: {item_id}\n"
        f"- 이름: {name}\n"
        f"- 설명: {desc}\n"
        f"- 기준 재화: {cur['name']} (`{cur['code']}`)\n"
        f"- 상점에는 표시되지 않으며, 보상/이벤트/정산 등으로만 지급할 수 있습니다.",
        ephemeral=True,
    )

# =========================================================
# 8. 낚시 전용 아이템 추가 + 낚시 확률 + 낚시
# =========================================================

@bot.tree.command(
    name="낚시아이템추가",
    description="낚시 전용 아이템을 추가합니다. (상점에 보이지 않음 / 재고 무제한)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    name="낚시로 얻을 아이템 이름",
    description="아이템 설명 (선택, 비워두면 '낚시 전용 아이템')",
    currency_identifier="기준 재화 코드 또는 이름 (가격은 0, 상점에는 안 보임)",
)
async def slash_add_fishing_item(
    inter: discord.Interaction,
    name: str,
    description: str | None,
    currency_identifier: str,
):
    if not await ensure_channel_inter(inter, "admin"):
        return

    desc = description or "낚시 전용 아이템"

    cur = await get_currency_by_identifier(inter.guild.id, currency_identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{currency_identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
            ephemeral=True,
        )
        return

    # ✅ 같은 이름의 아이템이 이미 있으면 "재사용"
    existing = await get_item_by_name(inter.guild.id, name.strip())
    if existing:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE items
                   SET price = 0,
                       description = ?,
                       stock = NULL,
                       is_shop = 0,
                       currency_id = ?
                 WHERE id = ?
                """,
                (desc, cur["id"], existing["id"]),
            )
            await db.commit()

        await send_reply(
            inter,
            f"♻ 이미 존재하는 아이템 **{existing['name']}** 을(를) 낚시 전용 아이템으로 설정했습니다.\n"
            f"- ID: {existing['id']}\n"
            f"- 설명: {desc}\n"
            f"- (상점에는 보이지 않고, 낚시/인벤토리에서만 사용됩니다.)",
            ephemeral=True,
        )
        return

    # ✅ 없으면 새로 생성
    item_id = await add_item(
        inter.guild.id,
        name,
        0,
        desc,
        cur["id"],
        stock=None,   # 무제한
        is_shop=False # 상점에는 안 보임
    )

    await send_reply(
        inter,
        f"✅ 낚시 전용 아이템 추가 완료!\n"
        f"- ID: {item_id}\n"
        f"- 이름: {name}\n"
        f"- 설명: {desc}\n"
        f"- (상점에는 보이지 않으며, 낚시/인벤토리에서만 사용됩니다.)",
        ephemeral=True,
    )




@bot.tree.command(
    name="낚시확률",
    description="낚시로 얻을 수 있는 아이템과 확률(%)을 설정합니다. (관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    item_name="낚시로 얻을 아이템 이름 (존재하지 않으면 자동 생성, 존재하면 확률만 변경)",
    chance="획득 확률(%) - 소수 가능, 예: 0.5, 10, 12.34 등",
)
async def slash_set_fishing_chance(
    inter: discord.Interaction,
    item_name: str,
    chance: float,
):
    if not await ensure_channel_inter(inter, "admin"):
        return

    if chance <= 0:
        await send_reply(inter, "확률은 0보다 커야 합니다.", ephemeral=True)
        return

    name = item_name.strip()

    # 1) 아이템 찾기 (있으면 그대로, 없으면 자동 생성)
    item = await get_item_by_name(inter.guild.id, name)
    created_new = False

    if not item:
        settings = await get_or_create_guild_settings(inter.guild.id)
        main_currency_id = settings["main_currency_id"]

        if main_currency_id is None:
            await send_reply(
                inter,
                "이 서버에 메인 재화가 아직 설정되지 않아 자동으로 낚시 아이템을 생성할 수 없습니다.\n"
                "`/재화`로 재화를 확인하고, 기본 설정을 먼저 마쳐 주세요.",
                ephemeral=True,
            )
            return

        auto_desc = f"낚시 전용 자동 생성 아이템 ({name})"
        item_id = await add_item(
            inter.guild.id,
            name,
            0,
            auto_desc,
            main_currency_id,
            stock=None,
            is_shop=False,
        )
        item = await get_item_by_id(inter.guild.id, item_id)
        created_new = True

    # 2) 이 길드의 모든 낚시 룻을 불러와서
    #    - 현재 아이템(item.id)의 기존 확률 합
    #    - 다른 아이템들의 확률 합을 분리해서 계산
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, item_id, chance FROM fishing_loot WHERE guild_id = ?",
            (inter.guild.id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()

    other_total = 0.0
    old_sum_for_this = 0.0
    ids_to_delete_for_this_item: list[int] = []

    for row in rows:
        c = float(row["chance"])
        if row["item_id"] == item["id"]:
            old_sum_for_this += c
            ids_to_delete_for_this_item.append(row["id"])
        else:
            other_total += c

    # 3) 새 확률 반영 후 전체 합 체크 (이 아이템 기존 확률은 전부 버리고 새 값만 사용)
    new_total = other_total + chance
    if new_total > 100.0 + 1e-6:
        await send_reply(
            inter,
            f"❌ 이 아이템을 {chance:.2f}% 로 설정하면 전체 확률 합이 "
            f"{new_total:.2f}% > 100% 가 됩니다.\n"
            "확률을 줄여서 다시 시도해 주세요.",
            ephemeral=True,
        )
        return

    # 4) 이 아이템에 대한 예전 레코드는 전부 삭제 → 중복 제거
    if ids_to_delete_for_this_item:
        async with aiosqlite.connect(DB_PATH) as db:
            for fid in ids_to_delete_for_this_item:
                await db.execute("DELETE FROM fishing_loot WHERE id = ?", (fid,))
            await db.commit()

    # 5) 깔끔하게 1줄만 다시 넣기
    await upsert_fishing_loot(inter.guild.id, item["id"], chance)

    total_after = new_total
    miss = max(0.0, 100.0 - total_after)

    created_msg = " (※ 새 낚시 전용 아이템 자동 생성)" if created_new else ""
    old_msg = (
        f"\n- 이전 확률(이 아이템 전체 합): {old_sum_for_this:.2f}%"
        if old_sum_for_this > 0
        else ""
    )

    await send_reply(
        inter,
        f"✅ 낚시 확률 설정 완료!{created_msg}\n"
        f"- 아이템: {item['name']}\n"
        f"- 설정 확률: {chance:.2f}%{old_msg}\n"
        f"- 현재 전체 아이템 확률 합: {total_after:.2f}%\n"
        f"- 나머지 확률(꽝): {miss:.2f}%",
        ephemeral=True,
    )





@bot.tree.command(
    name="낚시확률목록",
    description="현재 설정된 낚시 아이템과 확률 목록을 보여줍니다.",
)
async def slash_fishing_chance_list(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "admin"):
        return

    loot = await get_fishing_loot(inter.guild.id)
    if not loot:
        await send_reply(
            inter,
            "아직 설정된 낚시 아이템이 없습니다.\n`/낚시아이템추가` → `/낚시확률` 순서로 먼저 설정해 주세요.",
            ephemeral=True,
        )
        return

    total = 0.0
    lines = []
    for row in loot:
        c = float(row["chance"])
        total += c
        lines.append(f"- {row['item_name']}: {c:.2f}%")

    miss = max(0.0, 100.0 - total)
    lines.append(f"---")
    lines.append(f"- 아이템 합계: {total:.2f}%")
    lines.append(f"- 꽝(아무것도 없음): {miss:.2f}%")

    msg = "\n".join(lines)
    await send_reply(
        inter,
        f"🎣 현재 낚시 확률 목록:\n{msg}",
        ephemeral=True,
    )

@bot.tree.command(
    name="낚시확률초기화",
    description="이 서버의 모든 낚시 확률 설정을 초기화합니다. (관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_reset_fishing_chance(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "admin"):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM fishing_loot WHERE guild_id = ?",
            (inter.guild.id,),
        )
        await db.commit()

    await send_reply(
        inter,
        "🧹 이 서버의 낚시 확률 설정을 모두 초기화했습니다.\n"
        "이제 `/낚시확률` 명령으로 다시 설정해 주세요.",
        ephemeral=True,
    )


@bot.tree.command(
    name="낚시",
    description="낚시를 해서 아이템을 획득할 수 있습니다. (낚시 채널 전용)",
)
async def slash_fishing(inter: discord.Interaction):
    if not await ensure_channel_inter(inter, "fish"):
        return

    # 1) 낚시 가능한 아이템 목록 확인
    loot = await get_fishing_loot(inter.guild.id)
    if not loot:
        await send_reply(
            inter,
            "아직 낚시로 얻을 수 있는 아이템이 설정되지 않았어요.\n"
            "관리자가 `/낚시아이템추가`, `/낚시확률`로 먼저 설정해야 합니다.",
            ephemeral=True,
        )
        return

    # 2) 유저 정보 + 한국 시간(KST) 기준 오늘 날짜
    user = await get_or_create_user(inter.guild.id, inter.user.id)

    MAX_FISH_PER_DAY = 3
    today_str = get_today_kst_str()

    # 3) 오늘 낚시 횟수 확인
    current_count = await get_fishing_daily_count(inter.guild.id, user["id"], today_str)

    if current_count >= MAX_FISH_PER_DAY:
        await send_reply(
            inter,
            f"🎣 오늘은 이미 **{MAX_FISH_PER_DAY}번** 낚시를 했어요!\n"
            f"내일 다시 낚시해 주세요 😊",
            ephemeral=True,
        )
        return

    # 4) 여기서 1회 소모 처리 (성공/실패 상관없이 시도만 하면 카운트)
    new_count = await increment_fishing_daily_count(inter.guild.id, user["id"], today_str)


    # 5) 전체 아이템 확률 합 계산
    total = 0.0
    for row in loot:
        total += float(row["chance"])
    total = min(total, 100.0)  # 혹시 100 조금 넘는 오차 방어

    # 6) 0 ~ 100 구간에서 랜덤
    roll = random.random() * 100.0

    # 7) 누적 확률로 어떤 아이템이 당첨되는지 결정
    current = 0.0
    chosen = None
    for row in loot:
        c = float(row["chance"])
        if c <= 0:
            continue
        if current <= roll < current + c:
            chosen = row
            break
        current += c

    if chosen is None or roll >= total:
        # 꽝
        await send_reply(
            inter,
            f"🎣 낚시 결과: **꽝!**\n"
            f"(랜덤 값: {roll:.2f}% / 아이템 확률 합: {total:.2f}% )\n"
            f"오늘 사용한 낚시 횟수: {new_count}/{MAX_FISH_PER_DAY}",
            ephemeral=False,
        )
        return

    # 8) 당첨 아이템 인벤토리에 +1
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, quantity FROM inventories WHERE user_id = ? AND item_id = ?",
            (user["id"], chosen["item_id"]),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            inv_id, qty = row
            await db.execute(
                "UPDATE inventories SET quantity = ? WHERE id = ?",
                (qty + 1, inv_id),
            )
        else:
            await db.execute(
                "INSERT INTO inventories (user_id, item_id, quantity) VALUES (?, ?, ?)",
                (user["id"], chosen["item_id"], 1),
            )
        await db.commit()

    await send_reply(
        inter,
        f"🎣 낚시 결과: **{chosen['item_name']}** 을(를) 획득했습니다!\n"
        f"(랜덤 값: {roll:.2f} / 아이템 확률: {chosen['chance']:.2f}%)\n"
        f"오늘 사용한 낚시 횟수: {new_count}/{MAX_FISH_PER_DAY}\n"
        f"획득한 아이템은 인벤토리에 저장되었습니다. `/인벤토리` 로 확인해보세요.",
        ephemeral=False,
    )
@bot.tree.command(
    name="인벤초기화",
    description="특정 유저의 인벤토리를 전부 비웁니다. (관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    member="인벤토리를 초기화할 사용자",
)
async def slash_clear_inventory(
    inter: discord.Interaction,
    member: discord.Member,
):
    # 서버 안에서만 사용
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return

    # 관리자용 채널에서만 사용하고 싶으면 이 줄을 켜기
    # if not await ensure_channel_inter(inter, "admin"):
    #     return

    # 내부 users.id 가져오기
    user = await get_or_create_user(inter.guild.id, member.id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM inventories WHERE user_id = ?",
            (user["id"],),
        )
        await db.commit()

    await send_reply(
        inter,
        f"🧹 **{member.display_name}** 님의 인벤토리를 전부 초기화했습니다.",
        ephemeral=False,
    )

# =========================================================
# 9. 정산 / 확인 (관리자용 봇채널)
# =========================================================

@bot.tree.command(name="정산", description="특정 유저의 재화를 증감합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_settle(
    inter: discord.Interaction,
    member: discord.Member,
    amount: int,
    currency_identifier: str,
):
    # 서버 안에서만 사용, 채널 제한 없음
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return

    if amount == 0:
        await send_reply(inter, "0은 정산할 수 없어요. 양수 또는 음수 금액을 입력해주세요.", ephemeral=True)
        return

    cur = await get_currency_by_identifier(inter.guild.id, currency_identifier)
    if not cur:
        await send_reply(
            inter,
            f"`{currency_identifier}` 에 해당하는 재화를 찾을 수 없습니다. `/재화`로 확인해보세요.",
            ephemeral=True,
        )
        return

    user = await get_or_create_user(inter.guild.id, member.id)
    new_balance = await change_balance(user["id"], cur["id"], amount)

    sign = "지급" if amount > 0 else "차감"
    await send_reply(
        inter,
        f"✅ 정산 완료 ({sign})\n"
        f"- 대상: {member.mention}\n"
        f"- 재화: {cur['name']} (`{cur['code']}`)\n"
        f"- 변화량: {amount}\n"
        f"- 정산 후 소지금: {new_balance} {cur['name']}",
        ephemeral=False,
    )

@bot.tree.command(
    name="정산아이템",
    description="특정 유저에게 아이템을 지급하거나 회수합니다. (관리자)",
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    member="아이템을 줄(또는 회수할) 사용자",
    item_name="아이템 이름 (items 기준 이름)",
    quantity="지급(+), 회수(-)할 개수 (0 제외)",
)
async def slash_settle_item(
    inter: discord.Interaction,
    member: discord.Member,
    item_name: str,
    quantity: int,
):
    # 서버 안에서만 사용, 채널 제한 없음 (정산과 동일)
    if not is_guild_inter(inter):
        await send_reply(inter, "서버 안에서만 사용할 수 있어요.", ephemeral=True)
        return

    if quantity == 0:
        await send_reply(inter, "0개는 정산할 수 없어요. 양수(지급) 또는 음수(회수)를 입력해주세요.", ephemeral=True)
        return

    name = item_name.strip()
    item = await get_item_by_name(inter.guild.id, name)
    if not item:
        await send_reply(
            inter,
            f"`{name}` 이름의 아이템을 찾을 수 없습니다.\n"
            "`/아이템추가`, `/이벤트아이템추가`, `/낚시아이템추가` 등으로 먼저 아이템을 만들어 주세요.",
            ephemeral=True,
        )
        return

    user = await get_or_create_user(inter.guild.id, member.id)

    async with aiosqlite.connect(DB_PATH) as db:
        # 현재 인벤토리 보유량 확인
        cursor = await db.execute(
            "SELECT id, quantity FROM inventories WHERE user_id = ? AND item_id = ?",
            (user["id"], item["id"]),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if quantity > 0:
            # 지급
            if row:
                inv_id, have_qty = row
                await db.execute(
                    "UPDATE inventories SET quantity = ? WHERE id = ?",
                    (have_qty + quantity, inv_id),
                )
            else:
                await db.execute(
                    "INSERT INTO inventories (user_id, item_id, quantity) VALUES (?, ?, ?)",
                    (user["id"], item["id"], quantity),
                )
        else:
            # 회수 (quantity < 0)
            if not row:
                await send_reply(
                    inter,
                    f"{member.display_name} 님 인벤토리에 `{item['name']}` 이(가) 없습니다. 회수할 수 없어요.",
                    ephemeral=True,
                )
                return

            inv_id, have_qty = row
            need = -quantity  # 회수하려는 개수

            if have_qty < need:
                await send_reply(
                    inter,
                    f"회수하려는 개수가 보유량보다 많아요.\n"
                    f"- 보유: {have_qty}개\n"
                    f"- 회수 시도: {need}개",
                    ephemeral=True,
                )
                return

            new_qty = have_qty - need
            if new_qty > 0:
                await db.execute(
                    "UPDATE inventories SET quantity = ? WHERE id = ?",
                    (new_qty, inv_id),
                )
            else:
                await db.execute(
                    "DELETE FROM inventories WHERE id = ?",
                    (inv_id,),
                )

        await db.commit()

    action = "지급" if quantity > 0 else "회수"
    abs_q = abs(quantity)

    await send_reply(
        inter,
        f"✅ 아이템 정산 완료 ({action})\n"
        f"- 대상: {member.mention}\n"
        f"- 아이템: {item['name']}\n"
        f"- 개수 변화: {quantity:+}개",
        ephemeral=False,
    )


@bot.tree.command(name="확인", description="특정 유저의 소지금과 인벤토리를 확인합니다. (관리자)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_check_user(inter: discord.Interaction, member: discord.Member):
    if not await ensure_channel_inter(inter, "admin"):
        return

    user = await get_or_create_user(inter.guild.id, member.id)

    currencies = await list_currencies(inter.guild.id)
    balance_lines = []
    for cur in currencies:
        amount = await get_balance(user["id"], cur["id"])
        balance_lines.append(f"- {cur['name']} (`{cur['code']}`): {amount}")
    balance_text = "\n".join(balance_lines) if balance_lines else "재화 정보 없음"

    inv = await get_inventory(user["id"])
    if inv:
        inv_lines = []
        for item in inv:
            line = f"- {item['name']} x {item['quantity']}개"
            if item["description"]:
                line += f" ({item['description']})"
            inv_lines.append(line)
        inv_text = "\n".join(inv_lines)
    else:
        inv_text = "인벤토리가 비어 있습니다."

    await send_reply(
        inter,
        f"👤 **{member.display_name}** 님 정보\n\n"
        f"💰 소지금:\n{balance_text}\n\n"
        f"🎒 인벤토리:\n{inv_text}",
        ephemeral=True,
    )


# =========================================================
# 10. /설명 : 채널별로 다른 명령어 설명
# =========================================================

@bot.tree.command(name="설명", description="현재 채널에서 사용 가능한 명령어 설명을 보여줍니다.")
async def slash_help(inter: discord.Interaction):

    if not is_guild_inter(inter):
        await send_reply(inter, "서버에서만 사용 가능합니다.", ephemeral=True)
        return

    guild_id = inter.guild.id
    channel_id = inter.channel.id

    settings = await get_or_create_guild_settings(guild_id)
    attend_channel = settings["attend_channel_id"]
    shop_channel = settings["shop_channel_id"]
    user_channel = await get_user_channel_id(guild_id)
    admin_channel = await get_admin_channel_id(guild_id)
    fishing_channel = await get_fishing_channel_id(guild_id)
    trade_channel = await get_trade_channel_id(guild_id)

    is_admin = inter.user.guild_permissions.manage_guild

    embed = discord.Embed(
        title="📘 명령어 설명",
        description="현재 채널에서 사용 가능한 명령어 목록입니다.",
        color=0x5DADEC,
    )

    # 공통 (어디서나)
    cmds_common = [
        ("`/설명`", "현재 채널에서 사용 가능한 명령어 설명을 보여줍니다.")
    ]

    # 사용자 채널(소지금/인벤토리 등)
    cmds_user = [
        ("`/재화`", "서버 재화 목록 보기"),
        ("`/소지금`", "자신의 소지금 확인"),
        ("`/인벤토리`", "자신의 인벤토리 확인"),
    ]

    # 거래 채널(선물 전용)
    cmds_trade = [
        ("`/재화선물`", "다른 사용자에게 재화를 선물"),
        ("`/아이템선물`", "다른 사용자에게 아이템을 선물"),
    ]


    # 출석 채널
    cmds_attend = [
        ("`/출석`", "출석하고 보상을 받습니다."),
    ]

    # 상점 채널
    cmds_shop = [
        ("`/상점`", "일반 상점 보기"),
        ("`/이벤트상점`", "이벤트 상점 보기"),
        ("`/구매`", "상점 아이템 구매"),
        ("`/판매상점`", "판매 가능한 아이템 목록 확인"),
        ("`/판매`", "인벤토리 아이템 판매"),
    ]

    # 낚시 채널
    cmds_fish = [
        ("`/낚시`", "낚시를 해서 아이템을 획득합니다."),
    ]

    # 관리자 전용
    cmds_admin = [
        ("`/출석채널설정`", "출석 채널 설정"),
        ("`/상점채널설정`", "상점 채널 설정"),
        ("`/명령어채널설정`", "관리자 채널 설정"),
        ("`/사용자채널설정`", "사용자 채널 설정"),
        ("`/낚시채널설정`", "낚시 채널 설정"),
        ("`/거래채널설정`", "거래 채널 설정 (재화/아이템 선물)"),
        ("`/재화추가`", "새 재화 등록"),
        ("`/재화활성 / 재화비활성`", "재화 활성/비활성"),
        ("`/재화삭제`", "재화 삭제"),
        ("`/출석재화설정`", "출석 보상 재화 변경"),
        ("`/메인재화설정`", "메인 재화 이름 변경"),
        ("`/아이템추가`", "일반 상점 아이템 추가"),
        ("`/이벤트아이템추가`", "이벤트 상점 아이템 추가"),
        ("`/아이템삭제`", "아이템 삭제"),
        ("`/판매등록`", "판매 상점 아이템 등록/수정"),
        ("`/낚시아이템추가`", "낚시 전용 아이템 추가"),
        ("`/낚시확률`", "낚시 아이템 확률 설정"),
        ("`/낚시확률목록`", "낚시 확률 목록 보기"),
        ("`/정산`", "특정 사용자 재화 증감"),
        ("`/확인`", "특정 사용자 소지금 + 인벤토리 확인"),
    ]

    in_attend = (attend_channel is not None and channel_id == attend_channel)
    in_shop = (shop_channel is not None and channel_id == shop_channel)
    in_user = (user_channel is not None and channel_id == user_channel)
    in_admin = (admin_channel is not None and channel_id == admin_channel)
    in_fish = (fishing_channel is not None and channel_id == fishing_channel)
    in_trade = (trade_channel is not None and channel_id == trade_channel)


    embed.add_field(
        name="🔹 공통 명령어",
        value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_common]),
        inline=False,
    )

    if is_admin:
        embed.add_field(
            name="🔹 출석 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_attend]),
            inline=False,
        )
        embed.add_field(
            name="🔹 상점 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_shop]),
            inline=False,
        )
        embed.add_field(
            name="🔹 사용자 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_user]),
            inline=False,
        )
        embed.add_field(
            name="🔹 거래 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_trade]),
            inline=False,
        )
        embed.add_field(
            name="🔹 낚시 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_fish]),
            inline=False,
        )
        embed.add_field(
            name="🔹 관리자 전용 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_admin]),
            inline=False,
        )
        await send_reply(inter, embed=embed, ephemeral=True)
        return

    if in_attend:
        embed.add_field(
            name="🔹 출석 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_attend]),
            inline=False,
        )

    if in_shop:
        embed.add_field(
            name="🔹 상점 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_shop]),
            inline=False,
        )

    if in_user:
        embed.add_field(
            name="🔹 사용자 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_user]),
            inline=False,
        )
    if in_trade:
        embed.add_field(
            name="🔹 거래 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_trade]),
            inline=False,
        )
    if in_fish:
        embed.add_field(
            name="🔹 낚시 채널 명령어",
            value="\n".join([f"{cmd} — {desc}" for cmd, desc in cmds_fish]),
            inline=False,
        )

    await send_reply(inter, embed=embed, ephemeral=True)


# =========================================================
# (옵션) 슬래시 명령 전체 정리용 - 한 번 실행 후 계속 쓸 필요 없음
# =========================================================

@bot.command(name="clearallslash")
@commands.is_owner()
async def clear_all_slash_commands(ctx: commands.Context):
    """이 봇이 등록해둔 슬래시 명령(글로벌 + 길드)을 전부 정리합니다. (봇 주인만 사용 가능)"""

    bot.tree.clear_commands(guild=None)
    global_sync_result = await bot.tree.sync()

    removed_guilds = []
    for guild in bot.guilds:
        bot.tree.clear_commands(guild=guild)
        guild_sync_result = await bot.tree.sync(guild=guild)
        removed_guilds.append(f"{guild.name}({guild.id}): {len(guild_sync_result)}개 제거")

    msg = "✅ 슬래시 명령 정리 완료!\n"
    msg += f"- 글로벌 명령: {len(global_sync_result)}개\n"
    if removed_guilds:
        msg += "- 길드별 제거 결과:\n" + "\n".join(f"  • {line}" for line in removed_guilds)

    await ctx.send(msg)


# =========================================================
# 봇 실행
# =========================================================

bot.run(TOKEN)
