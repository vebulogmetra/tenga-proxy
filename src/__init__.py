__version__ = "1.2.5"
__app_name__ = "Tenga Proxy"
__app_description__ = "Клиент для управления прокси на основе <a href='https://github.com/SagerNet/sing-box'>sing-box</a>"
__app_author__ = "Artem G."
__app_website__ = "https://github.com/vebulogmetra/tenga-proxy"

from src.core import AppContext, get_context, init_context

__all__ = [
    '__version__',
    '__app_name__',
    '__app_description__',
    '__app_author__',
    '__app_website__',
    'AppContext',
    'get_context', 
    'init_context',
]
