from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_POLICY = _ROOT / "infra/k8s/local/offline-egress.nft"
_EXPECTED = """table inet nohiki_offline {
  set private_v4 {
    type ipv4_addr
    flags interval
    elements = { 10.0.0.0/8, 127.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 }
  }
  chain output {
    type filter hook output priority -10; policy accept;
    ip daddr @private_v4 accept
    ip6 daddr ::1 accept
    counter reject
  }
  chain forward {
    type filter hook forward priority -10; policy accept;
    ip daddr @private_v4 accept
    ip6 daddr ::1 accept
    counter reject
  }
}
"""


def _chain(source: str, name: str) -> str:
    match = re.search(rf"  chain {name} \{{\n(?P<body>(?:    .*\n)+)  \}}", source)
    assert match is not None
    return match.group("body")


def test_offline_policy_bytes_are_the_ratified_c1_probe_policy() -> None:
    assert _POLICY.read_text(encoding="utf-8") == _EXPECTED


def test_private_allowlist_is_closed_to_rfc1918_and_loopback() -> None:
    source = _POLICY.read_text(encoding="utf-8")
    elements = re.search(r"elements = \{ (?P<values>[^}]+) \}", source)
    assert elements is not None
    assert [value.strip() for value in elements.group("values").split(",")] == [
        "10.0.0.0/8",
        "127.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ]
    assert source.count("ip6 daddr ::1 accept") == 2


def test_output_and_forward_have_accept_policy_then_terminal_counted_reject() -> None:
    source = _POLICY.read_text(encoding="utf-8")
    for name in ("output", "forward"):
        lines = [line.strip() for line in _chain(source, name).splitlines()]
        assert lines == [
            f"type filter hook {name} priority -10; policy accept;",
            "ip daddr @private_v4 accept",
            "ip6 daddr ::1 accept",
            "counter reject",
        ]
    assert source.count("counter reject") == 2
    assert "drop" not in source
    assert "flush ruleset" not in source
