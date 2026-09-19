"""项目自己定义的错误:每种带一个 HTTP 状态码,返回给前端的格式统一是 {"error": {"code", "message"}}。"""

from __future__ import annotations


class AppError(Exception):
    code = "app_error"
    status = 500

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__


class BadRequest(AppError):
    code = "bad_request"
    status = 400


class NotFound(AppError):
    code = "not_found"
    status = 404


class TaskNotFound(NotFound):
    code = "task_not_found"


class ExportNotFound(NotFound):
    code = "export_not_found"


class ExportUnavailable(AppError):
    """想导的格式这台机器用不了,比如没装 Blender 却要点 FBX。"""

    code = "export_unavailable"
    status = 409


class TaskStateError(AppError):
    """任务状态不对,比如还没跑完就想导出、已经结束的还想取消。"""

    code = "task_state_error"
    status = 409


class FetchError(AppError):
    """抓数据(Overpass/地形)彻底失败:网址全试遍了、备用的招也用完了,只能报错。"""

    code = "fetch_error"
    status = 502


class TaskCancelled(Exception):
    """内部信号,不算错误:用户取消任务时,管线走到哪一步都能用它跳出去。"""
