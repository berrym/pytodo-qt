"""TodoDatabase.py

This module implements the todo database.
"""

import configparser
import os
import sys
import threading

from dataclasses import dataclass

import core.defaults
from core import defaults
from core.Logger import Logger
from net import TCPServerLib, TCPClientLib


logger = Logger(__name__)


def sort_active_list():
    """Sort the active to-do list."""
    logger.log.info(f"Sorting list {defaults.db.active_list}")
    defaults.db.todo_lists[defaults.db.active_list]["todo_list"].sort(
        key=lambda x: x[defaults.options["sort_key"]],
        reverse=defaults.options["reverse_sort"]
    )


def todo_index(reminder):
    """Return the index location of the to-do matching reminder."""
    i = 0
    for todo in defaults.db.todo_lists[defaults.db.active_list]["todo_list"]:
        if todo["reminder"] == reminder:
            return i
        else:
            i += 1


def write_text_file(fn="todo_list.txt"):
    """Write active list to plain text file."""
    if not defaults.db.todo_lists.values():
        return

    logger.log.info(f"Writing todo lists to file {fn}")
    try:
        with open(fn, "w", encoding="utf-8") as f:
            f.write(f"{core.defaults.db.active_list:*^60}\n\n")
            for todo in defaults.db.todo_lists[core.defaults.db.active_list]:
                f.write(f'{todo["reminder"]}\n')
    except IOError as e:
        logger.log.exception(f"Unable to write todo list to {fn}: {e}")


@dataclass
class Todo:
    complete: bool = False
    reminder: str = ""
    priority: int = 2

    def __getitem__(self, i):
        return getattr(self, i)

    def __setitem__(self, key, value):
        match key:
            case "complete":
                self.complete = value
            case "str":
                self.reminder = value
            case "priority":
                self.priority = value
            case _:
                raise KeyError


class Subscriptable:
    def __class_getitem__(cls, item):
        return cls._get_child_dict()[item]

    @classmethod
    def _get_child_dict(cls):
        return {k: v for k, v in cls.__dict__.items() if not k.startswith('_')}


@dataclass
class TodoList(Subscriptable):
    todo_list: list()
    todo_count: int = 0
    name: str = ""

    def __getitem__(self, item):
        return getattr(self, item)

    def __getattr__(self, item):
        return self.todo_list

    def __setitem__(self, key, value):
        match key:
            case "todo_count":
                self.todo_count = value
            case "name":
                self.name = value
            case "todo_list":
                self.todo_list = value
            case _:
                raise KeyError

    def __iter__(self):
        return TodoListIterator(self)

    def __len__(self):
        return self.todo_count


class TodoListIterator:
    def __init__(self, todo_list):
        self.todo_list = todo_list
        self.index = 0

    def __next__(self):
        if self.index < len(self.todo_list.todo_list[:]):
            result = self.todo_list.todo_list[self.index]
            self.index += 1
            return result
        raise StopIteration


@dataclass
class TodoDatabase:
    def __init__(self, list_count=0, todo_total=0, active_list=None, todo_lists={}):
        self.list_count = list_count
        self.todo_total = todo_total
        self.active_list = active_list
        self.todo_lists = todo_lists

    def __getitem__(self, item):
        match item:
            case "list_count":
                return self.list_count
            case "todo_total":
                return self.todo_total
            case "active_list":
                return self.active_list
            case "todo_lists":
                return self.todo_lists
            case _:
                raise KeyError

    def __str__(self):
        if self.active_list:
            todo_count = len(self.todo_lists[self.active_list]["todo_list"])
        else:
            return "No Lists"

        todo_total = 0
        for list_entry in self.todo_lists.values():
            todo_total += len(list_entry)
        self.todo_total = todo_total

        if self.todo_lists:
            list_count = len(self.todo_lists)
        else:
            list_count = 0
        self.list_count = list_count

        if not self.active_list:
            active_list = "No Lists"
        else:
            active_list = self.active_list

        return f"Lists: {list_count}  Shown: {active_list}  Todos: {todo_count} of {todo_total}"


