"""文件系统小工具:目前只有打包 zip 一个函数。"""

from __future__ import annotations

import zipfile
from pathlib import Path


def zip_dir(src_dir: Path, zip_path: Path) -> Path:
    """把 src_dir 里的内容(不带最外层文件夹本身)打包成 zip。"""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    # zip 自己就建在 src_dir 里的话,得把它排除掉,不然会把"写到一半的自己"打进包里
    self_path = zip_path.resolve()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file() and p.resolve() != self_path:
                zf.write(p, p.relative_to(src_dir).as_posix())
    return zip_path
