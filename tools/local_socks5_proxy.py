#!/usr/bin/env python3
"""Minimal localhost-only SOCKS5 CONNECT proxy for the Vast SSH route.

This intentionally uses only the Python standard library. It runs on the local
Mac as network routing only; audio, metadata, model and dataset files are still
written exclusively on the Vast server.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import ipaddress
from typing import Any


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(64 * 1024):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass


async def read_destination(reader: asyncio.StreamReader, address_type: int) -> str:
    if address_type == 1:
        return str(ipaddress.ip_address(await reader.readexactly(4)))
    if address_type == 3:
        length = (await reader.readexactly(1))[0]
        return (await reader.readexactly(length)).decode("idna")
    if address_type == 4:
        return str(ipaddress.ip_address(await reader.readexactly(16)))
    raise ValueError(f"unsupported SOCKS address type: {address_type}")


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        version, method_count = await reader.readexactly(2)
        methods = await reader.readexactly(method_count)
        if version != 5 or 0 not in methods:
            writer.write(b"\x05\xff")
            await writer.drain()
            return
        writer.write(b"\x05\x00")
        await writer.drain()

        version, command, _reserved, address_type = await reader.readexactly(4)
        if version != 5 or command != 1:
            writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return
        host = await read_destination(reader, address_type)
        port = int.from_bytes(await reader.readexactly(2), "big")
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=30,
        )
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()

        client_to_upstream = asyncio.create_task(relay(reader, upstream_writer))
        upstream_to_client = asyncio.create_task(relay(upstream_reader, writer))
        done, pending = await asyncio.wait(
            {client_to_upstream, upstream_to_client},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    except (ConnectionError, OSError, ValueError, asyncio.IncompleteReadError, asyncio.TimeoutError):
        with contextlib.suppress(ConnectionError):
            writer.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
    finally:
        if upstream_writer is not None:
            upstream_writer.close()
            with contextlib.suppress(ConnectionError):
                await upstream_writer.wait_closed()
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()


async def serve(host: str, port: int) -> None:
    server = await asyncio.start_server(handle_client, host=host, port=port)
    sockets: list[Any] = server.sockets or []
    addresses = ", ".join(str(sock.getsockname()) for sock in sockets)
    print(f"SOCKS5 routing proxy listening on {addresses}", flush=True)
    async with server:
        await server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a localhost-only standard-library SOCKS5 proxy.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19080)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("the routing proxy must remain bound to localhost")
    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
