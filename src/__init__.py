"""
Tenga - Python proxy client.
"""

__version__ = "2.0.0"
__app_name__ = "Tenga"

from src.core import AppContext, get_context, init_context

__all__ = [
    '__version__',
    '__app_name__',
    'AppContext',
    'get_context', 
    'init_context',
]


