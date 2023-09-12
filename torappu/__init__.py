from importlib.metadata import version

try:
    __version__ = version("torappu")
except Exception:
    __version__ = None
