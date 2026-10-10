"""A TCP server that sends the same bytes to every connected client."""

import asyncio

# A client that stops reading is dropped once this much is waiting for it, so it can't make the
# service use more and more memory.
_MAX_PENDING_BYTES = 1_000_000


class TcpBroadcaster:
    """Accepts any number of clients and sends them all the same data.

    Whatever clients send is read and thrown away.
    """

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()

    @property
    def address(self) -> str:
        """host:port, with the actual port once started (the config may say 0)."""
        return f"{self._host}:{self._port}"

    @property
    def n_clients(self) -> int:
        return len(self._clients)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, self._host, self._port)
        self._port = self._server.sockets[0].getsockname()[1]

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._clients.add(writer)
        try:
            while await reader.read(4096):
                pass
        except OSError:
            pass  # the client vanished without closing the connection properly
        finally:
            self._clients.discard(writer)
            writer.close()

    def send(self, data: bytes) -> None:
        for writer in list(self._clients):
            if writer.is_closing():
                continue
            if writer.transport.get_write_buffer_size() > _MAX_PENDING_BYTES:
                self._clients.discard(writer)
                writer.close()
            else:
                writer.write(data)

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        for writer in list(self._clients):
            writer.close()
        await self._server.wait_closed()
        self._server = None
