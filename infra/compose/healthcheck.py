#!/usr/bin/env python3
"""Generic healthcheck script for Docker Compose services."""

import argparse
import http.client
import socket
import sys

HTTP_OK = 200

parser = argparse.ArgumentParser(description="Generic healthcheck script")
parser.add_argument("--host", default="127.0.0.1", help="Host to check")
parser.add_argument("--port", type=int, default=8000, help="Port to check")
parser.add_argument("--path", help="HTTP path for HTTP healthcheck; if omitted, perform TCP check")
parser.add_argument("--timeout", type=float, default=1.0, help="Timeout in seconds")
args = parser.parse_args()

if args.path:
    try:
        conn = http.client.HTTPConnection(args.host, args.port, timeout=args.timeout)
        conn.request("GET", args.path)
        resp = conn.getresponse()
        sys.exit(0 if resp.status == HTTP_OK else 1)
    except OSError, http.client.HTTPException:
        sys.exit(1)
else:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(args.timeout)
    try:
        sock.connect((args.host, args.port))
        sys.exit(0)
    except OSError:
        sys.exit(1)
