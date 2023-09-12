from importlib.metadata import version

from .config import Config

try:
    __version__ = version("torappu")
except Exception:
    __version__ = None

_config = Config()


def get_config():
    return _config
