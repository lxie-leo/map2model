"""导出这摊事:所有格式共用 hub.glb 这一个"母版",各导出器从它出发各写各的。

registry 是登记簿:记着每种格式的信息、机器上缺不缺依赖(capabilities)、
导出请求来了该派给谁。
"""

from app.services.export.registry import FORMATS, capabilities, run_export

__all__ = ["FORMATS", "capabilities", "run_export"]
