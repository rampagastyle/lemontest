import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [int(id_.strip()) for id_ in os.getenv("ADMIN_IDS", "").split(",") if id_.strip()]
VK_API_TOKEN = os.getenv("VK_API_TOKEN", "")
VK_API_VERSION = "5.131"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VK_COMMUNITY_ID = os.getenv("VK_COMMUNITY_ID", "")
