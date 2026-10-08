"""Public HTTP/WebSocket gateway; only the Jira webhook exposes the backend."""
import asyncio
import os

from aiohttp import ClientError, ClientSession, ClientTimeout, DummyCookieJar, WSMsgType, web
from multidict import CIMultiDict
from yarl import URL

HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade"}
CLIENT = web.AppKey("client", ClientSession)


def clean_headers(headers, websocket=False):
    excluded = HOP_HEADERS | {h.strip().lower() for h in headers.get("Connection", "").split(",")}
    if websocket:
        excluded |= {"sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions",
                     "sec-websocket-protocol"}
    return CIMultiDict((k, v) for k, v in headers.items() if k.lower() not in excluded)


async def relay(source, target):
    async for message in source:
        if message.type == WSMsgType.TEXT:
            await target.send_str(message.data)
        elif message.type == WSMsgType.BINARY:
            await target.send_bytes(message.data)
        elif message.type == WSMsgType.ERROR:
            break
    await target.close(code=source.close_code or 1000)


def create_app(api_url="http://127.0.0.1:8001", ui_url="http://127.0.0.1:8501"):
    app = web.Application()

    async def session_context(app):
        # Never retain one browser's cookies for another browser's requests.
        async with ClientSession(cookie_jar=DummyCookieJar(), auto_decompress=False,
                                 timeout=ClientTimeout(total=None, sock_connect=10, sock_read=300)) as session:
            app[CLIENT] = session
            yield
    app.cleanup_ctx.append(session_context)

    async def proxy(request):
        webhook = request.path == "/api/jira/webhook"
        if request.path == "/api" or request.path.startswith("/api/"):
            if not webhook:
                raise web.HTTPNotFound()
            if request.method != "POST":
                raise web.HTTPMethodNotAllowed(request.method, ["POST"])
        upstream = URL((api_url if webhook else ui_url) + request.raw_path, encoded=True)
        is_ws = request.headers.get("Upgrade", "").lower() == "websocket"
        headers = clean_headers(request.headers, websocket=is_ws)
        try:
            if is_ws and not webhook:
                protocols = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()]
                async with app[CLIENT].ws_connect(upstream, headers=headers, protocols=protocols,
                                                 max_msg_size=200 * 1024 * 1024) as remote:
                    local = web.WebSocketResponse(protocols=[remote.protocol] if remote.protocol else (),
                                                  max_msg_size=200 * 1024 * 1024)
                    await local.prepare(request)
                    tasks = [asyncio.create_task(relay(local, remote)), asyncio.create_task(relay(remote, local))]
                    try:
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        await local.close()
                    return local
            async with app[CLIENT].request(request.method, upstream, headers=headers,
                                           data=request.content.iter_any() if request.can_read_body else None,
                                           allow_redirects=False) as remote:
                response = web.StreamResponse(status=remote.status, reason=remote.reason,
                                              headers=clean_headers(remote.headers))
                await response.prepare(request)
                async for chunk in remote.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(text="Upstream service unavailable") from None

    app.router.add_route("*", "/{path:.*}", proxy)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0",
                port=int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", "8000"))),
                access_log=None)
