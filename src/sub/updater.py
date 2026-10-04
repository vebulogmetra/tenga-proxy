from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import requests

from src.db import DataStore
from src.fmt import ProxyBean, parse_subscription_content
from src.sub.errors import (
    MAX_RESPONSE_SIZE,
    SubscriptionHttpError,
    SubscriptionTooLargeError,
    snippet_of,
)
from src.sub.metadata import apply_metadata, read_metadata

if TYPE_CHECKING:
    from src.db.profiles import ProfileManager

logger = logging.getLogger("tenga.sub.updater")


@dataclass(frozen=True)
class FetchedSubscription:
    """Тело ответа и его заголовки: в заголовках провайдер передаёт метаданные."""

    content: str
    headers: Mapping[str, str] = field(default_factory=dict)


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
        return self.fetch_response(url).content

    def fetch_response(self, url: str) -> FetchedSubscription:
        """Fetch subscription content together with the response headers."""
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
                self._raise_for_status(response)
                content = self._decode(response)
                # Как в Android: проверяется уже прочитанное тело. Защищает разбор
                # от гигантского ответа, но не саму загрузку.
                if len(content) > MAX_RESPONSE_SIZE:
                    raise SubscriptionTooLargeError(len(content))
                return FetchedSubscription(content, self._response_headers(response))
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
    def _response_headers(response: requests.Response) -> Mapping[str, str]:
        headers = getattr(response, "headers", None)
        # Заглушки ответов в тестах заголовков не имеют.
        return headers if isinstance(headers, Mapping) else {}

    @classmethod
    def _raise_for_status(cls, response: requests.Response) -> None:
        """Turn an HTTP error into one carrying the start of the response body."""
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            status = getattr(response, "status_code", 0)
            raise SubscriptionHttpError(
                status if isinstance(status, int) else 0,
                snippet_of(cls._decode(response)),
            ) from e

    @staticmethod
    def _decode(response: requests.Response) -> str:
        """Read the body as text, assuming UTF-8 when no charset is declared.

        Без charset в Content-Type requests по RFC 2616 берёт ISO-8859-1, и имена
        профилей с кириллицей или эмодзи приходят искажёнными. Подписки почти
        всегда в UTF-8, поэтому явно объявленную кодировку уважаем, а
        подставленную по умолчанию — нет.
        """
        try:
            content_type = response.headers.get("Content-Type", "") or ""
            if "charset=" in content_type.lower() and response.encoding:
                return response.text
            return response.content.decode("utf-8", errors="replace")
        except (AttributeError, TypeError, UnicodeDecodeError):
            # Ответ без привычных полей (нестандартный транспорт, заглушка в
            # тестах): текст всё равно нужно вернуть, а не уронить обновление.
            return response.text

    @staticmethod
    def _is_retryable(error: requests.RequestException) -> bool:
        """Стоит ли повторять запрос.

        HTTPError — это ответ сервера (404/403/500), повтор ничего не изменит.
        Обрывы соединения и таймауты обычно разовые.
        """
        if isinstance(error, (requests.HTTPError, SubscriptionTooLargeError)):
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

        fetched = self.fetch_response(url)
        beans = self.parse(fetched.content)
        if not self._profiles:
            return beans

        if group_id is None:
            group_id = self._profiles.current_group_id
        group = self._profiles.get_group(group_id)

        # До проверки списка: истёкшая подписка отдаёт ноль серверов, но срок и
        # объявление провайдера в ответе есть — их и нужно показать.
        if group is not None:
            apply_metadata(group, read_metadata(fetched.headers, fetched.content))

        if beans:
            if clear_existing:
                # Не clear_group + add_profile: так профили получали новые id, и
                # подключённый профиль, замеры и персональные настройки терялись.
                self._profiles.sync_group(group_id, beans)
            else:
                for bean in beans:
                    self._profiles.add_profile(bean, group_id)

            if group is not None:
                group.last_updated = int(time.time())

        if beans or group is not None:
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
