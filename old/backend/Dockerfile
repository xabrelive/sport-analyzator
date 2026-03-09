FROM python:3.12-slim

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1
RUN pip install uv

COPY . .
ENV PYTHONPATH=/app
RUN uv sync --no-dev --no-editable

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "11001"]
