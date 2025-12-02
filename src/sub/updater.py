from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING
import requests

from src.fmt import parse_subscription_content, ProxyBean
from src.db import DataStore

if TYPE_CHECKING:
    from src.db.profiles import ProfileManager


class SubscriptionUpdater:
    """Subscription update manager."""
    
    def __init__(
        self,
        config: Optional[DataStore] = None,
        profiles: Optional['ProfileManager'] = None,
    ):
        self._config = config
        self._profiles = profiles
    
    def fetch(self, url: str) -> str:
        """Fetch subscription content."""
        headers = {}
        
        if self._config:
            user_agent = self._config.get_user_agent()
            if user_agent:
                headers['User-Agent'] = user_agent
        
        verify = True
        if self._config and self._config.sub_insecure:
            verify = False
        
        response = requests.get(url, headers=headers, timeout=30, verify=verify)
        response.raise_for_status()
        
        return response.text
    
    def parse(self, content: str) -> List[ProxyBean]:
        """Parse subscription content."""
        return parse_subscription_content(content)
    
    def update(
        self,
        url: str,
        group_id: Optional[int] = None,
        clear_existing: bool = True,
    ) -> List[ProxyBean]:
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
    config: Optional[DataStore] = None,
    profiles: Optional['ProfileManager'] = None,
    group_id: Optional[int] = None,
    clear_existing: bool = True,
) -> List[ProxyBean]:
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
