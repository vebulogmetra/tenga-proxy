from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

from src.core.config import CORE_DIR, find_singbox_binary

if TYPE_CHECKING:
    from src.core.singbox_manager import SingBoxManager
    from src.db.data_store import DataStore
    from src.db.profiles import ProfileManager


@dataclass
class ProxyState:
    """Proxy state."""
    is_running: bool = False
    started_profile_id: int = -1
    upload_bytes: int = 0
    download_bytes: int = 0
    vpn_auto_connected: bool = False
    
    # Listeners
    _state_listeners: List[Callable[['ProxyState'], None]] = field(default_factory=list)
    
    def add_listener(self, callback: Callable[['ProxyState'], None]) -> None:
        """Add a state change listener."""
        if callback not in self._state_listeners:
            self._state_listeners.append(callback)
    
    def remove_listener(self, callback: Callable[['ProxyState'], None]) -> None:
        """Remove a listener."""
        if callback in self._state_listeners:
            self._state_listeners.remove(callback)
    
    def notify_listeners(self) -> None:
        """Notify listeners of state change."""
        for listener in self._state_listeners:
            try:
                listener(self)
            except Exception as e:
                print(f"Error in state listener: {e}")
    
    def set_running(self, profile_id: int) -> None:
        """Set state to running."""
        self.is_running = True
        self.started_profile_id = profile_id
        self.notify_listeners()
    
    def set_stopped(self) -> None:
        """Set state to stopped."""
        self.is_running = False
        self.started_profile_id = -1
        self.upload_bytes = 0
        self.download_bytes = 0
        self.notify_listeners()


class AppContext:
    """
    Central application context.
    Contains all main dependencies and state.
    """
    
    def __init__(
        self,
        config_dir: Optional[Path] = None,
        config: Optional['DataStore'] = None,
    ):
        self._config_dir = config_dir or self._get_default_config_dir()
        self._config: Optional['DataStore'] = config
        self._profiles: Optional['ProfileManager'] = None
        self._singbox_manager: Optional['SingBoxManager'] = None
        self._proxy_state = ProxyState()
        
        # Ensure config dir exists
        self._config_dir.mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def _get_default_config_dir() -> Path:
        """Get default configuration directory."""
        return CORE_DIR
    
    @property
    def config_dir(self) -> Path:
        """Configuration directory."""
        return self._config_dir
    
    @property
    def config(self) -> 'DataStore':
        """Application settings (lazy loading)."""
        if self._config is None:
            from src.db.data_store import DataStore
            config_file = self._config_dir / "settings.json"
            self._config = DataStore.load(config_file)
        return self._config
    
    @property
    def profiles(self) -> 'ProfileManager':
        """Profile manager (lazy loading)."""
        if self._profiles is None:
            from src.db.profiles import ProfileManager
            profiles_dir = self._config_dir / "profiles"
            self._profiles = ProfileManager(profiles_dir)
            self._profiles.load()
        return self._profiles
    
    @property
    def singbox_manager(self) -> 'SingBoxManager':
        """
        Sing-box manager (lazy loading).
        
        Created on first access.
        SingBoxManager will automatically find sing-box in core/bin/ or in system PATH.
        """
        if self._singbox_manager is None:
            from src.core.singbox_manager import SingBoxManager
            self._singbox_manager = SingBoxManager(binary_path=None)
        return self._singbox_manager
    
    @property
    def proxy_state(self) -> ProxyState:
        """Proxy state."""
        return self._proxy_state
    
    def find_singbox_binary(self) -> Optional[str]:
        """Find sing-box binary."""
        return find_singbox_binary()
    
    def save_config(self) -> bool:
        """Save configuration."""
        if self._config is None:
            return False
        config_file = self._config_dir / "settings.json"
        return self._config.save(config_file)
    
    def save_profiles(self) -> bool:
        """Save profiles."""
        if self._profiles is None:
            return False
        return self._profiles.save()
    
    def save_all(self) -> bool:
        """Save everything."""
        config_ok = self.save_config()
        profiles_ok = self.save_profiles()
        return config_ok and profiles_ok
    

_context: Optional[AppContext] = None


def get_context() -> AppContext:
    """
    Get global application context.
    Creates context with default settings if not initialized.
    """
    global _context
    if _context is None:
        _context = AppContext()
    return _context


def init_context(
    config_dir: Optional[Path] = None,
    config: Optional['DataStore'] = None,
) -> AppContext:
    """
    Initialize global context.
    Should be called once at application startup.
    """
    global _context
    _context = AppContext(config_dir=config_dir, config=config)
    return _context


def reset_context() -> None:
    """Reset context (for tests)."""
    global _context
    _context = None
