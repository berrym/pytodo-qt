"""sync_operations.py

Network synchronization enums.
"""

from enum import Enum


sync_operations = Enum(
    value="OPERATION",
    names=[
        ("PUSH_REQUEST", 1),
        ("PULL_REQUEST", 2),
        ("REJECT", 3),
        ("ACCEPT", 4),
        ("NO_DATA", 5),
    ],
)
