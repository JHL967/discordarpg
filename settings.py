import os
from dotenv import load_dotenv

load_dotenv()  # .env 파일을 읽어서 환경 변수로 등록
TOKEN = os.getenv("DISCORD_TOKEN")
