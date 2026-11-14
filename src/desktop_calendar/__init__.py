from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("desktop-calendar")
except PackageNotFoundError:
    __version__ = "0.0.0"