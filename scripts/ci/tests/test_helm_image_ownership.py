from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from _documents import load_jsonc, load_mapping

_ROOT = Path(__file__).resolve().parents[3]
_RENOVATE = _ROOT / ".github" / "renovate.json5"
_MAIN_VALUES = Path("infra/k8s/helm/values.yaml")
_PRODUCTION_DIGESTS = Path("infra/k8s/helm/values.prod.digests.yaml")
_HELM_ROOTS = (_ROOT / "infra" / "k8s" / "helm", _ROOT / "infra" / "k8s" / "helm-foundation")
_PINNED_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}@sha256:[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CANONICAL_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")

type _Location = tuple[str | int, ...]
type _Owner = Literal["ci-digest-pr", "renovate", "manual-pair", "inherited"]
type _SiteKey = tuple[Path, _Location]


@dataclass(frozen=True)
class _ImageSite:
    path: Path
    location: _Location
    value: object

    @property
    def key(self) -> _SiteKey:
        return self.path, self.location


# These vendored templates prepend @sha256:, so their values must remain raw hex.
_RAW_SHA_SITES = frozenset(
    {
        (
            _MAIN_VALUES,
            ("kube-prometheus-stack", "prometheusOperator", "image"),
        ),
        (
            _MAIN_VALUES,
            ("kube-prometheus-stack", "prometheusOperator", "admissionWebhooks", "patch", "image"),
        ),
        (
            _MAIN_VALUES,
            ("kube-prometheus-stack", "prometheusOperator", "prometheusConfigReloader", "image"),
        ),
        (
            _MAIN_VALUES,
            ("kube-prometheus-stack", "prometheus", "prometheusSpec", "image"),
        ),
        (
            _MAIN_VALUES,
            ("kube-prometheus-stack", "alertmanager", "alertmanagerSpec", "image"),
        ),
    }
)
_CANONICAL_SHA_SITES = frozenset(
    {
        (
            _MAIN_VALUES,
            ("kube-prometheus-stack", "kube-state-metrics", "image"),
        )
    }
)


def _as_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        message = "Helm values image mappings must use string keys"
        raise TypeError(message)
    return cast(dict[str, object], value)


def _values_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for helm_root in _HELM_ROOTS
            for pattern in ("values*.yaml", "values*.yml")
            for path in helm_root.rglob(pattern)
        )
    )


def _is_image_block(block: dict[str, object]) -> bool:
    tag = block.get("tag")
    repository = block.get("repository")
    return (
        "digest" in block
        or "sha" in block
        or tag == ""
        or (isinstance(tag, str) and _PINNED_TAG.fullmatch(tag) is not None)
        or (isinstance(repository, str) and bool(repository) and ("tag" in block or "version" in block))
    )


def _walk_image_sites(path: Path, node: object, location: _Location = ()) -> Iterator[_ImageSite]:
    mapping = _as_mapping(node)
    if mapping is not None:
        if location[-1:] == ("imageDigests",):
            for repository, digest in mapping.items():
                yield _ImageSite(path, (*location, repository), digest)
            return
        if _is_image_block(mapping):
            yield _ImageSite(path, location, mapping)
        for key, value in mapping.items():
            yield from _walk_image_sites(path, value, (*location, key))
        return

    if isinstance(node, list):
        for index, value in enumerate(cast(list[object], node)):
            yield from _walk_image_sites(path, value, (*location, index))
        return

    if location[-1:] == ("imageTag",) or (
        location
        and isinstance(location[-1], str)
        and location[-1].lower().endswith("image")
        and isinstance(node, str)
        and node
    ):
        yield _ImageSite(path, location, node)


def _image_sites() -> tuple[_ImageSite, ...]:
    return tuple(
        site for path in _values_files() for site in _walk_image_sites(path.relative_to(_ROOT), load_mapping(path))
    )


def _owners(site: _ImageSite) -> frozenset[_Owner]:
    owners: set[_Owner] = set()
    block = _as_mapping(site.value)
    if site.path == _PRODUCTION_DIGESTS and site.location[:2] == ("global", "imageDigests"):
        owners.add("ci-digest-pr")
    if block is not None:
        tag = block.get("tag")
        if isinstance(tag, str) and _PINNED_TAG.fullmatch(tag) is not None:
            owners.add("renovate")
        if "tag" in block and ("digest" in block or "sha" in block):
            owners.add("manual-pair")
        if tag == "":
            owners.add("inherited")
    if site.location[-2:] == ("global", "imageTag"):
        owners.add("inherited")
    return frozenset(owners)


