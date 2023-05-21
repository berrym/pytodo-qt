import json

import jsonpickle
import os

import core.defaults
from core import defaults
from core.Logger import Logger

logger = Logger(__name__)


def merge_todo_lists(*todo_lists):
    """Merge to-do lists keeping only unique values."""
    logger.log.info("Merging todo lists")
    new_lists = {}
    for list_entry in todo_lists:
        for k in list_entry:
            new_lists[k] = list_entry[k]

    return new_lists


def read_json_data(fn=defaults.lists_fn):
    """Read in to-do lists from a JSON file."""
    if not os.path.exists(fn):
        msg = f"JSON file {fn} does not exist"
        logger.log.warning(msg)
        return False, msg

    logger.log.info(f"Reading JSON file {fn}")
    try:
        with open(fn, "r", encoding="utf-8") as f:
            # Merge lists
            if len(defaults.db.todo_lists) > 0:
                todo_lists = jsonpickle.decode(bytes(f.read(), encoding="utf-8"))  # new_lists
                new_lists = merge_todo_lists(defaults.db.todo_lists, todo_lists)
                defaults.db.todo_lists = new_lists
            else:
                defaults.db.todo_lists = jsonpickle.decode(bytes(f.read(), encoding="utf-8"))
    except IOError as e:
        logger.log.exception(f"Error reading JSON file {fn}: {e}")
        return False, e

    # set active list
    if defaults.options["active_list"]:
        defaults.db.active_list = defaults.options["active_list"]
    elif len(defaults.db.todo_lists) == 0:
        msg = "No JSON data to read"
        logger.log.warning(f"{msg}")
        return False, msg
    else:
        for list_entry in defaults.db.todo_lists:
            defaults.db.active_list = list_entry
            logger.log.info(f"{list_entry} set as active_list")

    defaults.db.list_count = len(defaults.db.todo_lists.keys())
    defaults.db.todo_total = 0
    for list_entry in defaults.db.todo_lists.values():
        for _ in list_entry:
            defaults.db.todo_total += 1

    msg = f"Successfully read JSON file {fn}"
    logger.log.info(f"{msg}")
    return True, msg


def write_json_data(fn=core.defaults.lists_fn):
    """Write todo lists as a JSON file."""
    logger.log.info(f"Writing JSON file {fn}")
    try:
        with open(fn, "w+", encoding="utf-8") as f:
            db_lists = jsonpickle.encode(defaults.db.todo_lists, indent=2)
            f.write(db_lists)
    except IOError as e:
        msg = f"Error writing JSON file {fn}: {e}"
        logger.log.exception(msg)
        return False, msg

    msg = f"Successfully wrote JSON file {fn}"
    logger.log.info(msg)
    return True, msg
