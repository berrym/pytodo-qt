import json
import os

from src.core import core
from src.core.Logger import Logger

logger = Logger(__name__)


def merge_todo_lists(*todo_lists):
    """Merge todo lists keeping only unique values."""
    logger.log.info("Merging todo lists")
    new_lists = {}
    for list_entry in todo_lists:
        for k in list_entry:
            new_lists[k] = list_entry[k]

    return new_lists


def read_json_data(fn=core.lists_fn):
    """Read in todo lists from a JSON file."""
    if not os.path.exists(fn):
        msg = f"JSON file {fn} does not exist"
        logger.log.warning(msg)
        return False, msg

    logger.log.info(f"Reading JSON file {fn}")
    try:
        with open(fn, "r", encoding="utf-8") as f:
            # Merge lists
            if len(core.db.todo_lists) > 0:
                todo_lists = json.load(f)
                new_lists = merge_todo_lists(core.db.todo_lists, todo_lists)
                core.db.todo_lists = new_lists
            else:
                core.db.todo_lists = json.load(f)
    except IOError as e:
        logger.log.exception(f"Error reading JSON file {fn}: {e}")
        return False, e

    # set active list
    if core.options["active_list"]:
        core.db.active_list = core.options["active_list"]
    elif len(core.db.todo_lists) == 0:
        msg = "No JSON data to read"
        logger.log.warning(f"{msg}")
        return False, msg
    else:
        for list_entry in core.db.todo_lists:
            core.db.active_list = list_entry
            logger.log.info(f"{list_entry} set as active_list")

    core.db.list_count = len(core.db.todo_lists.keys())
    core.db.todo_total = 0
    for list_entry in core.db.todo_lists.values():
        core.db.todo_total += len(list_entry)

    msg = f"Successfully read JSON file {fn}"
    logger.log.info(f"{msg}")
    return True, msg


def write_json_data(fn=core.lists_fn):
    """Write todo lists as a JSON file."""
    logger.log.info(f"Writing JSON file {fn}")
    try:
        with open(fn, "w+", encoding="utf-8") as f:
            json.dump(core.db.todo_lists, f, indent=2)
    except IOError as e:
        msg = f"Error writing JSON file {fn}: {e}"
        logger.log.exception(msg)
        return False, msg

    msg = f"Successfully wrote JSON file {fn}"
    logger.log.info(msg)
    return True, msg
