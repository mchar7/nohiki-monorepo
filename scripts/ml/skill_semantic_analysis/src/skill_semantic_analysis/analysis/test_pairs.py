"""Test skill pairs for threshold calibration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SkillPair:
    """A pair of skills with expected match status."""

    skill_a: str
    skill_b: str
    should_match: bool
    category: str = ""
    notes: str = ""


def _tp(skill_a: str, skill_b: str, category: str = "", notes: str = "") -> SkillPair:
    """Create a true positive pair (should match)."""
    return SkillPair(skill_a, skill_b, should_match=True, category=category, notes=notes)


def _tn(skill_a: str, skill_b: str, category: str = "", notes: str = "") -> SkillPair:
    """Create a true negative pair (should NOT match)."""
    return SkillPair(skill_a, skill_b, should_match=False, category=category, notes=notes)


# TRUE POSITIVES: These SHOULD match (same skill, different representations)
TRUE_POSITIVE_PAIRS = [
    # Exact variations
    _tp("nodejs", "node.js", "exact_variation", "dot in name"),
    _tp("nodejs", "node js", "exact_variation", "space in name"),
    _tp("c++", "cpp", "exact_variation", "symbol vs letters"),
    _tp("c#", "csharp", "exact_variation", "symbol vs letters"),
    _tp("postgresql", "postgres", "exact_variation", "short form"),
    _tp("kubernetes", "k8s", "exact_variation", "numeronym"),
    _tp("elasticsearch", "elastic search", "exact_variation", "compound"),
    _tp("mongodb", "mongo db", "exact_variation", "compound word"),
    _tp("graphql", "graph ql", "exact_variation", "compound word"),
    _tp("vuejs", "vue.js", "exact_variation", "dot in name"),
    _tp("reactjs", "react.js", "exact_variation", "dot in name"),
    _tp("typescript", "ts", "abbreviation", "common abbreviation"),
    _tp("javascript", "js", "abbreviation", "very common abbreviation"),
    # Abbreviations and acronyms
    _tp("machine learning", "ml", "abbreviation", "standard acronym"),
    _tp("artificial intelligence", "ai", "abbreviation", "standard acronym"),
    _tp("natural language processing", "nlp", "abbreviation", "acronym"),
    _tp("amazon web services", "aws", "abbreviation", "cloud acronym"),
    _tp("google cloud platform", "gcp", "abbreviation", "cloud acronym"),
    _tp("user interface", "ui", "abbreviation", "standard acronym"),
    _tp("user experience", "ux", "abbreviation", "standard acronym"),
    # Case variations
    _tp("Python", "python", "case", "title vs lower"),
    _tp("JAVA", "java", "case", "upper vs lower"),
    # Semantic equivalents
    _tp("software engineering", "software development", "semantic", "synonyms"),
    _tp("web development", "web programming", "semantic", "synonyms"),
    _tp("backend development", "back-end development", "semantic", "hyphen"),
    _tp("frontend development", "front-end development", "semantic", "hyphen"),
    _tp("full stack", "fullstack", "semantic", "space vs compound"),
    _tp("devops", "dev ops", "semantic", "compound word"),
    _tp("microservices", "micro services", "semantic", "compound word"),
    # Version-agnostic matching
    _tp("python", "python3", "version", "versioned"),
    _tp("angular", "angular 2", "version", "versioned"),
    _tp("java", "java 11", "version", "versioned"),
    _tp(".net", ".net core", "version", "framework version"),
    _tp("dotnet", ".net", "version", "word vs symbol"),
    # Technology families
    _tp("react", "reactjs", "family", "base vs suffixed"),
    _tp("react native", "react-native", "family", "space vs hyphen"),
    _tp("node", "nodejs", "family", "base vs suffixed"),
    _tp("vue", "vuejs", "family", "base vs suffixed"),
    _tp("express", "expressjs", "family", "base vs suffixed"),
    _tp("next", "nextjs", "family", "base vs suffixed"),
]

# TRUE NEGATIVES: These should NOT match (different skills)
TRUE_NEGATIVE_PAIRS = [
    # Different programming languages
    _tn("python", "java", "different_lang", "different languages"),
    _tn("javascript", "java", "different_lang", "often confused"),
    _tn("c++", "c", "different_lang", "related but different"),
    _tn("c#", "c++", "different_lang", "related but different"),
    _tn("ruby", "python", "different_lang", "different languages"),
    _tn("rust", "go", "different_lang", "different languages"),
    _tn("kotlin", "java", "different_lang", "JVM but different"),
    _tn("typescript", "javascript", "different_lang", "superset but different"),
    # Different frameworks
    _tn("react", "angular", "different_framework", "different JS frameworks"),
    _tn("react", "vue", "different_framework", "different JS frameworks"),
    _tn("django", "flask", "different_framework", "different Python frameworks"),
    _tn("django", "fastapi", "different_framework", "different frameworks"),
    _tn("spring", "django", "different_framework", "different ecosystem"),
    _tn("nextjs", "nuxtjs", "different_framework", "different meta-frameworks"),
    # Different databases
    _tn("postgresql", "mysql", "different_db", "different RDBMS"),
    _tn("postgresql", "mongodb", "different_db", "SQL vs NoSQL"),
    _tn("mongodb", "redis", "different_db", "document vs key-value"),
    _tn("elasticsearch", "mongodb", "different_db", "different purposes"),
    _tn("redis", "memcached", "different_db", "different caches"),
    # Different cloud providers
    _tn("aws", "gcp", "different_cloud", "different providers"),
    _tn("aws", "azure", "different_cloud", "different providers"),
    _tn("s3", "gcs", "different_cloud", "different storage services"),
    # Different ML frameworks
    _tn("tensorflow", "pytorch", "different_ml", "different frameworks"),
    _tn("keras", "pytorch", "different_ml", "different frameworks"),
    _tn("pandas", "numpy", "different_ml", "different libraries"),
    # Different DevOps tools
    _tn("docker", "kubernetes", "different_devops", "container vs orchestration"),
    _tn("jenkins", "github actions", "different_devops", "different CI/CD"),
    _tn("terraform", "ansible", "different_devops", "IaC vs config mgmt"),
    _tn("prometheus", "grafana", "different_devops", "metrics vs viz"),
    # Different domains
    _tn("machine learning", "web development", "different_domain", "domains"),
    _tn("frontend", "backend", "different_domain", "specializations"),
    # Unrelated
    _tn("python", "excel", "unrelated", "programming vs tool"),
    _tn("docker", "communication", "unrelated", "tech vs soft skill"),
    _tn("kubernetes", "leadership", "unrelated", "tech vs soft skill"),
    _tn("react", "agile", "unrelated", "framework vs methodology"),
]

# Edge cases that need special attention (mixed true/false)
EDGE_CASES = [
    _tn("react", "react native", "edge", "web vs mobile"),
    _tn("node", "deno", "edge", "both JS runtimes but different"),
    _tp("mysql", "mariadb", "edge", "fork, mostly compatible"),
    _tp("vim", "neovim", "edge", "neovim is vim fork"),
    _tn("nginx", "apache", "edge", "different web servers"),
    _tn("rest api", "graphql", "edge", "different API paradigms"),
    _tn("git", "github", "edge", "tool vs platform"),
    _tn("linux", "ubuntu", "edge", "ubuntu is linux distro"),
    _tp("apache kafka", "kafka", "edge", "same thing"),
    _tp("apache spark", "spark", "edge", "same thing"),
]


def get_all_test_pairs() -> list[SkillPair]:
    """Get all test pairs for analysis."""
    return TRUE_POSITIVE_PAIRS + TRUE_NEGATIVE_PAIRS + EDGE_CASES


def get_true_positive_pairs() -> list[SkillPair]:
    """Get pairs that should match."""
    return TRUE_POSITIVE_PAIRS


def get_true_negative_pairs() -> list[SkillPair]:
    """Get pairs that should NOT match."""
    return TRUE_NEGATIVE_PAIRS


def get_edge_cases() -> list[SkillPair]:
    """Get edge case pairs."""
    return EDGE_CASES
