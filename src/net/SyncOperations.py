from enum import Enum


SyncOperations = Enum(
    value="OPERATION",
    names=[
        ("PUSH_REQUEST", 1),
        ("PULL_REQUEST", 2),
        ("ACCEPT", 3),
        ("REJECT", 4),
        ("NO_DATA", 5),
    ],
)
