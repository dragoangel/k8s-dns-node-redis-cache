BINARY   := node-cache
GITHUB_OWNER ?= $(shell git remote get-url origin 2>/dev/null | sed -E 's#.*github.com[:/]([^/]+)/.*#\1#' || true)
REGISTRY ?= ghcr.io/$(if $(GITHUB_OWNER),$(GITHUB_OWNER),your-github-org)
# k8s.io/dns (node-local-dns) release version — kept in sync with the pinned dependency tag.
# Bump via `make update-k8sdns` (auto-detects latest) or `make update-k8sdns K8SDNS_TAG=x.y.z`.
# See: https://github.com/kubernetes/dns/tags
VERSION     ?= $(shell cat go-node-cache-version 2>/dev/null || echo UNKNOWN)
IMAGE    := $(REGISTRY)/k8s-dns-node-redis-cache:$(VERSION)

VERSION_PKG := k8s.io/dns/pkg/version
GOFLAGS  := -ldflags="-s -w -X $(VERSION_PKG).VERSION=$(VERSION)"

.PHONY: build test lint docker-build docker-build-legacy docker-push docker-push-legacy update-coredns update-k8sdns update-redis-cache update-deps clean

build:
	CGO_ENABLED=0 go build $(GOFLAGS) -o bin/$(BINARY) ./cmd/node-cache/

test:
	go test -race -v ./...

lint:
	golangci-lint run ./...

docker-build:
	docker build --build-arg VERSION=$(VERSION) -t $(IMAGE) .

docker-build-legacy:
	docker build --provenance=false --sbom=false --build-arg VERSION=$(VERSION) -t $(IMAGE) .

docker-push: docker-build
	docker push $(IMAGE)

docker-push-legacy: docker-build-legacy
	docker push $(IMAGE)

# update-coredns: bump github.com/coredns/coredns to a release tag.
# Override the detected tag with `make update-coredns COREDNS_TAG=v1.14.3`.
update-coredns:
	@TAG=$${COREDNS_TAG:-$$(git ls-remote --tags --refs --sort='-v:refname' \
	    https://github.com/coredns/coredns.git 'refs/tags/v[0-9]*.[0-9]*.[0-9]*' \
	    | head -1 | sed 's|.*refs/tags/||')}; \
	test -n "$$TAG" || { echo "could not determine latest coredns tag; pass COREDNS_TAG=vX.Y.Z" >&2; exit 1; }; \
	echo "Bumping github.com/coredns/coredns to $$TAG"; \
	go get github.com/coredns/coredns@$$TAG && go mod tidy

# update-k8sdns: bump k8s.io/dns to a release tag and sync go-node-cache-version.
# k8s.io/dns publishes non-`v`-prefixed tags (e.g. 1.26.8), so go.mod records them
# as a pseudo-version, but `go get k8s.io/dns@<TAG>` resolves the tag correctly.
# Override the detected tag with `make update-k8sdns K8SDNS_TAG=1.26.5`.
update-k8sdns:
	@TAG=$${K8SDNS_TAG:-$$(git ls-remote --tags --refs --sort='-v:refname' \
	    https://github.com/kubernetes/dns.git 'refs/tags/[0-9]*.[0-9]*.[0-9]*' \
	    | head -1 | sed 's|.*refs/tags/||')}; \
	test -n "$$TAG" || { echo "could not determine latest k8s.io/dns tag; pass K8SDNS_TAG=x.y.z" >&2; exit 1; }; \
	echo "Bumping k8s.io/dns to $$TAG"; \
	go get k8s.io/dns@$$TAG && go mod tidy && echo $$TAG > go-node-cache-version; \
	echo "go-node-cache-version: $$(cat go-node-cache-version)"

# update-redis-cache: bump github.com/dragoangel/coredns-redis-cache-plugin to a release tag.
# Override the detected tag with `make update-redis-cache REDIS_CACHE_TAG=v1.1.0`.
update-redis-cache:
	@TAG=$${REDIS_CACHE_TAG:-$$(git ls-remote --tags --refs --sort='-v:refname' \
	    https://github.com/dragoangel/coredns-redis-cache-plugin.git 'refs/tags/v[0-9]*.[0-9]*.[0-9]*' \
	    | head -1 | sed 's|.*refs/tags/||')}; \
	test -n "$$TAG" || { echo "could not determine latest coredns-redis-cache-plugin tag; pass REDIS_CACHE_TAG=vX.Y.Z" >&2; exit 1; }; \
	echo "Bumping github.com/dragoangel/coredns-redis-cache-plugin to $$TAG"; \
	go get github.com/dragoangel/coredns-redis-cache-plugin@$$TAG && go mod tidy

# update-deps: bump pinned dependencies (coredns, k8s.io/dns, coredns-redis-cache-plugin)
# to their latest release tags. Transitive deps follow from each release's go.mod
# via `go mod tidy`, so no generic `go get -u` sweep is needed (and would diverge
# from what k8s.io/dns ships at its release tag).
# Override individual tags with COREDNS_TAG / K8SDNS_TAG / REDIS_CACHE_TAG.
update-deps: update-coredns update-k8sdns update-redis-cache

clean:
	rm -rf bin/
