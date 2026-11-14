# -*- coding: utf-8 -*-
"""Offline contract for the Ark Agent Plan TTS HTTP client."""
import base64
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hands import tts as T  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    fail = False

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        request = json.loads(body.decode("utf-8"))
        assert request["req_params"]["text"] == "你好，语音接通了吗？"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Tt-Logid", "offline-logid")
        self.end_headers()
        if self.fail:
            events = [{"code": 45000000, "message": "speaker denied", "data": None}]
        else:
            chunk = b"ID3\x04\x00\x00\x00\x00\x00\x00"
            events = [
                {"code": 0, "message": "", "data": base64.b64encode(chunk).decode()},
                {
                    "code": 20000000,
                    "message": "ok",
                    "data": None,
                    "usage": {"text_words": 9},
                },
            ]
        for item in events:
            self.wfile.write(
                (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8"))

    def log_message(self, fmt, *args):
        pass


def _server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread


def main():
    srv, thread = _server()
    url = "http://127.0.0.1:%d/tts" % srv.server_address[1]
    try:
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {
                "SOUL_TTS_KEY": "offline-key",
                "SOUL_TTS_URL": url,
                "SOUL_TTS_SPEAKER": "zh_male_test",
                "SOUL_TTS_TIMEOUT": "5",
            }, clear=False):
                out = T.synthesize("你好，语音接通了吗？", output_dir=td)
                path = Path(out["path"])
                assert path.is_file()
                assert path.read_bytes().startswith(b"ID3")
                assert out["audio_bytes"] == 10
                assert out["log_id"] == "offline-logid"
                assert out["usage"] == {"text_words": 9}
                assert out["speaker"] == "zh_male_test"

                _Handler.fail = True
                try:
                    T.synthesize("你好，语音接通了吗？", output_dir=td)
                except T.TTSError as exc:
                    assert "45000000" in str(exc)
                    assert "speaker denied" in str(exc)
                else:
                    raise AssertionError("服务端错误码未抛出")
                _Handler.fail = False

            with mock.patch.dict(os.environ, {}, clear=True):
                try:
                    T.synthesize("你好", output_dir=td)
                except T.TTSConfigError as exc:
                    assert "Agent Plan TTS Key" in str(exc)
                else:
                    raise AssertionError("缺少 Key 未抛出")
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)
    print("PASS t_tts_contract")


if __name__ == "__main__":
    main()
