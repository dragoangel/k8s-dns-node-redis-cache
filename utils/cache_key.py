#!/usr/bin/env python3
"""Generate a redis_cache key from a DNS query.

The plugin stores entries under `<key_prefix>:<hex>` where:
  - hex is xxhash64(qclass||qtype||DO||CD || lowercase(qname)) rendered as a
    16-char big-endian hex string;
  - the leading `qclass||qtype||DO||CD` is 6 bytes (uint16 + uint16 + uint8 +
    uint8), all big-endian;
  - key_prefix defaults to `cdrc` (set `key_prefix ""` in the Corefile to
    disable; the `:` separator is dropped along with it).

Requires `xxhash` (`pip install xxhash`).
"""

import argparse
import struct
import sys

try:
    import xxhash
except ImportError:
    sys.exit("This script requires the `xxhash` package. Install with: pip install xxhash")

QTYPES = {
    "A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "PTR": 12, "HINFO": 13,
    "MX": 15, "TXT": 16, "AAAA": 28, "SRV": 33, "OPT": 41, "DS": 43,
    "RRSIG": 46, "NSEC": 47, "DNSKEY": 48, "NSEC3": 50, "HTTPS": 65,
    "ANY": 255, "URI": 256, "CAA": 257,
}

QCLASSES = {
    "IN": 1,
    "CH": 3, "CHAOS": 3,
    "HS": 4, "HESIOD": 4,
    "ANY": 255,
}

# RFC 1035 caps a DNS name at 255 bytes; anything past that isn't a
# valid query, so reject rather than guess.
MAX_QNAME_BYTES = 255


def cache_key(prefix: str, qname: str, qclass: int, qtype: int, do: bool, cd: bool) -> str:
    """Reproduce the redis_cache key from cache.go: xxhash64(qclass||qtype||DO||CD || lower(qname))."""
    body = qname.lower().encode("ascii")
    if len(body) > MAX_QNAME_BYTES:
        sys.exit(f"error: qname is {len(body)} bytes, RFC 1035 caps a name at {MAX_QNAME_BYTES} — not a valid DNS query")
    hdr = struct.pack("!HHBB", qclass, qtype, 1 if do else 0, 1 if cd else 0)
    digest = xxhash.xxh64(hdr + body).intdigest()
    hexsum = struct.pack("!Q", digest).hex()
    if prefix == "":
        return hexsum
    return f"{prefix}:{hexsum}"


def parse_qtype(arg: str) -> int:
    upper = arg.upper()
    if upper in QTYPES:
        return QTYPES[upper]
    if arg.isdigit():
        return int(arg)
    sys.exit(f"unknown qtype: {arg}")


def parse_qclass(arg: str) -> int:
    upper = arg.upper()
    if upper in QCLASSES:
        return QCLASSES[upper]
    if arg.isdigit():
        return int(arg)
    sys.exit(f"unknown qclass: {arg}")


def main():
    p = argparse.ArgumentParser(
        description="Reproduce a redis_cache key for a given DNS question.",
    )
    p.add_argument("qname", help="DNS name (e.g. example.com.)")
    p.add_argument("qtype", help="Record type (e.g. A, AAAA, HINFO, 13)")
    p.add_argument("--qclass", default="IN", help="DNS class: IN (default), CH, HS, ANY, or numeric")
    p.add_argument("--do", action="store_true", help="DNSSEC OK flag (default off)")
    p.add_argument("--cd", action="store_true", help="Checking Disabled flag (default off)")
    p.add_argument("--prefix", default="cdrc", help='Key prefix (default "cdrc"; "" disables)')
    args = p.parse_args()

    qname = args.qname if args.qname.endswith(".") else args.qname + "."
    qtype = parse_qtype(args.qtype)
    qclass = parse_qclass(args.qclass)

    print(cache_key(args.prefix, qname, qclass, qtype, args.do, args.cd))


if __name__ == "__main__":
    main()
