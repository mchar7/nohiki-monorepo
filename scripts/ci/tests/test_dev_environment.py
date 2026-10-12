"""Contract tests for the portable developer toolchain.

Pure text checks over repo-root tooling files: stdlib only, no cluster, Nix, or
network, so they run wherever pytest does.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENVRC = REPO_ROOT / ".envrc"
FLAKE = REPO_ROOT / "flake.nix"
README = REPO_ROOT / "README.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing tooling file: {path}"
    return path.read_text(encoding="utf-8")


# (runtime env var, secret file path under the shared secrets dir)
SECRET_READS = [
    ("OPENAI_API_KEY", "llm/provider/api_keys/openai"),
    ("OPENROUTER_API_KEY", "llm/provider/api_keys/openrouter"),
    ("NOTIFICATION_EMAIL__API_KEY", "email/api_key"),
]


def _secrets_block(text: str) -> str:
    idx = text.find("SECRETS_DIR")
    assert idx != -1, ".envrc must define a SECRETS_DIR-based secret loader"
    return text[idx:]


def test_envrc_uses_shared_secrets_dir_anchored_at_project_root() -> None:
    text = _read(ENVRC)
    # Anchored under PROJECT_ROOT, not a bare pwd, and never the retired compose path.
    assert re.search(
        r'SECRETS_DIR="?\$\{?PROJECT_ROOT\}?/infra/shared/secrets"?',
        text,
    ), "SECRETS_DIR must point at ${PROJECT_ROOT}/infra/shared/secrets"
    assert "infra/compose/secrets" not in text, "SECRETS_DIR must not reference the retired infra/compose/secrets path"


def test_envrc_maps_each_secret_var_to_its_shared_path() -> None:
    block = _secrets_block(_read(ENVRC))
    for var, subpath in SECRET_READS:
        # Match either loader form: helper call or inline export.
        assert re.search(re.escape(var) + r'\b[^\n]*"' + re.escape(subpath) + r'"', block), (
            f"{var} must be sourced from the shared secret path {subpath!r}"
        )


def test_envrc_secret_reads_are_guarded_and_quoted() -> None:
    block = _secrets_block(_read(ENVRC))
    assert re.search(r'\[\s*-f\s+"[^"]+"\s*\]', block), "secret reads must be guarded by an [ -f ] existence check"
    assert re.search(r'\$\(cat\s+"[^"]+"\)', block), 'secret files must be read via quoted $(cat "...")'


def test_envrc_has_no_unquoted_command_substitution_paths() -> None:
    text = _read(ENVRC)
    # Guards against the word-splitting/glob footgun $(cat $SECRETS_DIR/key).
    unquoted = re.findall(r"\$\(cat\s+(?!\")\S", text)
    assert not unquoted, f"unquoted path passed to $(cat ...): {unquoted}"


def test_envrc_never_prints_secret_values() -> None:
    text = _read(ENVRC)
    for var, _ in SECRET_READS:
        assert not re.search(rf"echo\s+.*\$\{{?{re.escape(var)}\b", text), f"{var} value must never be echoed"


def test_flake_k8s_shell_is_context_neutral() -> None:
    text = _read(FLAKE)
    forbidden = {
        "/etc/rancher/k3s": "hardcoded workstation k3s kubeconfig path",
        "systemctl": "host service management",
        "services.k3s.enable": "NixOS-host provisioning hint",
    }
    for token, why in forbidden.items():
        assert token not in text, (
            f"flake.nix k8s shell must not reference {token!r} ({why}); honor the caller's KUBECONFIG"
        )
    assert not re.search(r"command\s+-v\s+k3s", text), "k8s shell must not probe for a k3s binary"


def test_flake_k8s_shell_still_provides_cluster_tooling() -> None:
    text = _read(FLAKE)
    match = re.search(r"devShells\.k8s\s*=\s*pkgs\.mkShell\s*\{.*?\n        \};", text, re.DOTALL)
    assert match, "devShells.k8s must be defined"
    block = match.group(0)
    for tool_set in ("infraTools", "k8sTools"):
        assert tool_set in block, f"devShells.k8s must include {tool_set}"


def test_readme_documents_both_nix_and_non_nix_setup() -> None:
    text = _read(README).lower()
    assert "direnv" in text, "README must keep the Nix + direnv setup path"
    assert "without nix" in text, "README must document a non-Nix setup path"
