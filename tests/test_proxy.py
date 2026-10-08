import asyncio
import gzip

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kedb.presentation.proxy import create_app


def test_proxy_http_routing_headers_and_websockets():
    async def run():
        async def api(request):
            assert request.path == "/api/jira/webhook"
            assert request.headers["X-Jira-Webhook-Token"] == "secret"
            return web.json_response({"payload": await request.json(), "query": request.query_string}, status=202)

        async def ui(request):
            if request.path == "/_stcore/stream":
                assert request.headers["Cookie"] == "session=browser"
                ws = web.WebSocketResponse(protocols=["streamlit"])
                await ws.prepare(request)
                async for msg in ws:
                    if isinstance(msg.data, bytes):
                        await ws.send_bytes(msg.data)
                    else:
                        await ws.send_str(msg.data)
                return ws
            if request.path == "/compressed":
                return web.Response(body=gzip.compress(b"javascript"), headers={"Content-Encoding": "gzip"})
            if request.path == "/redirect":
                raise web.HTTPFound("/destination")
            response = web.Response(text=request.headers.get("Cookie", "no cookies"))
            response.set_cookie("one", "1")
            response.set_cookie("two", "2")
            return response

        backend, frontend = web.Application(), web.Application()
        backend.router.add_route("*", "/{path:.*}", api)
        frontend.router.add_route("*", "/{path:.*}", ui)
        async with TestServer(backend) as api_server, TestServer(frontend) as ui_server:
            gateway = create_app(str(api_server.make_url("")), str(ui_server.make_url("")))
            async with TestClient(TestServer(gateway)) as client:
                response = await client.post("/api/jira/webhook?test=1", json={"issue": "T-1"},
                                             headers={"X-Jira-Webhook-Token": "secret"})
                assert response.status == 202
                assert await response.json() == {"payload": {"issue": "T-1"}, "query": "test=1"}
                assert (await client.get("/api/jira/issues")).status == 404
                assert (await client.get("/api/jira/webhook")).status == 405
                response = await client.get("/")
                assert await response.text() == "no cookies"
                assert len(response.headers.getall("Set-Cookie")) == 2
                client.session.cookie_jar.clear()
                assert await (await client.get("/")).text() == "no cookies"
                assert await (await client.get("/compressed")).read() == b"javascript"
                response = await client.get("/redirect", allow_redirects=False)
                assert response.status == 302 and response.headers["Location"] == "/destination"
                client.session.cookie_jar.clear()
                async with client.ws_connect("/_stcore/stream", protocols=["streamlit"],
                                             headers={"Cookie": "session=browser"}) as ws:
                    assert ws.protocol == "streamlit"
                    await ws.send_str("hello")
                    assert (await ws.receive()).data == "hello"
                    await ws.send_bytes(b"binary")
                    assert (await ws.receive()).data == b"binary"
    asyncio.run(run())


def test_proxy_unavailable_upstream():
    async def run():
        server = TestServer(web.Application())
        await server.start_server()
        url = str(server.make_url(""))
        await server.close()
        async with TestClient(TestServer(create_app(ui_url=url))) as client:
            assert (await client.get("/")).status == 502
    asyncio.run(run())
