"""pytodo-qt.core: Core functionality and data models.

Provides:
- Configuration management (TOML-based)
- XDG-compliant path management
- Data models with UUID and sync support
- Synchronization engine with LWW merge
"""

from .config import (
    AppConfig,
    AppearanceConfig,
    ConfigManager,
    DatabaseConfig,
    DiscoveryConfig,
    SecurityConfig,
    ServerConfig,
    get_config,
    get_config_manager,
)
from .models import (
    Database,
    TodoItem,
    TodoList,
    create_todo_item,
    create_todo_list,
)
from .paths import (
    get_config_dir,
    get_config_file,
    get_data_dir,
    get_database_file,
    get_log_file,
    get_state_dir,
    get_xdg_config_home,
    get_xdg_data_home,
    get_xdg_state_home,
)
from .sync_engine import (
    ConflictInfo,
    MergeResult,
    SyncEngine,
    get_sync_engine,
    merge_databases,
)

__all__ = [
    # Config
    "AppConfig",
    "ConfigManager",
    "DatabaseConfig",
    "ServerConfig",
    "SecurityConfig",
    "DiscoveryConfig",
    "AppearanceConfig",
    "get_config",
    "get_config_manager",
    # Paths
    "get_config_dir",
    "get_config_file",
    "get_data_dir",
    "get_database_file",
    "get_log_file",
    "get_state_dir",
    "get_xdg_config_home",
    "get_xdg_data_home",
    "get_xdg_state_home",
    # Models
    "Database",
    "TodoItem",
    "TodoList",
    "create_todo_item",
    "create_todo_list",
    # Sync
    "ConflictInfo",
    "MergeResult",
    "SyncEngine",
    "get_sync_engine",
    "merge_databases",
]
