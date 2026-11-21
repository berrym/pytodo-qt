"""One port for HTTPS and for a redirect to it.

The web interface is served over HTTPS only. An address typed without
``https://`` reaches the same port as plain HTTP, and a TLS server reads
that as a failed handshake and closes the connection without a word:
Chrome shows ``ERR_EMPTY_RESPONSE``, and nothing points to the missing
``https://`` (#82). A browser adds ``http://`` to a bare ``host:port``,
which is how an address typed by hand on a phone arrives.

The listener here takes each connection itself and looks at its first
byte without reading it. A TLS connection begins with a handshake
record, whose first byte is 0x16: the connection is handed, untouched,
to asyncio's TLS transport and aiohttp's own request handler, and is
served from then on as it was by ``web.TCPSite``. Anything else is
plain HTTP, and is answered with a redirect to the same address over
HTTPS.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from ..core.logger import Logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = Logger(__name__)

# The first byte of a TLS record that carries a handshake.
TLS_HANDSHAKE = b"\x16"

# How long a connection may take to send its first byte, and a plain
# HTTP request to send its request line and headers, in seconds.
FIRST_BYTE_DEADLINE = 10.0
REQUEST_DEADLINE = 10.0

# The most of a plain HTTP request that is read, in bytes: the request
# line and the headers, which are all the redirect needs.
REQUEST_LIMIT = 8192

# Where the event loop cannot be asked whether a socket is readable
# (the proactor loops on Windows), the first byte is waited for in
# threads, at most this many at a time.
PEEK_THREADS = 8

# A host as a browser writes it in the Host header: a name, an IPv4
# address or a bracketed IPv6 address, with an optional port.
_HOST = re.compile(r"^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(:[0-9]{1,5})?$")


def redirect_target(host: str | None, target: str, fallback_host: str) -> str:
    """The HTTPS address a plain HTTP request is sent on to.

    ``host`` is the request's Host header, ``target`` its request
    target, ``fallback_host`` the address and port the connection came
    in on. A Host header that is not a host, and a target that is not
    a path, are not written into the answer.
    """
    name = host.strip() if host else ""
    if not _HOST.match(name):
        name = fallback_host
    path = target if target.startswith("/") and not re.search(r"[\s\x00-\x1f\x7f]", target) else "/"
    return f"https://{name}{path}"


def redirect_response(location: str) -> bytes:
    """A 307 to ``location``.

    Temporary: a browser keeps a 301 for good, and a server started
    without certificates serves plain HTTP on this port.
    """
    return (
        "HTTP/1.1 307 Temporary Redirect\r\n"
        f"Location: {location}\r\n"
        "Content-Length: 0\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")


def _fallback_host(sock: socket.socket) -> str:
    address, port = sock.getsockname()[:2]
    return f"[{address}]:{port}" if ":" in address else f"{address}:{port}"


class SharedPortListener:
    """Listens on one port for HTTPS, and redirects plain HTTP to it.

    ``protocol_factory`` makes the protocol that serves a TLS connection
    (aiohttp's ``runner.server``), ``ssl_context`` is the server's TLS
    context.
    """

    def __init__(
        self,
        protocol_factory: Callable[[], asyncio.Protocol],
        ssl_context: ssl.SSLContext,
        host: str,
        port: int,
    ) -> None:
        self._protocol_factory = protocol_factory
        self._ssl_context = ssl_context
        self._host = host
        self._port = port
        self._listener: socket.socket | None = None
        self._accepting: asyncio.Task[None] | None = None
        # Each connection being looked at or redirected, by its task.
        self._taking: set[asyncio.Task[None]] = set()
        self._threads: ThreadPoolExecutor | None = None

    @property
    def port(self) -> int:
        """The port listened on: the one asked for, or the one given for 0."""
        if self._listener is None:
            return self._port
        return self._listener.getsockname()[1]

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        listener = socket.create_server((self._host, self._port), backlog=128)
        listener.setblocking(False)
        self._listener = listener
        self._accepting = loop.create_task(self._accept(listener))

    async def close(self) -> None:
        """Takes no more connections, and closes those not yet handed on.

        A connection handed on to the TLS transport is the request
        handler's from then on: the server closes it (WebServer.stop).
        """
        tasks = list(self._taking)
        if self._accepting is not None:
            tasks.append(self._accepting)
            self._accepting = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self._threads is not None:
            self._threads.shutdown(wait=False, cancel_futures=True)
            self._threads = None

    async def _accept(self, listener: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                sock, _ = await loop.sock_accept(listener)
            except asyncio.CancelledError:
                raise
            except OSError as e:
                # Out of file descriptors, or a connection reset before
                # it was taken: the next one is taken all the same.
                logger.log.warning("Web server: a connection was not accepted: %s", e)
                await asyncio.sleep(0.1)
                continue
            task = loop.create_task(self._take(sock))
            self._taking.add(task)
            task.add_done_callback(self._taking.discard)

    async def _take(self, sock: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        handed_on = False
        try:
            first = await self._first_byte(sock)
            if first == TLS_HANDSHAKE:
                handed_on = True
                await loop.connect_accepted_socket(
                    self._protocol_factory, sock, ssl=self._ssl_context
                )
            else:
                # Plain HTTP, or a peer that closed without a word, for
                # which the redirect ends at once.
                await self._redirect(sock)
        except (OSError, TimeoutError, ssl.SSLError):
            # Silent past its deadline, gone, or a failed handshake.
            pass
        finally:
            # A connection handed on is the transport's: on a failed or
            # cancelled handshake asyncio has closed it.
            if not handed_on:
                with contextlib.suppress(OSError):
                    sock.close()

    async def _first_byte(self, sock: socket.socket) -> bytes:
        """The connection's first byte, left unread; empty where the peer
        closed it without sending one."""
        loop = asyncio.get_running_loop()
        readable = loop.create_future()

        def ready() -> None:
            if not readable.done():
                readable.set_result(None)

        try:
            loop.add_reader(sock.fileno(), ready)
        except NotImplementedError:
            return await self._first_byte_in_thread(sock)
        try:
            await asyncio.wait_for(readable, FIRST_BYTE_DEADLINE)
        finally:
            loop.remove_reader(sock.fileno())
        return sock.recv(1, socket.MSG_PEEK)

    async def _first_byte_in_thread(self, sock: socket.socket) -> bytes:
        if self._threads is None:
            self._threads = ThreadPoolExecutor(
                max_workers=PEEK_THREADS, thread_name_prefix="web-first-byte"
            )

        def peek() -> bytes:
            sock.settimeout(FIRST_BYTE_DEADLINE)
            try:
                return sock.recv(1, socket.MSG_PEEK)
            except TimeoutError:
                raise
            finally:
                with contextlib.suppress(OSError):
                    sock.setblocking(False)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._threads, peek)

    async def _redirect(self, sock: socket.socket) -> None:
        fallback = _fallback_host(sock)
        reader, writer = await asyncio.open_connection(sock=sock, limit=REQUEST_LIMIT)
        try:
            async with asyncio.timeout(REQUEST_DEADLINE):
                request_line = await reader.readline()
                host = None
                read = len(request_line)
                while read < REQUEST_LIMIT:
                    line = await reader.readline()
                    read += len(line)
                    if line in (b"\r\n", b"\n", b""):
                        break
                    name, _, value = line.partition(b":")
                    if name.strip().lower() == b"host":
                        host = value.decode("latin-1").strip()
            parts = request_line.decode("latin-1").split()
            target = parts[1] if len(parts) >= 2 else "/"
            writer.write(redirect_response(redirect_target(host, target, fallback)))
            await writer.drain()
        except (ValueError, asyncio.LimitOverrunError):
            # A line longer than the limit: no answer for it.
            pass
        finally:
            writer.close()
            with contextlib.suppress(OSError, ConnectionError):
                await writer.wait_closed()
