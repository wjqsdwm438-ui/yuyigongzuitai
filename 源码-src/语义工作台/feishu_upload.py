"""飞书云空间文件上传适配器。

凭据只从环境变量读取：FEISHU_APP_ID、FEISHU_APP_SECRET。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Callable
from urllib import error, request


DEFAULT_BASE_URL = "https://open.feishu.cn"


class FeishuUploadError(RuntimeError):
    """飞书上传失败，错误消息不包含凭据。"""


def _json_request(
    url: str,
    *,
    method: str,
    body: bytes,
    headers: dict[str, str],
    opener: Callable = request.urlopen,
) -> dict:
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FeishuUploadError(f"飞书接口请求失败：{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise FeishuUploadError("飞书接口返回格式无效")
    if payload.get("code") != 0:
        msg = str(payload.get("msg") or "未知错误")
        raise FeishuUploadError(f"飞书接口拒绝请求：code={payload.get('code')}，msg={msg}")
    return payload


def get_tenant_access_token(
    app_id: str,
    app_secret: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    opener: Callable = request.urlopen,
) -> str:
    if not app_id or not app_secret:
        raise FeishuUploadError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    result = _json_request(
        f"{base_url.rstrip('/')}/open-apis/auth/v3/tenant_access_token/internal",
        method="POST",
        body=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        opener=opener,
    )
    token = result.get("tenant_access_token")
    if not isinstance(token, str) or not token:
        raise FeishuUploadError("飞书未返回 tenant_access_token")
    return token


def _multipart(fields: dict[str, str], file_name: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"----workbench-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_file(
    path: Path,
    *,
    parent_node: str,
    app_id: str,
    app_secret: str,
    parent_type: str = "explorer",
    base_url: str = DEFAULT_BASE_URL,
    opener: Callable = request.urlopen,
) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FeishuUploadError(f"源文件不存在或不是文件：{path}")
    if not parent_node.strip():
        raise FeishuUploadError("必须指定飞书目标文件夹 token（--父节点）")
    content = path.read_bytes()
    token = get_tenant_access_token(app_id, app_secret, base_url=base_url, opener=opener)
    body, content_type = _multipart(
        {"file_name": path.name, "parent_type": parent_type, "parent_node": parent_node, "size": str(len(content))},
        path.name,
        content,
    )
    result = _json_request(
        f"{base_url.rstrip('/')}/open-apis/drive/v1/files/upload_all",
        method="POST",
        body=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        opener=opener,
    )
    data = result.get("data")
    if not isinstance(data, dict) or not data.get("file_token"):
        raise FeishuUploadError("飞书上传成功响应缺少 file_token")
    return {"文件名": path.name, "文件大小": len(content), "文件token": data["file_token"]}


def upload_from_environment(path: Path, *, parent_node: str, base_url: str = DEFAULT_BASE_URL) -> dict:
    return upload_file(
        path,
        parent_node=parent_node,
        app_id=os.environ.get("FEISHU_APP_ID", ""),
        app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
        base_url=base_url,
    )
