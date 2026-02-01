"""settings.py

Application settings and version information.
"""

from . import paths
from .config import AppConfig, get_config_manager
from .logger import Logger

logger = Logger(__name__)


__version__ = "0.3.3"

# Config manager singleton
_config_mgr = None


def init_config() -> AppConfig:
    """Initialize configuration system."""
    global _config_mgr
    _config_mgr = get_config_manager()
    return _config_mgr.config


def save_config() -> bool:
    """Save current configuration."""
    if _config_mgr is not None:
        return _config_mgr.save()
    return False


# XDG-compliant directories
config_dir = paths.get_config_dir()
data_dir = paths.get_data_dir()
state_dir = paths.get_state_dir()

# XDG-compliant file paths
config_fn = paths.get_config_file()
db_fn = paths.get_database_file()
log_fn = paths.get_log_file()
