# test_bot.py  ─ 최소 슬래시 명령 테스트용
import discord
from discord.ext import commands
from discord import app_commands
from settings import TOKEN

intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ 로그인: {bot.user} (ID: {bot.user.id})")
    # 슬래시 명령 전부 동기화 (전역)
    cmds = await bot.tree.sync()
    print(f"✅ 전역 슬래시 명령 동기화: {len(cmds)}개")


@bot.tree.command(name="핑", description="pong을 돌려주는 테스트 명령어입니다.")
async def ping(inter: discord.Interaction):
    await inter.response.send_message("pong!", ephemeral=True)


bot.run(TOKEN)
