"""Exercise real HTTP byte ranges used by browser audio seeking."""
from functools import partial
from http.server import ThreadingHTTPServer
import threading
import urllib.request
import urllib.error

import pytest

from scripts.serve_demo import MediaHandler


def test_audio_byte_ranges(tmp_path):
    data = bytes(range(256)) * 4
    (tmp_path / "sample.wav").write_bytes(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(MediaHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/sample.wav"
    try:
        for value, expected, bounds in [
            ("bytes=10-19", data[10:20], "10-19"),
            ("bytes=1000-", data[1000:], "1000-1023"),
            ("bytes=-12", data[-12:], "1012-1023"),
        ]:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": value})) as response:
                assert response.status == 206
                assert response.headers["Content-Range"] == f"bytes {bounds}/1024"
                assert response.headers["Accept-Ranges"] == "bytes"
                assert response.read() == expected
        with pytest.raises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=1024-"}))
        assert failure.value.code == 416
        failure.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
