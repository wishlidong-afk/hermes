"""Offline dependency behavior probe; does not import Hermes or access live data."""
from __future__ import annotations

import http.client
import io
import json
import socket
import ssl

import certifi
import urllib3


def main() -> int:
    network_attempts = []

    def deny_network(*_args, **_kwargs):
        network_attempts.append("blocked")
        raise RuntimeError("network is forbidden in this probe")

    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network

    class MemorySocket:
        def makefile(self, *_args, **_kwargs):
            return io.BytesIO(
                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                + b"0" * 70000 + b"\r\n\r\n"
            )

    response = http.client.HTTPResponse(MemorySocket(), method="GET")
    response.begin()
    wrapped = urllib3.response.HTTPResponse(
        body=response, original_response=response, status=response.status,
        headers=dict(response.getheaders()), preload_content=False,
    )
    detail = "oversized chunk line accepted"
    rejected = False
    try:
        list(wrapped.read_chunked())
    except urllib3.exceptions.ProtocolError as exc:
        detail = str(exc)
        rejected = "Response chunk size line exceeded maximum allowed length" in detail
    finally:
        wrapped.close()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    common_names = {
        value
        for certificate in context.get_ca_certs()
        for rdn in certificate["subject"]
        for key, value in rdn
        if key == "commonName"
    }
    affected_root_present = "emSign ECC Root CA - G3" in common_names
    verification_enabled = context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    passed = rejected and not affected_root_present and verification_enabled and not network_attempts
    report = {
        "status": "PASS" if passed else "FAIL",
        "urllib3_version": urllib3.__version__,
        "certifi_version": certifi.__version__,
        "oversized_chunk_line_rejected": rejected,
        "chunk_detail": detail,
        "affected_root_present": affected_root_present,
        "tls_verification_enabled": verification_enabled,
        "ca_count": len(common_names),
        "network_attempts": len(network_attempts),
        "limits": "Offline chunk parser and CA-store checks, not an external TLS/proxy connectivity test.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
