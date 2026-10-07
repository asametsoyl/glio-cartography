"""Tissue packs: dataset-independent biology kept out of the engine code.

A tissue pack is a directory of small YAML files (see tissue_packs/gbm):

    tissue.yaml     identity, version, species, platforms
    regions.yaml    anatomic regions (name, labels, colour, signature genes)
                    and the region pairs used for contrast figures
    citations.yaml  where every signature comes from, with licence status
    report.yaml     optional report wording

The engine only talks to `TissuePack`; adding a tissue means adding a
directory, not editing code. The pack to use is chosen with the environment
variable ``GLIO_TISSUE_PACK`` (a pack id or a path to a pack directory,
default ``gbm``). Packs are searched in ``GLIO_TISSUE_PACKS_DIR`` (if set),
the bundled ``tissue_packs/`` directory and ``~/.glio_cartography/tissue_packs``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PACK = "gbm"
SCHEMA_VERSION = 1
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_MIN_GENES_PER_REGION = 3


class TissuePackError(ValueError):
    """Raised for a missing or invalid tissue pack; the message says what to fix."""


@dataclass(frozen=True)
class Region:
    name: str
    id: str
    label_en: str
    label_tr: str
    color: str
    genes: tuple[str, ...]
    citation: str | None = None
    notes: str = ""

    def label(self, lang: str) -> str:
        return self.label_en if lang == "en" else self.label_tr


@dataclass(frozen=True)
class TissuePack:
    id: str
    name: str
    version: str
    species: tuple[str, ...]
    platforms: tuple[str, ...]
    description: str
    regions: tuple[Region, ...]
    comparisons: tuple[tuple[str, str], ...]
    citations: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    reference_validation: str | None = None
    path: Path | None = None

    @property
    def region_names(self) -> list[str]:
        return [r.name for r in self.regions]

    def signatures(self) -> dict[str, list[str]]:
        """Region name -> lowercase signature genes (the GNN zone targets)."""
        return {r.name: list(r.genes) for r in self.regions}

    def colors(self) -> dict[str, str]:
        return {r.name: r.color for r in self.regions}

    def labels(self, lang: str) -> dict[str, str]:
        return {r.name: r.label(lang) for r in self.regions}

    def label(self, region_name: str, lang: str) -> str:
        for r in self.regions:
            if r.name == region_name:
                return r.label(lang)
        return region_name

    def provenance(self) -> dict:
        """Identity of the pack for analysis manifests and summaries."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "regions": self.region_names,
            "citations": sorted(self.citations),
            "unreviewed_licenses": sorted(
                k for k, v in self.citations.items() if v.get("license_status") == "needs_review"
            ),
        }


def _search_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = os.environ.get("GLIO_TISSUE_PACKS_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    dirs.append(Path(__file__).resolve().parent / "tissue_packs")
    user_dir = Path(os.environ.get("GLIO_USER_DATA", Path.home() / ".glio_cartography"))
    dirs.append(user_dir / "tissue_packs")
    return dirs


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise TissuePackError(f"Tissue pack file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TissuePackError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise TissuePackError(f"{path.name} must contain a mapping at the top level")
    return data


def _resolve(pack: str) -> Path:
    candidate = Path(pack)
    if candidate.is_dir():
        return candidate
    for base in _search_dirs():
        if (base / pack).is_dir():
            return base / pack
    searched = ", ".join(str(d) for d in _search_dirs())
    raise TissuePackError(f"Tissue pack '{pack}' not found. Searched: {searched}")


def load_tissue_pack(pack: str | None = None) -> TissuePack:
    """Load and validate a tissue pack (default: $GLIO_TISSUE_PACK or 'gbm')."""
    pack = pack or os.environ.get("GLIO_TISSUE_PACK") or DEFAULT_PACK
    root = _resolve(pack)

    tissue = _read_yaml(root / "tissue.yaml")
    regions_doc = _read_yaml(root / "regions.yaml")
    citations = {}
    if (root / "citations.yaml").is_file():
        citations = _read_yaml(root / "citations.yaml").get("citations") or {}
    report = _read_yaml(root / "report.yaml") if (root / "report.yaml").is_file() else {}

    for key in ("id", "name", "version"):
        if not tissue.get(key):
            raise TissuePackError(f"tissue.yaml is missing required key '{key}' ({root})")
    if int(tissue.get("schema_version", SCHEMA_VERSION)) != SCHEMA_VERSION:
        raise TissuePackError(
            f"Pack '{tissue['id']}' uses schema_version {tissue.get('schema_version')}, "
            f"this engine supports {SCHEMA_VERSION}"
        )

    raw_regions = regions_doc.get("regions")
    if not isinstance(raw_regions, list) or len(raw_regions) < 2:
        raise TissuePackError("regions.yaml must define a list of at least 2 regions")

    regions: list[Region] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    for i, r in enumerate(raw_regions):
        if not isinstance(r, dict) or not r.get("name"):
            raise TissuePackError(f"regions.yaml: region #{i + 1} needs a 'name'")
        name = str(r["name"])
        if name in seen_names:
            raise TissuePackError(f"regions.yaml: duplicate region name '{name}'")
        seen_names.add(name)
        rid = str(r.get("id") or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"))
        if rid in seen_ids:
            raise TissuePackError(f"regions.yaml: duplicate region id '{rid}'")
        seen_ids.add(rid)

        color = str(r.get("color", ""))
        if not _HEX_COLOR.match(color):
            raise TissuePackError(f"Region '{name}': color must be a #RRGGBB hex value, got '{color}'")

        genes = [str(g).strip().lower() for g in (r.get("genes") or []) if str(g).strip()]
        genes = list(dict.fromkeys(genes))
        if len(genes) < _MIN_GENES_PER_REGION:
            raise TissuePackError(
                f"Region '{name}': needs at least {_MIN_GENES_PER_REGION} signature genes, got {len(genes)}"
            )

        cite = r.get("citation")
        if cite is not None and cite not in citations:
            raise TissuePackError(
                f"Region '{name}' cites '{cite}' which is not defined in citations.yaml"
            )

        regions.append(Region(
            name=name, id=rid,
            label_en=str(r.get("label_en") or name),
            label_tr=str(r.get("label_tr") or r.get("label_en") or name),
            color=color.upper(), genes=tuple(genes),
            citation=cite, notes=str(r.get("notes") or "").strip(),
        ))

    comparisons = []
    for pair in regions_doc.get("comparisons") or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            raise TissuePackError(f"comparisons entries must be [regionA, regionB], got {pair!r}")
        for n in pair:
            if n not in seen_names:
                raise TissuePackError(f"comparisons refers to unknown region '{n}'")
        comparisons.append((str(pair[0]), str(pair[1])))

    return TissuePack(
        id=str(tissue["id"]), name=str(tissue["name"]), version=str(tissue["version"]),
        species=tuple(tissue.get("species") or ()), platforms=tuple(tissue.get("platforms") or ()),
        description=str(tissue.get("description") or "").strip(),
        regions=tuple(regions), comparisons=tuple(comparisons),
        citations=citations, report=report,
        reference_validation=(str(tissue['reference_validation']) if tissue.get('reference_validation') else None),
        path=root,
    )
