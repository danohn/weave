FROM python:3.12-slim

WORKDIR /app

# System dependencies:
#   wireguard-tools — wg(8) for managing the route reflector wg0 interface
#   iproute2        — ip(8) for link/addr/route management
#   frr             — bgpd + bfdd for BGP route reflection and BFD
RUN apt-get update && apt-get install -y \
    wireguard-tools \
    iproute2 \
    frr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv pip install --system .

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
