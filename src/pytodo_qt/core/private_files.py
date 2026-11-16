"""private_files.py

Files and directories that only the account running the application can
read.

The application keeps private keys, the tokens of paired devices, the
task database and its log under the account's home directory. Created
with the process's default permissions, they are readable by every other
account on the machine. The functions here create them without access
for group and others, and take that access away from the ones an earlier
version created.

POSIX permissions do not apply on Windows, where the directories are
inside the user profile and its access list already limits them to the
account; there the functions that change permissions do nothing.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path

from .logger import Logger

logger = Logger(__name__)

_GROUP_AND_OTHERS = stat.S_IRWXG | stat.S_IRWXO


def write_private_file(path: Path, data: bytes) -> None:
    """Write data to path so that no other account can read it at any moment.

    The data goes to a new file beside path, which is created readable
    and writable by the owner only, and that file then takes path's
    place in one step. A file already at path is neither readable while
    it is being rewritten nor left half-written, whatever its
    permissions were.
    """
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def create_private_file(path: Path) -> None:
    """Create an empty file at path for the owner only, unless one exists.

    For a file another library then opens and fills, such as an SQLite
    database: SQLite gives the files it keeps beside a database the
    database's own permissions.
    """
    with contextlib.suppress(FileExistsError):
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))


def make_private(path: Path) -> None:
    """Take access to an existing file or directory away from group and others.

    The owner's own permissions are left as they are. A path that does
    not exist is passed over, and a failure is logged and not raised:
    the caller goes on with a file it could not tighten.
    """
    if os.name == "nt":
        return
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & _GROUP_AND_OTHERS:
            path.chmod(mode & ~_GROUP_AND_OTHERS)
            logger.log.info("Removed access for other accounts from %s", path)
    except FileNotFoundError:
        return
    except OSError as e:
        logger.log.warning("Could not restrict access to %s: %s", path, e)


def ensure_private_dir(path: Path) -> None:
    """Create a directory for the owner only, or restrict one that exists.

    The XDG Base Directory Specification asks for mode 0700 on a
    directory created to hold an application's files. Only the directory
    itself is touched, never its parents.
    """
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
        return
    make_private(path)