class CreateTodoDatabase(TodoDatabase):
    """Maintains a database of to-do lists."""
    def __init__(self):
        super().__init__()
        logger.log.info("Building the todo database")
        self.initialized = False
        self.server_up = False

        # create an ini config parser
        self.config = configparser.ConfigParser()
        if not os.path.exists(defaults.ini_fn):
            self.write_default_config()
        self.parse_config()

        # buffer size for sending/receiving data
        self.buf_size = 4096

        # create a server, and start it in a new thread
        # the server will create a new thread for each connection established
        self.net_server = None
        if defaults.options["run"]:
            self.start_server()

        # create a client
        self.net_client = TCPClientLib.DataBaseClient()

    def write_default_config(self):
        """Write the default configuration for PyTodo."""
        logger.log.info(f"Writing default configuration to {defaults.ini_fn}")
        self.config["database"] = {}
        self.config["database"]["active_list"] = ""
        self.config["database"]["sort_key"] = "priority"
        self.config["database"]["reverse_sort"] = "no"
        self.config["server"] = {}
        self.config["server"]["key"] = "BewareTheBlackGuardian"
        self.config["server"]["run"] = "yes"
        self.config["server"]["address"] = "127.0.0.1"
        self.config["server"]["port"] = "5364"
        self.config["server"]["pull"] = "yes"
        self.config["server"]["push"] = "yes"

        try:
            with open(defaults.ini_fn, "w", encoding="utf-8") as f:
                self.config.write(f)
        except IOError as e:
            msg = f"Unable to write default config: {e}"
            logger.log.exception(msg)
            sys.exit(1)

    def write_config(self):
        """Write the current configuration options to config file."""
        logger.log.info(f"Writing configuration file {defaults.ini_fn}")
        self.config["database"]["active_list"] = defaults.options["active_list"]
        self.config["database"]["sort_key"] = defaults.options["sort_key"]
        if defaults.options["reverse_sort"]:
            self.config["database"]["reverse_sort"] = "yes"
        else:
            self.config["database"]["reverse_sort"] = "no"
        if defaults.options["run"]:
            self.config["server"]["run"] = "yes"
        else:
            self.config["server"]["run"] = "no"
        self.config["server"]["address"] = defaults.options["address"]
        self.config["server"]["port"] = str(defaults.options["port"])
        self.config["server"]["pull"] = defaults.options["pull"]
        self.config["server"]["push"] = defaults.options["push"]

        try:
            with open(defaults.ini_fn, "w", encoding="utf-8") as f:
                self.config.write(f)
                msg = f"Successfully wrote configuration file {defaults.ini_fn}"
                logger.log.info(msg)
                return True, msg
        except IOError as e:
            msg = f"Unable to write default configuration file {defaults.ini_fn}: {e}"
            logger.log.exception(msg)
            return False, msg

    def parse_config(self):
        """Parse configuration file.

        If a configuration file exists read it in and set relevant data.
        """
        logger.log.info(f"Parsing configuration file {core.defaults.ini_fn}")
        self.config.read(core.defaults.ini_fn)

        for k, v in self.config["database"].items():
            if k not in core.defaults.options:
                logger.log.info(f"{k} = {v}")
                core.defaults.options[k] = v

        for k, v in self.config["server"].items():
            if k not in defaults.options:
                logger.log.info(f"{k} = {v}")
                defaults.options[k] = v

        # fix some option types
        if core.defaults.options["reverse_sort"] == "yes":
            defaults.options["reverse_sort"] = True
        elif core.defaults.options["reverse_sort"] == "no":
            defaults.options["reverse_sort"] = False
        else:
            logger.log.warning("Reverse sort option invalid, defaulting to no")
            defaults.options["reverse_sort"] = False

        if core.defaults.options["run"] == "yes":
            core.defaults.options["run"] = True
        elif core.defaults.options["run"] == "no":
            defaults.options["run"] = False
        else:
            logger.log.warning("Run net_server option invalid, defaulting to yes")
            defaults.options["run"] = True

        try:
            core.defaults.options["port"] = int(core.defaults.options["port"])
        except ValueError as e:
            logger.log.exception(f"Port must be a number: {e}")
            defaults.options["port"] = 5364

    def server_running(self):
        """Determine if the server is running"""
        if self.server_up and self.net_server is not None:
            return True
        else:
            return False

    def start_server(self):
        """Create and start the server."""
        if self.server_running():
            return

        logger.log.info("Starting the server")
        self.net_server = TCPServerLib.DatabaseServer(
            (core.defaults.options["address"], defaults.options["port"]),
            TCPServerLib.TCPRequestHandler,
        )

        # start net_server thread
        st = threading.Thread(target=self.net_server.serve_forever)
        st.setDaemon = True
        st.start()
        self.server_up = True

        logger.log.info(
            f'Server up at {core.defaults.options["address"]}:{core.defaults.options["port"]}'
        )

    def stop_server(self):
        """Stop and destroy the server."""
        if self.server_running():
            logger.log.info("Shutting down the server")
            self.net_server.shutdown()
            self.net_server = None
            self.server_up = False
            logger.log.info("Server shut down")

    def restart_server(self):
        """Stop and then restart the server."""
        if self.server_running():
            self.stop_server()
            self.start_server()
        else:
            self.start_server()

    def sync_pull(self, host):
        """Perform a client pull."""
        return self.net_client.sync_pull(host)

    def sync_push(self, host):
        """Perform a client push."""
        return self.net_client.sync_push(host)
