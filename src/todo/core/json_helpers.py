import json
import os
import sys

from todo.core import error_on_none_db, settings
from todo.core.Logger import Logger


logger = Logger(__name__)


def merge_todo_lists(*todo_lists):
    """Merge to-do lists keeping only unique entries."""
    logger.log.info("Merging to-do lists")
    new_lists = {}
    for list_entry in todo_lists:
        for k in list_entry:
            new_lists[k] = list_entry[k]

    return new_lists


@error_on_none_db
def read_json_data(fn=settings.lists_fn):
    """Read in to-do lists from a JSON file."""
    if not os.path.exists(fn):
        msg = f"JSON file {fn} does not exist"
        logger.log.warning(msg)
        return False, msg

    logger.log.info("Reading JSON file %s", fn)
    try:
        with open(fn, "r", encoding="utf-8") as f:
            # Merge lists
            if len(settings.db.todo_lists) > 0:
                todo_lists = json.load(f)
                new_lists = merge_todo_lists(settings.db.todo_lists, todo_lists)
                settings.db.todo_lists = new_lists
            else:
                settings.db.todo_lists = json.load(f)
    except IOError as e:
        logger.log.exception("Error reading JSON file %s: %s", fn, e)
        return False, e

    # set active list
    if settings.options is not None and "active_list" in settings.options:
        if settings.options["active_list"]:
            settings.db.active_list = settings.options["active_list"]
        elif len(settings.db.todo_lists) == 0:
            msg = "No JSON data to read"
            logger.log.warning(f"{msg}")
            return False, msg
        else:
            for list_entry in settings.db.todo_lists:
                settings.db.active_list = list_entry
                logger.log.info("%s set as active_list", list_entry)
    else:
        logger.log.exception("settings.options does not exist, exiting")
        sys.exit(1)

    settings.db.list_count = len(settings.db.todo_lists.keys())
    settings.db.todo_total = 0
    for list_entry in settings.db.todo_lists.values():
        settings.db.todo_total += len(list_entry)

    msg = f"Successfully read JSON file {fn}"
    logger.log.info(f"{msg}")
    return True, msg


@error_on_none_db
def write_json_data(fn=settings.lists_fn):
    """Write to-do lists as a JSON file."""
    logger.log.info("Writing JSON file %s", fn)
    try:
        with open(fn, "w+", encoding="utf-8") as f:
            if settings.db.todo_lists is not None:
                json.dump(settings.db.todo_lists, f, indent=2)
            else:
                logger.log.exception("settings.db.todo_lists does not exist, exiting")
                sys.exit(1)
    except IOError as e:
        msg = f"Error writing JSON file {fn}: {e}"
        logger.log.exception(msg)
        return False, msg

    msg = f"Successfully wrote JSON file {fn}"
    logger.log.info(msg)
    return True, msg