def _description(site: _ImageSite) -> str:
    location = ".".join(str(part) for part in site.location)
    return f"{site.path}:{location}"


def _renovate_package_name(site: _ImageSite) -> str | None:
    block = _as_mapping(site.value)
    if block is None or not site.location or not str(site.location[-1]).lower().endswith("image"):
        return None
    repository = block.get("repository")
    if not isinstance(repository, str) or not repository or not ("tag" in block or "version" in block):
        return None
    registry = block.get("registry")
    prefix = f"{registry}/" if isinstance(registry, str) and registry else ""
    return f"{prefix}{repository}"


def _renovate_excluded_packages() -> frozenset[str]:
    config = load_jsonc(_RENOVATE)
    rules = config.get("packageRules")
    assert isinstance(rules, list), "Renovate packageRules must be a list"
    candidates = []
    for value in cast(list[object], rules):
        rule = _as_mapping(value)
        if (
            rule is not None
            and rule.get("matchManagers") == ["helm-values"]
            and rule.get("matchFileNames") == [_MAIN_VALUES.as_posix()]
            and rule.get("enabled") is False
        ):
            candidates.append(rule)
    assert len(candidates) == 1, "expected one values.yaml helm-values exclusion rule"
    package_names = candidates[0].get("matchPackageNames")
    assert isinstance(package_names, list), "helm-values exclusion must match package names"
    assert all(isinstance(name, str) for name in package_names), "excluded package names must be strings"
    return frozenset(cast(list[str], package_names))


def test_every_helm_image_site_has_exactly_one_owner() -> None:
    sites = _image_sites()
    assert sites, "no Helm image sites discovered"
    failures = [f"{_description(site)} has owners {sorted(_owners(site))}" for site in sites if len(_owners(site)) != 1]
    assert not failures, "every Helm image site must have exactly one owner:\n" + "\n".join(failures)


def test_manual_pairs_are_exactly_the_helm_values_dependencies_renovate_excludes() -> None:
    sites = _image_sites()
    manual_sites = tuple(site for site in sites if "manual-pair" in _owners(site))
    excluded = _renovate_excluded_packages()
    extractable_manual_packages = frozenset(
        package_name for site in manual_sites if (package_name := _renovate_package_name(site)) is not None
    )
    assert excluded == extractable_manual_packages, (
        "Renovate exclusions must equal the sibling-pair dependencies its helm-values manager can extract: "
        f"excluded={sorted(excluded)}, sibling_pairs={sorted(extractable_manual_packages)}"
    )

    blocked_self_contained = [
        _description(site) for site in sites if "renovate" in _owners(site) and _renovate_package_name(site) in excluded
    ]
    assert not blocked_self_contained, "Renovate exclusion also blocks self-contained image pins: " + ", ".join(
        blocked_self_contained
    )


def test_vendored_raw_sha_fields_never_gain_a_sha256_prefix() -> None:
    manual_by_key = {site.key: site for site in _image_sites() if "manual-pair" in _owners(site)}
    sha_sites = {key: site for key, site in manual_by_key.items() if "sha" in cast(dict[str, object], site.value)}
    declared_sha_sites = _RAW_SHA_SITES | _CANONICAL_SHA_SITES
    assert sha_sites.keys() == declared_sha_sites, (
        "every sibling sha field must declare whether its chart expects raw or canonical form: "
        f"discovered={sorted(map(str, sha_sites))}, declared={sorted(map(str, declared_sha_sites))}"
    )

    failures: list[str] = []
    for key in _RAW_SHA_SITES:
        site = sha_sites[key]
        value = cast(dict[str, object], site.value)["sha"]
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            failures.append(f"{_description(site)}.sha must be raw 64-character hex, got {value!r}")
    for key in _CANONICAL_SHA_SITES:
        site = sha_sites[key]
        value = cast(dict[str, object], site.value)["sha"]
        if not isinstance(value, str) or _CANONICAL_SHA256.fullmatch(value) is None:
            failures.append(f"{_description(site)}.sha must be sha256:<64-character hex>, got {value!r}")
    assert not failures, "\n".join(failures)
