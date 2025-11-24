FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 7003

# 容器启动命令：Gunicorn监听0.0.0.0:7003
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:7003", "app:app"]
