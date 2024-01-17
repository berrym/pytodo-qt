"""TodoDataBase.py

This module implements the todo database.
"""

import configparser
import os
import sys
import threading

from core import core
from core.Logger import Logger
from net import TCPServerLib, TCPClientLib

logger = Logger(__name__)


class CreateTodoDataBase:
    """Maintains a database of todo lists."""

    def __init__(self):
        """Create a working database."""
        logger.log.info("Building the todo database")
        self.initialized = False
        self.server_up = False

        # dictionary of todo lists, which are lists of dictionaries
        self.todo_lists = {}
        self.todo_total = 0
        self.list_count = 0

        # keep statistics on 'active' todo list
        self.active_list = ""
        self.todo_count = 0

        # create an ini config parser
        self.config = configparser.ConfigParser()
        if not os.path.exists(core.ini_fn):
            self.write_default_config()
        self.parse_config()

        # buffer size for sending/receiving data
        self.buf_size = 4096

        # create a server, and start it in a new thread
        # the server will create a new thread for each connection established
        self.net_server = None
        if core.options["run"]:
            self.start_server()

        # create a client
        self.net_client = TCPClientLib.DataBaseClient()

    def write_default_config(self):
        """Write the default configuration for PyTodo."""
        logger.log.info(f"Writing default configuration to {core.ini_fn}")
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
            with open(core.ini_fn, "w", encoding="utf-8") as f:
                self.config.write(f)
        except IOError as e:
            msg = f"Unable to write default config: {e}"
            logger.log.exception(msg)
            sys.exit(1)

    def write_config(self):
        """Write the current configuration options to config file."""
        logger.log.info(f"Writing configuration file {core.ini_fn}")
        self.config["database"]["active_list"] = core.options["active_list"]
        self.config["database"]["sort_key"] = core.options["sort_key"]
        if core.options["reverse_sort"]:
            self.config["database"]["reverse_sort"] = "yes"
        else:
            self.config["database"]["reverse_sort"] = "no"
        if core.options["run"]:
            self.config["server"]["run"] = "yes"
        else:
            self.config["server"]["run"] = "no"
        self.config["server"]["address"] = core.options["address"]
        self.config["server"]["port"] = str(core.options["port"])
        self.config["server"]["pull"] = core.options["pull"]
        self.config["server"]["push"] = core.options["push"]

        try:
            with open(core.ini_fn, "w", encoding="utf-8") as f:
                self.config.write(f)
                msg = f"Successfully wrote configuration file {core.ini_fn}"
                logger.log.info(msg)
                return True, msg
        except IOError as e:
            msg = f"Unable to write default configuration file {core.ini_fn}: {e}"
            logger.log.exception(msg)
            return False, msg

    def parse_config(self):
        """Parse configuration file.

        If a configuration file exists read it in and set relevant data.
        """
        logger.log.info(f"Parsing configuration file {core.ini_fn}")
        self.config.read(core.ini_fn)

        for k, v in self.config["database"].items():
            if k not in core.options:
                logger.log.info(f"{k} = {v}")
                core.options[k] = v

        for k, v in self.config["server"].items():
            if k not in core.options:
                logger.log.info(f"{k} = {v}")
                core.options[k] = v

        # fix some option types
        if core.options["reverse_sort"] == "yes":
            core.options["reverse_sort"] = True
        elif core.options["reverse_sort"] == "no":
            core.options["reverse_sort"] = False
        else:
            logger.log.warning("Reverse sort option invalid, defaulting to no")
            core.options["reverse_sort"] = False

        if core.options["run"] == "yes":
            core.options["run"] = True
        elif core.options["run"] == "no":
            core.options["run"] = False
        else:
            logger.log.warning("Run net_server option invalid, defaulting to yes")
            core.options["run"] = True

        try:
            core.options["port"] = int(core.options["port"])
        except ValueError as e:
            logger.log.exception(f"Port must be a number: {e}")
            core.options["port"] = 5364

    def write_text_file(self, fn="todo_list.txt"):
        """Write active list to plain text file."""
        if self.todo_count == 0:
            return

        logger.log.info(f"Writing todo lists to file {fn}")
        try:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(f"{self.active_list:*^60}\n\n")
                for todo in self.todo_lists[self.active_list]:
                    f.write(f'{todo["reminder"]}\n')
        except IOError as e:
            logger.log.exception(f"Unable to write todo list to {fn}: {e}")

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
        self.net_server = TCPServerLib.DataBaseServer(
            (core.options["address"], core.options["port"]),
            TCPServerLib.TCPRequestHandler,
        )

        # start net_server thread
        st = threading.Thread(target=self.net_server.serve_forever)
        st.setDaemon(True)
        st.start()
        self.server_up = True

        logger.log.info(
            f'Server up at {core.options["address"]}:{core.options["port"]}'
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

    def sort_active_list(self):
        """Sort the active todo list."""
        logger.log.info(f"Sorting list {self.active_list}")
        self.todo_lists[self.active_list].sort(
            key=lambda x: x[core.options["sort_key"]],
            reverse=core.options["reverse_sort"],
        )

    def todo_index(self, reminder):
        """Return the index location of the todo matching reminder."""
        i = 0
        for todo in self.todo_lists[self.active_list]:
            if todo["reminder"] == reminder:
                return i
            else:
                i += 1
