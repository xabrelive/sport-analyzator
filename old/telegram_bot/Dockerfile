FROM python:3.12-slim

WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
COPY app ./app
RUN uv sync --no-dev --no-editable
COPY . .
ENV PYTHONPATH=/app
CMD ["uv", "run", "python", "-m", "app.main"]
