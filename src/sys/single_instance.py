"""Защита от второго экземпляра. Реализация выбирается по ОС."""

from src.sys.linux.single_instance import SingleInstance

__all__ = ["SingleInstance"]
