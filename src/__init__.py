__version__ = "0.7.0"
__app_name__ = "Tenga Proxy"
__app_description__ = (
    "Клиент прокси с бекэндом <a href='https://github.com/XTLS/Xray-core'>xray-core</a>"
)
__app_author__ = "Artem G."
__app_website__ = "https://github.com/vebulogmetra/tenga-proxy"

from src.core import AppContext, get_context, init_context

__all__ = [
    "AppContext",
    "__app_author__",
    "__app_description__",
    "__app_name__",
    "__app_website__",
    "__version__",
    "get_context",
    "init_context",
]
