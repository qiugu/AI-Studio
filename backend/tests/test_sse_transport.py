from app.utils.sse import create_sse_response, json_sse_event


def test_json_sse_event_encodes_unicode_and_multiline_content():
    encoded = json_sse_event("message", {"content": "中文\n第二行"}).encode()

    assert b"event: message" in encoded
    assert "中文".encode() in encoded
    assert b"\\n" in encoded


def test_create_sse_response_uses_production_defaults():
    async def events():
        yield json_sse_event("done", {})

    response = create_sse_response(events())

    assert response.ping_interval == 15
    assert response.send_timeout == 30
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["connection"] == "keep-alive"
    assert response.headers["x-accel-buffering"] == "no"
