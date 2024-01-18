"""TodoDataBase.py

This module implements the to-do database.
"""

import configparser
import os
import sys
import threading

from todo.core import settings
from todo.core.Logger import Logger
from todo.net import tcp_server_lib, tcp_client_lib


logger = Logger(__name__)


class CreateTodoDataBase:
    """Maintains a database of to-do lists."""

    def __init__(self):
        """Create a working database."""
        logger.log.info("Building the to-do database")
        self.initialized = False
        self.server_up = False

        # dictionary of to-do lists, which are lists of dictionaries
        self.todo_lists = {}
        self.todo_total = 0
        self.list_count = 0

        # keep statistics on 'active' to-do list
        self.active_list = ""
        self.todo_count = 0

        # create an ini config parser
        self.config = configparser.ConfigParser()
        if not os.path.exists(settings.ini_fn):
            self.write_default_config()
        self.parse_config()

        # buffer size for sending/receiving data
        self.buf_size = 4096

        # create a server, and start it in a new thread
        # the server will create a new thread for each connection established
        self.net_server = None
        if settings.options["run"]:
            self.start_server()

        # create a client
        self.net_client = tcp_client_lib.DataBaseClient()

    def write_default_config(self):
        """Write the default configuration for To-Do."""
        logger.log.info("Writing default configuration to %s", settings.ini_fn)
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
            with open(settings.ini_fn, "w", encoding="utf-8") as f:
                self.config.write(f)
        except IOError as e:
            logger.log.exception("Unable to write default config: %s", e)
            sys.exit(1)

    def write_config(self):
        """Write the current configuration options to config file."""
        logger.log.info("Writing configuration file %s", settings.ini_fn)
        self.config["database"]["active_list"] = settings.options["active_list"]
        self.config["database"]["sort_key"] = settings.options["sort_key"]
        if settings.options["reverse_sort"]:
            self.config["database"]["reverse_sort"] = "yes"
        else:
            self.config["database"]["reverse_sort"] = "no"
        if settings.options["run"]:
            self.config["server"]["run"] = "yes"
        else:
            self.config["server"]["run"] = "no"
        self.config["server"]["address"] = settings.options["address"]
        self.config["server"]["port"] = str(settings.options["port"])
        self.config["server"]["pull"] = settings.options["pull"]
        self.config["server"]["push"] = settings.options["push"]

        try:
            with open(settings.ini_fn, "w", encoding="utf-8") as f:
                self.config.write(f)
                msg = f"Successfully wrote configuration file {settings.ini_fn}"
                logger.log.info(msg)
                return True, msg
        except IOError as e:
            msg = f"Unable to write default configuration file {settings.ini_fn}: {e}"
            logger.log.exception(msg)
            return False, msg

    def parse_config(self):
        """Parse configuration file.

        If a configuration file exists read it in and set relevant data.
        """
        logger.log.info("Parsing configuration file %s", settings.ini_fn)
        self.config.read(settings.ini_fn)

        for k, v in self.config["database"].items():
            if k not in settings.options:
                logger.log.info(f"%r = %r", k, v)
                settings.options[k] = v

        for k, v in self.config["server"].items():
            if k not in settings.options:
                logger.log.info(f"%r = %r", k, v)
                settings.options[k] = v

        # fix some option types
        if settings.options["reverse_sort"] == "yes":
            settings.options["reverse_sort"] = True
        elif settings.options["reverse_sort"] == "no":
            settings.options["reverse_sort"] = False
        else:
            logger.log.warning("Reverse sort option invalid, defaulting to no")
            settings.options["reverse_sort"] = False

        if settings.options["run"] == "yes":
            settings.options["run"] = True
        elif settings.options["run"] == "no":
            settings.options["run"] = False
        else:
            logger.log.warning("Run network server option invalid, defaulting to yes")
            settings.options["run"] = True

        try:
            settings.options["port"] = int(settings.options["port"])
        except ValueError as e:
            logger.log.exception("Port must be a number: %s", e)
            settings.options["port"] = 5364

    def write_text_file(self, fn="todo_list.txt"):
        """Write active list to plain text file."""
        if self.todo_count == 0:
            return

        logger.log.info("Writing todo lists to file %s", fn)
        try:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(f"{self.active_list:*^60}\n\n")
                for todo in self.todo_lists[self.active_list]:
                    f.write(f'{todo["reminder"]}\n')
        except IOError as e:
            logger.log.exception("Unable to write todo list to %s: %s", fn, e)

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
        self.net_server = tcp_server_lib.DataBaseServer(
            (settings.options["address"], settings.options["port"]),
            tcp_server_lib.TCPRequestHandler,
        )

        # start network server thread
        st = threading.Thread(target=self.net_server.serve_forever)
        st.daemon = True
        st.start()
        self.server_up = True

        logger.log.info(
            "Server up at %s:%d", settings.options["address"], settings.options["port"]
        )

    def stop_server(self):
        """Stop and destroy the server."""
        if self.net_server is not None and self.server_running():
            logger.log.info("Shutting down the server")
            self.net_server.shutdown()
            self.net_server = None
            self.server_up = False
            logger.log.info("Server shut down")
        else:
            logger.log.exception(
                "network server does not exist, or is not running, exiting"
            )
            sys.exit(1)

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

    def sort_active_list(self):
        """Sort the active to-do list."""
        logger.log.info("Sorting list %s", self.active_list)
        self.todo_lists[self.active_list].sort(
            key=lambda todo_list: todo_list[settings.options["sort_key"]],
            reverse=settings.options["reverse_sort"],
        )

    def todo_index(self, reminder):
        """Return the index location of the to-do matching reminder."""
        i = 0
        for todo in self.todo_lists[self.active_list]:
            if todo["reminder"] == reminder:
                return i
            else:
                i += 1
