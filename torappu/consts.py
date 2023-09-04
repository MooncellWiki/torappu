from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.absolute()
STORAGE_DIR = BASE_DIR / "storage"
TEMP_DIR = BASE_DIR / "temp"
FBS_DIR = BASE_DIR / "OpenArknightsFBS" / "FBS"
GAMEDATA_DIR = STORAGE_DIR / "asset" / "gamedata"
HEADERS = {
    "user-agent": "Dalvik/2.1.0 (Linux; U; Android 6.0.1; vivo X9L Build/MMB29M)"
}
WIKI_API_ENDPOINT = "https://prts.wiki/api.php"
HG_CN_BASEURL = "https://ak.hycdn.cn/assetbundle/official/Android/assets/"
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
