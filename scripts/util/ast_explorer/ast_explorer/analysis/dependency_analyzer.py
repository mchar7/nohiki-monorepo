"""Cross-package dependency analyzer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ast_explorer.discovery.packages import Package, PackageRegistry, PackageType, discover_packages
from ast_explorer.models.dependencies import (
    DependencyGraph,
    ImpactAnalysis,
    ImportReference,
    PackageDependency,
    SymbolUsage,
)

if TYPE_CHECKING:
    from ast_explorer.models.codebase import CodebaseAST
    from ast_explorer.models.nodes import SymbolNode


def _infer_package(file_path: Path, root: Path) -> Package:
    """Infer package from path when not in registry."""
    rel = file_path.relative_to(root) if file_path.is_relative_to(root) else file_path
    parts = rel.parts
    pkg_type = _infer_type(parts)
    name = _infer_name(parts, pkg_type)
    return Package(name=name, path=file_path, package_type=pkg_type, python_package=name.replace("-", "_"))


def _infer_type(parts: tuple[str, ...]) -> PackageType:
    """Infer package type from path parts."""
    match parts:
        case p if "backend" not in p:
            return PackageType.SCRIPT if "scripts" in p else PackageType.UNKNOWN
        case p if "services" in p:
            return PackageType.SERVICE
        case p if "libs" in p:
            return PackageType.SHARED_LIB
        case p if "jobs" in p:
            return PackageType.JOB
        case _:
            return PackageType.UNKNOWN


def _infer_name(parts: tuple[str, ...], pkg_type: PackageType) -> str:
    """Infer package name from path parts."""
    type_dirs = {PackageType.SERVICE: "services", PackageType.SHARED_LIB: "libs", PackageType.JOB: "jobs"}
    if (dir_name := type_dirs.get(pkg_type)) and dir_name in parts:
        idx = parts.index(dir_name)
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1] if parts else "unknown"


@dataclass(slots=True)
class ImportExtractor:
    """Extracts import statements from Python source code."""

    imports: list[ImportReference] = field(default_factory=list)

    def extract(self, content: str, file_path: Path) -> list[ImportReference]:
        """Extract all imports from Python source."""
        self.imports = []
        self._extract_from_imports(content, file_path)
        self._extract_regular_imports(content, file_path)
        return self.imports

    def _extract_from_imports(self, content: str, file_path: Path) -> None:
        """Extract 'from X import Y' statements."""
        pattern = re.compile(
            r"^from\s+([\w.]+)\s+import\s+\(?([^)\n]+)\)?",
            re.MULTILINE,
        )

        for match in pattern.finditer(content):
            module = match.group(1)
            names_str = match.group(2).strip()
            line = content[: match.start()].count("\n") + 1

            names = self._parse_import_names(names_str)
            if names:
                self.imports.append(
                    ImportReference(
                        module=module,
                        names=tuple(names),
                        file_path=file_path,
                        line=line,
                        is_from_import=True,
                    )
                )

    def _extract_regular_imports(self, content: str, file_path: Path) -> None:
        """Extract 'import X' statements."""
        pattern = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?", re.MULTILINE)

        for match in pattern.finditer(content):
            module = match.group(1)
            alias = match.group(2)
            line = content[: match.start()].count("\n") + 1

            self.imports.append(
                ImportReference(
                    module=module,
                    names=(module.split(".")[-1],),
                    file_path=file_path,
                    line=line,
                    is_from_import=False,
                    alias=alias,
                )
            )

    def _parse_import_names(self, names_str: str) -> list[str]:
        """Parse comma-separated import names, handling multi-line."""
        cleaned = re.sub(r"\s+", " ", names_str.strip())
        cleaned = re.sub(r"#.*", "", cleaned)

        names: list[str] = []
        for raw_part in cleaned.split(","):
            name = raw_part.strip()
            if " as " in name:
                name = name.split(" as ")[0].strip()
            if name and name not in ("(", ")"):
                names.append(name)
        return names


class DependencyAnalyzer:
    """Analyzes cross-package dependencies in a codebase."""

    def __init__(self, root: Path) -> None:
        """Initialize analyzer with root path."""
        self.root = root.resolve()
        self._extractor = ImportExtractor()
        self._registry: PackageRegistry = discover_packages(self.root)
        self._packages: dict[str, Package] = {}
        self._dependencies: dict[str, list[PackageDependency]] = {}
        self._symbol_usages: dict[str, SymbolUsage] = {}

    def analyze(self, codebase: CodebaseAST) -> DependencyGraph:
        """Analyze dependencies in the codebase."""
        self._packages = {}
        self._dependencies = {}
        self._symbol_usages = {}

        self._discover_packages(codebase)

        for file_ast in codebase.files.values():
            self._analyze_file_imports(file_ast.path)

        self._build_symbol_usages()

        return DependencyGraph(
            packages=self._packages,
            dependencies=self._dependencies,
            symbol_usages=self._symbol_usages,
            shared_lib_packages=self._registry.shared_libs,
        )

    def _discover_packages(self, codebase: CodebaseAST) -> None:
        """Discover all packages from parsed files using registry."""
        for file_ast in codebase.files.values():
            pkg = self._get_package(file_ast.path, codebase.root)
            if pkg.name not in self._packages:
                self._packages[pkg.name] = pkg
                self._dependencies[pkg.name] = []

    def _analyze_file_imports(self, file_path: Path) -> None:
        """Analyze imports in a single file."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return

        pkg = self._get_package(file_path, self.root)
        imports = self._extractor.extract(content, file_path)
        deps_by_target: dict[str, PackageDependency] = {
            d.target_package: d for d in self._dependencies.get(pkg.name, [])
        }

        for imp in imports:
            target = imp.package_name
            if target == pkg.python_package or not self._is_trackable_import(target, imp.module):
                continue
            if target not in deps_by_target:
                deps_by_target[target] = PackageDependency(source_package=pkg, target_package=target)
            deps_by_target[target].imports.append(imp)

        self._dependencies[pkg.name] = list(deps_by_target.values())

    def _is_trackable_import(self, target_pkg: str, module: str) -> bool:
        """Check if this import should be tracked (shared lib or domain model)."""
        return self._registry.is_shared_lib(target_pkg) or (module.startswith("nohiki.") and ".v" in module)

    def _build_symbol_usages(self) -> None:
        """Build symbol usage index."""
        all_imports = (imp for deps in self._dependencies.values() for dep in deps for imp in dep.imports)

        for imp in all_imports:
            for name in imp.names:
                qname = f"{imp.module}.{name}"
                usage = self._symbol_usages.setdefault(
                    qname, SymbolUsage(name, qname, Path(imp.module.replace(".", "/")))
                )
                usage.used_in.append(imp)

    def _get_package(self, file_path: Path, root: Path) -> Package:
        """Get Package for a file path, using registry or inference."""
        return self._registry.get_package_for_path(file_path) or _infer_package(file_path, root)

    def get_impact_analysis(self, symbol: SymbolNode, dep_graph: DependencyGraph) -> ImpactAnalysis:
        """Analyze the impact of changing a symbol."""
        pkg = self._get_package(symbol.file_path, self.root)
        analysis = ImpactAnalysis(
            symbol=symbol,
            symbol_qualified_name=symbol.qualified_name,
            defined_in_package=pkg.name,
            defined_in_file=symbol.file_path,
        )
        self._find_symbol_usages(symbol, dep_graph, analysis)
        return analysis

    def _find_symbol_usages(self, symbol: SymbolNode, dep_graph: DependencyGraph, analysis: ImpactAnalysis) -> None:
        """Find all usages of a symbol across packages."""
        for pkg_name, deps in dep_graph.dependencies.items():
            matching = [imp for dep in deps for imp in dep.imports if symbol.name in imp.names]
            if not matching:
                continue
            analysis.direct_imports.extend(matching)
            analysis.affected_packages.add(pkg_name)
            if (pkg := dep_graph.packages.get(pkg_name)) and pkg.package_type == PackageType.SERVICE:
                analysis.affected_services.add(pkg_name)


def analyze_dependencies(codebase: CodebaseAST) -> DependencyGraph:
    """Analyze dependencies in a codebase."""
    analyzer = DependencyAnalyzer(codebase.root)
    return analyzer.analyze(codebase)


def get_symbol_impact(symbol_name: str, codebase: CodebaseAST, dep_graph: DependencyGraph) -> ImpactAnalysis | None:
    """Get impact analysis for a symbol by name."""
    symbol = codebase.find_symbol(symbol_name)
    if not symbol and (symbols := codebase.search_symbols(symbol_name)):
        symbol = symbols[0]
    return DependencyAnalyzer(codebase.root).get_impact_analysis(symbol, dep_graph) if symbol else None
