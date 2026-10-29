# Doors Rework tracker — container image
FROM python:3.12-slim-bookworm

# --- System deps + Microsoft ODBC Driver 17 for SQL Server ---------------
# Needed for pyodbc's connection to the SyteLine ERP reports DB.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 apt-transport-https ca-certificates unixodbc unixodbc-dev libgssapi-krb5-2 \
    && mkdir -p /usr/share/keyrings \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && apt-get purge -y --auto-remove curl gnupg2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 rework
USER rework

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PORT=5050
EXPOSE 5050

CMD ["python", "server.py"]
