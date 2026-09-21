# 后端镜像:Python 3.12 slim + 项目依赖。
# 注意:故意不用 3.14——mapbox-earcut 等包还没有 3.14 的轮子。

FROM python:3.12-slim

WORKDIR /app

# 先装依赖(利用层缓存),再拷代码:代码放前面的话,改一行代码整个
# 依赖层都要重下。安装 editable 包需要 app 目录存在,先放个占位的
# __init__.py 让 setuptools 过关,真代码在下一层再覆盖进来。
# GIS 和 USD 这两组可选依赖也一并装上,容器里 17 种格式开箱即用
# (不装的话 GPKG/USDZ 这些按钮就是灰的,和本机跑不一致)。
# (以前还要装中文字体给 PNG/PDF 图例用,图例英文化后不需要了)
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --no-cache-dir -e ".[gis,usd]" -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY app ./app

# 数据目录(运行时由卷挂载覆盖)
RUN mkdir -p /app/data
ENV M2M_DATA_DIR=/app/data

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
