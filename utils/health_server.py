"""
Minimal HTTP health server on port 8080.
Railway uses this for healthcheck — prevents unnecessary restarts.
Also provides /metrics endpoint with bot stats.
"""
import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_stats_fn = None   # injected from main.py


def set_stats_fn(fn):
    global _stats_fn
    _stats_fn = fn


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request = await asyncio.wait_for(reader.read(512), timeout=5)
        path = request.decode(errors="ignore").split(" ")[1] if b" " in request else "/"

        if path.startswith("/metrics") and _stats_fn:
            try:
                st = await _stats_fn()
                body = json.dumps({
                    "status": "ok",
                    "uptime_since": datetime.utcnow().isoformat(),
                    **st,
                }, ensure_ascii=False).encode()
                status = "200 OK"
                ct = "application/json"
            except Exception as e:
                body = json.dumps({"status": "error", "detail": str(e)}).encode()
                status = "500 Internal Server Error"
                ct = "application/json"
        else:
            body = b"OK"
            status = "200 OK"
            ct = "text/plain"

        response = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {ct}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + body

        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def start_health_server(port: int = 8080) -> None:
    try:
        server = await asyncio.start_server(_handle, "0.0.0.0", port)
        logger.info("🏥 Health server on :%d", port)
        async with server:
            await server.serve_forever()
    except Exception as e:
        logger.warning("Health server failed: %s", e)
