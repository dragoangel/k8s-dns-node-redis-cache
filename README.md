# k8s-dns-node-redis-cache

Node-local DNS cache with a shared Redis/Valkey-backed L2 cache.

This project is a fork/adaptation of Kubernetes `node-local-dns` with:

- Redis-backed shared cache plugin (`github.com/dragoangel/coredns-redis-cache-plugin` - included in `main.go`)
- Hostname resolution support for `forward` upstream targets (via patched CoreDNS - replaced in `go.mod`)
- Containerized workflow for local development and production image publishing

## Why this exists

Compared to running DNS only through a centralized CoreDNS `Deployment`, `node-local-dns` as a `DaemonSet` gives each node its own local DNS cache and local DNS path. Key benefits are:
- Local cache with low latency and fewer (or no) cross-node hops for DNS queries
- Eliminated blast radius: when one shared CoreDNS `Deployment` replica is overloaded, all nodes in the cluster see slower or less reliable DNS responses; with node-local DNS, overload is isolated to the local node's DNS path
- Better isolation: DNS load spikes on one node are contained to that node

This project eliminates the gap of small, per-node-limited DNS caches by introducing a shared Redis/Valkey L2 cache, which improves cache reuse across nodes and reduces load on upstream DNS servers.

## Repository layout

- `cmd/node-cache/main.go`: customized entrypoint and plugin wiring
- `Dockerfile`: multi-stage build of a distroless runtime image
- `compose.yaml`: local dev stack that pulls the published node-cache image
- `compose.build.yaml`: local override that builds node-cache from source
- `utils/cache_key.py`: generate the Redis key for a given DNS query — use this to find the key under which a specific record is stored in Redis
- `utils/decode_cache_record.py`: decode raw DNS wire-format values stored in Redis — to decode what is actually cached

## Local development

### Prerequisites

- Go 1.26+
- Docker with compose

### Build and test

```bash
make build
make test
```

### Run local stack

Step 1: create your local `.env` file with a random Valkey password.

```bash
if [ ! -f .env ]; then cp .env.example .env; fi

if grep -q '^VALKEY_PASSWORD=changeMeViaEnvFile$' .env || ! grep -q '^VALKEY_PASSWORD=' .env; then
  if command -v openssl >/dev/null 2>&1; then
    rand_tool="openssl"
    valkey_password="$(openssl rand -hex 16)"
  elif command -v python3 >/dev/null 2>&1; then
    rand_tool="python3-secrets"
    valkey_password="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16))
PY
)"
  elif [ -r /dev/urandom ]; then
    rand_tool="/dev/urandom"
    valkey_password="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
  else
    echo "No secure random source found (openssl, python3, /dev/urandom)" >&2
    echo "Enter VALKEY_PASSWORD manually (input hidden), or Ctrl+C to abort." >&2
    stty -echo
    read -r valkey_password
    stty echo
    printf '\n' >&2
  fi

  if [ -n "$valkey_password" ]; then
    echo "Using random source: $rand_tool"

    if grep -q '^VALKEY_PASSWORD=changeMeViaEnvFile$' .env; then
      sed -i "s/^VALKEY_PASSWORD=.*/VALKEY_PASSWORD=${valkey_password}/" .env
    else
      printf '\nVALKEY_PASSWORD=%s\n' "$valkey_password" >> .env
    fi
  fi
fi
```

DNS is exposed by default on `127.0.0.1:5553` (TCP/UDP). You can adjust `DNS_BIND_PORT` and `DNS_BIND_IP` in `.env`.
You can also adjust other settings in `.env`, like `VALKEY_MAXMEMORY`, `VALKEY_MAXMEMORY_POLICY`, and image versions (tags), etc.

Step 2, option A: run against the published image from GitHub.

```bash
docker compose up -d
```

Step 2, option B: run a local development stack with a build override.

```bash
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

## Inspecting the cache

The `utils/` scripts can be used to verify what data is stored in Redis and validate cache correctness.

**Requirements:** `pip install xxhash`

Generate the Redis key for a DNS query and look it up:

```bash
# load local env vars used below (.env preferred, fallback to .env.example)
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE=".env.example"
fi
set -a; source "$ENV_FILE"; set +a

# reusable inputs
QNAME="example.com"
PREFIX=""   # matches key_prefix "" in compose Corefile

# same name, different record types
KEY_A="$(python3 utils/cache_key.py --prefix "$PREFIX" "$QNAME" A)"
KEY_TXT="$(python3 utils/cache_key.py --prefix "$PREFIX" "$QNAME" TXT)"

# same name/type, different flags (defaults are DO=0, CD=0)
KEY_A_DEFAULT="$(python3 utils/cache_key.py --prefix "$PREFIX" "$QNAME" A)"
KEY_A_DO="$(python3 utils/cache_key.py --prefix "$PREFIX" --do "$QNAME" A)"
KEY_A_CD="$(python3 utils/cache_key.py --prefix "$PREFIX" --cd "$QNAME" A)"
KEY_A_DO_CD="$(python3 utils/cache_key.py --prefix "$PREFIX" --do --cd "$QNAME" A)"

echo "$KEY_A $KEY_TXT $KEY_A_DEFAULT $KEY_A_DO $KEY_A_CD $KEY_A_DO_CD"

# generate matching cache entries
dig A "$QNAME" @"${DNS_BIND_IP}" -p "${DNS_BIND_PORT}"
dig TXT "$QNAME" @"${DNS_BIND_IP}" -p "${DNS_BIND_PORT}"
dig +dnssec A "$QNAME" @"${DNS_BIND_IP}" -p "${DNS_BIND_PORT}"
dig +dnssec +cdflag A "$QNAME" @"${DNS_BIND_IP}" -p "${DNS_BIND_PORT}"

# fetch and decode a cached value from read endpoint (replica)
docker compose exec -T valkey-replica valkey-cli -a "$VALKEY_PASSWORD" \
    --raw GET "$KEY_A_DEFAULT" | python3 utils/decode_cache_record.py
```

## Container image publishing

This repo includes GitHub Actions workflows that:

- run CI on pushes and pull requests
- publish multi-arch images (`linux/amd64`, `linux/arm64`) to GHCR on:
  - pushes to `main`
  - semantic version tags (for example `v1.2.3`)

Published image name:

- `ghcr.io/dragoangel/k8s-dns-node-redis-cache`

## Release process

1. Update dependency versions as needed (`make update-deps`).
2. Commit changes.
3. Create and push a tag like `v1.0.0`.
4. GitHub Actions publishes the tagged image to GHCR.

## Notes

- `go.mod` currently uses a temporary CoreDNS fork via `replace` until upstream changes are merged.
- Default compose password values are for local testing only. Use strong secrets in real deployments.

## License

Apache-2.0. See `LICENSE`.
