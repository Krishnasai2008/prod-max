import contextlib
import http.client
import io
import json
import threading
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from pm import api, web

NOW = datetime(2026, 11, 9, 10, 0)
PORT = 8321
CSP = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net/npm/mathjax@3.2.2/; "
       "style-src 'self' 'unsafe-inline'; "
       "font-src 'self' https://cdn.jsdelivr.net/npm/mathjax@3.2.2/; "
       "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


class TestCheck(unittest.TestCase):
    def test_good_hosts_are_allowed(self):
        for host in ("127.0.0.1:8321", "localhost:8321"):
            with self.subTest(host=host):
                self.assertIsNone(web.check("GET", {"Host": host}, PORT))

    def test_bad_hosts_are_refused(self):
        for headers in ({"Host": "evil.example:8321"}, {"Host": "127.0.0.1:9999"}, {}):
            with self.subTest(headers=headers):
                self.assertEqual(web.check("GET", headers, PORT), "bad host")

    def test_a_foreign_origin_is_refused(self):
        headers = {"Host": "127.0.0.1:8321", "Origin": "https://evil.example",
                   "Content-Type": "application/json"}
        self.assertEqual(web.check("POST", headers, PORT), "bad origin")

    def test_post_needs_a_json_content_type(self):
        for content_type in (None, "text/plain", "application/x-www-form-urlencoded"):
            with self.subTest(content_type=content_type):
                headers = {"Host": "127.0.0.1:8321"}
                if content_type is not None:
                    headers["Content-Type"] = content_type
                self.assertEqual(web.check("POST", headers, PORT), "send json")

    def test_same_origin_json_post_is_allowed(self):
        headers = {"Host": "127.0.0.1:8321", "Origin": "http://127.0.0.1:8321",
                   "Content-Type": "application/json; charset=utf-8"}
        self.assertIsNone(web.check("POST", headers, PORT))
        headers = {"Host": "localhost:8321", "Origin": "http://localhost:8321",
                   "Content-Type": "application/json"}
        self.assertIsNone(web.check("POST", headers, PORT))

    def test_other_methods_are_refused_before_the_path(self):
        for method in ("DELETE", "PUT", "PATCH", "OPTIONS", "HEAD"):
            with self.subTest(method=method):
                self.assertEqual(web.check(method, {"Host": "127.0.0.1:8321"}, PORT),
                                 "use GET or POST")


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "pm.db"
        self.server = web.make_server(self.db, 0, lambda: NOW)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            if isinstance(body, (dict, list)):
                body = json.dumps(body)
                headers = {"Content-Type": "application/json", **(headers or {})}
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            payload = response.read()
            headers = {name.lower(): value for name, value in response.getheaders()}
            return response.status, headers, payload
        finally:
            conn.close()


