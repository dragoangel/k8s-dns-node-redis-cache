#!/usr/bin/env python3
"""Decode a DNS wire-format record from redis_cache.

Cached values are raw DNS wire format. Typical workflow:

    # read from piped stdin
    redis-cli GET <key> | decode_cache_record.py
    # read from file
    redis-cli GET <key> > /tmp/value && decode_cache_record.py /tmp/value
    # read from hex string
    decode_cache_record.py --hex 0001818000010001...
"""

import argparse
import struct
import sys

QTYPES = {
    1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 12: "PTR", 13: "HINFO",
    15: "MX", 16: "TXT", 28: "AAAA", 33: "SRV", 41: "OPT", 43: "DS",
    46: "RRSIG", 47: "NSEC", 48: "DNSKEY", 50: "NSEC3", 65: "HTTPS",
    255: "ANY", 256: "URI", 257: "CAA",
}

RCODES = {
    0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN",
    4: "NOTIMP", 5: "REFUSED",
}


def decode_name(data, offset):
    """Decode a DNS name from wire format, handling compression pointers."""
    labels = []
    seen = set()
    while offset < len(data):
        if offset in seen:
            break
        seen.add(offset)
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:
            ptr = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            offset += 2
            suffix, _ = decode_name(data, ptr)
            labels.append(suffix)
            return ".".join(labels), offset
        offset += 1
        labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
        offset += length
    return ".".join(labels) + "." if labels else ".", offset


def find_edns_do(data, arcount):
    """Walk to ADDITIONAL section and return the DO bit from the EDNS OPT record,
    or None if no OPT is present. OPT's TTL field (RFC 6891) encodes
    extended-rcode(1B) | version(1B) | DO(1b) | Z(15b); DO is the MSB of the
    low 16 bits."""
    if arcount == 0 or len(data) < 12:
        return None
    _, _, qdcount, ancount, nscount, _ = struct.unpack("!6H", data[:12])
    offset = 12
    for _ in range(qdcount):
        _, offset = decode_name(data, offset)
        if offset + 4 > len(data):
            return None
        offset += 4
    for _ in range(ancount + nscount):
        _, offset = decode_name(data, offset)
        if offset + 10 > len(data):
            return None
        rdlength = struct.unpack("!H", data[offset + 8:offset + 10])[0]
        offset += 10 + rdlength
    for _ in range(arcount):
        _, offset = decode_name(data, offset)
        if offset + 10 > len(data):
            return None
        rtype, _, ttl, rdlength = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10 + rdlength
        if rtype == 41:
            return (ttl >> 15) & 1
    return None


def decode_record(data, offset):
    """Decode a single DNS resource record."""
    name, offset = decode_name(data, offset)
    if offset + 10 > len(data):
        return None, offset
    rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[offset:offset + 10])
    offset += 10
    rdata_raw = data[offset:offset + rdlength]
    rdata = format_rdata(rtype, rdata_raw, data, offset)
    offset += rdlength
    return {"name": name, "type": QTYPES.get(rtype, str(rtype)), "class": rclass, "ttl": ttl, "rdata": rdata}, offset


def format_rdata(rtype, rdata, full, offset):
    """Format RDATA for common types."""
    try:
        if rtype == 1 and len(rdata) == 4:  # A
            return ".".join(str(b) for b in rdata)
        if rtype == 28 and len(rdata) == 16:  # AAAA
            import socket
            return socket.inet_ntop(socket.AF_INET6, rdata)
        if rtype in (2, 5, 12):  # NS, CNAME, PTR
            name, _ = decode_name(full, offset)
            return name
        if rtype == 6:  # SOA
            mname, pos = decode_name(full, offset)
            rname, pos = decode_name(full, pos)
            if pos + 20 <= len(full):
                serial, refresh, retry, expire, minimum = struct.unpack("!5I", full[pos:pos + 20])
                return f"{mname} {rname} {serial} {refresh} {retry} {expire} {minimum}"
            return f"{mname} {rname}"
        if rtype == 15 and len(rdata) >= 2:  # MX
            pref = struct.unpack("!H", rdata[:2])[0]
            exchange, _ = decode_name(full, offset + 2)
            return f"{pref} {exchange}"
        if rtype == 16:  # TXT
            parts, pos = [], 0
            while pos < len(rdata):
                tlen = rdata[pos]
                pos += 1
                parts.append(rdata[pos:pos + tlen].decode("utf-8", errors="replace"))
                pos += tlen
            return " ".join(f'"{p}"' for p in parts)
    except Exception:
        pass
    return rdata.hex()


def parse_args():
    p = argparse.ArgumentParser(
        description="Decode a DNS wire-format record cached by redis_cache.",
    )
    p.add_argument("--hex", metavar="STR",
                   help="hex-encoded wire bytes")
    p.add_argument("file", nargs="?",
                   help="file containing raw wire bytes; '-' or omitted reads stdin")
    return p.parse_args()


def load_data(args):
    if args.hex:
        return bytes.fromhex(args.hex.replace(" ", "").replace("\n", ""))
    if args.file is None or args.file == "-":
        return sys.stdin.buffer.read()
    with open(args.file, "rb") as fh:
        return fh.read()


def main():
    args = parse_args()
    data = load_data(args)

    if len(data) < 12:
        print("Error: data too short for DNS header", file=sys.stderr)
        sys.exit(1)

    msg_id, flags, qdcount, ancount, nscount, arcount = struct.unpack("!6H", data[:12])
    qr = (flags >> 15) & 1
    opcode = (flags >> 11) & 0xF
    aa = (flags >> 10) & 1
    tc = (flags >> 9) & 1
    rd = (flags >> 8) & 1
    ra = (flags >> 7) & 1
    ad = (flags >> 5) & 1
    cd = (flags >> 4) & 1
    rcode = flags & 0xF

    # DO lives in the EDNS OPT pseudo-RR (additional section), not the header.
    # Scan for it so the cache-key-relevant bits (DO + CD) are both visible.
    do = find_edns_do(data, arcount)

    print(f"ID:     {msg_id}")
    print(f"Flags:  QR={qr} Opcode={opcode} AA={aa} TC={tc} RD={rd} RA={ra} AD={ad} CD={cd} Rcode={RCODES.get(rcode, rcode)}")
    print(f"EDNS:   DO={do if do is not None else '-'}")
    print(f"Counts: QUERY={qdcount} ANSWER={ancount} AUTHORITY={nscount} ADDITIONAL={arcount}")

    offset = 12

    if qdcount:
        print("\n;; QUESTION SECTION:")
        for _ in range(qdcount):
            qname, offset = decode_name(data, offset)
            if offset + 4 > len(data):
                break
            qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])
            offset += 4
            print(f"  {qname}\t{QTYPES.get(qtype, str(qtype))}\tIN")

    for section, count in [("ANSWER", ancount), ("AUTHORITY", nscount), ("ADDITIONAL", arcount)]:
        if count:
            print(f"\n;; {section} SECTION:")
            for _ in range(count):
                rr, offset = decode_record(data, offset)
                if rr is None:
                    break
                print(f"  {rr['name']}\t{rr['ttl']}\tIN\t{rr['type']}\t{rr['rdata']}")


if __name__ == "__main__":
    main()
