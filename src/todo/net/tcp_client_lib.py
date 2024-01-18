"""tcp_client_lib.py

This module implements the To-Do database network client.
"""

import json
import os
import socket
import time

from todo.core import settings, json_helpers
from todo.core.Logger import Logger
from todo.crypto.AESCipher import AESCipher
from todo.net.sync_operations import sync_operations

from . import recv_all


logger = Logger(__name__)


class DataBaseClient:
    """To-Do database client class."""

    def __init__(self):
        """Initialize client."""
        self.buf_size = 4096
        self.aes_cipher = AESCipher(settings.options["key"])

    def send_request(self, host, sock, request):
        """Send a request to remote connection."""
        logger.log.info(f"sending {request} to {host}")
        encrypted_request = self.aes_cipher.encrypt(request)
        sock.send(encrypted_request)

    def get_response(self, sock):
        """Get a response from remote connection."""
        encrypted_data = sock.recv(self.buf_size)
        decrypted_data = self.aes_cipher.decrypt(encrypted_data)
        response = decrypted_data.decode("utf-8")
        return response

    def process_response(self, host, sock, request, response):
        """Process remote host's response to a request."""
        msg = f"{host} responded to {request} with {response}"
        logger.log.info(msg)

        if response == sync_operations["ACCEPT"].name:
            if request == sync_operations["PULL_REQUEST"].name:
                size_header = sock.recv(self.buf_size)
                decrypted_header = self.aes_cipher.decrypt(size_header)
                size = int(decrypted_header)
                logger.log.info("remote lists is %d bytes", size)
                time.sleep(1)
                data = recv_all(sock, size)
                return self.process_data(host, data)
            elif request == sync_operations["PUSH_REQUEST"].name:
                return True, msg
            else:
                return False, msg
        else:
            return False, msg

    def process_data(self, host, data):
        """Process encrypted data received."""
        # decrypt and decode received data
        decrypted_data = self.aes_cipher.decrypt(data)
        try:
            deserialized = json.loads(decrypted_data)
        except OSError as e:
            logger.log.exception(e)
            return False, e

        # write data to a temporary file, then read it in
        tmp = os.path.join(settings.todo_dir, ".todo_lists.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(deserialized)
            msg = f"Pull from {host} successful."
            logger.log.info(msg)
            result, e = json_helpers.read_json_data(tmp)
            if not result:
                return False, e
            os.remove(tmp)
            return True, msg
        except IOError as e:
            msg = f"Unable to write temporary file: {e}"
            logger.log.exception(msg)
            return False, msg

    def synchronize(self, host, request):
        """Synchronize to-do lists with other hosts."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(30)
                try:
                    sock.connect(host)
                except socket.error as err:
                    msg = f"Unable to connect to host: {err}"
                    logger.log.exception(msg)
                    return False, msg
                self.send_request(host, sock, request)
                response = self.get_response(sock)
                return self.process_response(host, sock, request, response)
        except OSError as e:
            msg = f"Unable to connect to host {host}: {e}"
            logger.log.exception(msg)
            return False, msg

    def sync_pull(self, host):
        """Synchronize database with another by pulling it from a host."""
        logger.log.info("Performing a Sync Pull")
        return self.synchronize(host, sync_operations["PULL_REQUEST"].name)

    def sync_push(self, host):
        """Synchronize lists between devices by pushing them to a host.

        To-Do doesn't really support pushing because that is rude.
        In our terminology, if you do a push, it really means asking
        the device you want your to-do lists on to pull from you.
        """
        logger.log.info("Performing a Sync Push")
        return self.synchronize(host, sync_operations["PUSH_REQUEST"].name)