class TestServer(ServerCase):
    def add_task(self, **body):
        status, _, payload = self.request("POST", "/api/tasks",
                                          {"title": "OS lab", "est": "4h", **body})
        self.assertEqual(status, 200, payload)
        return json.loads(payload)["id"]

    def test_ping_has_the_safety_headers(self):
        status, headers, payload = self.request("GET", "/api/ping")
        self.assertEqual((status, json.loads(payload)), (200, {"pm": True}))
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["content-security-policy"], CSP)
        self.assertIn("https://cdn.jsdelivr.net/npm/mathjax@3.2.2/",
                      headers["content-security-policy"])
        self.assertEqual(headers["cache-control"], "no-store")

    def test_a_raw_body_is_sent_with_its_type_and_cache(self):
        with mock.patch("pm.web.handle",
                        return_value=(200, api.Raw("image/png", b"abc", 3600))):
            status, headers, payload = self.request("GET", "/api/items/1/page.png")
        self.assertEqual((status, payload), (200, b"abc"))
        self.assertEqual(headers["content-type"], "image/png")
        self.assertEqual(headers["cache-control"], "private, max-age=3600")

    def test_a_raw_body_with_no_max_age_is_not_cached(self):
        with mock.patch("pm.web.handle",
                        return_value=(200, api.Raw("image/png", b"abc"))):
            status, headers, payload = self.request("GET", "/api/items/1/page.png")
        self.assertEqual((status, payload), (200, b"abc"))
        self.assertEqual(headers["cache-control"], "no-store")

    def test_post_then_state_uses_a_fresh_connection(self):
        self.add_task()
        status, _, payload = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual([task["title"] for task in json.loads(payload)["tasks"]], ["OS lab"])

    def test_a_foreign_origin_cannot_add_a_task(self):
        self.add_task()
        status, headers, payload = self.request(
            "POST", "/api/tasks", {"title": "evil", "est": "1h"},
            headers={"Origin": "https://evil.example"})
        self.assertEqual((status, json.loads(payload)), (403, {"error": "bad origin"}))
        self.assertEqual(headers["content-security-policy"], CSP)
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual([task["title"] for task in state["tasks"]], ["OS lab"])

    def test_a_text_plain_post_is_refused(self):
        status, _, payload = self.request(
            "POST", "/api/tasks", '{"title": "evil", "est": "1h"}',
            headers={"Content-Type": "text/plain"})
        self.assertEqual((status, json.loads(payload)), (403, {"error": "send json"}))

    def test_a_bad_host_is_refused(self):
        status, _, payload = self.request("GET", "/api/ping", headers={"Host": "evil.example"})
        self.assertEqual((status, json.loads(payload)), (403, {"error": "bad host"}))

    def test_the_page_and_its_files_are_served(self):
        status, headers, payload = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual(headers["cache-control"], "no-cache")
        self.assertEqual(payload, (web.UI / "index.html").read_bytes())
        status, headers, _ = self.request("GET", "/ui/app.css")
        self.assertEqual((status, headers["content-type"]), (200, "text/css"))

    def test_unknown_and_traversal_paths_are_404(self):
        for path in ("/ui/../cli.py", "/ui/nope.js", "/ui/", "/etc/passwd"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_a_json_body_that_is_not_an_object_is_400(self):
        status, _, payload = self.request("POST", "/api/tasks", [1])
        self.assertEqual((status, json.loads(payload)),
                         (400, {"error": "send a json object"}))

    def test_invalid_json_is_400(self):
        status, _, payload = self.request("POST", "/api/tasks", "{not json",
                                          headers={"Content-Type": "application/json"})
        self.assertEqual((status, json.loads(payload)),
                         (400, {"error": "send a json object"}))

    def test_a_body_over_the_limit_is_413_and_is_not_read(self):
        status, _, payload = self.request(
            "POST", "/api/tasks", b"{}",
            headers={"Content-Length": "70000", "Content-Type": "application/json"})
        self.assertEqual((status, json.loads(payload)), (413, {"error": "too large"}))

    def test_a_post_without_a_body_sends_an_empty_object(self):
        status, _, payload = self.request("POST", "/api/stop",
                                          headers={"Content-Type": "application/json"})
        self.assertEqual((status, json.loads(payload)), (400, {"error": "nothing running"}))

    def test_delete_is_405_with_the_normal_headers(self):
        status, headers, payload = self.request("DELETE", "/api/ping")
        self.assertEqual((status, json.loads(payload)),
                         (405, {"error": "use GET or POST"}))
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["content-security-policy"], CSP)

    def test_options_is_405_and_never_sends_cors_headers(self):
        status, headers, payload = self.request("OPTIONS", "/api/tasks")
        self.assertEqual((status, json.loads(payload)),
                         (405, {"error": "use GET or POST"}))
        self.assertEqual([name for name in headers if name.startswith("access-control")], [])

    def test_an_unexpected_error_is_500_and_the_server_keeps_serving(self):
        stderr = io.StringIO()
        with mock.patch("pm.web.handle", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stderr(stderr):
                status, _, payload = self.request("GET", "/api/ping")
        self.assertEqual((status, json.loads(payload)),
                         (500, {"error": "internal error"}))
        self.assertIn("RuntimeError", stderr.getvalue())
        self.assertEqual(self.request("GET", "/api/ping")[0], 200)


class TestServe(unittest.TestCase):
    def test_keyboard_interrupt_returns_zero_and_closes_the_server(self):
        server = mock.MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("pm.web.make_server", return_value=server):
            self.assertEqual(web.serve("pm.db", PORT, lambda: NOW), 0)
        server.server_close.assert_called_once_with()

    def test_a_normal_return_also_closes_the_server(self):
        server = mock.MagicMock()
        with mock.patch("pm.web.make_server", return_value=server):
            self.assertEqual(web.serve("pm.db", PORT, lambda: NOW), 0)
        server.server_close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
