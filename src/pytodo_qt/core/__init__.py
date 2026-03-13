"""pytodo-qt.core: Core functionality and data models.

Provides:
- Configuration management (TOML-based)
- XDG-compliant path management
- Data models with UUID and sync support
- SQLite database storage
- JSON to SQLite migration
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
from .database import (
    SCHEMA_VERSION,
    DatabaseError,
    DatabaseStorage,
)
from .instance_lock import InstanceLock
from .migration import (
    MigrationError,
    get_migration_status,
    migrate_json_to_sqlite,
    needs_migration,
)
from .models import (
    Database,
    TodoItem,
    TodoList,
    create_todo_item,
    create_todo_list,
)
from .nlp_parser import EntityKind, EntitySpan, ParseResult, parse
from .paths import (
    get_config_dir,
    get_config_file,
    get_data_dir,
    get_database_file,
    get_legacy_json_database,
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
    # Database Storage
    "DatabaseStorage",
    # Instance lock
    "InstanceLock",
    # NLP Parser
    "EntityKind",
    "EntitySpan",
    "ParseResult",
    "parse",
    "DatabaseError",
    "SCHEMA_VERSION",
    # Migration
    "MigrationError",
    "migrate_json_to_sqlite",
    "needs_migration",
    "get_migration_status",
    # Paths
    "get_config_dir",
    "get_config_file",
    "get_data_dir",
    "get_database_file",
    "get_legacy_json_database",
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
