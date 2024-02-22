import os
import sys
from pathlib import Path

from httpx import URL

WINDOWS = sys.platform.startswith("win") or (sys.platform == "cli" and os.name == "nt")

BASE_DIR: Path = Path(__file__).parent.parent.absolute()

TEMP_DIR = BASE_DIR / "temp"
FBS_DIR = BASE_DIR / "OpenArknightsFBS" / "FBS"
ASSETS_DIR = BASE_DIR / "assets"

STORAGE_DIR = BASE_DIR / "storage"
GAMEDATA_DIR = STORAGE_DIR / "asset" / "gamedata"
HOT_UPDATE_LIST_DIR = STORAGE_DIR / "hot_update_list"

HEADERS = {
    "user-agent": "Dalvik/2.1.0 (Linux; U; Android 6.0.1; vivo X9L Build/MMB29M)"
}

WIKI_API_ENDPOINT = URL("https://prts.wiki/api.php")
HG_CN_BASEURL = URL("https://ak.hycdn.cn/assetbundle/official/Android/assets/")

PROFESSIONS = {
    "PIONEER": "先锋",
    "WARRIOR": "近卫",
    "SNIPER": "狙击",
    "SUPPORT": "辅助",
    "CASTER": "术师",
    "SPECIAL": "特种",
    "MEDIC": "医疗",
    "TANK": "重装",
}
