"""缓存 key 和写文件的工具。写文件都走"先写临时文件、写完再改名顶上去"这一套:
中途断电顶多是少一个文件,不会留下写了一半的坏文件。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any


def sha256_hex(text: str) -> str:
    """把文本算成 sha256 十六进制串,拿来当缓存文件名。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json_atomic(path: Path, obj: Any) -> None:
    """把对象写成 JSON 文件,走临时文件那套安全写法。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def stream_to_file(aiter: AsyncIterator[bytes], path: Path) -> int:
    """网络下载的字节流边收边写进磁盘,收完把临时文件改名顶上去。返回一共写了多少字节。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in aiter:
                f.write(chunk)
                total += len(chunk)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return total
