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

EXPOSE 53/udp 53/tcp

ENTRYPOINT ["/node-cache"]
