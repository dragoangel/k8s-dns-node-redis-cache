# Build stage
FROM golang:1.26-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
ARG VERSION=""
RUN BUILD_VER="${VERSION:-$(cat go-node-cache-version 2>/dev/null || echo -n unknown)}" && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w -X k8s.io/dns/pkg/version.VERSION=${BUILD_VER}" -o /node-cache ./cmd/node-cache/

# Runtime stage
# node-local-dns requires root for network interface setup and iptables management
FROM gcr.io/distroless/static-debian12

COPY --from=builder /node-cache /node-cache
LABEL org.opencontainers.image.title="k8s-dns-node-redis-cache" \
      org.opencontainers.image.description="Node-local DNS cache with a shared Redis/Valkey-backed L2 cache" \
      org.opencontainers.image.authors="Dmytro Alieksieiev (dragoangel)" \
      org.opencontainers.image.source="https://github.com/dragoangel/k8s-dns-node-redis-cache" \
      org.opencontainers.image.licenses="Apache-2.0"

EXPOSE 53/udp 53/tcp

ENTRYPOINT ["/node-cache"]
