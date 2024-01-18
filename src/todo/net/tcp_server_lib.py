"""tcp_server_lib.py

This module implements a threaded tcp socket server and request handler for To-Do.
"""

import json
import os
import socketserver
import sys
import time

from PyQt5 import QtWidgets
from todo.core import error_on_none_db, settings
from todo.core.Logger import Logger
from todo.crypto.AESCipher import AESCipher
from todo.net.sync_operations import sync_operations


logger = Logger(__name__)


class DataBaseServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded tcp server."""

    allow_reuse_address = True


class TCPRequestHandler(socketserver.StreamRequestHandler):
    """Socket server request handler."""

    def __init__(self, request, client_address, server):
        """Initialize request handler."""
        self.aes_cipher = AESCipher(settings.options["key"])
        self.buf_size = 4096
        self.peer_name = None
        self.host = None
        self.data = None
        self.encrypted_header = None
        self.encrypted_data = None
        self.decrypted_data = None
        self.command = None
        self.encrypted_reply = None
        super().__init__(request, client_address, server)

    def process_request(self):
        """Process a request."""
        self.encrypted_data = self.request.recv(self.buf_size)
        self.decrypted_data = self.aes_cipher.decrypt(self.encrypted_data)
        self.command = self.decrypted_data.decode("utf-8")

        if self.command == sync_operations["PULL_REQUEST"].name:
            self.pull()
        elif self.command == sync_operations["PUSH_REQUEST"].name:
            self.push()
        else:
            pass

    def pull(self):
        """Pull to-do lists from remote host."""
        logger.log.info("received PULL_REQUEST from %s", self.peer_name)
        if not settings.options["pull"]:
            logger.log.info("PULL_REQUEST denied")
            self.encrypted_reply = self.aes_cipher.encrypt(
                sync_operations["REJECT"].name
            )
            self.request.send(self.encrypted_reply)
            return

        if os.path.exists(settings.lists_fn):
            self.data = ""
            with open(settings.lists_fn, encoding="utf-8") as f:
                for line in f:
                    self.data += line

        if self.data is not None:
            logger.log.info("PULL_REQUEST ACCEPTED")
            self.encrypted_reply = self.aes_cipher.encrypt(
                sync_operations["ACCEPT"].name
            )
            self.request.sendall(self.encrypted_reply)
            time.sleep(1)
            self.send_size_header()
        else:
            self.encrypted_reply = self.aes_cipher.encrypt(
                sync_operations["NO_DATA"].name
            )
            self.request.send(self.encrypted_reply)

    def send_size_header(self):
        """Send the size of the to-do lists."""
        size = sys.getsizeof(self.data)
        self.encrypted_header = self.aes_cipher.encrypt(str(size))
        self.request.sendall(self.encrypted_header)
        time.sleep(1)
        self.send_data()

    def send_data(self):
        """Send to-do list data."""
        try:
            serialized = json.dumps(self.data)
        except OSError as e:
            logger.log.exception(e)
            return False, e
        self.encrypted_data = self.aes_cipher.encrypt(serialized)
        self.request.sendall(self.encrypted_data)
        return True

    @error_on_none_db
    def push(self):
        """Push to-do lists to remote hosts."""
        logger.log.info("PUSH_REQUEST from %s", self.peer_name)
        if not settings.options["push"]:
            msg = f"PUSH_REQUEST from {self.peer_name} denied"
            self.encrypted_reply = self.aes_cipher.encrypt(
                sync_operations["REJECT"].name
            )
            self.request.send(self.encrypted_reply)
            QtWidgets.QMessageBox.warning(None, "Push Sync", msg)
            logger.log.warning(msg)
            return

        logger.log.info("PUSH_REQUEST accepted")
        self.encrypted_reply = self.aes_cipher.encrypt(sync_operations["ACCEPT"].name)
        self.request.send(self.encrypted_reply)

        if self.peer_name is not None:
            self.host = (self.peer_name[0], settings.options["port"])
        else:
            msg = "Not performing push sync, no host peer"
            QtWidgets.QMessageBox.warning(None, "Push Sync", msg)
            logger.log.warning(msg)
            return

        settings.db.sync_pull(self.host)

    def handle(self):
        """Handle requests."""
        self.peer_name = self.request.getpeername()
        self.process_request()
