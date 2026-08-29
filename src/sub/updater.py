from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import requests

from src.db import DataStore
from src.fmt import ProxyBean, parse_subscription_content

if TYPE_CHECKING:
    from src.db.profiles import ProfileManager

logger = logging.getLogger("tenga.sub.updater")


class SubscriptionUpdater:
    """Subscription update manager."""

    MAX_ATTEMPTS = 3
    RETRY_BASE_DELAY_SEC = 1.0

    def __init__(
        self,
        config: DataStore | None = None,
        profiles: ProfileManager | None = None,
    ):
        self._config = config
        self._profiles = profiles

    def fetch(self, url: str) -> str:
        """Fetch subscription content."""
        headers = {}

        if self._config:
            user_agent = self._config.get_user_agent()
            if user_agent:
                headers["User-Agent"] = user_agent

        verify = True
        if self._config and self._config.sub_insecure:
            verify = False

        last_error: requests.RequestException | None = None
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                response = requests.get(url, headers=headers, timeout=30, verify=verify)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                # Повторяем только сетевые сбои: HTTP-код — окончательный ответ
                # сервера, повтор лишь задержит обновление.
                if not self._is_retryable(e) or attempt == self.MAX_ATTEMPTS - 1:
                    raise
                last_error = e
                delay = self.RETRY_BASE_DELAY_SEC * (2**attempt)
                logger.warning(
                    "Попытка %d/%d загрузить подписку не удалась (%s), повтор через %.1f с",
                    attempt + 1,
                    self.MAX_ATTEMPTS,
                    e,
                    delay,
                )
                time.sleep(delay)

        # Недостижимо: последняя попытка либо возвращает результат, либо бросает.
        raise last_error or requests.RequestException("Не удалось загрузить подписку")

    @staticmethod
    def _is_retryable(error: requests.RequestException) -> bool:
        """Стоит ли повторять запрос.

        HTTPError — это ответ сервера (404/403/500), повтор ничего не изменит.
        Обрывы соединения и таймауты обычно разовые.
        """
        if isinstance(error, requests.HTTPError):
            return False
        return isinstance(error, (requests.ConnectionError, requests.Timeout))

    def parse(self, content: str) -> list[ProxyBean]:
        """Parse subscription content."""
        return parse_subscription_content(content)

    def update(
        self,
        url: str,
        group_id: int | None = None,
        clear_existing: bool = True,
    ) -> list[ProxyBean]:
        """
        Update subscription.

        Args:
            url: Subscription URL
            group_id: Group ID for adding profiles
            clear_existing: Clear existing profiles in group

        Returns:
            List of added profiles
        """

        content = self.fetch(url)

        beans = self.parse(content)
        # Add to profiles
        if self._profiles and beans:
            if group_id is None:
                group_id = self._profiles.current_group_id

            if clear_existing:
                self._profiles.clear_group(group_id)

            for bean in beans:
                self._profiles.add_profile(bean, group_id)

            self._profiles.save()

        return beans


def update_subscription(
    url: str,
    config: DataStore | None = None,
    profiles: ProfileManager | None = None,
    group_id: int | None = None,
    clear_existing: bool = True,
) -> list[ProxyBean]:
    """
    Update subscription (helper function).

    Args:
        url: Subscription URL
        config: Configuration (for User-Agent etc.)
        profiles: Profile manager
        group_id: Group ID
        clear_existing: Clear existing profiles

    Returns:
        List of added profiles
    """
    updater = SubscriptionUpdater(config=config, profiles=profiles)
    return updater.update(url, group_id, clear_existing)
