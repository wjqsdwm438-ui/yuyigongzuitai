import json
from pathlib import Path
import tempfile
import unittest

from 语义工作台.feishu_upload import FeishuUploadError, get_tenant_access_token, upload_file


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class FeishuUploadTests(unittest.TestCase):
    def test_upload_file_uses_token_then_multipart(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ds4.1.txt"
            source.write_bytes(b"secret-value")
            calls = []

            def opener(req, timeout):
                calls.append((req.full_url, req.get_header("Authorization"), req.data))
                if req.full_url.endswith("tenant_access_token/internal"):
                    return Response({"code": 0, "tenant_access_token": "t-test"})
                self.assertEqual(req.get_header("Authorization"), "Bearer t-test")
                self.assertIn(b"secret-value", req.data)
                return Response({"code": 0, "data": {"file_token": "file-test"}})

            result = upload_file(source, parent_node="folder-test", app_id="cli-test", app_secret="secret-test", opener=opener)
            self.assertEqual(result["文件token"], "file-test")
            self.assertEqual(len(calls), 2)

    def test_missing_credentials_fail_without_request(self):
        def no_request(*_):
            self.fail("不应调用网络")

        with self.assertRaisesRegex(FeishuUploadError, "FEISHU_APP_ID"):
            get_tenant_access_token("", "secret", opener=no_request)
