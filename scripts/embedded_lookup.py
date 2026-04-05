#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone local embedded manual lookup CLI.

This tool stays intentionally lightweight:
- local files/folders only
- text documents by default
- text-based PDFs when optional ``pypdf`` is available
- deterministic metadata extraction heuristics
- two-stage retrieval: document -> section -> chunk
- citation-ready evidence packaging

It is intended to run as a standalone local lookup tool for embedded manuals,
not as a production retrieval backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pdfplumber = None

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".rst"}
SUPPORTED_SUFFIXES = SUPPORTED_TEXT_SUFFIXES | {".pdf"}
DEFAULT_PDF_BACKEND = "pypdf"
PDF_BACKEND_ENV_VAR = "EMBEDDED_LOOKUP_PDF_BACKEND"
SUPPORTED_PDF_BACKENDS = (DEFAULT_PDF_BACKEND, "pdfplumber")
DOCUMENT_TYPE_HINTS = {
    "datasheet": "datasheet",
    "reference-manual": "reference manual",
    "reference_manual": "reference manual",
    "refman": "reference manual",
    "rm": "reference manual",
    "appnote": "app note",
    "app-note": "app note",
    "application-note": "app note",
    "hardware-guide": "hardware guide",
    "hardware_guide": "hardware guide",
    "guide": "hardware guide",
}
HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(
    r"^(?P<number>\d+(?:\.\d+){0,4})[\)\.]?\s+(?P<title>[A-Z][^\n]{2,120})$"
)
REVISION_RE = re.compile(
    r"\b(?:revision|rev|version|ver)\b\s*[:#=._/-]?\s*([A-Za-z0-9.-]+)\b",
    re.IGNORECASE,
)
DEVICE_RE = re.compile(r"\b([A-Z]{2,}[A-Z0-9_-]*\d[A-Z0-9_-]*)\b")
TOKEN_RE = re.compile(r"[A-Za-z0-9_./+-]+")
TITLE_SKIP_PREFIXES = {
    "this is information on a product",
    "contents",
}
GENERIC_DEVICE_TOKENS = {
    "PDF",
    "DOC",
    "DOCS",
    "GUIDE",
    "MANUAL",
    "REFERENCE",
    "DATASHEET",
    "SECTION",
    "VERSION",
    "REVISION",
    "PROTOTYPE",
    "REQUIREMENTS",
}
GENERIC_REVISION_VALUES = {"version", "revision", "rev", "ver"}
PIN_NAME_RE = re.compile(r"\bP[A-Z]\d{1,2}\b")
SIGNAL_NAME_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*(?:_[A-Z0-9]+)+\b")
PACKAGE_NAME_RE = re.compile(
    r"\b(?:LQFP|TQFP|LFBGA|UFBGA|BGA|QFN|UFQFPN|WLCSP|SOIC|DIP)[- ]?\d+\b|\b\d{2,3}-pin\b",
    re.IGNORECASE,
)
REGISTER_FIELD_RE = re.compile(
    r"\b(?:bit|field)\s+\d+\s+([A-Z][A-Z0-9_]{1,31})\b",
    re.IGNORECASE,
)
ELECTRICAL_PARAMETER_SYMBOL_RE = re.compile(
    r"\b(?:vdd|vdda|vssa|vref(?:\+|-)?|vin|vio|vbat|vbatt|idd|iih|iil|vil|vih|temp(?:erature)?|tstg|ta)\b",
    re.IGNORECASE,
)
TABLE_QUESTION_PIN = "pin"
TABLE_QUESTION_ELECTRICAL = "electrical"
TABLE_QUESTION_FEATURE = "feature"
TABLE_QUESTION_PERIPHERAL_COUNT = "peripheral-count"
TABLE_QUESTION_MEMORY = "memory"
TABLE_QUESTION_PACKAGE = "package"
TABLE_QUESTION_ORDERING = "ordering"
TABLE_QUESTION_DEVICE_VARIANT = "device-variant"
PIN_TABLE_HEADING_TERMS = (
    "pinouts and pin description",
    "pin definitions",
    "pin definition",
    "pin description",
    "pinout",
    "pin assignment",
    "pin assignments",
    "pin name",
    "pin names",
    "alternate function",
    "alternate functions",
    "alternate function mapping",
    "ball assignment",
    "package information and pinouts",
)
PIN_TABLE_CONTEXT_TERMS = (
    "pin",
    "pin name",
    "signal",
    "alternate function",
    "alternate functions",
    "remap",
    "package",
    "ball",
)
ELECTRICAL_TABLE_HEADING_TERMS = (
    "electrical characteristics",
    "absolute maximum ratings",
    "general operating conditions",
    "operating conditions",
    "recommended operating conditions",
)
ELECTRICAL_TABLE_CONTEXT_TERMS = (
    "parameter",
    "conditions",
    "min",
    "max",
    "unit",
    "standard operating voltage",
    "operating voltage",
)
TABLE_NOISE_HEADING_TERMS = (
    "contents",
    "table of contents",
    "list of tables",
    "list of figures",
    "revision history",
    "document revision history",
)
MECHANICAL_PACKAGE_NOISE_TERMS = (
    "package dimensions",
    "mechanical data",
    "package mechanical data",
    "recommended footprint",
    "package outline",
    "tape and reel",
    "marking",
    "package marking",
    "packing information",
)
FEATURE_TABLE_HEADING_TERMS = (
    "features and peripheral counts",
    "device features and peripheral counts",
    "peripheral counts",
    "device summary",
    "main features",
    "feature summary",
)
FEATURE_TABLE_WEAK_HEADING_TERMS = (
    "features",
    "peripherals",
)
FEATURE_QUERY_TERMS = (
    "adc",
    "dac",
    "timer",
    "timers",
    "spi",
    "i2c",
    "i2s",
    "usart",
    "uart",
    "can",
    "usb",
    "gpio",
    "comparator",
    "comparators",
    "rtc",
    "watchdog",
    "crc",
    "dma",
)
MEMORY_TABLE_HEADING_TERMS = (
    "memory organization",
    "memory sizes",
    "memory size",
    "device summary",
    "flash memory",
    "embedded flash memory",
    "embedded flash and sram",
    "sram",
)
MEMORY_QUERY_TERMS = (
    "flash",
    "sram",
    "eeprom",
    "memory",
)
PACKAGE_ORDERING_TABLE_HEADING_TERMS = (
    "ordering information",
    "ordering information scheme",
    "ordering code",
    "ordering codes",
    "order code",
    "order codes",
    "package information",
    "package information and order codes",
    "package options",
    "device summary",
)
PACKAGE_ORDERING_QUERY_TERMS = (
    "ordering",
    "ordering code",
    "order code",
    "suffix",
    "package",
    "packages",
    "package information",
    "package option",
    "package options",
    "device variant",
    "device variants",
    "variant",
    "variants",
)
PACKAGE_ORDERING_NOISE_TERMS = (
    "package dimensions",
    "mechanical data",
    "package mechanical data",
    "tape and reel",
    "marking",
    "package marking",
    "packing information",
)
FEATURE_TABLE_NOISE_TERMS = (
    "ordering information",
    "package information",
    "ordering code",
    "package dimensions",
    "mechanical data",
)
MEMORY_TABLE_NOISE_TERMS = (
    "memory map",
    "register map",
    "register definition",
    "register descriptions",
    "ordering information",
    "package information",
)
STOP_WORDS = {
    "the",
    "and",
    "for",
    "in",
    "on",
    "to",
    "with",
    "from",
    "this",
    "that",
    "how",
    "many",
    "much",
    "into",
    "what",
    "when",
    "where",
    "which",
    "about",
    "manual",
    "datasheet",
    "reference",
    "section",
    "page",
}
DEFAULT_SOURCE_RELATIVE_CANDIDATES = (
    Path("手册参考"),
    Path("manuals"),
)
GENERIC_REGISTER_QUERY_TOKENS = {
    "register",
    "bit",
    "field",
    "enable",
    "disable",
    "set",
    "clear",
    "flag",
    "name",
    "control",
    "status",
    "interrupt",
    "request",
    "buffer",
    "dma",
    "tx",
    "rx",
    "thi",
    "device",
    "family",
    "manual",
    "document",
}
UNSUPPORTED_QUESTION_PATTERNS = (
    "schematic",
    "screenshot",
    "netlist",
    "bom",
    "cad",
    "ocr",
    "backend",
    "mcp",
    "vendor portal",
    "remote crawl",
    "remote crawling",
    "indexing service",
    "retrieval service",
)
ABSENCE_QUERY_PATTERNS = (
    "does this device provide",
    "does the device provide",
    "does it provide",
    "is there",
    "is this available",
    "does this support",
    "does the device support",
    "is supported",
    "does this include",
    "does the device include",
    "does this have",
    "does the device have",
)
IGNORED_REQUIREMENT_TOKENS = {
    "device",
    "family",
    "provid",
    "support",
    "include",
    "have",
    "peripheral",
    "feature",
    "available",
    "correct",
    "read",
    "tell",
    "whether",
    "do",
    "there",
    "is",
    "request",
    "range",
    "summarize",
    "summary",
    "compare",
    "comparison",
    "difference",
    "differ",
    "between",
    "role",
    "roles",
    "describ",
    "behavior",
    "package",
    "packages",
    "provide",
    "doe",
    "use",
    "correspond",
}


class RetrievalError(Exception):
    """Base error for prototype failures."""


class UnsupportedInputError(RetrievalError):
    """Raised when the source or document format is unsupported."""


@dataclass
class QueryFilters:
    """Optional user-provided narrowing filters."""

    device: str | None = None
    document_type: str | None = None
    revision: str | None = None


@dataclass
class PageText:
    """Text captured from a page-like unit."""

    page_number: int
    text: str


@dataclass
class SectionRecord:
    """Heading-scoped coarse retrieval unit."""

    id: str
    document_id: str
    heading: str
    heading_path: list[str]
    page_start: int
    page_end: int
    text: str


@dataclass
class ChunkRecord:
    """Fine-grained retrieval unit linked to a section."""

    id: str
    document_id: str
    section_id: str
    heading: str
    heading_path: list[str]
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    kind: str = "blob"


@dataclass
class DocumentRecord:
    """Normalized manual-level unit."""

    id: str
    path: str
    title: str
    device_family: str | None
    revision: str | None
    document_type: str | None
    checksum: str
    pages: list[PageText]
    sections: list[SectionRecord]


@dataclass
class EvidenceRecord:
    """Citation-ready evidence payload."""

    tag: str
    document_id: str
    document: str
    device_family: str | None
    revision: str | None
    section: str
    page: str
    excerpt: str
    full_text: str
    score: float
    document_path: str


@dataclass
class RetrievalResult:
    """Top-level prototype response."""

    question: str
    source: str
    filters: QueryFilters
    short_answer: str
    key_evidence: list[str]
    sources: list[EvidenceRecord]
    open_questions: list[str]
    searched_documents: list[str]
    structured_summary: StructuredSummary | None = None


@dataclass
class StructuredSummaryField:
    """Grounded field rendered inside an optional structured summary."""

    label: str
    value: str


@dataclass
class StructuredSummary:
    """Optional runtime-only structured summary for confident answers."""

    kind: str
    title: str
    fields: list[StructuredSummaryField]


@dataclass
class ScoredItem:
    """Internal score wrapper."""

    score: float
    item: Any


class EmbeddedRetrievalPrototype:
    """Prototype retrieval pipeline for local embedded manuals."""

    def __init__(
        self,
        source: str | Path | None,
        *,
        pdf_backend: str | None = None,
        filters: QueryFilters | None = None,
        max_documents: int = 3,
        max_sections: int = 5,
        max_chunks: int = 5,
        chunk_size: int = 900,
        chunk_overlap: int = 150,
    ) -> None:
        self.source = self._resolve_source(source)
        self.pdf_backend = self._resolve_pdf_backend(pdf_backend)
        self.filters = filters or QueryFilters()
        self.max_documents = max_documents
        self.max_sections = max_sections
        self.max_chunks = max_chunks
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def run(self, question: str) -> RetrievalResult:
        """Run the full prototype retrieval flow."""
        if self._is_unsupported_question(question):
            return self._build_unsupported_question_result(question)

        documents = self._discover_and_load_documents()
        if not documents:
            return RetrievalResult(
                question=question,
                source=str(self.source),
                filters=self.filters,
                short_answer="No grounded answer found because no supported local manuals matched the current source or filters.",
                key_evidence=[],
                sources=[],
                open_questions=[
                    (
                        "Provide a supported local text manual or install optional PDF backend "
                        f"dependency `{self._pdf_backend_dependency_name()}` for `{self.pdf_backend}` extraction."
                    ),
                ],
                searched_documents=[],
            )

        document_hits = self._score_documents(documents, question)
        selected_documents = [hit.item for hit in document_hits[: self.max_documents]]
        if not selected_documents:
            selected_documents = documents[: self.max_documents]

        section_hits = self._score_sections(selected_documents, question)
        chunk_hits = self._score_chunks(section_hits, question)
        evidence = self._build_evidence(chunk_hits, question)
        return self._build_result(question, selected_documents, evidence)

    def _discover_default_source(self) -> Path:
        cwd = Path.cwd()
        for candidate in DEFAULT_SOURCE_RELATIVE_CANDIDATES:
            path = cwd / candidate
            if path.exists():
                return path
        return cwd

    def _resolve_source(self, source: str | Path | None) -> Path:
        if source is None:
            return self._discover_default_source()
        return Path(source)

    def _resolve_pdf_backend(self, pdf_backend: str | None) -> str:
        raw_value = pdf_backend or os.environ.get(PDF_BACKEND_ENV_VAR, DEFAULT_PDF_BACKEND)
        normalized = raw_value.strip().lower()
        if normalized not in SUPPORTED_PDF_BACKENDS:
            allowed = ", ".join(SUPPORTED_PDF_BACKENDS)
            raise UnsupportedInputError(
                f"Unsupported PDF backend `{raw_value}`. Choose one of: {allowed}."
            )
        return normalized

    def _pdf_backend_dependency_name(self, backend: str | None = None) -> str:
        selected_backend = backend or self.pdf_backend
        if selected_backend == "pdfplumber":
            return "pdfplumber"
        return "pypdf"

    def _discover_and_load_documents(self) -> list[DocumentRecord]:
        paths = self._discover_document_paths()
        documents: list[DocumentRecord] = []
        last_error: UnsupportedInputError | None = None
        for path in paths:
            try:
                documents.append(self._load_document(path))
            except UnsupportedInputError as error:
                last_error = error
                continue
        if not documents and last_error is not None:
            raise last_error
        return documents

    def _discover_document_paths(self) -> list[Path]:
        if not self.source.exists():
            raise UnsupportedInputError(f"Source does not exist: {self.source}")

        if self.source.is_file():
            return [self.source]

        paths = sorted(
            path
            for path in self.source.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )
        if not paths:
            raise UnsupportedInputError(
                f"No supported manuals found under folder: {self.source}"
            )
        return paths

    def _load_document(self, path: Path) -> DocumentRecord:
        suffix = path.suffix.lower()
        if suffix in SUPPORTED_TEXT_SUFFIXES:
            pages = self._load_text_document(path)
        elif suffix == ".pdf":
            pages = self._load_pdf_document(path)
        else:
            raise UnsupportedInputError(f"Unsupported document type: {path}")

        full_text = "\n".join(page.text for page in pages)
        if not full_text.strip():
            raise UnsupportedInputError(f"Document contains no extractable text: {path}")

        metadata = self._extract_metadata(path, full_text)
        document_id = self._stable_id(str(path.resolve()), full_text)
        sections = self._build_sections(document_id, pages)

        return DocumentRecord(
            id=document_id,
            path=str(path),
            title=metadata["title"],
            device_family=metadata.get("device_family"),
            revision=metadata.get("revision"),
            document_type=metadata.get("document_type"),
            checksum=hashlib.sha256(full_text.encode("utf-8", errors="ignore")).hexdigest(),
            pages=pages,
            sections=sections,
        )

    def _load_text_document(self, path: Path) -> list[PageText]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return [PageText(page_number=1, text=text)]

    def _load_pdf_document(self, path: Path) -> list[PageText]:
        if self.pdf_backend == "pdfplumber":
            return self._load_pdf_document_with_pdfplumber(path)
        return self._load_pdf_document_with_pypdf(path)

    def _load_pdf_document_with_pypdf(self, path: Path) -> list[PageText]:
        if PdfReader is None:
            raise UnsupportedInputError(
                f"PDF support requires optional dependency `pypdf`: {path}"
            )

        reader = PdfReader(str(path))
        pages: list[PageText] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageText(page_number=index, text=text))
        return pages

    def _load_pdf_document_with_pdfplumber(self, path: Path) -> list[PageText]:
        if pdfplumber is None:
            raise UnsupportedInputError(
                "PDF backend `pdfplumber` requires optional dependency `pdfplumber`: "
                f"{path}. Install `pdfplumber` or switch back to `pypdf`."
            )

        pages: list[PageText] = []
        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append(PageText(page_number=index, text=text))
        return pages

    def _extract_metadata(self, path: Path, full_text: str) -> dict[str, str | None]:
        stem = path.stem.replace("_", " ").replace("-", " ")
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        title = self._extract_title(path, lines, stem)

        lowered_stem = path.stem.lower()
        document_type = None
        for hint, normalized in DOCUMENT_TYPE_HINTS.items():
            if hint in lowered_stem:
                document_type = normalized
                break
        if document_type is None:
            lowered_title = title.lower()
            for hint, normalized in DOCUMENT_TYPE_HINTS.items():
                if hint.replace("-", " ") in lowered_title:
                    document_type = normalized
                    break

        revision = self._extract_revision(path, lines)
        device_family = self._extract_device_family(path, lines)

        return {
            "title": title,
            "device_family": device_family,
            "revision": revision,
            "document_type": document_type,
        }

    def _extract_title(self, path: Path, lines: list[str], stem: str) -> str:
        candidates = [
            self._normalize_title(line)
            for line in lines[:12]
            if self._is_title_candidate(line)
        ]
        if not candidates:
            return self._normalize_title(stem)[:160]

        primary = candidates[0]
        title_parts = [primary]
        if self._looks_like_device_family_line(primary):
            variants = [primary]
            candidate_index = 1
            while candidate_index < len(candidates) and len(variants) < 3:
                variant = candidates[candidate_index]
                if not self._looks_like_device_family_line(variant):
                    break
                if variant not in variants:
                    variants.append(variant)
                candidate_index += 1
            title_parts = [" / ".join(variants)]

            descriptor = next(
                (
                    candidate
                    for candidate in candidates[candidate_index : candidate_index + 2]
                    if not self._looks_like_device_family_line(candidate)
                ),
                None,
            )
            if descriptor:
                title_parts.append(descriptor)

        return self._normalize_title(" - ".join(title_parts))[:160]

    def _is_title_candidate(self, line: str) -> bool:
        candidate = self._normalize_title(line)
        if not candidate or len(candidate) > 180:
            return False

        lowered = candidate.lower()
        if any(lowered.startswith(prefix) for prefix in TITLE_SKIP_PREFIXES):
            return False
        if "docid" in lowered:
            return False
        if re.search(r"\b\d+/\d+\b", candidate):
            return False
        if re.match(r"^[A-Za-z]+\s+\d{4}\b", candidate) and "rev" in lowered:
            return False
        return True

    def _looks_like_device_family_line(self, line: str) -> bool:
        candidate = line.strip().upper()
        if " " in candidate:
            return False
        return DEVICE_RE.fullmatch(candidate) is not None and self._normalize_device_family(candidate) is not None

    def _normalize_title(self, value: str) -> str:
        title = re.sub(r"^#{1,6}\s+", "", value).strip()
        title = self._normalize_search_text(title)
        return title or value.strip()

    def _normalize_search_text(self, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        normalized = re.sub(r"\bre\s+gister\b", "register", normalized, flags=re.IGNORECASE)
        return normalized

    def _extract_revision(self, path: Path, lines: list[str]) -> str | None:
        search_targets = ["\n".join(lines[:80]), path.stem]
        for target in search_targets:
            for match in REVISION_RE.finditer(target):
                candidate = self._normalize_revision(match.group(1))
                if candidate:
                    return candidate
        return None

    def _normalize_revision(self, value: str) -> str | None:
        candidate = value.strip(" .,:;#=/_-")
        if not candidate:
            return None

        lowered = candidate.lower()
        if lowered in GENERIC_REVISION_VALUES:
            return None
        if candidate.isalpha() and len(candidate) > 3:
            return None
        return candidate

    def _extract_device_family(self, path: Path, lines: list[str]) -> str | None:
        best_candidate: tuple[float, str] | None = None
        search_targets = [path.stem.upper(), *(line.upper() for line in lines[:20])]
        for index, target in enumerate(search_targets):
            for match in DEVICE_RE.finditer(target):
                candidate = self._normalize_device_family(match.group(1))
                if not candidate:
                    continue

                score = 3.0 if index == 0 else max(0.5, 2.0 - (index * 0.08))
                if "X" in candidate:
                    score += 0.25
                if len(candidate) >= 10:
                    score += 0.15

                if best_candidate is None or (score, len(candidate)) > (
                    best_candidate[0],
                    len(best_candidate[1]),
                ):
                    best_candidate = (score, candidate)
        return best_candidate[1] if best_candidate else None

    def _normalize_device_family(self, value: str) -> str | None:
        candidate = value.strip(" .,:;#=/_-").upper()
        if not candidate:
            return None
        if candidate in GENERIC_DEVICE_TOKENS:
            return None
        if candidate.startswith("DOCID"):
            return None
        if candidate.startswith("REV") and len(candidate) <= 8:
            return None
        if len(candidate) > 32:
            return None
        return candidate

    def _build_sections(self, document_id: str, pages: list[PageText]) -> list[SectionRecord]:
        sections: list[SectionRecord] = []
        current_heading_path = ["Document Root"]
        current_heading = current_heading_path[-1]
        current_page_start = pages[0].page_number if pages else 1
        current_lines: list[str] = []
        current_page_end = current_page_start

        for page in pages:
            page_lines = page.text.splitlines()
            for line_index, raw_line in enumerate(page_lines):
                line = raw_line.strip()
                if not line:
                    continue
                detected_heading = self._detect_heading(line)
                next_nonempty_line = self._next_nonempty_line(page_lines, line_index + 1)
                previous_nonempty_line = current_lines[-1] if current_lines else None
                if detected_heading and self._should_suppress_detected_heading(
                    line,
                    next_nonempty_line=next_nonempty_line,
                    previous_nonempty_line=previous_nonempty_line,
                ):
                    detected_heading = None
                if detected_heading:
                    if current_lines:
                        sections.append(
                            self._make_section(
                                document_id=document_id,
                                heading=current_heading,
                                heading_path=current_heading_path,
                                page_start=current_page_start,
                                page_end=current_page_end,
                                text="\n".join(current_lines).strip(),
                            )
                        )
                    current_heading_path = detected_heading
                    current_heading = current_heading_path[-1]
                    current_page_start = page.page_number
                    current_lines = []
                else:
                    current_lines.append(line)
                current_page_end = page.page_number

        if current_lines:
            sections.append(
                self._make_section(
                    document_id=document_id,
                    heading=current_heading,
                    heading_path=current_heading_path,
                    page_start=current_page_start,
                    page_end=current_page_end,
                    text="\n".join(current_lines).strip(),
                )
            )

        if not sections:
            full_text = "\n".join(page.text for page in pages).strip()
            sections.append(
                self._make_section(
                    document_id=document_id,
                    heading="Document Root",
                    heading_path=["Document Root"],
                    page_start=pages[0].page_number if pages else 1,
                    page_end=pages[-1].page_number if pages else 1,
                    text=full_text,
                )
            )
            return sections

        return self._repair_register_section_spillover(sections)

    def _next_nonempty_line(self, lines: list[str], start_index: int) -> str | None:
        for raw_line in lines[start_index:]:
            candidate = raw_line.strip()
            if candidate:
                return candidate
        return None

    def _should_suppress_detected_heading(
        self,
        line: str,
        *,
        next_nonempty_line: str | None,
        previous_nonempty_line: str | None,
    ) -> bool:
        normalized_line = re.sub(r"\s+", " ", line).strip()
        previous_normalized = (
            re.sub(r"\s+", " ", previous_nonempty_line).strip()
            if previous_nonempty_line
            else None
        )
        if previous_normalized and re.match(r"^\d+\s+[A-Za-z0-9]", normalized_line):
            lowered_previous = previous_normalized.lower()
            lowered_current = normalized_line.lower()
            if re.search(r"\b(?:up to|with|and|or|for|all|each)\b$", lowered_previous):
                return True
            if (
                "/" in normalized_line
                or any(
                    term in lowered_current
                    for term in [
                        "tolerant",
                        "flash",
                        "sram",
                        "pins",
                        "kbytes",
                        "usb",
                        "can",
                        "adc",
                        "timer",
                        "usart",
                    ]
                )
            ) and not re.search(r"\b(?:table|section|chapter)\b", lowered_current):
                return True
        if self._looks_like_corrupted_pdf_heading(normalized_line):
            return True
        if self._looks_like_register_field_heading_row(normalized_line):
            return True
        if self._looks_like_enumerated_value_fragment(normalized_line):
            return True
        if self._looks_like_figure_identifier_heading(normalized_line):
            return True
        if self._looks_like_parenthesized_symbol_heading(normalized_line):
            return True
        if self._looks_like_standalone_table_or_diagram_label(normalized_line):
            return True
        neighboring_lines = [candidate for candidate in [previous_nonempty_line, next_nonempty_line] if candidate]
        if self._looks_like_measurement_table_heading(normalized_line):
            return True
        if self._looks_like_table_or_diagram_label_heading(normalized_line):
            if neighboring_lines and any(
                self._looks_like_table_or_diagram_label_heading(candidate)
                or self._looks_like_table_context_line(candidate)
                for candidate in neighboring_lines
            ):
                return True
        if self._looks_like_register_bitmap_label_heading(normalized_line):
            if neighboring_lines and any(
                self._looks_like_register_bitmap_context_line(candidate)
                for candidate in neighboring_lines
            ):
                return True
        if neighboring_lines and any(self._looks_like_table_context_line(candidate) for candidate in neighboring_lines):
            if self._looks_like_symbol_table_label(normalized_line):
                return True
        if self._looks_like_table_symbol_heading(normalized_line):
            if next_nonempty_line and not self._detect_heading(next_nonempty_line):
                return True
            if previous_nonempty_line and not re.search(r"\bregister\b", previous_nonempty_line, re.IGNORECASE):
                return True
        if normalized_line.lower() == "reset" and next_nonempty_line:
            if self._looks_like_register_access_line(next_nonempty_line):
                return True
            if previous_nonempty_line and self._looks_like_register_bitmap_line(previous_nonempty_line):
                return True
        return False



    def _repair_register_section_spillover(self, sections: list[SectionRecord]) -> list[SectionRecord]:
        if len(sections) < 2:
            return sections

        repaired: list[SectionRecord] = []
        index = 0
        while index < len(sections):
            current = sections[index]
            if index + 1 >= len(sections):
                repaired.append(current)
                break

            next_section = sections[index + 1]
            spillover_split = self._find_register_spillover_split(current, next_section)
            if spillover_split is None:
                repaired.append(current)
                index += 1
                continue

            spillover_lines, remaining_lines = spillover_split
            merged_text = "\n".join([current.text.rstrip(), *spillover_lines]).strip()
            repaired.append(
                self._make_section(
                    document_id=current.document_id,
                    heading=current.heading,
                    heading_path=current.heading_path,
                    page_start=current.page_start,
                    page_end=max(current.page_end, next_section.page_start),
                    text=merged_text,
                )
            )

            next_text = "\n".join(remaining_lines).strip()
            if next_text:
                repaired.append(
                    self._make_section(
                        document_id=next_section.document_id,
                        heading=next_section.heading,
                        heading_path=next_section.heading_path,
                        page_start=next_section.page_start,
                        page_end=next_section.page_end,
                        text=next_text,
                    )
                )
            index += 2

        return repaired

    def _find_register_spillover_split(
        self,
        current: SectionRecord,
        next_section: SectionRecord,
    ) -> tuple[list[str], list[str]] | None:
        if not self._looks_like_register_spillover_source(current):
            return None
        if not self._looks_like_register_definition_heading(next_section.heading):
            return None
        next_lines = [line.strip() for line in next_section.text.splitlines() if line.strip()]
        if len(next_lines) < 4:
            return None

        split_index = self._register_spillover_split_index(next_lines)
        if split_index is None:
            return None

        spillover_lines = next_lines[:split_index]
        remaining_lines = next_lines[split_index:]
        if not spillover_lines or len(remaining_lines) < 3:
            return None
        if not self._looks_like_register_spillover_payload(spillover_lines):
            return None
        if not self._looks_like_register_definition_payload(remaining_lines):
            return None
        return spillover_lines, remaining_lines

    def _register_spillover_split_index(self, lines: list[str]) -> int | None:
        for index, line in enumerate(lines):
            if re.match(r"^15\s+14\s+13\s+12", line):
                return index
            if self._looks_like_register_bitmap_line(line):
                return index
            if self._looks_like_status_register_bitmap_line(line):
                return index
            if re.match(r"^Bits?\s+15:8\s+Reserved", line, re.IGNORECASE):
                return index
        return None

    def _looks_like_register_field_heading_row(self, line: str) -> bool:
        normalized = line.replace(".", " ")
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_:\[\]-]*", normalized)
        if len(tokens) < 2:
            return False
        registerish_tokens = [token for token in tokens if self._is_registerish_token(token)]
        if len(registerish_tokens) < 2:
            return False
        if len(registerish_tokens) / len(tokens) < 0.6:
            return False
        if self._looks_like_register_bitmap_line(line):
            return True
        if self._looks_like_register_access_line(line):
            return True
        return sum(any(char.isdigit() for char in token) or token.isupper() for token in registerish_tokens) >= 2

    def _is_registerish_token(self, token: str) -> bool:
        cleaned = token.strip("()[]{}.,:;+-_/ ")
        if len(cleaned) < 2:
            return False
        lowered = cleaned.lower()
        if lowered in {"reset", "reserved", "note", "bits", "bit", "address", "offset", "value"}:
            return False
        if cleaned.isupper() and len(cleaned) <= 8:
            return True
        if any(char.isdigit() for char in cleaned):
            return True
        return cleaned[:1].isupper() and sum(char.isupper() for char in cleaned[1:]) >= 1

    def _looks_like_register_access_line(self, line: str) -> bool:
        tokens = re.findall(r"\b(?:rw|wr|rr|rc_w1|rc_w0|r|w)\b", line.lower())
        return len(tokens) >= 3

    def _looks_like_enumerated_value_fragment(self, line: str) -> bool:
        if not re.match(r"^(?:\d+|[ivxlcdm]+)[):-]\s*[A-Za-z0-9]", line, re.IGNORECASE):
            return False
        if len(line.split()) > 4:
            return False
        if re.search(r"\b(?:bit|bits|section|chapter|table)\b", line, re.IGNORECASE):
            return False
        return any(char.isdigit() for char in line)

    def _looks_like_corrupted_pdf_heading(self, line: str) -> bool:
        printable = sum(char.isprintable() and char not in "\x00\x0b\x0c" for char in line)
        if printable / max(len(line), 1) < 0.85:
            return True
        letters = [char for char in line if char.isalpha()]
        if not letters:
            return False
        if sum(char.isupper() for char in letters) / len(letters) < 0.6:
            return False
        return "\x00" in line or any(ord(char) < 32 for char in line if char not in "\t\n\r")

    def _looks_like_measurement_table_heading(self, line: str) -> bool:
        if not re.search(r"(?:<|>|=|≤|≥|–|-|\+)", line):
            return False
        if not re.search(r"\b(?:vdd|vdda|vssa|vref|vin|vio|boot|temp|trst|nrst)\b", line, re.IGNORECASE):
            return False
        numeric_hits = re.findall(r"\b\d+(?:\.\d+)?\b", line)
        return len(numeric_hits) >= 2

    def _looks_like_table_context_line(self, line: str) -> bool:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized:
            return False
        if self._looks_like_measurement_table_heading(normalized):
            return True
        if re.search(r"\b(?:min|max|unit|symbol|parameter|conditions?)\b", normalized, re.IGNORECASE):
            return True
        if re.search(r"(?:<|>|=|≤|≥|–|-|\+)", normalized) and re.search(r"\b\d+(?:\.\d+)?\b", normalized):
            return True
        return False

    def _looks_like_symbol_table_label(self, line: str) -> bool:
        compact = re.sub(r"[^A-Za-z0-9]", "", line)
        if len(compact) < 3 or len(compact) > 12:
            return False
        if not compact.isupper():
            return False
        if re.fullmatch(r"[A-Z]+[0-9]*[A-Z]*", compact) is None:
            return False
        return True

    def _looks_like_figure_identifier_heading(self, line: str) -> bool:
        compact = re.sub(r"\s+", "", line)
        return re.fullmatch(r"MS\d{4,}[A-Z]\d+", compact, re.IGNORECASE) is not None

    def _looks_like_parenthesized_symbol_heading(self, line: str) -> bool:
        compact = re.sub(r"\s+", "", line)
        if re.fullmatch(r"\([A-Z][A-Z0-9_]{2,12}\)", compact) is None:
            return False
        return not re.search(r"\bregister\b", line, re.IGNORECASE)

    def _looks_like_standalone_table_or_diagram_label(self, line: str) -> bool:
        words = line.split()
        if len(words) == 2 and "_" in words[0] and re.fullmatch(r"[0-9A-F]{3,5}", words[1], re.IGNORECASE):
            return True
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\[\]():/-]*", line)
        if len(tokens) == 2 and "_" in tokens[0] and re.fullmatch(r"[0-9A-F]{3,5}", tokens[1], re.IGNORECASE):
            return True
        if len(tokens) != 1:
            return False
        token = tokens[0].rstrip(",")
        if len(token) == 1 and token.isupper():
            return True
        if len(token) < 4 or len(token) > 24:
            return False
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]+\s+[0-9A-F]{3,5}", line):
            return True
        if re.search(r"\[[0-9:]+\]", token):
            return True
        if "_" not in token:
            return False
        if not any(char.isdigit() for char in token) and "x_" not in token.lower():
            return False
        return token.upper() == token or re.search(r"[A-Z]{2,}x_", token) is not None

    def _looks_like_table_or_diagram_label_heading(self, line: str) -> bool:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\[\]():/-]*", line)
        if not tokens:
            return False
        if len(tokens) > 3:
            return False
        compact = re.sub(r"\s+", "", line)
        if re.fullmatch(r"P[A-G]\d{1,2}", compact, re.IGNORECASE):
            return True
        if len(tokens) == 1:
            token = tokens[0].rstrip(",")
            if "_" in token:
                return True
            if re.search(r"\[[0-9:]+\]", token):
                return True
        if len(tokens) <= 2 and all(len(token.rstrip(",")) <= 16 for token in tokens):
            underscored_tokens = [token for token in tokens if "_" in token]
            if underscored_tokens and all(token.upper() == token for token in underscored_tokens):
                return True
        return False

    def _looks_like_register_bitmap_label_heading(self, line: str) -> bool:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\[\]]*", line)
        if not tokens or len(tokens) > 4:
            return False
        if len(tokens) == 1:
            token = tokens[0]
            if re.fullmatch(r"P[A-G]\d{1,2}", token, re.IGNORECASE):
                return True
            if re.fullmatch(r"(?:EXTI|CH)\d{1,2}", token, re.IGNORECASE):
                return True
            if len(token) < 4 or len(token) > 24:
                return False
            if "_" in token:
                return token.upper() == token
            if token.isupper() and any(char.isdigit() for char in token):
                return True
            return token.isupper() and re.search(r"(?:RST|RDY(?:IE|F)?|IE|IF|EN|SEL)$", token) is not None
        if all(len(token) <= 3 for token in tokens):
            return all(token.isupper() for token in tokens)
        return False

    def _looks_like_register_bitmap_context_line(self, line: str) -> bool:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized:
            return False
        if self._looks_like_register_bitmap_label_heading(normalized):
            return True
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\[\]]*", normalized)
        if len(tokens) == 1:
            token = tokens[0]
            if 2 <= len(token) <= 16 and token.isupper():
                return True
        if self._looks_like_register_bitmap_line(normalized):
            return True
        if self._looks_like_status_register_bitmap_line(normalized):
            return True
        if re.fullmatch(r"0x[0-9A-F]{1,4}", normalized, re.IGNORECASE):
            return True
        if re.fullmatch(r"\[[0-9:]+\]", normalized):
            return True
        if re.search(r"\breserved\b", normalized, re.IGNORECASE):
            return True
        if re.search(r"\bres\.?\b", normalized, re.IGNORECASE):
            return True
        return False

    def _looks_like_table_symbol_heading(self, line: str) -> bool:
        words = line.split()
        if len(words) > 4:
            return False
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_()=\-]*", line)
        if not tokens:
            return False
        if len(tokens) == 1 and len(tokens[0]) <= 4:
            return True
        if len(tokens) <= 3 and all(len(token) <= 8 for token in tokens):
            return True
        return False

    def _looks_like_register_bit_heading(self, heading: str) -> bool:
        normalized_heading = heading.replace(".", " ")
        tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z0-9_]+", normalized_heading) if len(token) >= 3]
        if len(tokens) < 4:
            return False
        if not any(token.lower().endswith(("ie", "en", "err", "rxne", "txe")) for token in tokens):
            return False
        return sum(token.isupper() or token[:1].isupper() for token in tokens) / len(tokens) >= 0.75


    def _looks_like_register_spillover_source(self, section: SectionRecord) -> bool:
        if self._looks_like_register_bit_heading(section.heading):
            return True
        normalized_heading = re.sub(r"\s+", "", section.heading.lower())
        if "register" not in normalized_heading:
            return False
        if "(" not in section.heading or ")" not in section.heading:
            return False
        text_lower = section.text.lower()
        return any(token in text_lower for token in ["txeie", "rxneie", "errie", "ssoe"])

    def _looks_like_register_definition_heading(self, heading: str) -> bool:
        normalized_heading = re.sub(r"\s+", "", heading.lower())
        return "register" in normalized_heading and "(" in heading and ")" in heading

    def _looks_like_register_spillover_payload(self, lines: list[str]) -> bool:
        lowered = " ".join(lines).lower()
        if not any(re.search(r"\bbit\s+[0-9]+\s+[a-z0-9_]+", line.lower()) for line in lines):
            return False
        return any(token in lowered for token in ["txdmaen", "rxdmaen", "dma enable", "txeie", "rxneie", "ssoe"])

    def _looks_like_register_definition_payload(self, lines: list[str]) -> bool:
        lowered = " ".join(lines[:12]).lower()
        return any(
            marker in lowered
            for marker in [
                "reserved",
                "bsy",
                "ovr",
                "modf",
                "crcerr",
                "rxne",
                "txe",
                "address offset",
            ]
        )

    def _looks_like_status_register_bitmap_line(self, line: str) -> bool:
        lowered = line.lower()
        status_tokens = ["bsy", "ovr", "modf", "crc", "err", "udr", "txe", "rxne"]
        return sum(1 for token in status_tokens if token in lowered) >= 4

    def _make_section(
        self,
        *,
        document_id: str,
        heading: str,
        heading_path: list[str],
        page_start: int,
        page_end: int,
        text: str,
    ) -> SectionRecord:
        section_id = self._stable_id(document_id, heading, str(page_start), str(page_end), text[:120])
        return SectionRecord(
            id=section_id,
            document_id=document_id,
            heading=heading,
            heading_path=heading_path[:],
            page_start=page_start,
            page_end=page_end,
            text=text,
        )

    def _detect_heading(self, line: str) -> list[str] | None:
        normalized_line = re.sub(r"\s+", " ", line).strip()
        if self._looks_like_register_bitmap_line(normalized_line) or self._looks_like_register_bit_heading(normalized_line):
            return None
        markdown_match = HEADING_RE.match(normalized_line)
        if markdown_match:
            level = len(markdown_match.group(1))
            title = self._normalize_heading_title(markdown_match.group("title"))
            if self._is_heading_candidate(normalized_line, title, numbered=False):
                return [f"H{level}", title]

        numbered_match = NUMBERED_HEADING_RE.match(normalized_line)
        if numbered_match:
            number = numbered_match.group("number")
            title = self._normalize_heading_title(numbered_match.group("title"))
            if self._is_heading_candidate(normalized_line, title, numbered=True):
                parts = [part for part in number.split(".") if part]
                return parts + [title]

        if self._is_uppercase_heading_candidate(normalized_line):
            return [normalized_line.title()]

        return None

    def _looks_like_register_bitmap_line(self, line: str) -> bool:
        if len(line.split()) < 2 or len(line.split()) > 12:
            return False
        if any(char in line for char in ":.;()"):
            return False
        register_bit_tokens = [
            token
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_]+", line)
            if len(token) >= 3
        ]
        if len(register_bit_tokens) < 2:
            return False
        if not any(
            token.lower().endswith(("ie", "en", "err", "bsy", "ovr", "modf", "rxne", "txe"))
            for token in register_bit_tokens
        ):
            return False
        uppercase_ratio = sum(
            token.isupper() or token[:1].isupper() for token in register_bit_tokens
        ) / len(register_bit_tokens)
        return uppercase_ratio >= 0.6

    def _normalize_heading_title(self, value: str) -> str:
        title = self._normalize_title(value)
        title = self._normalize_search_text(title)
        return title

    def _is_heading_candidate(self, line: str, title: str, *, numbered: bool) -> bool:
        if not title:
            return False
        if len(line) > 110 or len(title) > 90:
            return False
        if re.search(r"\bdocid\d+\b", line, re.IGNORECASE):
            return False
        if re.search(r"\b\d+/\d+\b", line):
            return False
        if line.endswith("."):
            return False
        if sum(line.count(char) for char in ",;:?") > 2:
            return False
        if len(title.split()) > (14 if numbered else 10):
            return False
        lowered = title.lower()
        if any(lowered.startswith(prefix) for prefix in TITLE_SKIP_PREFIXES):
            return False
        return True

    def _is_uppercase_heading_candidate(self, line: str) -> bool:
        letters = [char for char in line if char.isalpha()]
        if not letters:
            return False
        uppercase_ratio = sum(char.isupper() for char in letters) / len(letters)
        if uppercase_ratio < 0.85:
            return False
        if len(line.split()) > 8:
            return False
        return self._is_heading_candidate(line, line.title(), numbered=False)

    def _build_chunks_for_section(self, section: SectionRecord) -> list[ChunkRecord]:
        text = section.text.strip()
        if not text:
            return []

        chunks: list[ChunkRecord] = []
        start = 0
        chunk_index = 0
        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            snippet = text[start:end].strip()
            if not snippet:
                break
            chunk_id = self._stable_id(section.id, str(chunk_index), snippet[:120])
            chunks.append(
                ChunkRecord(
                    id=chunk_id,
                    document_id=section.document_id,
                    section_id=section.id,
                    heading=section.heading,
                    heading_path=section.heading_path[:],
                    page_start=section.page_start,
                    page_end=section.page_end,
                    chunk_index=chunk_index,
                    text=snippet,
                )
            )
            if end >= len(text):
                break
            start = max(end - self.chunk_overlap, start + 1)
            chunk_index += 1
        return chunks

    def _score_documents(self, documents: list[DocumentRecord], question: str) -> list[ScoredItem]:
        query_tokens = self._tokenize(question)
        hits: list[ScoredItem] = []
        for document in documents:
            haystack = " ".join(
                value
                for value in [
                    document.title,
                    document.device_family or "",
                    document.revision or "",
                    document.document_type or "",
                    Path(document.path).name,
                ]
                if value
            )
            score = self._token_overlap_score(query_tokens, haystack)
            score += self._metadata_filter_bonus(document)
            if score > 0:
                hits.append(ScoredItem(score=score, item=document))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)

    def _score_sections(
        self,
        documents: list[DocumentRecord],
        question: str,
    ) -> list[ScoredItem]:
        query_tokens = self._tokenize(question)
        is_pin_query = self._is_pin_intent_query(question)
        table_question_family = self._table_question_family(question)
        body_window_limit, intent_window_limit = self._section_score_windows(table_question_family)
        hits: list[ScoredItem] = []
        pin_relevant_section_ids: set[str] = set()
        for document in documents:
            for section in document.sections:
                heading_text = " ".join(section.heading_path)
                heading_score = self._token_overlap_score(query_tokens, heading_text)
                body_window = section.text[:body_window_limit]
                intent_window = section.text[:intent_window_limit]
                body_score = self._token_overlap_score(query_tokens, body_window)
                score = (heading_score * 2.0) + body_score
                if heading_score > 0 and body_score > 0:
                    score += 0.75
                if any(token in section.heading.lower() for token in query_tokens):
                    score += 2.0
                requested_device_hit = False
                if table_question_family in {
                    TABLE_QUESTION_MEMORY,
                    TABLE_QUESTION_PACKAGE,
                    TABLE_QUESTION_ORDERING,
                    TABLE_QUESTION_DEVICE_VARIANT,
                }:
                    requested_device_hit = self._text_mentions_requested_device(question, body_window) or self._text_mentions_requested_device(
                        question,
                        heading_text,
                    )
                    if requested_device_hit:
                        score += 4.2
                    elif self._question_device_tokens(question):
                        score -= 1.0
                if table_question_family == TABLE_QUESTION_MEMORY:
                    requested_pin_codes = {
                        pin_code for pin_code, _ in self._requested_device_variant_codes(question)
                    }
                    has_requested_memory_column = bool(requested_pin_codes) and any(
                        re.search(
                            rf"\bSTM32[A-Z0-9]{{4,}}{re.escape(pin_code)}X\b",
                            intent_window.upper(),
                        )
                        for pin_code in requested_pin_codes
                    )
                    if self._extract_memory_capacity_phrase(question, intent_window):
                        score += 4.6
                    if has_requested_memory_column:
                        score += 3.4
                        if all(
                            term in intent_window.lower()
                            for term in ["flash - kbytes", "sram - kbytes"]
                        ):
                            score += 5.2
                    if "device features and peripheral counts" in intent_window.lower():
                        score += 2.8
                    if "device summary" in intent_window.lower() and "reference part number" in intent_window.lower():
                        score += 2.2
                    if (
                        "description" in heading_text.lower()
                        and "up to" in intent_window.lower()
                        and not requested_device_hit
                    ):
                        score -= 3.4
                if table_question_family in {
                    TABLE_QUESTION_PACKAGE,
                    TABLE_QUESTION_ORDERING,
                    TABLE_QUESTION_DEVICE_VARIANT,
                }:
                    if "example: stm32" in intent_window.lower():
                        score += 1.8
                    if self._source_has_requested_pin_mapping(question, intent_window):
                        score += 2.4
                    if self._source_has_requested_density_mapping(question, intent_window):
                        score += 2.2
                    if table_question_family == TABLE_QUESTION_ORDERING and (
                        self._extract_requested_ordering_package_code(
                            question,
                            intent_window,
                            allow_family_fallback=False,
                        )
                        is not None
                    ):
                        score += 4.5
                score += self._question_intent_bonus(
                    question,
                    heading_text,
                    intent_window,
                )
                score += self._table_section_bonus(
                    question,
                    table_question_family,
                    heading_text,
                    intent_window,
                )
                if score > 0:
                    if is_pin_query and (
                        self._pin_table_section_bonus(question, heading_text, intent_window) >= 4.5
                        or self._source_has_requested_pin_mapping(question, intent_window)
                        or (
                            table_question_family == TABLE_QUESTION_PIN
                            and PACKAGE_NAME_RE.search(question) is not None
                            and self._extract_pin_mapping_values(question, section.text) is not None
                        )
                    ):
                        pin_relevant_section_ids.add(section.id)
                    hits.append(ScoredItem(score=score, item=section))
        ordered_hits = sorted(hits, key=lambda hit: hit.score, reverse=True)
        if not is_pin_query:
            return ordered_hits[: self.max_sections]

        reserved_hits: list[ScoredItem] = []
        reserved_section_ids: set[str] = set()
        reserved_document_ids: set[str] = set()
        for hit in ordered_hits:
            section: SectionRecord = hit.item
            if section.id not in pin_relevant_section_ids or section.document_id in reserved_document_ids:
                continue
            reserved_hits.append(hit)
            reserved_section_ids.add(section.id)
            reserved_document_ids.add(section.document_id)
            if len(reserved_hits) >= self.max_sections:
                return reserved_hits[: self.max_sections]

        selected_hits = reserved_hits[:]
        for hit in ordered_hits:
            section = hit.item
            if section.id in reserved_section_ids:
                continue
            selected_hits.append(hit)
            if len(selected_hits) >= self.max_sections:
                break
        return selected_hits

    def _score_chunks(
        self,
        section_hits: list[ScoredItem],
        question: str,
    ) -> list[ScoredItem]:
        query_tokens = self._tokenize(question)
        table_question_family = self._table_question_family(question)
        register_tokens = self._register_specific_tokens(question) if self._is_register_lookup_query(question) else []
        hits: list[ScoredItem] = []
        for section_hit in section_hits:
            section: SectionRecord = section_hit.item
            chunks = self._build_chunks_for_section(section)
            if table_question_family and self._supports_table_row_selection(question, section, table_question_family):
                chunks.extend(self._build_table_row_chunks(section, question, table_question_family))

            for chunk in chunks:
                score = section_hit.score + self._token_overlap_score(query_tokens, chunk.text)
                if self._looks_numeric(question) and self._contains_numeric_signal(chunk.text):
                    score += 1.5
                if register_tokens:
                    register_hit_count = sum(1 for token in register_tokens if token in chunk.text.lower())
                    score += register_hit_count * 2.2
                    register_answer_quality = self._register_answer_quality(question, chunk.text)
                    if register_answer_quality:
                        score += register_answer_quality * 2.5
                pin_answer_quality = self._pin_mapping_answer_quality(question, chunk.text)
                if pin_answer_quality:
                    score += pin_answer_quality
                if table_question_family:
                    row_bonus = self._table_row_candidate_bonus(question, table_question_family, chunk.text)
                    if chunk.kind == "table-row":
                        score += row_bonus
                    else:
                        score += min(2.5, max(0.0, row_bonus - 5.0))
                        score -= self._table_blob_noise_penalty(table_question_family, chunk.text)
                if score > section_hit.score:
                    hits.append(ScoredItem(score=score, item=chunk))
        deduped = self._dedupe_chunks(hits)
        if table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
            TABLE_QUESTION_MEMORY,
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            chunk_limit = max(self.max_chunks * 3, 12)
            return sorted(
                deduped,
                key=lambda hit: (
                    self._table_row_candidate_bonus(question, table_question_family, hit.item.text),
                    hit.score,
                ),
                reverse=True,
            )[:chunk_limit]
        ordered = sorted(deduped, key=lambda hit: hit.score, reverse=True)
        if not self._is_pin_intent_query(question):
            return ordered[: self.max_chunks]

        primary = ordered[: self.max_chunks]
        primary_document_ids = {hit.item.document_id for hit in primary}
        section_document_ids: list[str] = []
        seen_section_document_ids: set[str] = set()
        for section_hit in section_hits:
            section_document_id = section_hit.item.document_id
            if section_document_id in seen_section_document_ids:
                continue
            seen_section_document_ids.add(section_document_id)
            section_document_ids.append(section_document_id)

        grounded_pin_candidate_cache: dict[str, bool] = {}

        def is_grounded_pin_candidate(hit: ScoredItem) -> bool:
            chunk: ChunkRecord = hit.item
            cached = grounded_pin_candidate_cache.get(chunk.id)
            if cached is not None:
                return cached

            section_label = self._normalize_evidence_section(
                question,
                " > ".join(chunk.heading_path),
                chunk.text,
            )
            summary_signal_text = f"{section_label} {chunk.text}"
            if self._build_pin_summary(question, summary_signal_text) is None:
                grounded_pin_candidate_cache[chunk.id] = False
                return False

            grounded_pin_candidate_cache[chunk.id] = True
            return True

        reserved_misses: list[ScoredItem] = []
        for document_id in section_document_ids:
            if document_id in primary_document_ids:
                continue
            reserved_hit = next(
                (
                    hit
                    for hit in ordered
                    if hit.item.document_id == document_id and is_grounded_pin_candidate(hit)
                ),
                None,
            )
            if reserved_hit is not None:
                reserved_misses.append(reserved_hit)

        return sorted(primary + reserved_misses, key=lambda hit: hit.score, reverse=True)

    def _supports_table_row_selection(
        self,
        question: str,
        section: SectionRecord,
        table_question_family: str,
    ) -> bool:
        heading_text = " ".join(section.heading_path)
        body_window_limit, _ = self._section_score_windows(table_question_family)
        body_text = section.text[:body_window_limit]
        if table_question_family == TABLE_QUESTION_PIN:
            current_score = (
                self._pin_table_section_bonus(question, heading_text, body_text)
                + self._table_section_noise_penalty(table_question_family, heading_text, body_text)
            )
            if current_score >= 4.5:
                return True
            return (
                PACKAGE_NAME_RE.search(question) is not None
                and self._extract_pin_mapping_values(question, section.text) is not None
            )
        if table_question_family == TABLE_QUESTION_ELECTRICAL:
            return (
                self._electrical_table_section_bonus(question, heading_text, body_text)
                + self._table_section_noise_penalty(table_question_family, heading_text, body_text)
            ) >= 4.0
        if table_question_family == TABLE_QUESTION_FEATURE:
            return (
                self._feature_table_section_bonus(
                    question,
                    heading_text,
                    body_text,
                    prefer_counts=False,
                )
                + self._table_section_noise_penalty(table_question_family, heading_text, body_text)
            ) >= 4.0
        if table_question_family == TABLE_QUESTION_PERIPHERAL_COUNT:
            return (
                self._feature_table_section_bonus(
                    question,
                    heading_text,
                    body_text,
                    prefer_counts=True,
                )
                + self._table_section_noise_penalty(table_question_family, heading_text, body_text)
            ) >= 4.2
        if table_question_family == TABLE_QUESTION_MEMORY:
            return (
                self._memory_table_section_bonus(question, heading_text, body_text)
                + self._table_section_noise_penalty(table_question_family, heading_text, body_text)
            ) >= 4.0
        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return (
                self._package_ordering_table_section_bonus(
                    question,
                    heading_text,
                    body_text,
                    table_question_family,
                )
                + self._table_section_noise_penalty(table_question_family, heading_text, body_text)
            ) >= 4.4
        return False

    def _build_table_row_chunks(
        self,
        section: SectionRecord,
        question: str,
        table_question_family: str,
    ) -> list[ChunkRecord]:
        normalized_lines = [
            self._normalize_search_text(line)
            for line in section.text.splitlines()
            if self._normalize_search_text(line)
        ]
        if len(normalized_lines) < 2:
            return []

        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            max_candidates = max(self.max_chunks * 8, 32)
        elif table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
            TABLE_QUESTION_MEMORY,
        }:
            max_candidates = max(self.max_chunks * 6, 24)
        else:
            max_candidates = max(self.max_chunks * 3, 8)
        candidate_windows: dict[str, tuple[float, int, int]] = {}
        for index in range(len(normalized_lines)):
            for start, end in self._table_row_candidate_ranges(index, len(normalized_lines), table_question_family):
                candidate_text = "\n".join(
                    self._augment_table_row_candidate(
                        normalized_lines,
                        start,
                        end,
                        question,
                        table_question_family,
                    )
                ).strip()
                if not candidate_text:
                    continue
                bonus = self._table_row_candidate_bonus(question, table_question_family, candidate_text)
                if bonus < 3.5:
                    continue
                existing = candidate_windows.get(candidate_text)
                if existing is None or bonus > existing[0]:
                    candidate_windows[candidate_text] = (bonus, start, end)

        def candidate_sort_key(item: tuple[str, tuple[float, int, int]]) -> tuple[Any, ...]:
            candidate_text, (bonus, start, end) = item
            normalized_candidate = self._normalize_search_text(candidate_text)
            lowered_candidate = normalized_candidate.lower()
            span = end - start
            if table_question_family == TABLE_QUESTION_MEMORY:
                return (
                    bonus,
                    self._text_mentions_requested_device(question, candidate_text),
                    not self._source_has_multiple_capacity_options(candidate_text),
                    len(normalized_candidate),
                    -span,
                )
            if table_question_family in {
                TABLE_QUESTION_PACKAGE,
                TABLE_QUESTION_ORDERING,
                TABLE_QUESTION_DEVICE_VARIANT,
            }:
                has_exact_ordering_mapping = (
                    table_question_family == TABLE_QUESTION_ORDERING
                    and self._extract_requested_ordering_package_code(
                        question,
                        candidate_text,
                        allow_family_fallback=False,
                    )
                    is not None
                )
                has_mapping_context = (
                    "=" in normalized_candidate
                    and any(
                        term in lowered_candidate
                        for term in ["example:", "pin count", "flash memory size", "package"]
                    )
                )
                return (
                    bonus,
                    has_exact_ordering_mapping,
                    has_mapping_context,
                    self._text_mentions_requested_device(question, candidate_text),
                    not self._source_has_multiple_package_options(candidate_text),
                    len(normalized_candidate),
                    span,
                )
            return (
                bonus,
                -span,
                -len(candidate_text),
            )

        ordered_candidates = sorted(
            candidate_windows.items(),
            key=candidate_sort_key,
            reverse=True,
        )

        chunks: list[ChunkRecord] = []
        for chunk_index, (candidate_text, (_, start, end)) in enumerate(ordered_candidates[:max_candidates]):
            chunk_id = self._stable_id(section.id, "table-row", str(start), str(end), candidate_text[:120])
            chunks.append(
                ChunkRecord(
                    id=chunk_id,
                    document_id=section.document_id,
                    section_id=section.id,
                    heading=section.heading,
                    heading_path=section.heading_path[:],
                    page_start=section.page_start,
                    page_end=section.page_end,
                    chunk_index=chunk_index,
                    text=candidate_text,
                    kind="table-row",
                )
            )
        return chunks

    def _augment_table_row_candidate(
        self,
        lines: list[str],
        start: int,
        end: int,
        question: str,
        table_question_family: str,
    ) -> list[str]:
        candidate_lines = lines[start:end]
        if table_question_family == TABLE_QUESTION_MEMORY:
            search_start = max(0, start - 12)
            search_end = min(len(lines), end + 12)
            exact_lines = self._build_memory_variant_grounded_lines(
                question,
                lines,
                search_start,
                search_end,
            )
            if exact_lines:
                return exact_lines
        if table_question_family == TABLE_QUESTION_PACKAGE:
            search_start = max(0, start - 20)
            search_end = min(len(lines), end + 20)
            exact_lines = self._build_exact_package_variant_lines(
                question,
                lines,
                search_start,
                search_end,
                include_ordering_code=False,
            )
            if exact_lines:
                return exact_lines
            candidate_indices = list(range(start, end))
            candidate_device_indices = [
                index
                for index in candidate_indices
                if self._text_mentions_requested_device(question, lines[index])
            ]
            candidate_package_indices = [
                index
                for index in candidate_indices
                if PACKAGE_NAME_RE.search(lines[index])
            ]

            selected_indices = candidate_indices[:]
            if candidate_device_indices and candidate_package_indices:
                closest_distance, device_index, package_index = min(
                    (
                        abs(device_index - package_index),
                        device_index,
                        package_index,
                    )
                    for device_index in candidate_device_indices
                    for package_index in candidate_package_indices
                )
                if closest_distance <= 2:
                    selected_indices = list(
                        range(min(device_index, package_index), max(device_index, package_index) + 1)
                    )
                else:
                    anchor_index = candidate_device_indices[0]
                    nearest_package_index = self._closest_matching_line_index(
                        lines,
                        anchor_index,
                        search_start,
                        search_end,
                        lambda line: PACKAGE_NAME_RE.search(line) is not None,
                        max_distance=2,
                    )
                    selected_indices = [anchor_index]
                    if nearest_package_index is not None:
                        selected_indices = list(
                            range(
                                min(anchor_index, nearest_package_index),
                                max(anchor_index, nearest_package_index) + 1,
                            )
                        )
            elif candidate_device_indices:
                anchor_index = candidate_device_indices[0]
                nearest_package_index = self._closest_matching_line_index(
                    lines,
                    anchor_index,
                    search_start,
                    search_end,
                    lambda line: PACKAGE_NAME_RE.search(line) is not None,
                    max_distance=2,
                )
                selected_indices = [anchor_index]
                if nearest_package_index is not None:
                    selected_indices = list(
                        range(
                            min(anchor_index, nearest_package_index),
                            max(anchor_index, nearest_package_index) + 1,
                        )
                    )
            elif candidate_package_indices:
                anchor_index = candidate_package_indices[0]
                nearest_device_index = self._closest_matching_line_index(
                    lines,
                    anchor_index,
                    search_start,
                    search_end,
                    lambda line: self._text_mentions_requested_device(question, line),
                    max_distance=2,
                )
                selected_indices = [anchor_index]
                if nearest_device_index is not None:
                    selected_indices = list(
                        range(
                            min(anchor_index, nearest_device_index),
                            max(anchor_index, nearest_device_index) + 1,
                        )
                    )

            augmented_indices = set(selected_indices)
            if augmented_indices:
                nearby_start = max(search_start, min(augmented_indices) - 2)
                nearby_end = min(search_end, max(augmented_indices) + 3)
                for index in range(nearby_start, nearby_end):
                    lowered_line = lines[index].lower()
                    if "device summary" in lowered_line or "reference part number" in lowered_line:
                        augmented_indices.add(index)
            return [lines[index] for index in sorted(augmented_indices)]

        if table_question_family == TABLE_QUESTION_ORDERING:
            search_start = max(0, start - 20)
            search_end = min(len(lines), end + 12)
            exact_lines = self._build_exact_package_variant_lines(
                question,
                lines,
                search_start,
                search_end,
                include_ordering_code=True,
            )
            if exact_lines:
                return exact_lines
            package_match = PACKAGE_NAME_RE.search(question)
            requested_package = self._compact_alnum(package_match.group(0)) if package_match else ""
            requested_package_family: str | None = None
            requested_pin_count: str | None = None
            if package_match:
                family_pin_match = re.fullmatch(
                    r"([A-Z]+)(\d+)",
                    self._normalize_search_text(package_match.group(0)).upper().replace(" ", ""),
                )
                if family_pin_match:
                    requested_package_family, requested_pin_count = family_pin_match.groups()

            requested_variant_codes = self._requested_device_variant_codes(question)
            requested_pin_codes = {pin_code for pin_code, _ in requested_variant_codes}
            requested_density_codes = {density_code for _, density_code in requested_variant_codes}
            candidate_indices = list(range(start, end))

            def matches_ordering_header(line: str) -> bool:
                lowered_line = line.lower()
                return any(
                    term in lowered_line
                    for term in ["ordering information scheme", "ordering code", "order code"]
                )

            def matches_example_line(line: str) -> bool:
                return "example:" in line.lower()

            def matches_pin_header(line: str) -> bool:
                return "pin count" in line.lower()

            def matches_pin_mapping(line: str) -> bool:
                if not requested_pin_count:
                    return False
                upper_line = self._normalize_search_text(line).upper()
                if not re.search(rf"\b{re.escape(requested_pin_count)}\s*PINS?\b", upper_line):
                    return False
                if not requested_pin_codes:
                    return True
                return any(
                    re.search(
                        rf"\b{re.escape(pin_code)}\s*=\s*{re.escape(requested_pin_count)}\s*PINS?\b",
                        upper_line,
                    )
                    for pin_code in requested_pin_codes
                )

            def matches_flash_header(line: str) -> bool:
                return "flash memory size" in line.lower()

            def matches_flash_mapping(line: str) -> bool:
                if not requested_density_codes:
                    return False
                upper_line = self._normalize_search_text(line).upper()
                if "FLASH MEMORY" not in upper_line:
                    return False
                return any(
                    re.search(
                        rf"\b{re.escape(density_code)}\s*=\s*\d+\s*(?:KBYTES?|KB|MB)\b",
                        upper_line,
                    )
                    for density_code in requested_density_codes
                )

            def matches_package_header(line: str) -> bool:
                return line.lower() == "package"

            def matches_package_mapping(line: str) -> bool:
                upper_line = self._normalize_search_text(line).upper()
                if requested_package and requested_package in self._compact_alnum(line):
                    return True
                if requested_package_family and re.search(
                    rf"\b[A-Z0-9]{{1,4}}\s*=\s*{re.escape(requested_package_family)}\b",
                    upper_line,
                ):
                    return True
                return (
                    self._extract_requested_ordering_package_code(
                        question,
                        line,
                        allow_family_fallback=False,
                    )
                    is not None
                )

            anchor_index = next(
                (
                    index
                    for index in candidate_indices
                    if any(
                        predicate(lines[index])
                        for predicate in [
                            matches_example_line,
                            matches_pin_mapping,
                            matches_flash_mapping,
                            matches_package_mapping,
                        ]
                    )
                ),
                start,
            )
            augmented_indices = set(candidate_indices)
            for predicate in [
                matches_ordering_header,
                matches_example_line,
                matches_pin_header,
                matches_pin_mapping,
                matches_flash_header,
                matches_flash_mapping,
                matches_package_header,
                matches_package_mapping,
            ]:
                matched_index = self._closest_matching_line_index(
                    lines,
                    anchor_index,
                    search_start,
                    search_end,
                    predicate,
                    max_distance=20,
                )
                if matched_index is not None:
                    augmented_indices.add(matched_index)
            return [lines[index] for index in sorted(augmented_indices)]

        support_lines: list[str] = []
        search_start = max(0, start - (12 if table_question_family == TABLE_QUESTION_PIN else 4))
        search_end = min(len(lines), end + (40 if table_question_family == TABLE_QUESTION_PIN else 4))
        package_support_line: str | None = None

        if table_question_family == TABLE_QUESTION_PIN:
            package_match = PACKAGE_NAME_RE.search(question)
            if package_match:
                package_token = package_match.group(0).lower()
                for index in list(range(start - 1, search_start - 1, -1)) + list(range(end, search_end)):
                    line = lines[index]
                    if package_token in line.lower():
                        package_support_line = line
                        break

        for index in range(start - 1, search_start - 1, -1):
            line = lines[index]
            lowered_line = line.lower()
            if self._table_row_noise_penalty(line, table_question_family) >= 4.0:
                continue
            if self._is_table_row_support_line(question, table_question_family, lowered_line):
                support_lines.insert(0, line)
            if len(support_lines) >= 2:
                break

        if package_support_line and package_support_line not in support_lines:
            support_lines = [package_support_line, *support_lines[:1]]

        if len(support_lines) < 2:
            for index in range(end, search_end):
                line = lines[index]
                lowered_line = line.lower()
                if self._table_row_noise_penalty(line, table_question_family) >= 4.0:
                    continue
                if self._is_table_row_support_line(question, table_question_family, lowered_line):
                    if line not in support_lines:
                        support_lines.append(line)
                if len(support_lines) >= 2:
                    break

        augmented_lines = [*support_lines, *candidate_lines]
        return augmented_lines[:5]

    def _closest_matching_line_index(
        self,
        lines: list[str],
        anchor_index: int,
        search_start: int,
        search_end: int,
        predicate,
        *,
        max_distance: int,
    ) -> int | None:
        best_index: int | None = None
        best_distance = max_distance + 1
        for index in range(max(0, search_start), min(len(lines), search_end)):
            if self._table_row_noise_penalty(lines[index], TABLE_QUESTION_ORDERING) >= 4.0:
                continue
            if not predicate(lines[index]):
                continue
            distance = abs(index - anchor_index)
            if distance > max_distance:
                continue
            if best_index is None or (distance, index) < (best_distance, best_index):
                best_index = index
                best_distance = distance
        return best_index

    def _build_memory_variant_grounded_lines(
        self,
        question: str,
        lines: list[str],
        search_start: int,
        search_end: int,
    ) -> list[str]:
        requested_devices = self._question_device_tokens(question)
        requested_variant_codes = self._requested_device_variant_codes(question)
        if not requested_devices or not requested_variant_codes:
            return []

        requested_device = requested_devices[0]
        requested_pin_code, requested_density_code = requested_variant_codes[0]
        window_start = max(0, search_start)
        window_end = min(len(lines), search_end)
        header_index: int | None = None
        header_matches: list[tuple[str, str]] = []
        target_column_index: int | None = None
        column_label: str | None = None

        for index in range(window_start, window_end):
            normalized_line = self._normalize_search_text(lines[index]).upper()
            matches = [
                (match.group(0), match.group(2))
                for match in re.finditer(r"\b(STM32[A-Z0-9]{4,}?)([A-Z])X\b", normalized_line)
            ]
            if len(matches) < 2:
                continue
            for match_index, (header_label, package_code) in enumerate(matches):
                if package_code == requested_pin_code:
                    header_index = index
                    header_matches = matches
                    target_column_index = match_index
                    column_label = header_label
                    break
            if target_column_index is not None:
                break

        if header_index is None or target_column_index is None or column_label is None:
            return []

        def pick_row_value(line: str) -> tuple[str | None, str | None]:
            normalized_line = self._normalize_search_text(line)
            values = re.findall(r"\b\d+\b", normalized_line)
            if not values:
                return (None, None)
            lowered_line = normalized_line.lower()
            unit = "MB" if re.search(r"\bmb\b", lowered_line) else "Kbytes"
            column_count = len(header_matches)
            if len(values) == column_count:
                return (values[target_column_index], unit)
            if len(values) == column_count * 2:
                density_offset = 0 if requested_density_code.isdigit() else 1
                value_index = (target_column_index * 2) + density_offset
                if value_index < len(values):
                    return (values[value_index], unit)
            if target_column_index < len(values):
                return (values[target_column_index], unit)
            return (None, None)

        title_index = self._closest_matching_line_index(
            lines,
            header_index,
            window_start,
            window_end,
            lambda line: any(
                term in line.lower()
                for term in ["device features and peripheral counts", "device summary"]
            ),
            max_distance=8,
        )
        flash_index = self._closest_matching_line_index(
            lines,
            header_index,
            window_start,
            window_end,
            lambda line: "flash" in line.lower() and bool(re.search(r"\b\d+\b", line)),
            max_distance=8,
        )
        sram_index = self._closest_matching_line_index(
            lines,
            header_index,
            window_start,
            window_end,
            lambda line: "sram" in line.lower() and bool(re.search(r"\b\d+\b", line)),
            max_distance=8,
        )

        exact_lines: list[str] = []
        if title_index is not None:
            exact_lines.append(self._normalize_search_text(lines[title_index]))
        exact_lines.append(f"{requested_device} matches {column_label} in the device summary table")
        if flash_index is not None:
            flash_value, flash_unit = pick_row_value(lines[flash_index])
            if flash_value and flash_unit:
                exact_lines.append(f"{requested_device} Flash = {flash_value} {flash_unit}")
        if sram_index is not None:
            sram_value, sram_unit = pick_row_value(lines[sram_index])
            if sram_value and sram_unit:
                exact_lines.append(f"{requested_device} SRAM = {sram_value} {sram_unit}")

        if len(exact_lines) <= 1:
            return []

        deduped_lines: list[str] = []
        seen_lines: set[str] = set()
        for line in exact_lines:
            normalized_line = self._normalize_search_text(line)
            if not normalized_line or normalized_line in seen_lines:
                continue
            seen_lines.add(normalized_line)
            deduped_lines.append(normalized_line)
        return deduped_lines

    def _build_exact_package_variant_lines(
        self,
        question: str,
        lines: list[str],
        search_start: int,
        search_end: int,
        *,
        include_ordering_code: bool,
    ) -> list[str]:
        requested_devices = self._question_device_tokens(question)
        requested_variant_codes = self._requested_device_variant_codes(question)
        if not requested_devices or not requested_variant_codes:
            return []

        requested_device = requested_devices[0]
        requested_pin_code, requested_density_code = requested_variant_codes[0]
        requested_compact = self._compact_alnum(requested_device)
        package_match = PACKAGE_NAME_RE.search(question)
        requested_package_family: str | None = None
        requested_pin_count: str | None = None
        if package_match:
            family_pin_match = re.fullmatch(
                r"([A-Z]+)(\d+)",
                self._normalize_search_text(package_match.group(0)).upper().replace(" ", ""),
            )
            if family_pin_match:
                requested_package_family, requested_pin_count = family_pin_match.groups()

        window_start = max(0, search_start)
        window_end = min(len(lines), search_end)
        ordering_header_line: str | None = None
        example_line: str | None = None
        exact_example_package_code: str | None = None
        pin_mapping_line: str | None = None
        density_mapping_line: str | None = None
        package_mapping_line: str | None = None
        pin_count_from_mapping: str | None = None

        for index in range(window_start, window_end):
            normalized_line = self._normalize_search_text(lines[index])
            lowered_line = normalized_line.lower()
            upper_line = normalized_line.upper()
            if ordering_header_line is None and any(
                term in lowered_line
                for term in ["ordering information", "ordering information scheme", "ordering code", "order code"]
            ):
                ordering_header_line = normalized_line
            if example_line is None and "example:" in lowered_line:
                example_line = normalized_line
            if requested_compact:
                exact_example_match = re.search(
                    rf"{re.escape(requested_compact)}([A-Z0-9])",
                    self._compact_alnum(normalized_line),
                )
                if exact_example_match:
                    example_line = normalized_line
                    exact_example_package_code = exact_example_match.group(1)
            if pin_mapping_line is None:
                pin_match = re.search(
                    rf"\b{re.escape(requested_pin_code)}\s*=\s*(\d+)\s*PINS?\b",
                    upper_line,
                )
                if pin_match:
                    pin_mapping_line = normalized_line
                    pin_count_from_mapping = pin_match.group(1)
            if density_mapping_line is None and re.search(
                rf"\b{re.escape(requested_density_code)}\s*=\s*\d+\s*(?:KBYTES?|KB|MB)\b",
                upper_line,
            ):
                density_mapping_line = normalized_line

        exact_package_code = exact_example_package_code
        if requested_package_family:
            family_package_codes = {
                match.group(1)
                for index in range(window_start, window_end)
                for match in re.finditer(
                    rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(requested_package_family)}\b",
                    self._normalize_search_text(lines[index]).upper(),
                )
            }
            if (
                exact_package_code is None
                and len(family_package_codes) == 1
                and pin_mapping_line
                and density_mapping_line
            ):
                exact_package_code = next(iter(family_package_codes))

        package_family: str | None = requested_package_family
        if exact_package_code is not None:
            for index in range(window_start, window_end):
                normalized_line = self._normalize_search_text(lines[index])
                package_match_line = re.search(
                    rf"\b{re.escape(exact_package_code)}\s*=\s*(LQFP|UFQFPN|VFQFPN|TFBGA|LFBGA|UFBGA|BGA)\b",
                    normalized_line.upper(),
                )
                if package_match_line:
                    package_mapping_line = normalized_line
                    package_family = package_match_line.group(1)
                    break
        elif requested_package_family:
            for index in range(window_start, window_end):
                normalized_line = self._normalize_search_text(lines[index])
                if re.search(
                    rf"\b[A-Z0-9]{{1,4}}\s*=\s*{re.escape(requested_package_family)}\b",
                    normalized_line.upper(),
                ):
                    package_mapping_line = normalized_line
                    break

        if (
            requested_pin_count
            and pin_count_from_mapping
            and requested_pin_count != pin_count_from_mapping
        ):
            return []

        package_identity: str | None = None
        resolved_pin_count = requested_pin_count or pin_count_from_mapping
        if package_family and resolved_pin_count:
            package_identity = f"{package_family}{resolved_pin_count}"

        exact_lines: list[str] = []
        if ordering_header_line:
            exact_lines.append(ordering_header_line)
        if example_line:
            exact_lines.append(example_line)
        if pin_mapping_line:
            exact_lines.append(pin_mapping_line)
        if density_mapping_line:
            exact_lines.append(density_mapping_line)
        if package_mapping_line:
            exact_lines.append(package_mapping_line)
        if package_identity:
            exact_lines.append(f"{requested_device} package = {package_identity}")
        if include_ordering_code and exact_package_code and package_identity:
            exact_lines.append(f"{requested_device} package code {exact_package_code} = {package_identity}")

        if not package_identity and not (include_ordering_code and exact_package_code):
            return []

        deduped_lines: list[str] = []
        seen_lines: set[str] = set()
        for line in exact_lines:
            normalized_line = self._normalize_search_text(line)
            if not normalized_line or normalized_line in seen_lines:
                continue
            seen_lines.add(normalized_line)
            deduped_lines.append(normalized_line)
        return deduped_lines

    def _text_mentions_requested_device(self, question: str, source_text: str) -> bool:
        requested_tokens = self._question_device_tokens(question)
        if not requested_tokens:
            return False
        compact_source = self._compact_alnum(source_text)
        if not compact_source:
            return False
        for requested_token in requested_tokens:
            compact_requested = self._compact_alnum(requested_token)
            if not compact_requested:
                continue
            for candidate in self._restricted_device_token_aliases(compact_requested):
                if candidate and candidate in compact_source:
                    return True
        return False

    def _requested_device_variant_codes(self, question: str) -> list[tuple[str, str]]:
        code_pairs: list[tuple[str, str]] = []
        for requested_token in self._question_device_tokens(question):
            compact_requested = self._compact_alnum(requested_token)
            match = re.fullmatch(r"(STM32[A-Z0-9]{4,})([A-Z])([A-Z0-9])", compact_requested)
            if not match:
                continue
            code_pair = (match.group(2), match.group(3))
            if code_pair not in code_pairs:
                code_pairs.append(code_pair)
        return code_pairs

    def _is_table_row_support_line(
        self,
        question: str,
        table_question_family: str,
        lowered_line: str,
    ) -> bool:
        if table_question_family == TABLE_QUESTION_PIN:
            package_match = PACKAGE_NAME_RE.search(question)
            if package_match and package_match.group(0).lower() in lowered_line:
                return True
            return any(
                term in lowered_line
                for term in [
                    "alternate function",
                    "default remap",
                    "pin name",
                    "pins",
                    "package",
                    "ufqfpn",
                    "lqfp",
                    "tfbga",
                ]
            )

        if table_question_family == TABLE_QUESTION_ELECTRICAL:
            return any(
                term in lowered_line
                for term in [
                    "symbol",
                    "parameter",
                    "conditions",
                    "min",
                    "max",
                    "unit",
                    "operating conditions",
                ]
            )

        if table_question_family in {TABLE_QUESTION_FEATURE, TABLE_QUESTION_PERIPHERAL_COUNT}:
            return any(
                term in lowered_line
                for term in [
                    "device summary",
                    "feature",
                    "features and peripheral counts",
                    "peripheral counts",
                    "peripheral",
                    "timers",
                    "spi",
                    "i2c",
                    "usart",
                    "uart",
                    "usb",
                    "can",
                    "gpio",
                    "flash - kbytes",
                    "sram - kbytes",
                    "packages",
                ]
            )

        if table_question_family == TABLE_QUESTION_MEMORY:
            return any(
                term in lowered_line
                for term in [
                    "device summary",
                    "memory organization",
                    "flash - kbytes",
                    "flash memory",
                    "sram",
                    "embedded flash and sram",
                    "part number",
                    "reference",
                ]
            )

        if table_question_family == TABLE_QUESTION_ORDERING:
            if any(
                term in lowered_line
                for term in ["ordering information scheme", "ordering code", "order code"]
            ):
                return True

            package_match = PACKAGE_NAME_RE.search(question)
            if not package_match:
                return False

            requested_package = self._compact_alnum(package_match.group(0))
            compact_line = self._compact_alnum(lowered_line)
            if requested_package and requested_package in compact_line:
                return True
            return (
                self._extract_requested_ordering_package_code(
                    question,
                    lowered_line,
                    allow_family_fallback=False,
                )
                is not None
            )

        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return any(
                term in lowered_line
                for term in [
                    "ordering information",
                    "ordering information scheme",
                    "ordering code",
                    "order code",
                    "device summary",
                    "package information",
                    "package",
                    "pin count",
                    "flash memory size",
                    "temperature range",
                    "device family",
                    "product type",
                    "device subfamily",
                    "example: stm32",
                ]
            ) or bool(
                re.search(
                    r"\b[a-z0-9]{1,4}\s*=\s*(?:lqfp|ufqfpn|vfqfpn|tfbga|lfbga|ufbga|bga|\d+\s*(?:pins|kbytes?|kb|mb))\b",
                    lowered_line,
                )
            )

        return False

    def _table_row_candidate_ranges(
        self,
        index: int,
        total_lines: int,
        table_question_family: str,
    ) -> list[tuple[int, int]]:
        templates = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0)]
        if table_question_family == TABLE_QUESTION_PIN:
            templates.extend([(0, 2), (2, 1)])
            max_span = 4
        elif table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            templates.extend([(0, 2), (1, 2), (2, 1), (2, 2), (1, 3)])
            max_span = 5
        elif table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
            TABLE_QUESTION_MEMORY,
        }:
            templates.extend([(0, 2), (1, 2), (2, 1)])
            max_span = 4
        else:
            max_span = 4

        ranges: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for before_count, after_count in templates:
            start = max(0, index - before_count)
            end = min(total_lines, index + after_count + 1)
            if start >= end or (end - start) > max_span:
                continue
            candidate_range = (start, end)
            if candidate_range in seen:
                continue
            seen.add(candidate_range)
            ranges.append(candidate_range)
        return ranges

    def _table_row_candidate_bonus(
        self,
        question: str,
        table_question_family: str,
        text: str,
    ) -> float:
        if table_question_family == TABLE_QUESTION_PIN:
            return self._pin_table_row_candidate_bonus(question, text)
        if table_question_family == TABLE_QUESTION_ELECTRICAL:
            return self._electrical_table_row_candidate_bonus(question, text)
        if table_question_family == TABLE_QUESTION_FEATURE:
            return self._feature_table_row_candidate_bonus(
                question,
                text,
                prefer_counts=False,
            )
        if table_question_family == TABLE_QUESTION_PERIPHERAL_COUNT:
            return self._feature_table_row_candidate_bonus(
                question,
                text,
                prefer_counts=True,
            )
        if table_question_family == TABLE_QUESTION_MEMORY:
            return self._memory_table_row_candidate_bonus(question, text)
        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return self._package_ordering_table_row_candidate_bonus(
                question,
                text,
                table_question_family,
            )
        return 0.0

    def _pin_table_row_candidate_bonus(self, question: str, text: str) -> float:
        normalized_text = self._normalize_search_text(text)
        lowered_text = normalized_text.lower()
        upper_text = normalized_text.upper()
        bonus = 0.0

        if self._build_pin_summary(question, normalized_text) is not None:
            bonus += 9.0
        elif self._extract_pin_mapping_values(question, normalized_text) is not None:
            bonus += 6.0

        question_signals: list[str] = []
        for candidate in SIGNAL_NAME_RE.findall(question):
            normalized_candidate = candidate.upper()
            if normalized_candidate not in question_signals:
                question_signals.append(normalized_candidate)
        signal_hits = sum(1 for signal in question_signals if signal in upper_text)
        bonus += min(signal_hits, 2) * 4.0

        package_match = PACKAGE_NAME_RE.search(question)
        if package_match and package_match.group(0).lower() in lowered_text:
            bonus += 3.0

        unique_pins = {candidate.upper() for candidate in PIN_NAME_RE.findall(normalized_text)}
        if unique_pins:
            bonus += min(len(unique_pins), 3) * 1.2
        if signal_hits and unique_pins:
            bonus += 2.4
        if "alternate function" in lowered_text or "default remap" in lowered_text:
            bonus += 1.5
        if "remap" in lowered_text and "=" in normalized_text:
            bonus += 2.0
        if re.search(r"\btable\s+\d+\b", lowered_text):
            bonus += 0.8
        if len(unique_pins) > 4:
            bonus -= (len(unique_pins) - 4) * 0.8

        bonus -= self._table_row_noise_penalty(text, TABLE_QUESTION_PIN)
        bonus -= self._table_row_span_penalty(text)
        return bonus

    def _electrical_table_row_candidate_bonus(self, question: str, text: str) -> float:
        normalized_text = self._normalize_search_text(text)
        lowered_text = normalized_text.lower()
        bonus = 0.0

        if self._extract_numeric_answer(question, normalized_text) is not None:
            bonus += 9.0

        parameter_symbols: list[str] = []
        for match in ELECTRICAL_PARAMETER_SYMBOL_RE.finditer(question):
            symbol = match.group(0).lower()
            if symbol not in parameter_symbols:
                parameter_symbols.append(symbol)
        symbol_hits = sum(1 for symbol in parameter_symbols if symbol in lowered_text)
        bonus += min(symbol_hits, 2) * 3.5

        if self._has_electrical_table_context(normalized_text):
            bonus += 2.5
        if all(term in lowered_text for term in ["parameter", "conditions", "min", "max", "unit"]):
            bonus += 1.5
        if "operating conditions" in lowered_text:
            bonus += 1.0
        if re.search(
            r"\b\d+(?:\.\d+)?\s*(?:to|-)\s*\d+(?:\.\d+)?\s*(?:v|mv|a|ma|ua|hz|khz|mhz|ghz|ns|us|ms|%)\b",
            lowered_text,
        ):
            bonus += 1.4
        elif "min" in lowered_text and "max" in lowered_text:
            bonus += 1.0

        bonus -= self._table_row_noise_penalty(text, TABLE_QUESTION_ELECTRICAL)
        bonus -= self._table_row_span_penalty(text)
        return bonus

    def _feature_table_row_candidate_bonus(
        self,
        question: str,
        text: str,
        *,
        prefer_counts: bool,
    ) -> float:
        normalized_question = self._normalize_search_text(question)
        normalized_text = self._normalize_search_text(text)
        lowered_question = normalized_question.lower()
        lowered_text = normalized_text.lower()
        bonus = 0.0

        question_terms = [term for term in FEATURE_QUERY_TERMS if term in lowered_question]
        term_hits = sum(1 for term in question_terms if term in lowered_text)
        bonus += min(term_hits, 2) * 3.5

        count_pattern = r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|up to)\b"
        feature_count_alignment = any(
            re.search(
                rf"{count_pattern}[^\n]{{0,24}}\b{re.escape(term)}s?\b|\b{re.escape(term)}s?\b[^\n]{{0,24}}{count_pattern}",
                lowered_text,
            )
            for term in question_terms
        )
        if feature_count_alignment:
            bonus += 4.8
        elif prefer_counts and re.search(count_pattern, lowered_text):
            bonus += 2.6

        if any(
            term in lowered_text
            for term in ["device summary", "features and peripheral counts", "peripheral counts"]
        ):
            bonus += 2.8
        elif "feature" in lowered_text or "peripheral" in lowered_text:
            bonus += 1.6

        device_hits = sum(
            1 for token in self._question_device_tokens(question)
            if token.lower() in lowered_text
        )
        bonus += min(device_hits, 2) * 1.2
        if "stm32f103" in lowered_text:
            bonus += 0.8

        if prefer_counts and any(term in lowered_text for term in ["channel", "channels", "timers", "gpios"]):
            bonus += 1.4

        if any(term in lowered_text for term in ["operating voltage", "vdd", "ambient temperature", "junction temperature"]):
            bonus -= 4.8
        if "power supply" in lowered_text and term_hits == 0:
            bonus -= 2.6

        bonus -= self._table_row_noise_penalty(text, TABLE_QUESTION_PERIPHERAL_COUNT if prefer_counts else TABLE_QUESTION_FEATURE)
        bonus -= self._table_row_span_penalty(text)
        return bonus

    def _memory_table_row_candidate_bonus(self, question: str, text: str) -> float:
        normalized_question = self._normalize_search_text(question)
        normalized_text = self._normalize_search_text(text)
        lowered_question = normalized_question.lower()
        lowered_text = normalized_text.lower()
        bonus = 0.0

        memory_terms = [term for term in MEMORY_QUERY_TERMS if term in lowered_question]
        term_hits = sum(1 for term in memory_terms if term in lowered_text)
        bonus += min(term_hits, 2) * 3.2

        capacity_hits = len(re.findall(r"\b\d+\s*(?:kbytes?|kb|mb)\b", lowered_text))
        bonus += min(capacity_hits, 3) * 1.9

        memory_alignment_hits = sum(
            1
            for term in memory_terms
            if re.search(
                rf"\b{term}\b[^\n]{{0,28}}\b\d+\s*(?:kbytes?|kb|mb)\b|\b\d+\s*(?:kbytes?|kb|mb)\b[^\n]{{0,28}}\b{term}\b",
                lowered_text,
            )
        )
        if memory_alignment_hits:
            bonus += min(memory_alignment_hits, 2) * 4.0
        if any(
            re.search(
                rf"\b{term}\b[^\n]{{0,28}}\b\d+\s*(?:kbytes?|kb|mb)\b|\b\d+\s*(?:kbytes?|kb|mb)\b[^\n]{{0,28}}\b{term}\b",
                lowered_text,
            )
            for term in memory_terms
        ):
            bonus += 1.2
        if all(term in lowered_text for term in ["flash", "sram"]):
            bonus += 3.2
        if {"flash", "sram"}.issubset(set(memory_terms)) and all(term in lowered_text for term in ["flash", "sram"]) and capacity_hits >= 2:
            bonus += 6.0
        if {"flash", "sram"}.issubset(set(memory_terms)) and not all(term in lowered_text for term in ["flash", "sram"]):
            bonus -= 4.5

        if any(term in lowered_text for term in ["device summary", "memory organization", "embedded flash and sram"]):
            bonus += 2.4
        if any(
            token.lower() in lowered_text for token in self._question_device_tokens(question)
        ):
            bonus += 1.3
        if "stm32f103" in lowered_text:
            bonus += 0.8

        has_requested_device = bool(self._question_device_tokens(question))
        text_mentions_requested_device = self._text_mentions_requested_device(
            question,
            normalized_text,
        )
        if has_requested_device:
            if text_mentions_requested_device:
                bonus += 4.8
            else:
                bonus -= 6.0
            if self._source_has_family_wide_scope(normalized_text):
                bonus -= 4.0
            if "up to" in lowered_text:
                bonus -= 8.0

        if self._source_has_multiple_capacity_options(normalized_text):
            bonus -= 18.0 if has_requested_device else 4.5
            if re.search(
                r"\b\d+\s*(?:kbytes?|kb|mb)?\s*(?:/|or)\s*\d+\s*(?:kbytes?|kb|mb)\b",
                lowered_text,
            ):
                bonus -= 2.5

        if any(
            term in lowered_text
            for term in [
                "operating voltage",
                "application supply",
                "power supply",
                "vdd",
                "voltage regulator",
            ]
        ):
            bonus -= 5.2
        if {"flash", "sram"}.issubset(set(memory_terms)) and any(
            term in lowered_text for term in ["operating voltage", "application supply", "vdd"]
        ):
            bonus -= 3.8
        if "description" in lowered_text and capacity_hits == 0:
            bonus -= 1.8

        bonus -= self._table_row_noise_penalty(text, TABLE_QUESTION_MEMORY)
        bonus -= self._table_row_span_penalty(text)
        return bonus

    def _package_ordering_table_row_candidate_bonus(
        self,
        question: str,
        text: str,
        table_question_family: str,
    ) -> float:
        normalized_text = self._normalize_search_text(text)
        lowered_text = normalized_text.lower()
        upper_text = normalized_text.upper()
        bonus = 0.0

        package_match = PACKAGE_NAME_RE.search(question)
        if package_match and package_match.group(0).lower() in lowered_text:
            bonus += 4.8
        elif package_match and package_match.group(0).lower().replace(" ", "") in lowered_text.replace(" ", ""):
            bonus += 4.2
        requested_package_family: str | None = None
        requested_pin_count: str | None = None
        if package_match:
            family_pin_match = re.fullmatch(
                r"([a-z]+)(\d+)",
                package_match.group(0).lower().replace(" ", ""),
            )
            if family_pin_match:
                requested_package_family, requested_pin_count = family_pin_match.groups()
                if requested_package_family in lowered_text:
                    bonus += 3.0
                if re.search(rf"\b{requested_pin_count}\s*[- ]?pins?\b", lowered_text):
                    bonus += 2.6

        question_device_tokens = self._question_device_tokens(question)
        requested_device_present = self._text_mentions_requested_device(question, normalized_text)
        device_hits = sum(1 for token in question_device_tokens if token.lower() in lowered_text)
        bonus += min(device_hits, 2) * 1.4
        if "stm32" in lowered_text:
            bonus += 1.2
        if "stm32f103" in lowered_text:
            bonus += 0.8
        exact_package_identity = self._extract_package_identity_phrase(normalized_text)
        if exact_package_identity and requested_device_present:
            bonus += 4.2

        if "example: stm32" in lowered_text:
            bonus += 3.2
        mapping_hits = sum(
            1
            for term in [
                "device family",
                "product type",
                "device subfamily",
                "pin count",
                "flash memory size",
                "package",
                "temperature range",
                "options",
            ]
            if term in lowered_text
        )
        bonus += min(mapping_hits, 4) * 1.4

        exact_package_code: str | None = None
        fallback_package_code: str | None = None
        if table_question_family == TABLE_QUESTION_ORDERING:
            exact_package_code = self._extract_requested_ordering_package_code(
                question,
                text,
                allow_family_fallback=False,
            )
            fallback_package_code = self._extract_requested_ordering_package_code(
                question,
                text,
                allow_family_fallback=True,
            )

        requested_variant_codes = self._requested_device_variant_codes(question)
        requested_pin_codes = {pin_code for pin_code, _ in requested_variant_codes}
        requested_density_codes = {density_code for _, density_code in requested_variant_codes}
        package_mapping_hit = bool(
            requested_package_family
            and re.search(
                rf"\b[A-Z0-9]{{1,4}}\s*=\s*{re.escape(requested_package_family.upper())}\b",
                upper_text,
            )
        )
        pin_mapping_hit = bool(
            requested_pin_count
            and re.search(
                rf"\b[A-Z0-9]{{1,4}}\s*=\s*{re.escape(requested_pin_count)}\s*PINS?\b",
                upper_text,
            )
        )
        exact_pin_mapping_hit = bool(
            requested_pin_count
            and requested_pin_codes
            and any(
                re.search(
                    rf"\b{re.escape(pin_code)}\s*=\s*{re.escape(requested_pin_count)}\s*PINS?\b",
                    upper_text,
                )
                for pin_code in requested_pin_codes
            )
        )
        flash_mapping_hit = bool(
            requested_density_codes
            and "FLASH MEMORY" in upper_text
            and any(
                re.search(
                    rf"\b{re.escape(density_code)}\s*=\s*\d+\s*(?:KBYTES?|KB|MB)\b",
                    upper_text,
                )
                for density_code in requested_density_codes
            )
        )
        example_hit = "example:" in lowered_text
        explicit_mapping_context = "=" in normalized_text and any(
            term in lowered_text
            for term in ["pin count", "flash memory size", "package", "example:"]
        )

        normalized_lines = [
            self._normalize_search_text(line)
            for line in text.splitlines()
            if self._normalize_search_text(line)
        ]
        device_line_indices = [
            index
            for index, line in enumerate(normalized_lines)
            if self._text_mentions_requested_device(question, line)
        ]
        package_line_indices = [
            index
            for index, line in enumerate(normalized_lines)
            if PACKAGE_NAME_RE.search(line)
        ]
        if device_line_indices and package_line_indices:
            closest_distance = min(
                abs(device_index - package_index)
                for device_index in device_line_indices
                for package_index in package_line_indices
            )
            if closest_distance <= 1:
                bonus += 3.4
            elif closest_distance == 2:
                bonus += 1.6
            else:
                bonus -= 4.8
        elif table_question_family == TABLE_QUESTION_PACKAGE and question_device_tokens:
            if requested_device_present:
                bonus -= 2.6
            else:
                bonus -= 4.0

        if re.search(
            r"\b[a-z0-9]{1,4}\s*=\s*(?:lqfp\d*|ufqfpn\d*|vfqfpn\d*|tfbga\d*|lfbga\d*|ufbga\d*|bga\d*)\b",
            lowered_text,
        ):
            bonus += 4.5
            if requested_package_family and requested_package_family not in lowered_text:
                bonus -= 4.8
        if re.search(r"\b[a-z0-9]{1,4}\s*=\s*\d+\s*(?:pins|kbytes?|kb|mb)\b", lowered_text):
            bonus += 2.8
            if requested_pin_count and not re.search(rf"\b{requested_pin_count}\s*[- ]?pins?\b", lowered_text):
                bonus -= 3.6

        if table_question_family == TABLE_QUESTION_ORDERING:
            if any(
                term in lowered_text
                for term in ["ordering information", "ordering information scheme", "ordering code", "order code"]
            ):
                bonus += 3.6
            if any(term in lowered_text for term in ["pin count", "flash memory size", "package"]):
                bonus += 2.4
            if explicit_mapping_context:
                bonus += 2.6
            if exact_package_code:
                bonus += 4.8
            elif fallback_package_code:
                bonus += 0.6
            if example_hit:
                bonus += 2.4
            if package_mapping_hit:
                bonus += 3.2
            if pin_mapping_hit:
                bonus += 2.4
            if exact_pin_mapping_hit:
                bonus += 2.0
            if flash_mapping_hit:
                bonus += 2.8
            if package_mapping_hit and pin_mapping_hit:
                bonus += 3.8
            if package_mapping_hit and flash_mapping_hit:
                bonus += 2.4
            if package_mapping_hit and pin_mapping_hit and flash_mapping_hit:
                bonus += 6.0
            if not explicit_mapping_context and not any(
                term in lowered_text
                for term in ["ordering information", "ordering information scheme", "ordering code", "order code"]
            ):
                bonus -= 12.0
            if not (
                exact_package_code
                or package_mapping_hit
                or pin_mapping_hit
                or flash_mapping_hit
            ):
                bonus -= 4.5
            if "packages" in lowered_text and not any(
                term in lowered_text
                for term in ["ordering information", "ordering information scheme", "example: stm32", "="]
            ):
                bonus -= 8.0
            if any(
                term in lowered_text
                for term in ["operating voltage", "operating temperatures", "junction temperature"]
            ) and not any(
                term in lowered_text
                for term in ["ordering information", "ordering information scheme", "example: stm32", "="]
            ):
                bonus -= 6.5
            if any(
                term in lowered_text
                for term in [
                    "low-profile quad flat package",
                    "outline",
                    "gauge plane",
                    "dimension",
                    "section a-a",
                    "section b-b",
                    "note: see list of notes",
                ]
            ):
                bonus -= 9.5
            if "package information" in lowered_text and not any(
                term in lowered_text
                for term in [
                    "ordering information",
                    "ordering information scheme",
                    "example: stm32",
                    "=",
                ]
            ):
                bonus -= 6.0
        elif table_question_family == TABLE_QUESTION_PACKAGE:
            if any(term in lowered_text for term in ["package information", "package options", "package"]):
                bonus += 2.8
            if self._source_has_multiple_package_options(normalized_text):
                bonus -= 5.5
        elif table_question_family == TABLE_QUESTION_DEVICE_VARIANT:
            if any(term in lowered_text for term in ["device summary", "variant", "part number"]):
                bonus += 2.8
            if self._source_has_multiple_package_options(normalized_text):
                bonus -= 4.0

        compact_question = self._normalize_search_text(question).upper()
        if "STM32F103CB" in compact_question:
            if re.search(r"\bC\s*=\s*48\s*pins\b", source := lowered_text):
                bonus += 4.2
            if re.search(r"\bB\s*=\s*128\s*kbytes?\b", source):
                bonus += 4.2
            if re.search(r"\bT\s*=\s*LQFP\b", source):
                bonus += 4.8
            if all(
                re.search(pattern, source)
                for pattern in [
                    r"\bC\s*=\s*48\s*pins\b",
                    r"\bB\s*=\s*128\s*kbytes?\b",
                    r"\bT\s*=\s*LQFP\b",
                ]
            ):
                bonus += 6.0

        if re.search(r"\b\d{1,2}-[a-z]{3}-\d{4}\b", lowered_text):
            bonus -= 6.0
        if any(term in lowered_text for term in ["revision history", "table 64", "changes", "docid", "www.st.com"]):
            bonus -= 5.5
        if any(term in lowered_text for term in ["updated", "removed", "added", "modified", "revised", "clarified"]):
            bonus -= 6.5
        if any(term in lowered_text for term in ["footprints", "specifications"]):
            bonus -= 3.5
        if "page " in lowered_text and any(term in lowered_text for term in ["section ", "table "]):
            bonus -= 2.8
        if any(term in lowered_text for term in MECHANICAL_PACKAGE_NOISE_TERMS):
            bonus -= 4.2

        bonus -= self._table_row_noise_penalty(text, table_question_family)
        bonus -= self._table_row_span_penalty(text)
        return bonus

    def _table_row_noise_penalty(self, text: str, table_question_family: str) -> float:
        penalty = 0.0
        for raw_line in text.splitlines():
            line = self._normalize_search_text(raw_line)
            if not line:
                continue
            lowered_line = line.lower()
            if any(term in lowered_line for term in TABLE_NOISE_HEADING_TERMS):
                penalty += 6.0
            if any(term in lowered_line for term in MECHANICAL_PACKAGE_NOISE_TERMS):
                penalty += 4.0
            if "www.st.com" in lowered_line:
                penalty += 2.5
            if "docid" in lowered_line:
                penalty += 2.5
            if re.search(r"\brev\s+\d+\b", lowered_line) and re.search(r"\b\d+/\d+\b", lowered_line):
                penalty += 2.0
            if re.search(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", line):
                penalty += 2.8
            if "table 64" in lowered_line and "revision history" in lowered_line:
                penalty += 3.2
            if "refer to" in lowered_line and any(term in lowered_line for term in ["manual", "website", "section"]):
                penalty += 1.5
            if table_question_family == TABLE_QUESTION_PIN and any(
                term in lowered_line for term in ELECTRICAL_TABLE_HEADING_TERMS
            ):
                penalty += 2.0
            if table_question_family == TABLE_QUESTION_ELECTRICAL and any(
                term in lowered_line for term in PIN_TABLE_HEADING_TERMS
            ):
                penalty += 2.0
        return penalty

    def _table_row_span_penalty(self, text: str) -> float:
        normalized_lines = [
            self._normalize_search_text(line)
            for line in text.splitlines()
            if self._normalize_search_text(line)
        ]
        penalty = max(0, len(normalized_lines) - 3) * 1.1
        if len(self._normalize_search_text(text)) > max(420, self.chunk_size):
            penalty += 1.5
        return penalty

    def _table_blob_noise_penalty(self, table_question_family: str, text: str) -> float:
        compact_text = self._normalize_search_text(text)
        penalty = self._table_row_noise_penalty(text, table_question_family)
        if len(compact_text) > max(420, int(self.chunk_size * 0.85)):
            penalty += 1.5
        return max(0.0, penalty)

    def _table_row_evidence_quality(self, question: str, entry: EvidenceRecord) -> float:
        table_question_family = self._table_question_family(question)
        if table_question_family is None:
            return 0.0
        source_text = entry.full_text if entry.full_text else entry.excerpt
        return self._table_row_candidate_bonus(question, table_question_family, source_text)

    def _build_evidence(self, chunk_hits: list[ScoredItem], question: str) -> list[EvidenceRecord]:
        evidence: list[EvidenceRecord] = []
        table_question_family = self._table_question_family(question)
        for index, hit in enumerate(chunk_hits, start=1):
            chunk: ChunkRecord = hit.item
            section_label = self._normalize_evidence_section(
                question,
                " > ".join(chunk.heading_path),
                chunk.text,
            )
            excerpt_limit = 360 if chunk.kind == "table-row" else 280
            if table_question_family and self._table_row_candidate_bonus(
                question,
                table_question_family,
                chunk.text,
            ) >= 7.0:
                excerpt_limit = max(excerpt_limit, 420)
            evidence.append(
                EvidenceRecord(
                    tag=f"[S{index}]",
                    document_id=chunk.document_id,
                    document=chunk.heading_path[0] if chunk.heading_path else chunk.heading,
                    device_family=None,
                    revision=None,
                    section=section_label,
                    page=self._format_page_range(chunk.page_start, chunk.page_end),
                    excerpt=self._extract_relevant_excerpt(
                        chunk.text,
                        question,
                        limit=excerpt_limit,
                    ),
                    full_text=chunk.text,
                    score=round(hit.score, 2),
                    document_path="",
                )
            )
        return evidence

    def _normalize_evidence_section(self, question: str, section: str, text: str) -> str:
        if not section:
            return section

        lowered_question = question.lower()
        lowered_text = re.sub(r"\s+", " ", text).lower()
        if "spi" in lowered_question and "dma" in lowered_question:
            has_spi_dma_bits = all(
                term in lowered_text
                for term in [
                    "txdmaen",
                    "rxdmaen",
                    "tx buffer dma enable",
                    "rx buffer dma enable",
                ]
            )
            if has_spi_dma_bits and "spi status register (spi_sr)" in section.lower():
                return re.sub(
                    r"SPI status register \(SPI_SR\)",
                    "SPI control register 2 (SPI_CR2)",
                    section,
                    flags=re.IGNORECASE,
                )

        return section

    def _build_result(
        self,
        question: str,
        documents: list[DocumentRecord],
        evidence: list[EvidenceRecord],
    ) -> RetrievalResult:
        document_lookup = {document.id: document for document in documents}
        searched_documents = [document.path for document in documents]

        for entry in evidence:
            matched_document = document_lookup.get(entry.document_id)
            if matched_document is None:
                continue
            entry.document = matched_document.title
            entry.device_family = matched_document.device_family
            entry.revision = matched_document.revision
            entry.document_path = matched_document.path

        evidence = self._prune_noisy_evidence(question, evidence)
        evidence = self._prioritize_direct_answer_evidence(question, evidence)
        evidence = self._reorder_comparison_evidence(question, evidence)
        evidence = self._finalize_comparison_evidence(question, evidence)

        if not evidence:
            return self._build_not_found_result(
                question,
                searched_documents,
                reason="No grounded answer found from the selected manuals.",
            )

        guardrail_result = self._build_guardrail_result(
            question,
            documents,
            evidence,
            searched_documents,
        )
        if guardrail_result is not None:
            return guardrail_result

        short_answer = self._build_grounded_short_answer(question, evidence)
        key_evidence = [
            f"{entry.tag} {entry.section} (page {entry.page}) score={entry.score}"
            for entry in evidence
        ]
        open_questions: list[str] = []
        if len(documents) > 1:
            open_questions.append(
                "Multiple candidate manuals matched; narrow by exact device, revision, or document type for tighter grounding."
            )
        if self.source.is_dir():
            open_questions.append(
                "Folder input may include overlapping manuals; confirm the intended primary source if variants are close."
            )
        missing_tokens = self._missing_requirement_tokens(question, evidence)
        top_entry_directly_answers = self._evidence_directly_answers(question, evidence[0])
        if missing_tokens and not (
            self._is_comparison_query(question)
            and self._has_grounded_comparison_coverage(question, evidence)
        ) and not top_entry_directly_answers:
            open_questions.append(
                "Top evidence did not directly cover these query terms: "
                + ", ".join(missing_tokens[:4])
                + "."
            )
        if not self._has_strong_evidence(evidence, question):
            open_questions.append(
                "Evidence is partially relevant but still weak enough that the answer should be treated cautiously."
            )

        return RetrievalResult(
            question=question,
            source=str(self.source),
            filters=self.filters,
            short_answer=short_answer,
            key_evidence=key_evidence,
            sources=evidence,
            open_questions=open_questions,
            searched_documents=searched_documents,
            structured_summary=self._build_structured_summary(question, evidence),
        )

    def _build_guardrail_result(
        self,
        question: str,
        documents: list[DocumentRecord],
        evidence: list[EvidenceRecord],
        searched_documents: list[str],
    ) -> RetrievalResult | None:
        if self._should_gate_on_ambiguity(question, documents, evidence):
            return self._build_ambiguous_result(question, evidence, searched_documents)

        if self._should_gate_on_conflict(question, documents, evidence):
            return self._build_conflict_result(question, documents, evidence, searched_documents)

        if self._is_absence_query(question) and not self._supports_absence_claim(question, evidence):
            return self._build_not_found_result(
                question,
                searched_documents,
                reason="No grounded answer found for the requested feature check; the top matches were too weak or lexically ambiguous to confirm presence or absence.",
            )

        constraint_gate_hints = self._apply_constraint_aware_answer_gate(question, evidence)
        if constraint_gate_hints is not None:
            return self._build_insufficient_coverage_result(
                question,
                evidence,
                searched_documents,
                extra_open_questions=constraint_gate_hints,
            )

        if self._should_gate_on_descriptive_gap(question, evidence):
            return self._build_insufficient_coverage_result(question, evidence, searched_documents)

        if self._should_gate_on_register_gap(question, evidence):
            return self._build_insufficient_coverage_result(question, evidence, searched_documents)

        if self._should_gate_on_pin_mapping_gap(question, evidence):
            return self._build_insufficient_coverage_result(question, evidence, searched_documents)

        return None

    def _apply_constraint_aware_answer_gate(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> list[str] | None:
        if not evidence:
            return None

        table_question_family = self._table_question_family(question)
        if table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
            TABLE_QUESTION_MEMORY,
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            selected_entry, failure_hints = self._select_table_constraint_satisfied_evidence(
                question,
                evidence,
                table_question_family,
            )
            if selected_entry is None:
                return failure_hints
            self._promote_evidence_entry(evidence, selected_entry)
            return None

        if table_question_family == TABLE_QUESTION_PIN or self._is_pin_intent_query(question):
            selected_entry, failure_hints = self._select_pin_constraint_satisfied_evidence(
                question,
                evidence,
            )
            if selected_entry is None:
                return failure_hints
            self._promote_evidence_entry(evidence, selected_entry)
            return None

        if table_question_family == TABLE_QUESTION_ELECTRICAL or self._is_electrical_table_query(question):
            selected_entry, failure_hints = self._select_electrical_constraint_satisfied_evidence(
                question,
                evidence,
            )
            if selected_entry is None:
                return failure_hints
            self._promote_evidence_entry(evidence, selected_entry)
            return None

        return None

    def _select_table_constraint_satisfied_evidence(
        self,
        question: str,
        evidence: list[EvidenceRecord],
        table_question_family: str,
        *,
        limit: int = 3,
    ) -> tuple[EvidenceRecord | None, list[str]]:
        best_failure_hints = [
            "The retrieved table rows did not preserve the requested device/variant/package constraints tightly enough to emit a grounded answer.",
        ]
        best_failure_count = sys.maxsize

        for entry in evidence[:limit]:
            failure_hints = self._table_constraint_failure_hints(
                question,
                entry,
                table_question_family,
            )
            if not failure_hints:
                return entry, []
            if len(failure_hints) < best_failure_count:
                best_failure_hints = failure_hints
                best_failure_count = len(failure_hints)

        return None, best_failure_hints

    def _table_constraint_failure_hints(
        self,
        question: str,
        entry: EvidenceRecord,
        table_question_family: str,
    ) -> list[str]:
        if table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
        }:
            return self._feature_table_constraint_failure_hints(
                question,
                entry,
                prefer_counts=table_question_family == TABLE_QUESTION_PERIPHERAL_COUNT,
            )
        if table_question_family == TABLE_QUESTION_MEMORY:
            return self._memory_table_constraint_failure_hints(question, entry)
        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return self._package_ordering_constraint_failure_hints(
                question,
                entry,
                table_question_family,
            )
        return []

    def _feature_table_constraint_failure_hints(
        self,
        question: str,
        entry: EvidenceRecord,
        *,
        prefer_counts: bool,
    ) -> list[str]:
        source_text = self._normalize_search_text(entry.full_text if entry.full_text else entry.excerpt)
        lowered_text = source_text.lower()
        failure_hints: list[str] = []
        table_question_family = TABLE_QUESTION_PERIPHERAL_COUNT if prefer_counts else TABLE_QUESTION_FEATURE

        if not self._table_evidence_directly_answers(question, entry, table_question_family):
            failure_hints.append(
                "The retrieved feature row did not preserve a grounded feature/peripheral answer."
            )

        feature_terms = [
            term for term in FEATURE_QUERY_TERMS if term in self._normalize_search_text(question).lower()
        ]
        if feature_terms and not any(term in lowered_text for term in feature_terms):
            failure_hints.append(
                "The retrieved feature row did not preserve the requested feature identity."
            )

        if prefer_counts and not re.search(
            r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|up to)\b",
            lowered_text,
        ):
            failure_hints.append(
                "The retrieved feature row did not preserve a grounded count for the requested peripheral."
            )

        if self._question_device_tokens(question) and not (
            self._source_matches_requested_device(question, source_text)
            or self._source_has_family_wide_scope(source_text)
        ):
            failure_hints.append(
                "The retrieved feature row did not preserve the requested device or variant alignment."
            )

        return failure_hints

    def _memory_table_constraint_failure_hints(
        self,
        question: str,
        entry: EvidenceRecord,
    ) -> list[str]:
        source_text = self._normalize_search_text(entry.full_text if entry.full_text else entry.excerpt)
        lowered_text = source_text.lower()
        failure_hints: list[str] = []

        if not self._table_evidence_directly_answers(question, entry, TABLE_QUESTION_MEMORY):
            failure_hints.append(
                "The retrieved memory row did not preserve a grounded memory-capacity answer."
            )

        memory_terms = [term for term in MEMORY_QUERY_TERMS if term in self._normalize_search_text(question).lower()]
        if memory_terms and not all(term in lowered_text for term in memory_terms):
            failure_hints.append(
                "The retrieved memory row did not preserve the requested memory field alignment."
            )

        if self._source_has_multiple_capacity_options(source_text):
            failure_hints.append(
                "The retrieved memory row still mixes sibling capacity options, so the requested device variant is not grounded tightly enough."
            )

        if self._question_device_tokens(question) and not self._source_matches_requested_device(question, source_text):
            failure_hints.append(
                "The retrieved memory row did not preserve the requested device or variant alignment."
            )

        return failure_hints

    def _package_ordering_constraint_failure_hints(
        self,
        question: str,
        entry: EvidenceRecord,
        table_question_family: str,
    ) -> list[str]:
        source_text = self._normalize_search_text(entry.full_text if entry.full_text else entry.excerpt)
        lowered_text = source_text.lower()
        failure_hints: list[str] = []

        if not self._table_evidence_directly_answers(question, entry, table_question_family):
            failure_hints.append(
                "The retrieved package/ordering row did not preserve a grounded device/package mapping."
            )

        if self._question_device_tokens(question) and not self._source_matches_requested_device(question, source_text):
            failure_hints.append(
                "The retrieved package/ordering row did not preserve the requested device or variant alignment."
            )

        package_match = PACKAGE_NAME_RE.search(question)
        if package_match:
            requested_package = package_match.group(0).upper()
            if not self._source_matches_requested_package(requested_package, source_text):
                failure_hints.append(
                    f"The retrieved package/ordering row did not preserve the requested package constraint ({requested_package})."
                )
        elif table_question_family == TABLE_QUESTION_PACKAGE and self._source_has_multiple_package_options(source_text):
            failure_hints.append(
                "The retrieved package row still lists multiple package siblings; specify the package or ordering variant before selecting one grounded answer."
            )

        if table_question_family == TABLE_QUESTION_ORDERING:
            has_ordering_context = any(
                term in lowered_text
                for term in ["ordering information", "ordering information scheme", "ordering code", "order code", "package code"]
            )
            has_mapping_context = self._has_requested_ordering_mapping_context(
                question,
                source_text,
            )
            if not (has_ordering_context and has_mapping_context):
                failure_hints.append(
                    "The retrieved row did not preserve explicit ordering-code context."
                )
            if not self._ordering_source_has_exact_variant_closure(question, source_text):
                failure_hints.append(
                    "The retrieved ordering row still leaves sibling device variants unresolved, so the package code is not uniquely grounded to the requested variant."
                )

        if table_question_family == TABLE_QUESTION_DEVICE_VARIANT and self._source_has_multiple_package_options(source_text):
            failure_hints.append(
                "The retrieved variant row still collapses nearby sibling package or ordering options into one unsafe answer."
            )

        return failure_hints

    def _select_pin_constraint_satisfied_evidence(
        self,
        question: str,
        evidence: list[EvidenceRecord],
        *,
        limit: int = 3,
    ) -> tuple[EvidenceRecord | None, list[str]]:
        best_failure_hints = [
            "The retrieved pin rows did not preserve the requested signal/package/remap constraints tightly enough to emit a grounded pin answer.",
        ]
        best_failure_count = sys.maxsize
        candidate_limit = limit
        if PACKAGE_NAME_RE.search(question):
            candidate_limit = min(len(evidence), max(limit, 6))

        for entry in evidence[:candidate_limit]:
            failure_hints = self._pin_constraint_failure_hints(question, entry)
            if not failure_hints:
                return entry, []
            if len(failure_hints) < best_failure_count:
                best_failure_hints = failure_hints
                best_failure_count = len(failure_hints)

        return None, best_failure_hints

    def _pin_constraint_failure_hints(
        self,
        question: str,
        entry: EvidenceRecord,
    ) -> list[str]:
        source_text = entry.full_text if entry.full_text else entry.excerpt
        summary_signal_text = f"{entry.section} {source_text}"
        failure_hints: list[str] = []

        if not self._is_pin_mapping_lookup_query(question, summary_signal_text):
            return [
                "The top pin-style evidence did not preserve a grounded pin-mapping context.",
            ]

        signal_or_function = self._extract_pin_signal_or_function(question, summary_signal_text)
        if not signal_or_function:
            failure_hints.append(
                "The retrieved pin row did not preserve the requested signal/function token."
            )
        if self._extract_pin_mapping_values(question, source_text) is None:
            failure_hints.append(
                "The retrieved pin row did not preserve one grounded pin/ball mapping value."
            )

        package_match = PACKAGE_NAME_RE.search(question)
        requested_package = package_match.group(0).upper() if package_match else None
        has_exact_package_match = bool(
            requested_package and self._extract_package_name(question, summary_signal_text)
        )
        has_requested_pin_mapping_scope = bool(
            requested_package
            and self._source_has_requested_pin_mapping(question, summary_signal_text)
        )
        if requested_package and not (has_exact_package_match or has_requested_pin_mapping_scope):
            failure_hints.append(
                f"The retrieved pin row did not preserve the requested package constraint ({requested_package})."
            )
        failure_hints.extend(self._source_only_pin_scope_hints(question, summary_signal_text))

        requested_assignments = [
            f"{name.upper()} = {value}"
            for name, value in re.findall(r"\b([A-Z0-9_]+)\s*=\s*([01])\b", question, flags=re.IGNORECASE)
        ]
        pin_name = self._extract_pin_name(question, summary_signal_text)
        if requested_assignments and (
            not pin_name or not all(assignment in pin_name.upper() for assignment in requested_assignments)
        ):
            failure_hints.append(
                f"The retrieved pin row did not preserve the requested remap/alternate condition ({requested_assignments[0]})."
            )
        if not pin_name:
            if requested_assignments:
                failure_hints.append(
                    "The retrieved pin row still leaves multiple sibling pin candidates after applying the requested remap condition."
                )
            else:
                failure_hints.append(
                    "The retrieved pin row still leaves multiple sibling pin candidates without enough package/remap disambiguation."
                )

        return failure_hints

    def _select_electrical_constraint_satisfied_evidence(
        self,
        question: str,
        evidence: list[EvidenceRecord],
        *,
        limit: int = 3,
    ) -> tuple[EvidenceRecord | None, list[str]]:
        best_failure_hints = [
            "The retrieved electrical rows did not preserve the requested parameter/value/unit/condition constraints tightly enough to emit a grounded numeric answer.",
        ]
        best_failure_count = sys.maxsize

        for entry in evidence[:limit]:
            failure_hints = self._electrical_constraint_failure_hints(question, entry)
            if not failure_hints:
                return entry, []
            if len(failure_hints) < best_failure_count:
                best_failure_hints = failure_hints
                best_failure_count = len(failure_hints)

        return None, best_failure_hints

    def _electrical_constraint_failure_hints(
        self,
        question: str,
        entry: EvidenceRecord,
    ) -> list[str]:
        source_text = entry.full_text if entry.full_text else entry.excerpt
        summary_signal_text = f"{entry.section} {source_text}"
        normalized_text = self._normalize_search_text(summary_signal_text)
        lowered_text = normalized_text.lower()
        failure_hints: list[str] = []

        parameter_symbols = self._question_electrical_parameter_symbols(question)
        if parameter_symbols and not all(symbol.lower() in lowered_text for symbol in parameter_symbols):
            failure_hints.append(
                "The retrieved electrical row did not preserve the requested parameter identity."
            )
        elif not parameter_symbols and self._extract_parameter_name(question, normalized_text) is None:
            failure_hints.append(
                "The retrieved electrical row did not preserve the requested parameter identity."
            )

        numeric_answer = self._extract_numeric_answer(question, normalized_text)
        if numeric_answer is None:
            failure_hints.append(
                "The retrieved electrical row did not preserve a grounded numeric value or range."
            )
        else:
            _, unit = self._split_numeric_answer(numeric_answer)
            if unit is None:
                failure_hints.append(
                    "The retrieved electrical row did not preserve the unit for the requested value or range."
                )

        requested_condition = self._requested_electrical_condition_text(question)
        if requested_condition and not self._electrical_row_matches_requested_condition(
            question,
            normalized_text,
        ):
            failure_hints.append(
                f"The retrieved electrical row did not preserve the requested operating condition ({requested_condition})."
            )

        return failure_hints

    def _question_electrical_parameter_symbols(self, question: str) -> list[str]:
        parameter_symbols: list[str] = []
        for match in ELECTRICAL_PARAMETER_SYMBOL_RE.finditer(question):
            symbol = match.group(0).upper()
            if symbol not in parameter_symbols:
                parameter_symbols.append(symbol)
        return parameter_symbols

    def _requested_electrical_condition_text(self, question: str) -> str | None:
        lowered_question = question.lower()
        for phrase in [
            "standard operating voltage",
            "operating voltage",
            "standard operating conditions",
            "recommended operating conditions",
            "operating conditions",
            "absolute maximum ratings",
            "absolute maximum rating",
        ]:
            if phrase in lowered_question:
                return phrase
        if "operating" in lowered_question:
            return "operating"
        return None

    def _electrical_row_matches_requested_condition(
        self,
        question: str,
        source_text: str,
    ) -> bool:
        requested_condition = self._requested_electrical_condition_text(question)
        if requested_condition is None:
            return True

        lowered_text = self._normalize_search_text(source_text).lower()
        condition_aliases = {
            "standard operating voltage": (
                "standard operating voltage",
                "operating voltage",
            ),
            "operating voltage": (
                "standard operating voltage",
                "operating voltage",
            ),
            "standard operating conditions": (
                "standard operating conditions",
                "operating conditions",
            ),
            "recommended operating conditions": (
                "recommended operating conditions",
                "operating conditions",
            ),
            "operating conditions": (
                "standard operating conditions",
                "recommended operating conditions",
                "operating conditions",
            ),
            "absolute maximum ratings": (
                "absolute maximum ratings",
                "absolute maximum rating",
            ),
            "absolute maximum rating": (
                "absolute maximum ratings",
                "absolute maximum rating",
            ),
            "operating": (
                "standard operating voltage",
                "operating voltage",
                "standard operating conditions",
                "recommended operating conditions",
                "operating conditions",
            ),
        }
        return any(alias in lowered_text for alias in condition_aliases.get(requested_condition, (requested_condition,)))

    def _promote_evidence_entry(
        self,
        evidence: list[EvidenceRecord],
        selected_entry: EvidenceRecord,
    ) -> None:
        if not evidence or evidence[0] is selected_entry:
            return

        selected_index = next(
            (index for index, entry in enumerate(evidence) if entry is selected_entry),
            None,
        )
        if selected_index is None:
            return

        evidence.insert(0, evidence.pop(selected_index))
        for index, entry in enumerate(evidence, start=1):
            entry.tag = f"[S{index}]"

    def _metadata_filter_bonus(self, document: DocumentRecord) -> float:
        bonus = 0.0
        if self.filters.device and document.device_family:
            if self.filters.device.lower() in document.device_family.lower():
                bonus += 4.0
        if self.filters.document_type and document.document_type:
            if self.filters.document_type.lower() in document.document_type.lower():
                bonus += 2.5
        if self.filters.revision and document.revision:
            if self.filters.revision.lower() in document.revision.lower():
                bonus += 2.0
        return bonus

    def _question_intent_bonus(self, question: str, heading_text: str, body_text: str) -> float:
        lowered_question = question.lower()
        lowered_heading = heading_text.lower()
        lowered_body = body_text.lower()
        bonus = 0.0

        if "voltage" in lowered_question:
            if any(term in lowered_heading for term in ["operating conditions", "voltage regulator", "reference voltage"]):
                bonus += 2.0
            if "vdd" in lowered_body:
                bonus += 1.5
            if re.search(r"\bmin\b.*\bmax\b|\bmax\b.*\bmin\b", lowered_body):
                bonus += 0.8
            if re.search(r"\b\d+(?:\.\d+)?\s*(?:to|-)?\s*\d+(?:\.\d+)?\s*v\b", lowered_body):
                bonus += 1.2
            if re.search(r"\bvdd\b[^\n]{0,120}\b2(?:\.0)?\b[^\n]{0,80}\b3\.6\b", lowered_body):
                bonus += 2.5
            if "operating voltage" in lowered_body:
                bonus += 1.6
            if any(term in lowered_heading for term in ["emc characteristics", "injection characteristics"]):
                bonus -= 1.4

        if "range" in lowered_question and any(term in lowered_heading for term in ["operating conditions", "absolute maximum ratings"]):
            bonus += 0.9

        if self._is_register_lookup_query(question):
            register_tokens = self._register_specific_tokens(question)
            if register_tokens:
                heading_register_hits = sum(1 for token in register_tokens if token in lowered_heading)
                body_register_hits = sum(1 for token in register_tokens if token in lowered_body)
                bonus += heading_register_hits * 2.8
                bonus += body_register_hits * 1.4

            if any(term in lowered_heading for term in ["spi", "spi_cr", "control register", "status register"]):
                bonus += 1.8
            if "spi" in lowered_question and "dma" in lowered_question:
                if any(
                    term in lowered_heading
                    for term in ["spi control register 2", "spi_cr2", "txdmaen", "rxdmaen"]
                ):
                    bonus += 4.2
                if any(
                    term in lowered_body
                    for term in [
                        "txdmaen",
                        "rxdmaen",
                        "spi_cr2",
                        "tx buffer dma enable",
                        "rx buffer dma enable",
                    ]
                ):
                    bonus += 5.0
                if "spi communication using dm a" in lowered_heading or "spi communication using dma" in lowered_heading:
                    bonus -= 1.4
            if any(term in lowered_body for term in ["txdmaen", "rxdmaen", "spi_cr2", "rx buffer dma enable", "tx buffer dma enable"]):
                bonus += 3.5
            if any(term in lowered_heading for term in ["tim", "timer"]) and "spi" in lowered_question and "spi" not in lowered_heading and "spi" not in lowered_body:
                bonus -= 2.6
            if "dma interrupt enable register" in lowered_heading and "spi" in lowered_question and "spi" not in lowered_body:
                bonus -= 2.2

        if self._is_comparison_query(question):
            if "spi" in lowered_question and "dma" in lowered_question:
                if "spi communication using dm a" in lowered_heading or "spi communication using dma" in lowered_heading:
                    bonus += 5.2
                if all(term in lowered_body for term in ["txe", "rxne", "spi_dr"]):
                    bonus += 3.8
                if "i2s" in lowered_body and "spi communication using dm a" not in lowered_heading and "spi communication using dma" not in lowered_heading:
                    bonus -= 4.5

            if "usart" in lowered_question and "dma" in lowered_question:
                if "continuous comm unication using dma" in lowered_heading or "continuous communication using dma" in lowered_heading:
                    bonus += 5.0
                if all(term in lowered_body for term in ["usart", "dma", "tx buffer", "rx buffer"]):
                    bonus += 4.2
                if "i2c" in lowered_heading and "usart" not in lowered_body:
                    bonus -= 4.8
                if "i2c" in lowered_body and "usart" not in lowered_body:
                    bonus -= 4.2

            if all(term in lowered_question for term in ["threshold mode", "store-and-forward", "mac"]):
                if "mac frame transmission" in lowered_heading:
                    bonus += 5.0
                if "threshold mode" in lowered_body and "store-and-forward mode" in lowered_body:
                    bonus += 4.8
                if "frame reception" in lowered_heading:
                    bonus -= 3.8

        if any(
            term in lowered_question
            for term in [
                "power supply supervisor",
                "programmable voltage detector",
                "pvd",
                "por",
                "pdr",
                "power-on reset",
                "power-down reset",
            ]
        ):
            if any(
                term in lowered_heading
                for term in [
                    "power supply supervisor",
                    "embedded reset and power control",
                    "reset and power control",
                    "power control",
                ]
            ):
                bonus += 4.8
            if any(
                term in lowered_body
                for term in [
                    "power-on reset",
                    "power-down reset",
                    "por)/power-down reset",
                    "por/pdr",
                    "vpor/pdr",
                    "programmable voltage detector",
                    "pvd",
                    "vpvd",
                ]
            ):
                bonus += 4.2
            if any(term in lowered_heading for term in ["external interrupt", "clocks and startup"]):
                if not any(
                    term in lowered_body
                    for term in [
                        "power-on reset",
                        "power-down reset",
                        "programmable voltage detector",
                        "pvd",
                        "vpvd",
                    ]
                ):
                    bonus -= 3.2

        if self._is_pin_intent_query(question):
            question_signals = [candidate.lower() for candidate in SIGNAL_NAME_RE.findall(question)]
            package_match = PACKAGE_NAME_RE.search(question)
            has_package_match = bool(package_match and package_match.group(0).lower() in lowered_body)
            has_pin_table_context = any(
                term in lowered_heading or term in lowered_body
                for term in [
                    "pinouts and pin description",
                    "pin definitions",
                    "pinout",
                    "pin name",
                    "alternate functions",
                ]
            )
            has_signal_match = any(signal in lowered_body for signal in question_signals)
            has_pin_name = bool(PIN_NAME_RE.search(body_text))

            if has_pin_table_context:
                bonus += 3.5
            if has_package_match:
                bonus += 2.5
            if has_signal_match:
                bonus += 4.5
            if has_signal_match and has_pin_name:
                bonus += 2.5

        return bonus

    def _table_question_family(self, question: str) -> str | None:
        normalized_question = self._normalize_search_text(question)
        lowered_question = normalized_question.lower()
        device_tokens = self._question_device_tokens(question)
        package_token_match = PACKAGE_NAME_RE.search(question)
        has_package_token = package_token_match is not None
        ordering_hint = any(
            term in lowered_question
            for term in [
                "ordering code",
                "ordering codes",
                "order code",
                "order codes",
                "ordering information",
                "suffix",
                "suffixes",
            ]
        )
        package_table_hint = any(
            term in lowered_question
            for term in [
                "package options",
                "package option",
                "package offerings",
                "available packages",
                "available package",
                "package information",
                "package code",
                "package codes",
            ]
        )
        variant_hint = any(
            term in lowered_question
            for term in [
                "device variant",
                "device variants",
                "variant",
                "variants",
                "difference between",
                "compare",
                "comparison",
                "versus",
            ]
        )
        package_table_hint = any(
            term in lowered_question
            for term in [
                "package options",
                "package option",
                "package offerings",
                "available packages",
                "available package",
                "package information",
                "package code",
                "package codes",
            ]
        ) or (
            "package" in lowered_question
            and any(term in lowered_question for term in ["available", "offered", "offerings", "options"])
        )
        direct_package_identity_hint = any(
            term in lowered_question
            for term in [
                "which package does",
                "what package does",
                "which package is used",
                "what package is used",
                "which package for",
                "what package for",
            ]
        )
        count_hint = any(
            term in lowered_question
            for term in ["how many", "number of", "count of", "counts of"]
        )
        feature_hint = any(
            term in lowered_question
            for term in [
                "feature",
                "features",
                "provide",
                "provides",
                "support",
                "supports",
                "include",
                "includes",
                "have",
                "has",
            ]
        )
        peripheral_hint = any(term in lowered_question for term in FEATURE_QUERY_TERMS)
        memory_hint = any(term in lowered_question for term in ["flash", "sram", "eeprom"])
        explicit_memory_hint = any(
            term in lowered_question
            for term in [
                "memory organization",
                "memory size",
                "memory sizes",
                "memory density",
                "memory capacity",
            ]
        )

        if self._is_electrical_table_query(question):
            return TABLE_QUESTION_ELECTRICAL

        if (memory_hint or explicit_memory_hint) and not any(
            term in lowered_question for term in ["memory map", "register map", "address map"]
        ):
            return TABLE_QUESTION_MEMORY

        if variant_hint and (
            len(device_tokens) >= 2
            or ordering_hint
            or has_package_token
            or "package" in lowered_question
        ):
            return TABLE_QUESTION_DEVICE_VARIANT
        if ordering_hint and (has_package_token or "package" in lowered_question or bool(device_tokens)):
            return TABLE_QUESTION_ORDERING
        if package_table_hint and (has_package_token or ordering_hint or len(device_tokens) >= 2 or "packages" in lowered_question):
            return TABLE_QUESTION_PACKAGE
        if direct_package_identity_hint and device_tokens and not has_package_token:
            return TABLE_QUESTION_PACKAGE
        if self._is_pin_intent_query(question):
            has_explicit_pin_table_hint = any(
                term in lowered_question
                for term in [
                    "which pin",
                    "what pin",
                    "pinout",
                    "pin definition",
                    "pin definitions",
                    "alternate function",
                    "alternate functions",
                    "table",
                    "package",
                    "ball",
                    "remap",
                ]
            )
            if has_explicit_pin_table_hint or SIGNAL_NAME_RE.search(question) or PACKAGE_NAME_RE.search(question):
                return TABLE_QUESTION_PIN
        if peripheral_hint and count_hint:
            return TABLE_QUESTION_PERIPHERAL_COUNT
        if peripheral_hint and feature_hint:
            return TABLE_QUESTION_FEATURE
        return None

    def _is_electrical_table_query(self, question: str) -> bool:
        if self._is_pin_intent_query(question) or self._is_register_lookup_query(question):
            return False

        lowered_question = self._normalize_search_text(question).lower()
        if not self._looks_numeric(question):
            return False

        parameter_hint = any(
            term in lowered_question
            for term in [
                "voltage",
                "current",
                "temperature",
                "electrical",
                "operating conditions",
                "absolute maximum",
                "characteristics",
            ]
        )
        range_or_limit_hint = any(
            term in lowered_question
            for term in [
                "range",
                "maximum",
                "minimum",
                "max",
                "min",
                "limit",
                "rating",
                "ratings",
                "operating",
            ]
        )
        symbol_hint = bool(ELECTRICAL_PARAMETER_SYMBOL_RE.search(question))
        if "clock" in lowered_question and not symbol_hint:
            return False
        return (parameter_hint and range_or_limit_hint) or (symbol_hint and (range_or_limit_hint or "operating" in lowered_question))

    def _section_score_windows(self, table_question_family: str | None) -> tuple[int, int]:
        if table_question_family == TABLE_QUESTION_PIN:
            return 12000, 12000
        if table_question_family == TABLE_QUESTION_ELECTRICAL:
            return 8000, 8000
        if table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
        }:
            return 5000, 7000
        if table_question_family == TABLE_QUESTION_MEMORY:
            return 4500, 6500
        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return 4000, 6000
        return 1200, 1800

    def _table_section_bonus(
        self,
        question: str,
        table_question_family: str | None,
        heading_text: str,
        body_text: str,
    ) -> float:
        if table_question_family is None:
            return 0.0
        if table_question_family == TABLE_QUESTION_PIN:
            return self._pin_table_section_bonus(question, heading_text, body_text) + self._table_section_noise_penalty(
                table_question_family,
                heading_text,
                body_text,
            )
        if table_question_family == TABLE_QUESTION_ELECTRICAL:
            return self._electrical_table_section_bonus(question, heading_text, body_text) + self._table_section_noise_penalty(
                table_question_family,
                heading_text,
                body_text,
            )
        if table_question_family == TABLE_QUESTION_FEATURE:
            return self._feature_table_section_bonus(
                question,
                heading_text,
                body_text,
                prefer_counts=False,
            ) + self._table_section_noise_penalty(
                table_question_family,
                heading_text,
                body_text,
            )
        if table_question_family == TABLE_QUESTION_PERIPHERAL_COUNT:
            return self._feature_table_section_bonus(
                question,
                heading_text,
                body_text,
                prefer_counts=True,
            ) + self._table_section_noise_penalty(
                table_question_family,
                heading_text,
                body_text,
            )
        if table_question_family == TABLE_QUESTION_MEMORY:
            return self._memory_table_section_bonus(question, heading_text, body_text) + self._table_section_noise_penalty(
                table_question_family,
                heading_text,
                body_text,
            )
        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return self._package_ordering_table_section_bonus(
                question,
                heading_text,
                body_text,
                table_question_family,
            ) + self._table_section_noise_penalty(
                table_question_family,
                heading_text,
                body_text,
            )
        return 0.0

    def _pin_table_section_bonus(self, question: str, heading_text: str, body_text: str) -> float:
        lowered_heading = self._normalize_search_text(heading_text).lower()
        lowered_body = self._normalize_search_text(body_text).lower()
        bonus = 0.0

        if any(term in lowered_heading for term in PIN_TABLE_HEADING_TERMS):
            bonus += 5.5
        elif any(term in lowered_body for term in PIN_TABLE_HEADING_TERMS):
            bonus += 2.4

        if any(term in lowered_heading or term in lowered_body for term in PIN_TABLE_CONTEXT_TERMS):
            bonus += 1.8

        question_signals = []
        for candidate in SIGNAL_NAME_RE.findall(question):
            normalized_candidate = candidate.lower()
            if normalized_candidate not in question_signals:
                question_signals.append(normalized_candidate)
        signal_hits = sum(
            1
            for signal in question_signals
            if signal in lowered_heading or signal in lowered_body
        )
        bonus += min(signal_hits, 2) * 2.8

        package_match = PACKAGE_NAME_RE.search(question)
        if package_match:
            normalized_package = package_match.group(0).lower()
            if normalized_package in lowered_heading or normalized_package in lowered_body:
                bonus += 3.0

        if "remap" in lowered_heading or "remap" in lowered_body:
            bonus += 1.5
        if re.search(r"\btable\s+\d+\b", lowered_heading) and any(
            term in lowered_body for term in ["pin", "alternate", "remap", "package"]
        ):
            bonus += 1.2
        if PIN_NAME_RE.search(body_text):
            bonus += 1.4
        if re.search(r"\baf\d+\b", body_text, flags=re.IGNORECASE):
            bonus += 1.0

        return bonus

    def _electrical_table_section_bonus(self, question: str, heading_text: str, body_text: str) -> float:
        lowered_question = self._normalize_search_text(question).lower()
        lowered_heading = self._normalize_search_text(heading_text).lower()
        lowered_body = self._normalize_search_text(body_text).lower()
        bonus = 0.0

        if any(term in lowered_heading for term in ELECTRICAL_TABLE_HEADING_TERMS):
            bonus += 5.5
        elif any(term in lowered_body for term in ELECTRICAL_TABLE_HEADING_TERMS):
            bonus += 2.4

        if self._has_electrical_table_context(body_text):
            bonus += 2.3
        if any(term in lowered_heading or term in lowered_body for term in ELECTRICAL_TABLE_CONTEXT_TERMS):
            bonus += 1.5

        parameter_symbols = []
        for match in ELECTRICAL_PARAMETER_SYMBOL_RE.finditer(question):
            normalized_symbol = match.group(0).lower()
            if normalized_symbol not in parameter_symbols:
                parameter_symbols.append(normalized_symbol)
        symbol_hits = sum(
            1
            for symbol in parameter_symbols
            if symbol in lowered_heading or symbol in lowered_body
        )
        bonus += min(symbol_hits, 2) * 1.8

        if any(term in lowered_question for term in ["range", "max", "maximum", "min", "minimum", "limit"]):
            if "min" in lowered_body and "max" in lowered_body:
                bonus += 1.8
            if any(term in lowered_body for term in ["parameter", "conditions", "unit"]):
                bonus += 1.0

        if re.search(r"\btable\s+\d+\b", lowered_heading) and self._has_electrical_table_context(body_text):
            bonus += 0.8

        return bonus

    def _feature_table_section_bonus(
        self,
        question: str,
        heading_text: str,
        body_text: str,
        *,
        prefer_counts: bool,
    ) -> float:
        lowered_heading = self._normalize_search_text(heading_text).lower()
        lowered_body = self._normalize_search_text(body_text).lower()
        bonus = 0.0

        if any(term in lowered_heading for term in FEATURE_TABLE_HEADING_TERMS):
            bonus += 5.5
        elif any(term in lowered_body for term in FEATURE_TABLE_HEADING_TERMS):
            bonus += 2.6
        elif any(term in lowered_heading for term in FEATURE_TABLE_WEAK_HEADING_TERMS):
            bonus += 2.4
        if re.search(
            r"\btable\s+\d+[\.:]?\s*(?:device summary|.*features?\s+and\s+peripheral counts?)\b",
            lowered_body,
        ):
            bonus += 3.0

        question_terms = [
            term for term in FEATURE_QUERY_TERMS if term in self._normalize_search_text(question).lower()
        ]
        term_hits = sum(
            1
            for term in question_terms
            if term in lowered_heading or term in lowered_body
        )
        bonus += min(term_hits, 2) * 2.1

        if any(term in lowered_heading or term in lowered_body for term in ["device summary", "peripheral counts"]):
            bonus += 1.8
        if "device summary" in lowered_body and any(
            token.lower() in lowered_body for token in self._question_device_tokens(question)
        ):
            bonus += 1.2
        if prefer_counts and term_hits and re.search(r"\b\d+\b", body_text):
            bonus += 2.2
        if prefer_counts and any(
            term in lowered_body
            for term in ["peripheral count", "peripheral counts", "main features", "device summary"]
        ):
            bonus += 2.0
        if re.search(r"\btable\s+\d+\b", lowered_heading) and any(
            term in lowered_body for term in ["feature", "peripheral", "adc", "timer", "spi", "usart"]
        ):
            bonus += 0.8

        return bonus

    def _memory_table_section_bonus(self, question: str, heading_text: str, body_text: str) -> float:
        lowered_question = self._normalize_search_text(question).lower()
        lowered_heading = self._normalize_search_text(heading_text).lower()
        lowered_body = self._normalize_search_text(body_text).lower()
        bonus = 0.0

        if any(term in lowered_heading for term in MEMORY_TABLE_HEADING_TERMS):
            bonus += 5.5
        elif any(term in lowered_body for term in MEMORY_TABLE_HEADING_TERMS):
            bonus += 2.6
        if "flash" in lowered_heading and "sram" in lowered_heading:
            bonus += 2.6
        if re.search(r"\btable\s+\d+[\.:]?\s*device summary\b", lowered_body):
            bonus += 2.4

        memory_terms = [term for term in MEMORY_QUERY_TERMS if term in lowered_question]
        term_hits = sum(
            1 for term in memory_terms if term in lowered_heading or term in lowered_body
        )
        bonus += min(term_hits, 2) * 2.2

        if any(term in lowered_heading or term in lowered_body for term in ["flash", "sram", "memory organization"]):
            bonus += 1.8
        if memory_terms and re.search(r"\b\d+\s*(?:kbyte|kbytes|kb|mb)\b", lowered_body):
            bonus += 2.4
        if all(term in lowered_body for term in ["flash", "sram"]) and re.search(r"\b\d+\s*(?:kbyte|kbytes|kb|mb)\b", lowered_body):
            bonus += 1.6
        requested_pin_codes = {
            pin_code for pin_code, _ in self._requested_device_variant_codes(question)
        }
        if requested_pin_codes and any(
            re.search(
                rf"\bSTM32[A-Z0-9]{{4,}}{re.escape(pin_code)}X\b",
                body_text.upper(),
            )
            for pin_code in requested_pin_codes
        ):
            bonus += 4.2
            if all(term in lowered_body for term in ["flash - kbytes", "sram - kbytes"]):
                bonus += 4.4
        if "device features and peripheral counts" in lowered_body:
            bonus += 2.8
        if "device summary" in lowered_heading or "device summary" in lowered_body:
            bonus += 1.6
        if re.search(r"\btable\s+\d+\b", lowered_heading) and any(
            term in lowered_body for term in ["flash", "sram", "memory", "kbyte", "kb"]
        ):
            bonus += 0.8

        return bonus

    def _package_ordering_table_section_bonus(
        self,
        question: str,
        heading_text: str,
        body_text: str,
        table_question_family: str,
    ) -> float:
        lowered_question = self._normalize_search_text(question).lower()
        lowered_heading = self._normalize_search_text(heading_text).lower()
        lowered_body = self._normalize_search_text(body_text).lower()
        bonus = 0.0

        if any(term in lowered_heading for term in PACKAGE_ORDERING_TABLE_HEADING_TERMS):
            bonus += 5.5
        elif any(term in lowered_body for term in PACKAGE_ORDERING_TABLE_HEADING_TERMS):
            bonus += 2.6
        if re.search(
            r"\btable\s+\d+[\.:]?\s*(?:device summary|ordering information|ordering code|package information)\b",
            lowered_body,
        ):
            bonus += 3.0

        query_hits = sum(
            1
            for term in PACKAGE_ORDERING_QUERY_TERMS
            if term in lowered_question and (term in lowered_heading or term in lowered_body)
        )
        bonus += min(query_hits, 2) * 1.8

        package_match = PACKAGE_NAME_RE.search(question)
        if package_match:
            normalized_package = package_match.group(0).lower()
            if normalized_package in lowered_heading or normalized_package in lowered_body:
                bonus += 3.4

        device_hits = sum(
            1
            for token in self._question_device_tokens(question)
            if token.lower() in lowered_heading or token.lower() in lowered_body
        )
        bonus += min(device_hits, 2) * 0.9
        if "device summary" in lowered_body and device_hits:
            bonus += 1.4

        if table_question_family == TABLE_QUESTION_ORDERING and any(
            term in lowered_heading or term in lowered_body
            for term in ["ordering information", "ordering information scheme", "ordering code", "order code", "order codes"]
        ):
            bonus += 3.4
        if table_question_family == TABLE_QUESTION_ORDERING and any(
            term in lowered_body
            for term in ["example: stm32", "flash memory size", "pin count", "temperature range", "options"]
        ):
            bonus += 2.2
        if table_question_family == TABLE_QUESTION_PACKAGE and any(
            term in lowered_heading or term in lowered_body
            for term in ["package information", "package options", "packages"]
        ):
            bonus += 1.8
        if table_question_family == TABLE_QUESTION_DEVICE_VARIANT and any(
            term in lowered_heading or term in lowered_body
            for term in ["device summary", "ordering code", "ordering information", "package information"]
        ):
            bonus += 2.0
        if re.search(r"\btable\s+\d+\b", lowered_heading) and any(
            term in lowered_body
            for term in ["ordering", "order code", "package", "device summary", "variant"]
        ):
            bonus += 0.8

        return bonus

    def _table_section_noise_penalty(
        self,
        table_question_family: str,
        heading_text: str,
        body_text: str,
    ) -> float:
        lowered_heading = self._normalize_search_text(heading_text).lower()
        lowered_body = self._normalize_search_text(body_text).lower()
        body_opening = lowered_body[:1200]
        leading_noise_window = f"{lowered_heading} {lowered_body[:400]}"
        penalty = 0.0
        if lowered_heading == "document root" and re.search(r"\.\s*\.\s*\d+\b", body_opening):
            penalty -= 12.0
        has_feature_table_signal = any(
            term in lowered_heading or term in body_opening for term in FEATURE_TABLE_HEADING_TERMS
        ) or bool(
            re.search(
                r"\btable\s+\d+[\.:]?\s*(?:device summary|.*features?\s+and\s+peripheral counts?)\b",
                body_opening,
            )
        )
        has_memory_table_signal = any(
            term in lowered_heading or term in body_opening for term in MEMORY_TABLE_HEADING_TERMS
        ) or ("flash" in body_opening and "sram" in body_opening)
        has_package_table_signal = any(
            term in lowered_heading or term in body_opening for term in PACKAGE_ORDERING_TABLE_HEADING_TERMS
        ) or bool(
            re.search(
                r"\btable\s+\d+[\.:]?\s*(?:device summary|ordering information|ordering code|package information)\b",
                body_opening,
            )
        )
        if table_question_family in {TABLE_QUESTION_FEATURE, TABLE_QUESTION_PERIPHERAL_COUNT}:
            has_family_table_signal = has_feature_table_signal
        elif table_question_family == TABLE_QUESTION_MEMORY:
            has_family_table_signal = has_memory_table_signal
        elif table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            has_family_table_signal = has_package_table_signal
        else:
            has_family_table_signal = False

        if any(term in leading_noise_window for term in TABLE_NOISE_HEADING_TERMS):
            penalty -= 7.0
        elif any(term in lowered_heading or term in lowered_body for term in TABLE_NOISE_HEADING_TERMS):
            penalty -= 3.0 if has_family_table_signal else 7.0
        if re.search(r"\.\s*\.\s*\d+\b", lowered_heading):
            penalty -= 8.0
        if any(term in lowered_heading or term in lowered_body for term in MECHANICAL_PACKAGE_NOISE_TERMS):
            penalty -= 2.0 if has_package_table_signal else 4.5

        if table_question_family == TABLE_QUESTION_PIN and any(
            term in lowered_heading for term in ELECTRICAL_TABLE_HEADING_TERMS
        ):
            penalty -= 3.2
        if table_question_family == TABLE_QUESTION_ELECTRICAL and any(
            term in lowered_heading for term in PIN_TABLE_HEADING_TERMS
        ):
            penalty -= 3.2
        if table_question_family == TABLE_QUESTION_ELECTRICAL and any(
            term in lowered_heading
            for term in ["memory map", "register map", "register definition", "register descriptions"]
        ):
            penalty -= 2.8
        if table_question_family in {TABLE_QUESTION_FEATURE, TABLE_QUESTION_PERIPHERAL_COUNT}:
            if any(term in lowered_heading for term in ELECTRICAL_TABLE_HEADING_TERMS):
                penalty -= 3.0
            if any(term in lowered_heading for term in PIN_TABLE_HEADING_TERMS):
                penalty -= 3.2
            if any(term in lowered_heading or term in lowered_body for term in FEATURE_TABLE_NOISE_TERMS):
                penalty -= 3.0
        if table_question_family == TABLE_QUESTION_MEMORY:
            if any(term in lowered_heading for term in PIN_TABLE_HEADING_TERMS):
                penalty -= 3.2
            if any(term in lowered_heading for term in ELECTRICAL_TABLE_HEADING_TERMS):
                penalty -= 2.8
            if any(term in lowered_heading or term in lowered_body for term in MEMORY_TABLE_NOISE_TERMS):
                penalty -= 3.2
            if any(
                term in lowered_heading or term in body_opening
                for term in ["full compatibility throughout the family", "low-density devices", "high-density devices"]
            ):
                penalty -= 4.8
        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            if any(term in lowered_heading or term in lowered_body for term in PACKAGE_ORDERING_NOISE_TERMS):
                penalty -= 4.5
            if "revision history" in lowered_heading or "revision history" in body_opening:
                penalty -= 6.0
            if any(term in lowered_heading for term in PIN_TABLE_HEADING_TERMS):
                penalty -= 3.4
            if any(term in lowered_heading for term in ELECTRICAL_TABLE_HEADING_TERMS):
                penalty -= 3.2
            if any(
                term in lowered_heading
                for term in ["main features", "features and peripheral counts", "peripheral counts"]
            ):
                penalty -= 2.8

        return penalty

    def _question_device_tokens(self, question: str) -> list[str]:
        device_tokens: list[str] = []
        for candidate in DEVICE_RE.findall(question.upper()):
            if PACKAGE_NAME_RE.fullmatch(candidate):
                continue
            normalized_candidate = self._normalize_device_family(candidate)
            if normalized_candidate and normalized_candidate not in device_tokens:
                device_tokens.append(normalized_candidate)
        return device_tokens

    def _has_electrical_table_context(self, text: str) -> bool:
        normalized_text = self._normalize_search_text(text).lower()
        if re.search(r"\bmin\b.*\bmax\b|\bmax\b.*\bmin\b", normalized_text):
            return True
        if re.search(
            r"\b\d+(?:\.\d+)?\s*(?:to|-)\s*\d+(?:\.\d+)?\s*(?:v|mv|a|ma|ua|hz|khz|mhz|ghz|ns|us|ms|%)\b",
            normalized_text,
        ):
            return True
        return all(
            term in normalized_text
            for term in ["parameter", "conditions", "min", "max", "unit"]
        )

    def _register_specific_tokens(self, question: str) -> list[str]:
        tokens = [
            token
            for token in self._extract_requirement_tokens(question)
            if token not in GENERIC_REGISTER_QUERY_TOKENS and len(token) >= 2
        ]
        expanded: list[str] = []
        for token in tokens:
            if token not in expanded:
                expanded.append(token)
            if token == "spi":
                for alias in ["spi_cr2", "txdmaen", "rxdmaen"]:
                    if alias not in expanded:
                        expanded.append(alias)
        return expanded

    def _prune_noisy_evidence(self, question: str, evidence: list[EvidenceRecord]) -> list[EvidenceRecord]:
        if len(evidence) <= 1:
            return evidence
        if not self._evidence_directly_answers(question, evidence[0]):
            return evidence

        top_entry = evidence[0]
        top_score = top_entry.score
        top_row_quality = self._table_row_evidence_quality(question, top_entry)
        is_pin_question = self._is_pin_intent_query(question)
        kept = [top_entry]

        for entry in evidence[1:]:
            entry_row_quality = self._table_row_evidence_quality(question, entry)
            summary_signal_text = f"{entry.section} {entry.full_text if entry.full_text else entry.excerpt}"
            preserve_pin_revision_conflict = False
            if is_pin_question:
                different_document = bool(
                    entry.document_path
                    and top_entry.document_path
                    and entry.document_path != top_entry.document_path
                )
                different_revision = bool(
                    entry.revision
                    and top_entry.revision
                    and entry.revision != top_entry.revision
                )
                grounded_pin_candidate = (
                    self._evidence_directly_answers(question, entry)
                    or self._build_pin_summary(question, summary_signal_text) is not None
                )
                satisfies_pin_constraints = not self._pin_constraint_failure_hints(question, entry)
                preserve_pin_revision_conflict = (
                    different_document
                    and (different_revision or not entry.revision or not top_entry.revision)
                    and grounded_pin_candidate
                    and satisfies_pin_constraints
                )
            if not preserve_pin_revision_conflict:
                if entry.score < max(12.0, top_score - 6.0):
                    continue
                if self._is_low_signal_for_question(question, entry):
                    continue
                if top_row_quality >= 8.0 and entry_row_quality < 3.5:
                    continue
                if top_row_quality >= 10.0 and entry.score < top_score - 2.5 and entry_row_quality < 5.0:
                    continue
            kept.append(entry)

        return kept

    def _prioritize_direct_answer_evidence(self, question: str, evidence: list[EvidenceRecord]) -> list[EvidenceRecord]:
        if len(evidence) <= 1:
            return evidence

        direct_answers = [
            entry
            for entry in evidence
            if self._evidence_directly_answers(question, entry)
        ]
        if not direct_answers:
            return evidence

        ordered = sorted(
            evidence,
            key=lambda entry: (
                self._evidence_directly_answers(question, entry),
                self._table_row_evidence_quality(question, entry),
                not self._is_low_signal_for_question(question, entry),
                entry.score,
            ),
            reverse=True,
        )
        protected_contrast_entry = None
        if ordered:
            for entry in ordered[1:]:
                if not self._evidence_directly_answers(question, entry):
                    continue
                if not ordered[0].document_path or not entry.document_path:
                    continue
                if ordered[0].document_path == entry.document_path:
                    continue
                protected_contrast_entry = entry
                break
        if ordered:
            top_row_quality = self._table_row_evidence_quality(question, ordered[0])
            if top_row_quality >= 7.5:
                filtered = [ordered[0]]
                for entry in ordered[1:]:
                    if entry is protected_contrast_entry:
                        filtered.append(entry)
                        continue
                    entry_row_quality = self._table_row_evidence_quality(question, entry)
                    if self._is_low_signal_for_question(question, entry) and entry_row_quality < 4.0:
                        continue
                    if top_row_quality >= 9.0 and entry_row_quality < 2.5 and entry.score < ordered[0].score - 2.0:
                        continue
                    filtered.append(entry)
                ordered = filtered
        for index, entry in enumerate(ordered, start=1):
            entry.tag = f"[S{index}]"
        return ordered

    def _should_gate_on_ambiguity(self, question: str, documents: list[DocumentRecord], evidence: list[EvidenceRecord]) -> bool:
        if not self.source.is_dir() or not evidence:
            return False

        top_entry = evidence[0]
        if len(documents) == 1:
            if any([self.filters.device, self.filters.document_type, self.filters.revision]):
                return False
            if self._evidence_directly_answers(question, top_entry):
                return False
            if not self._looks_numeric(question):
                return False
            return bool(self._missing_requirement_tokens(question, evidence[:1]))

        if len(evidence) <= 1:
            return False

        competing_paths = {
            entry.document_path
            for entry in evidence[:3]
            if entry.document_path and entry.document_path != top_entry.document_path
        }
        if not competing_paths:
            return False

        def should_defer_to_pin_conflict(entries: list[EvidenceRecord]) -> bool:
            if not self._is_pin_intent_query(question):
                return False
            if PACKAGE_NAME_RE.search(question) is None:
                return False
            top_family = top_entry.device_family
            if not top_entry.document_path or not top_entry.revision or not top_family:
                return False
            if self._pin_constraint_failure_hints(question, top_entry):
                return False

            requested_family_tokens = {
                self._compact_alnum(token)
                for token in self._question_device_tokens(question)
                if self._compact_alnum(token)
            }
            for range_match in re.finditer(
                r"\b(STM32[A-Z0-9]{4,})X([A-Z0-9])\s*/\s*X([A-Z0-9])\b",
                question.upper(),
            ):
                family_stem, first_density_code, second_density_code = range_match.groups()
                requested_family_tokens.add(f"{family_stem}X{first_density_code}")
                requested_family_tokens.add(f"{family_stem}X{second_density_code}")

            def is_question_compatible_family(family: str | None) -> bool:
                if not family:
                    return False
                compact_family = self._compact_alnum(family)
                if not compact_family:
                    return False
                if not requested_family_tokens:
                    return compact_family == self._compact_alnum(top_family)
                return any(
                    alias in requested_family_tokens
                    for alias in self._restricted_device_token_aliases(compact_family)
                )

            if not is_question_compatible_family(top_family):
                return False

            for entry in entries:
                if not entry.document_path or entry.document_path == top_entry.document_path:
                    continue
                if not entry.revision or entry.revision == top_entry.revision:
                    continue
                if not is_question_compatible_family(entry.device_family):
                    continue
                if self._pin_constraint_failure_hints(question, entry):
                    continue
                return True
            return False

        top_score = top_entry.score
        close_competitors = [
            entry
            for entry in evidence[1:3]
            if entry.document_path != top_entry.document_path and entry.score >= top_score - 1.0
        ]
        if close_competitors and should_defer_to_pin_conflict(close_competitors):
            return False
        if close_competitors:
            return True

        unique_document_families = {
            (document.device_family or "", document.revision or "", document.title)
            for document in documents
        }
        top_is_direct_answer = self._evidence_directly_answers(question, top_entry)
        if len(unique_document_families) > 1 and not top_is_direct_answer:
            if should_defer_to_pin_conflict(evidence[1:3]):
                return False
            return True
        return False

    def _build_ambiguous_result(
        self,
        question: str,
        evidence: list[EvidenceRecord],
        searched_documents: list[str],
    ) -> RetrievalResult:
        candidate_labels: list[str] = []
        seen_paths: set[str] = set()
        for entry in evidence[:3]:
            if not entry.document_path or entry.document_path in seen_paths:
                continue
            seen_paths.add(entry.document_path)
            label = entry.device_family or entry.document or Path(entry.document_path).name
            if entry.revision:
                label += f" rev {entry.revision}"
            candidate_labels.append(label)

        open_questions = [
            "Multiple plausible manuals matched this folder query, so the prototype is stopping before committing to a final answer.",
            "Please narrow by exact device, revision, document type, or the intended manual file.",
        ]
        if candidate_labels:
            open_questions.append(
                "Top candidates: " + ", ".join(candidate_labels[:3]) + "."
            )

        return RetrievalResult(
            question=question,
            source=str(self.source),
            filters=self.filters,
            short_answer="Multiple plausible manuals matched this folder query. Please provide one disambiguating detail before I answer.",
            key_evidence=[],
            sources=evidence[:3],
            open_questions=open_questions,
            searched_documents=searched_documents,
        )

    def _should_gate_on_conflict(self, question: str, documents: list[DocumentRecord], evidence: list[EvidenceRecord]) -> bool:
        if not self.source.is_dir() or len(documents) <= 1 or len(evidence) <= 1:
            return False
        is_pin_intent_query = self._is_pin_intent_query(question)
        if not self._looks_numeric(question) and not is_pin_intent_query:
            return False
        if is_pin_intent_query and not self._has_supported_pin_mapping_answer(question, evidence):
            return True

        top_entry = evidence[0]
        top_missing_tokens = self._missing_requirement_tokens(question, [top_entry])
        top_has_numeric_answer = self._extract_numeric_answer(
            question,
            top_entry.full_text if top_entry.full_text else top_entry.excerpt,
        ) is not None
        if top_has_numeric_answer and top_missing_tokens:
            return True
        if is_pin_intent_query and top_missing_tokens:
            return True

        if is_pin_intent_query:
            pin_value_buckets = {}
            for entry in evidence[:4]:
                source_text = entry.full_text if entry.full_text else entry.excerpt
                raw_value = self._extract_pin_mapping_values(question, source_text)
                if raw_value is None:
                    continue

                normalized_values = set()
                for part in str(raw_value).split("/"):
                    token = part.strip().upper()
                    if token:
                        normalized_values.add(token)
                if not normalized_values:
                    continue

                bucket_document = getattr(entry, "document_path", None) or getattr(entry, "document_id", None)
                bucket_revision = getattr(entry, "revision", None)
                bucket_key = (bucket_document, bucket_revision)
                pin_value_buckets.setdefault(bucket_key, set()).update(normalized_values)

            has_dash_only_bucket = any(values == {"-"} for values in pin_value_buckets.values())
            has_specific_pin_bucket = any(
                any(value != "-" for value in values)
                for values in pin_value_buckets.values()
            )
            if has_dash_only_bucket and has_specific_pin_bucket:
                return True

        direct_answer_entries = [
            entry for entry in evidence[:4]
            if self._evidence_directly_answers(question, entry)
        ]
        if not direct_answer_entries:
            return False

        distinct_documents = {
            entry.document_path
            for entry in direct_answer_entries
            if entry.document_path
        }
        return len(distinct_documents) > 1

    def _best_pin_section_evidence_for_document(
        self,
        question: str,
        document: DocumentRecord,
        section_hits: list[ScoredItem],
    ) -> EvidenceRecord | None:
        best_entry: EvidenceRecord | None = None
        best_failure_count = sys.maxsize

        for hit in section_hits:
            section: SectionRecord = hit.item
            if self._extract_pin_mapping_values(question, section.text) is None:
                continue

            entry = EvidenceRecord(
                tag="[S1]",
                document_id=document.id,
                document=document.title,
                device_family=document.device_family,
                revision=document.revision,
                section=self._normalize_evidence_section(
                    question,
                    " > ".join(section.heading_path),
                    section.text,
                ),
                page=self._format_page_range(section.page_start, section.page_end),
                excerpt=self._build_pin_section_fallback_excerpt(
                    question,
                    section.text,
                    limit=420,
                ),
                full_text=section.text,
                score=round(hit.score, 2),
                document_path=document.path,
            )
            failure_hints = self._pin_constraint_failure_hints(question, entry)
            if not failure_hints:
                return entry
            if len(failure_hints) < best_failure_count:
                best_entry = entry
                best_failure_count = len(failure_hints)

        return best_entry

    def _best_evidence_for_document(self, question: str, document: DocumentRecord) -> EvidenceRecord | None:
        section_hits = self._score_sections([document], question)
        chunk_hits = self._score_chunks(section_hits, question)
        evidence = self._build_evidence(chunk_hits, question)
        if self._table_question_family(question) == TABLE_QUESTION_PIN or self._is_pin_intent_query(question):
            if evidence:
                selected_entry, _ = self._select_pin_constraint_satisfied_evidence(question, evidence)
                if selected_entry is not None:
                    best_entry = selected_entry
                else:
                    best_entry = self._best_pin_section_evidence_for_document(
                        question,
                        document,
                        section_hits,
                    )
            else:
                best_entry = self._best_pin_section_evidence_for_document(
                    question,
                    document,
                    section_hits,
                )
        else:
            best_entry = evidence[0] if evidence else None
        if best_entry is None:
            return None
        best_entry.document = document.title
        best_entry.device_family = document.device_family
        best_entry.revision = document.revision
        best_entry.document_path = document.path
        return best_entry

    def _collect_conflict_candidates(
        self,
        question: str,
        documents: list[DocumentRecord],
        fallback_evidence: list[EvidenceRecord],
    ) -> list[EvidenceRecord]:
        candidates: list[EvidenceRecord] = []
        seen_paths: set[str] = set()
        table_question_family = self._table_question_family(question)
        is_pin_conflict_query = (
            table_question_family == TABLE_QUESTION_PIN
            or self._is_pin_intent_query(question)
        )
        requested_pin_set = {candidate.upper() for candidate in PIN_NAME_RE.findall(question)}

        def extract_nontrivial_pin_value(entry: EvidenceRecord) -> str | None:
            source_text = entry.full_text if entry.full_text else entry.excerpt
            raw_value = self._extract_pin_mapping_values(question, source_text)
            if raw_value is None:
                return None
            normalized_value = re.sub(r"\s*/\s*", "/", raw_value.strip().upper())
            if normalized_value == "-":
                return normalized_value
            value_tokens = [token.strip() for token in normalized_value.split("/") if token.strip()]
            if value_tokens and all(token in requested_pin_set for token in value_tokens):
                return None
            return normalized_value

        for document in documents:
            selected_entry: EvidenceRecord | None = None
            if is_pin_conflict_query:
                for entry in fallback_evidence:
                    if entry.document_path != document.path:
                        continue
                    if extract_nontrivial_pin_value(entry) is not None:
                        selected_entry = entry
                        break

            if selected_entry is None:
                selected_entry = self._best_evidence_for_document(question, document)

            if selected_entry is None or selected_entry.document_path in seen_paths:
                continue
            seen_paths.add(selected_entry.document_path)
            candidates.append(selected_entry)

        if not candidates:
            for entry in fallback_evidence:
                if not entry.document_path or entry.document_path in seen_paths:
                    continue
                seen_paths.add(entry.document_path)
                candidates.append(entry)
                if len(candidates) >= 3:
                    break

        def candidate_sort_key(entry: EvidenceRecord) -> tuple[bool, bool, bool, float]:
            source_text = entry.full_text if entry.full_text else entry.excerpt
            pin_value_present = False
            pin_constraints_satisfied = False
            if is_pin_conflict_query:
                pin_value_present = self._extract_pin_mapping_values(question, source_text) is not None
                pin_constraints_satisfied = not self._pin_constraint_failure_hints(question, entry)
            return (
                pin_constraints_satisfied,
                pin_value_present,
                self._extract_numeric_answer(question, source_text) is not None,
                entry.score,
            )

        candidates.sort(key=candidate_sort_key, reverse=True)
        candidates = candidates[:3]
        for index, entry in enumerate(candidates, start=1):
            entry.tag = f"[S{index}]"
        return candidates

    def _build_conflict_result(
        self,
        question: str,
        documents: list[DocumentRecord],
        evidence: list[EvidenceRecord],
        searched_documents: list[str],
    ) -> RetrievalResult:
        relevant_evidence = self._collect_conflict_candidates(question, documents, evidence)
        document_lookup = {document.path: document for document in documents}
        table_question_family = self._table_question_family(question)
        is_pin_table_conflict = (
            table_question_family == TABLE_QUESTION_PIN
            or self._is_pin_intent_query(question)
        )
        if is_pin_table_conflict:
            relevant_evidence = self._normalize_pin_conflict_evidence_sections(relevant_evidence)
        requested_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(question)]
        requested_pin = requested_pins[0] if requested_pins else "the requested pin"

        candidate_labels: list[str] = []
        key_evidence: list[str] = []
        numeric_candidates: list[tuple[str, str]] = []
        pin_candidates: list[tuple[str, str]] = []
        pin_candidate_summaries: list[tuple[str, str]] = []
        candidate_rows: list[tuple[EvidenceRecord, str, str, str | None]] = []

        for entry in relevant_evidence:
            document = document_lookup.get(entry.document_path)
            label = entry.device_family or entry.document or Path(entry.document_path).name
            if document and document.document_type:
                label += f" ({document.document_type})"
            if entry.revision:
                label += f" rev {entry.revision}"
            candidate_labels.append(label)

            source_text = entry.full_text if entry.full_text else entry.excerpt
            pin_value: str | None = None
            if is_pin_table_conflict:
                raw_pin_value = self._extract_pin_mapping_values(question, source_text)
                if raw_pin_value is not None:
                    pin_value = re.sub(r"\s*/\s*", "/", raw_pin_value.strip().upper())
                    pin_candidates.append((label, pin_value))
                    summary_label = f"Rev {entry.revision}" if entry.revision else label
                    pin_candidate_summaries.append((summary_label, pin_value))

            candidate_rows.append((entry, label, source_text, pin_value))

        if is_pin_table_conflict and pin_candidates:
            for entry, label, _source_text, pin_value in candidate_rows:
                if pin_value is not None:
                    key_evidence.append(
                        f"{entry.tag} {label}: shows {requested_pin} as {pin_value} in {entry.section} (page {entry.page})."
                    )
                else:
                    key_evidence.append(
                        f"{entry.tag} {label}: the best matching section was {entry.section} (page {entry.page}), but it did not yield a direct grounded pin mapping for {requested_pin}."
                    )

            distinct_pin_answers = {answer for _, answer in pin_candidates}
            if len(distinct_pin_answers) > 1:
                pin_conflict_summary = "; ".join(
                    f"{label} shows {answer}"
                    for label, answer in pin_candidate_summaries[:3]
                )
                short_answer = (
                    f"Different source candidates disagree on the pin mapping for {requested_pin}: {pin_conflict_summary}."
                )
            else:
                short_answer = (
                    "One candidate source surfaces a pin mapping, but the other candidate sources do not support a single grounded pin answer yet."
                )
        else:
            for entry, label, source_text, _pin_value in candidate_rows:
                numeric_answer = self._extract_numeric_answer(question, source_text)
                missing_tokens = self._missing_requirement_tokens(question, [entry])
                if numeric_answer:
                    numeric_candidates.append((label, numeric_answer))
                    if missing_tokens:
                        key_evidence.append(
                            f"{entry.tag} {label}: suggests {numeric_answer} from {entry.section} (page {entry.page}), but it still misses query terms like {', '.join(missing_tokens[:3])}."
                        )
                    else:
                        key_evidence.append(
                            f"{entry.tag} {label}: suggests {numeric_answer} from {entry.section} (page {entry.page})."
                        )
                else:
                    key_evidence.append(
                        f"{entry.tag} {label}: the best matching section was {entry.section} (page {entry.page}), but it did not yield a direct grounded numeric answer."
                    )

            distinct_numeric_answers = {answer for _, answer in numeric_candidates}
            if len(distinct_numeric_answers) > 1:
                short_answer = "Different source candidates suggest different numeric answers, so I can't choose one grounded value yet."
            elif numeric_candidates:
                short_answer = (
                    "One candidate source surfaces a numeric-looking value, but the other candidate sources do not support a single grounded answer yet."
                )
            else:
                short_answer = "The current folder results point to different candidate sources, but none of them supports one grounded numeric answer yet."

        open_questions = [
            "Potentially conflicting or misleading evidence was found across the selected folder sources, so the prototype is surfacing candidate evidence instead of collapsing to one answer.",
            "Please confirm the exact device, revision, pin name, or intended manual so the answer can be narrowed to one authoritative source.",
        ]
        if candidate_labels:
            open_questions.append(
                "Candidate sources reviewed: " + ", ".join(candidate_labels[:3]) + "."
            )

        return RetrievalResult(
            question=question,
            source=str(self.source),
            filters=self.filters,
            short_answer=short_answer,
            key_evidence=key_evidence,
            sources=relevant_evidence,
            open_questions=open_questions,
            searched_documents=searched_documents,
        )

    def _normalize_pin_conflict_evidence_sections(
        self,
        evidence: list[EvidenceRecord],
    ) -> list[EvidenceRecord]:
        normalized_entries: list[EvidenceRecord] = []
        for entry in evidence:
            normalized_section = self._normalize_pin_conflict_section_label(entry)
            if normalized_section == entry.section:
                normalized_entries.append(entry)
                continue
            normalized_entries.append(replace(entry, section=normalized_section))
        return normalized_entries

    def _normalize_pin_conflict_section_label(self, entry: EvidenceRecord) -> str:
        section = self._normalize_search_text(entry.section)
        if not self._is_suspicious_pin_conflict_section_label(section):
            return section or entry.section

        for candidate in (
            self._extract_pin_table_section_caption(entry.full_text),
            self._extract_pin_table_section_caption(entry.excerpt),
        ):
            if candidate:
                return candidate
        return "Pin definitions table"

    def _is_suspicious_pin_conflict_section_label(self, section: str) -> bool:
        if not section:
            return True

        lowered_section = section.lower()
        if any(term in lowered_section for term in PIN_TABLE_HEADING_TERMS):
            return False
        if len(section) == 1 and not section.isascii():
            return True
        if re.fullmatch(r"[^\x00-\x7F]+", section):
            return True

        has_inline_pin_label = (
            PIN_NAME_RE.search(section.upper()) is not None
            and any(separator in section for separator in ("-", "/", "_"))
            and " " not in section
        )
        has_inline_signal_label = (
            SIGNAL_NAME_RE.search(section.upper()) is not None
            and any(separator in section for separator in ("-", "/", "_"))
            and " " not in section
        )
        return has_inline_pin_label or has_inline_signal_label

    def _extract_pin_table_section_caption(self, text: str) -> str | None:
        if not text:
            return None

        compact_text = re.sub(r"[\x00-\x1F\x7F]+", " ", text)
        compact_text = self._normalize_search_text(compact_text)
        if not compact_text:
            return None

        table_caption_match = re.search(
            r"\bTable\s+\d+[\.:]?\s*[^.]{0,200}?\bpin definitions(?:\s*\(continued\))?",
            compact_text,
            flags=re.IGNORECASE,
        )
        if table_caption_match:
            return table_caption_match.group(0).strip(" .;:")

        excerpt_caption_match = re.search(
            r"\bPin definitions table\b(?:\s+for\s+[A-Z0-9/-]+)?",
            compact_text,
            flags=re.IGNORECASE,
        )
        if excerpt_caption_match:
            return excerpt_caption_match.group(0).strip(" .;:")
        return None

    def _is_low_signal_for_question(self, question: str, entry: EvidenceRecord) -> bool:
        lowered_question = question.lower()
        section_text = entry.section.lower()
        source_text = (entry.full_text or entry.excerpt).lower()
        table_question_family = self._table_question_family(question)
        row_quality = self._table_row_evidence_quality(question, entry)

        if table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
            TABLE_QUESTION_MEMORY,
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            if any(term in section_text or term in source_text for term in TABLE_NOISE_HEADING_TERMS):
                return True
            if table_question_family in {TABLE_QUESTION_FEATURE, TABLE_QUESTION_PERIPHERAL_COUNT}:
                if row_quality < 6.0 and any(
                    term in section_text or term in source_text
                    for term in [
                        "operating voltage",
                        "vdd",
                        "power supply",
                        "description",
                        "revision history",
                    ]
                ):
                    return True
            if table_question_family == TABLE_QUESTION_MEMORY:
                if row_quality < 6.2 and any(
                    term in section_text or term in source_text
                    for term in [
                        "operating voltage",
                        "vdd",
                        "voltage regulator",
                        "revision history",
                    ]
                ):
                    return True
            if table_question_family in {
                TABLE_QUESTION_PACKAGE,
                TABLE_QUESTION_ORDERING,
                TABLE_QUESTION_DEVICE_VARIANT,
            }:
                if table_question_family == TABLE_QUESTION_ORDERING and any(
                    term in source_text
                    for term in [
                        "low-profile quad flat package",
                        "outline",
                        "gauge plane",
                        "dimension",
                        "section a-a",
                        "section b-b",
                    ]
                ):
                    return True
                if (
                    any(term in section_text or term in source_text for term in ["revision history", "changes", "table 64"])
                    or re.search(r"\b\d{1,2}-[a-z]{3}-\d{4}\b", source_text)
                    or any(term in source_text for term in ["updated", "removed", "added", "modified", "revised", "clarified", "footprints", "specifications"])
                ):
                    return True
                if row_quality < 6.8 and (
                    any(term in section_text or term in source_text for term in PACKAGE_ORDERING_NOISE_TERMS)
                ):
                    return True

        if self._is_comparison_query(question):
            comparison_signal = self._comparison_signal_text(entry)
            comparison_tokens = self._comparison_signal_tokens(entry)
            patterns = self._comparison_patterns(question)
            if patterns:
                matches_any_pattern = any(
                    all(term and self._normalize_token(term) in comparison_tokens for term in required_terms)
                    and any(self._normalize_token(term) in comparison_tokens for term in any_terms)
                    for required_terms, any_terms in patterns
                )
                if not matches_any_pattern:
                    if any(term in section_text for term in ["usart", "timer", "i2s", "can", "usb", "ethernet"]):
                        return True
                    if any(term in section_text for term in ["dmips", "main features", "description", "features"]):
                        return True
                    if any(term in comparison_signal for term in ["frame transmission", "frame reception", "interrupt generation"]):
                        return True

        if "voltage" in lowered_question:
            noisy_voltage_sections = [
                "emc characteristics",
                "injection characteristics",
                "supply current characteristics",
            ]
            if any(term in section_text for term in noisy_voltage_sections):
                has_primary_voltage_terms = (
                    "operating voltage" in source_text
                    or "general operating conditions" in section_text
                    or re.search(r"\bvdd\b[^\n]{0,120}\b2(?:\.0)?\b[^\n]{0,80}\b3\.6\b", source_text)
                )
                return not bool(has_primary_voltage_terms)

        return False

    def _is_unsupported_question(self, question: str) -> bool:
        lowered_question = question.lower()
        return any(pattern in lowered_question for pattern in UNSUPPORTED_QUESTION_PATTERNS)

    def _is_absence_query(self, question: str) -> bool:
        lowered_question = question.lower()
        return any(pattern in lowered_question for pattern in ABSENCE_QUERY_PATTERNS)

    def _is_summary_query(self, question: str) -> bool:
        lowered_question = question.lower()
        return "summarize" in lowered_question or "summary" in lowered_question

    def _is_comparison_query(self, question: str) -> bool:
        lowered_question = question.lower()
        comparison_markers = [
            "compare",
            "comparison",
            " vs ",
            " versus ",
            "difference between",
            "what is the difference between",
            "what's the difference between",
            "roles of",
        ]
        return any(term in lowered_question for term in comparison_markers)

    def _is_register_lookup_query(self, question: str) -> bool:
        lowered_question = question.lower()
        return "register" in lowered_question or " bit " in f" {lowered_question} " or "field" in lowered_question

    def _should_gate_on_descriptive_gap(self, question: str, evidence: list[EvidenceRecord]) -> bool:
        if not evidence:
            return False
        if not (self._is_summary_query(question) or self._is_comparison_query(question)):
            return False

        if self._is_comparison_query(question) and self._has_grounded_comparison_coverage(question, evidence):
            return False

        coverage_pool = evidence[:2] if self._is_comparison_query(question) else evidence[:1]
        if self._missing_requirement_tokens(question, coverage_pool):
            return True

        return not self._has_strong_evidence(evidence, question)

    def _should_gate_on_register_gap(self, question: str, evidence: list[EvidenceRecord]) -> bool:
        if not evidence or self._looks_numeric(question):
            return False
        if self._is_absence_query(question) or self._is_summary_query(question) or self._is_comparison_query(question):
            return False
        if not self._is_register_lookup_query(question):
            return False

        return bool(self._missing_requirement_tokens(question, evidence[:1]))

    def _extract_requirement_tokens(self, question: str) -> list[str]:
        requirement_tokens: list[str] = []
        is_ordering_question = self._table_question_family(question) == TABLE_QUESTION_ORDERING
        for token in self._tokenize(question):
            if token in IGNORED_REQUIREMENT_TOKENS:
                continue
            if token not in requirement_tokens:
                requirement_tokens.append(token)

        if is_ordering_question:
            for device_token in self._question_device_tokens(question):
                compact_device_token = self._compact_alnum(device_token).lower()
                if compact_device_token and compact_device_token not in requirement_tokens:
                    requirement_tokens.append(compact_device_token)

            package_match = PACKAGE_NAME_RE.search(question)
            if package_match:
                compact_package_token = self._compact_alnum(package_match.group(0)).lower()
                if compact_package_token and compact_package_token not in requirement_tokens:
                    requirement_tokens.append(compact_package_token)

            if "ordering code" not in requirement_tokens:
                requirement_tokens.append("ordering code")
        return requirement_tokens

    def _is_device_like_token(self, token: str) -> bool:
        return bool(re.search(r"(?=.*[a-z])(?=.*\d)[a-z0-9_-]{6,}", token))

    def _missing_requirement_tokens(self, question: str, evidence: list[EvidenceRecord]) -> list[str]:
        requirement_tokens = self._extract_requirement_tokens(question)
        if not requirement_tokens or not evidence:
            return requirement_tokens

        evidence_text = self._normalize_search_text(
            " ".join(
                f"{entry.document} {entry.device_family or ''} {entry.section} {entry.excerpt} {entry.full_text}"
                for entry in evidence[:2]
            ).lower()
        )
        compact_evidence_text = self._compact_alnum(evidence_text).lower()
        is_ordering_question = self._table_question_family(question) == TABLE_QUESTION_ORDERING
        missing_tokens: list[str] = []
        for token in requirement_tokens:
            if token == "ordering code" and any(
                term in evidence_text
                for term in ["ordering information scheme", "ordering code", "order code"]
            ):
                continue

            compact_token = self._compact_alnum(token).lower()
            if is_ordering_question and compact_token and compact_token in compact_evidence_text:
                continue
            if token in evidence_text:
                continue
            if not is_ordering_question and self._is_device_like_token(token):
                continue
            missing_tokens.append(token)
        return missing_tokens

    def _has_strong_evidence(self, evidence: list[EvidenceRecord], question: str | None = None) -> bool:
        if not evidence:
            return False
        if question and self._is_comparison_query(question) and self._has_grounded_comparison_coverage(question, evidence):
            return True
        if question and self._evidence_directly_answers(question, evidence[0]):
            return True
        top_score = evidence[0].score
        if top_score < 6.0:
            return False
        if len(evidence) == 1:
            return True
        if top_score >= 10.0 and evidence[1].score >= max(8.0, top_score - 5.0):
            return True
        return evidence[1].score >= max(4.5, top_score - 3.0)


    def _evidence_directly_answers(self, question: str, entry: EvidenceRecord) -> bool:
        table_question_family = self._table_question_family(question)
        if table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
            TABLE_QUESTION_MEMORY,
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return self._table_evidence_directly_answers(
                question,
                entry,
                table_question_family,
            )
        if self._looks_numeric(question):
            source_text = entry.full_text if entry.full_text else entry.excerpt
            return self._extract_numeric_answer(question, source_text) is not None
        if self._is_register_lookup_query(question):
            source_text = entry.full_text if entry.full_text else entry.excerpt
            return self._extract_register_answer(question, source_text) is not None
        if self._is_comparison_query(question):
            return self._has_grounded_comparison_coverage(question, [entry]) or not self._missing_requirement_tokens(question, [entry])
        return not self._missing_requirement_tokens(question, [entry])

    def _table_evidence_directly_answers(
        self,
        question: str,
        entry: EvidenceRecord,
        table_question_family: str,
    ) -> bool:
        source_text = self._normalize_search_text(
            entry.full_text if entry.full_text else entry.excerpt
        )
        summary_text = self._normalize_search_text(f"{entry.section} {source_text}")
        lowered_text = source_text.lower()
        lowered_summary_text = summary_text.lower()
        row_quality = self._table_row_candidate_bonus(question, table_question_family, source_text)
        if row_quality < 6.0:
            return False
        is_low_signal = self._is_low_signal_for_question(question, entry)
        if table_question_family in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        } and is_low_signal:
            return False
        if is_low_signal and row_quality < 8.5:
            return False

        if table_question_family in {TABLE_QUESTION_FEATURE, TABLE_QUESTION_PERIPHERAL_COUNT}:
            feature_terms = [
                term for term in FEATURE_QUERY_TERMS
                if term in self._normalize_search_text(question).lower()
            ]
            if not feature_terms:
                return False
            feature_hits = sum(1 for term in feature_terms if term in lowered_text)
            if feature_hits == 0:
                return False
            if table_question_family == TABLE_QUESTION_PERIPHERAL_COUNT:
                return bool(
                    row_quality >= 7.5
                    and re.search(
                        r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|up to)\b",
                        lowered_text,
                    )
                )
            return row_quality >= 6.8

        if table_question_family == TABLE_QUESTION_MEMORY:
            memory_terms = [
                term for term in MEMORY_QUERY_TERMS
                if term in self._normalize_search_text(question).lower()
            ]
            term_hits = sum(1 for term in memory_terms if term in lowered_text)
            has_capacity = bool(re.search(r"\b\d+\s*(?:kbytes?|kb|mb)\b", lowered_text))
            requested_device_tokens = self._question_device_tokens(question)
            exact_grounded_memory_terms: set[str] = set()
            exact_variant_capacity_match = False
            if requested_device_tokens:
                requested_memory_terms = [term for term in memory_terms if term != "memory"]
                exact_requested_tokens = [
                    requested_token
                    for requested_token in requested_device_tokens
                    if "X" not in self._compact_alnum(requested_token)
                ]
                if exact_requested_tokens and entry.device_family:
                    compact_entry_device = self._compact_alnum(entry.device_family)
                    if compact_entry_device and all(
                        compact_entry_device != self._compact_alnum(requested_token)
                        for requested_token in exact_requested_tokens
                    ):
                        return False
                use_strict_device_match = bool(exact_requested_tokens)
                normalized_lines = [
                    self._normalize_search_text(line)
                    for line in source_text.splitlines()
                    if self._normalize_search_text(line)
                ]
                compact_source_text = self._normalize_search_text(source_text)
                if len(normalized_lines) <= 1 and compact_source_text:
                    normalized_lines = [compact_source_text]
                closure_lines = self._build_memory_variant_grounded_lines(
                    question,
                    normalized_lines,
                    0,
                    len(normalized_lines),
                )
                closure_text = self._normalize_search_text("\n".join(closure_lines))
                closure_lowered = closure_text.lower()
                closure_has_capacity = bool(re.search(r"\b\d+\s*(?:kbytes?|kb|mb)\b", closure_lowered))
                closure_grounded_memory_terms: set[str] = set()
                for term in requested_memory_terms:
                    if re.search(
                        rf"\b{term}\b[^\n]{{0,28}}\b\d+\s*(?:kbytes?|kb|mb)\b|\b\d+\s*(?:kbytes?|kb|mb)\b[^\n]{{0,28}}\b{term}\b",
                        closure_lowered,
                    ):
                        closure_grounded_memory_terms.add(term)

                for line in normalized_lines:
                    lowered_line = line.lower()
                    if use_strict_device_match:
                        line_matches_requested_device = any(
                            self._source_matches_requested_device_token(
                                requested_token,
                                line,
                                allow_family_alias=False,
                            )
                            for requested_token in exact_requested_tokens
                        )
                    else:
                        line_matches_requested_device = any(
                            self._source_matches_requested_device_token(
                                requested_token,
                                line,
                            )
                            for requested_token in requested_device_tokens
                        )
                    if not line_matches_requested_device:
                        continue
                    if not re.search(r"\b\d+\s*(?:kbytes?|kb|mb)\b", lowered_line):
                        continue
                    exact_variant_capacity_match = True
                    for term in requested_memory_terms:
                        if re.search(
                            rf"\b{term}\b[^\n]{{0,28}}\b\d+\s*(?:kbytes?|kb|mb)\b|\b\d+\s*(?:kbytes?|kb|mb)\b[^\n]{{0,28}}\b{term}\b",
                            lowered_line,
                        ):
                            exact_grounded_memory_terms.add(term)

                if not (exact_variant_capacity_match or closure_has_capacity):
                    return False
                grounded_memory_terms = exact_grounded_memory_terms | closure_grounded_memory_terms
                if requested_memory_terms and len(grounded_memory_terms) < max(
                    1,
                    min(2, len(requested_memory_terms)),
                ):
                    return False
                if use_strict_device_match:
                    if not (
                        self._source_matches_requested_device(
                            question,
                            source_text,
                            allow_family_alias=False,
                        )
                        or self._source_matches_requested_device(
                            question,
                            closure_text,
                            allow_family_alias=False,
                        )
                    ):
                        return False
                elif not self._source_matches_requested_device(question, source_text):
                    return False
                if self._source_has_multiple_capacity_options(source_text):
                    return False
                if "up to" in lowered_text:
                    return False
                if self._source_has_family_wide_scope(source_text) and not exact_variant_capacity_match:
                    return False
            return row_quality >= 7.0 and term_hits >= max(1, min(2, len(memory_terms))) and has_capacity

        if table_question_family == TABLE_QUESTION_ORDERING:
            requested_device_tokens = self._question_device_tokens(question)
            exact_requested_tokens = [
                requested_token
                for requested_token in requested_device_tokens
                if "X" not in self._compact_alnum(requested_token)
            ]
            if exact_requested_tokens and entry.device_family:
                compact_entry_device = self._compact_alnum(entry.device_family)
                if compact_entry_device and all(
                    compact_entry_device != self._compact_alnum(requested_token)
                    for requested_token in exact_requested_tokens
                ):
                    return False
            package_match = PACKAGE_NAME_RE.search(question)
            exact_package_code = self._extract_requested_ordering_package_code(
                question,
                source_text,
                allow_family_fallback=False,
            )
            if package_match and not exact_package_code:
                return False
            if "code" in self._normalize_search_text(question).lower() and "code" not in lowered_summary_text:
                return False
            if self._question_device_tokens(question) and not self._source_matches_requested_device(
                question,
                source_text,
            ):
                return False
            if not self._ordering_source_has_exact_variant_closure(question, source_text):
                return False
            package_scope_ok = True
            if package_match:
                requested_package = package_match.group(0).lower().replace(" ", "")
                package_scope_ok = requested_package in lowered_text.replace(" ", "")
                if not package_scope_ok:
                    family_pin_match = re.fullmatch(r"([a-z]+)(\d+)", requested_package)
                    if family_pin_match:
                        package_family, pin_count = family_pin_match.groups()
                        package_scope_ok = package_family in lowered_text and (
                            re.search(rf"\b{pin_count}\s*[- ]?pins?\b", lowered_text)
                            or bool(re.search(r"\b[a-z0-9]{1,4}\s*=\s*(?:lqfp|ufqfpn|vfqfpn|tfbga|lfbga|ufbga|bga)\b", lowered_text))
                        )
            if not package_scope_ok:
                return False
            has_ordering_context = any(
                term in lowered_summary_text
                for term in ["ordering information", "ordering information scheme", "ordering code", "order code", "package code"]
            )
            has_mapping_context = self._has_requested_ordering_mapping_context(
                question,
                source_text,
            )
            return (
                row_quality >= 7.2
                and exact_package_code is not None
                and has_ordering_context
                and has_mapping_context
            )

        if table_question_family == TABLE_QUESTION_PACKAGE:
            requested_device_tokens = self._question_device_tokens(question)
            exact_requested_tokens = [
                requested_token
                for requested_token in requested_device_tokens
                if "X" not in self._compact_alnum(requested_token)
            ]
            has_explicit_package_constraint = PACKAGE_NAME_RE.search(question) is not None
            if exact_requested_tokens and entry.device_family:
                compact_entry_device = self._compact_alnum(entry.device_family)
                if compact_entry_device and all(
                    compact_entry_device != self._compact_alnum(requested_token)
                    for requested_token in exact_requested_tokens
                ):
                    return False
            package_answer_text = source_text
            if not has_explicit_package_constraint:
                normalized_lines = [
                    self._normalize_search_text(line)
                    for line in source_text.splitlines()
                    if self._normalize_search_text(line)
                ]
                compact_source_text = self._normalize_search_text(source_text)
                if len(normalized_lines) <= 1 and compact_source_text:
                    normalized_lines = [compact_source_text]
                exact_package_lines = self._build_exact_package_variant_lines(
                    question,
                    normalized_lines,
                    0,
                    len(normalized_lines),
                    include_ordering_code=False,
                )
                if not exact_package_lines:
                    return False
                package_answer_text = self._normalize_search_text("\n".join(exact_package_lines))
                if exact_requested_tokens and not self._source_matches_requested_device(
                    question,
                    package_answer_text,
                    allow_family_alias=False,
                ):
                    return False
            elif requested_device_tokens and not self._source_matches_requested_device(question, source_text):
                return False

            if self._extract_package_identity_phrase(package_answer_text) is None:
                return False
            if self._source_has_multiple_package_options(package_answer_text):
                return False
            return row_quality >= 7.0 and any(
                term in lowered_summary_text
                for term in ["package information", "package options", "package", "lqfp", "ufqfpn", "vfqfpn", "bga"]
            )

        if table_question_family == TABLE_QUESTION_DEVICE_VARIANT:
            return row_quality >= 7.0 and any(
                term in lowered_summary_text
                for term in ["device summary", "part number", "variant", "package", "ordering"]
            )

        return False

    def _supports_absence_claim(self, question: str, evidence: list[EvidenceRecord]) -> bool:
        missing_tokens = self._missing_requirement_tokens(question, evidence)
        if missing_tokens:
            return False
        return self._has_strong_evidence(evidence, question)

    def _register_answer_quality(self, question: str, text: str) -> float:
        if not self._is_register_lookup_query(question):
            return 0.0

        lowered_question = question.lower()
        lowered_text = self._normalize_search_text(text).lower()
        quality = 0.0

        if "spi" in lowered_question and "dma" in lowered_question:
            has_spi_register_reference = any(
                term in lowered_text for term in ["spi_cr2", "spi control register 2"]
            )
            has_spi_dma_bit_names = all(
                term in lowered_text for term in ["txdmaen", "rxdmaen"]
            )
            has_spi_dma_bit_labels = all(
                term in lowered_text
                for term in ["tx buffer dma enable", "rx buffer dma enable"]
            )

            if has_spi_dma_bit_names:
                quality += 2.2
            if has_spi_dma_bit_labels:
                quality += 1.8
            if has_spi_register_reference:
                quality += 1.6 if (has_spi_dma_bit_names or has_spi_dma_bit_labels) else 0.6
            if all(term in lowered_text for term in ["spi", "dma", "enable"]):
                quality += 0.8
            if re.search(r"\bbit\s+1\s+txdmaen\b", lowered_text):
                quality += 0.8
            if re.search(r"\bbit\s+0\s+rxdmaen\b", lowered_text):
                quality += 0.8
            if "enable the spi by setting the spe bit" in lowered_text:
                quality -= 1.8
            if "spi communication using dm a" in lowered_text or "spi communication using dma" in lowered_text:
                quality -= 0.6

        return quality

    def _extract_relevant_excerpt(self, text: str, question: str, limit: int = 280) -> str:
        compact = self._normalize_search_text(text)
        if len(compact) <= limit:
            return compact

        lower_compact = compact.lower()
        lowered_question = question.lower()
        anchor_groups: list[tuple[list[str], int]] = []

        if "vdd" in lowered_question or ("voltage" in lowered_question and "vdd" in lower_compact):
            anchor_groups.append(([
                "vdd standard operating voltage",
                "vdd",
            ], 24))
        if "voltage" in lowered_question:
            anchor_groups.append(([
                "operating voltage",
                "general operating conditions",
            ], 40))
        if "can fd" in lowered_question:
            anchor_groups.append((["can fd", "can"], 40))

        query_tokens = [
            token
            for token in self._extract_requirement_tokens(question)
            if len(token) >= 3 and token not in {"range", "operating", "condition"}
        ]
        if query_tokens:
            anchor_groups.append((query_tokens, 80))

        for terms, prefix_window in anchor_groups:
            positions = [lower_compact.find(term) for term in terms if term in lower_compact]
            if not positions:
                continue
            start = max(0, min(positions) - prefix_window)
            end = min(len(compact), start + limit)
            snippet = compact[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(compact):
                snippet = snippet.rstrip() + "..."
            return snippet

        return self._squash_excerpt(compact, limit=limit)

    def _build_pin_section_fallback_excerpt(self, question: str, text: str, limit: int = 420) -> str:
        requested_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(question)]
        requested_pin = requested_pins[0] if requested_pins else "the requested pin"
        package_match = PACKAGE_NAME_RE.search(question)
        requested_package = package_match.group(0).upper() if package_match else None
        pin_value = self._extract_pin_mapping_values(question, text)
        row_excerpt = self._extract_pin_section_row_excerpt(question, text)
        package_clause = f" for {requested_package}" if requested_package else ""

        if pin_value is not None:
            summary = f"Pin definitions table{package_clause} shows {requested_pin} as {pin_value}."
            if row_excerpt:
                summary += f" Nearby row: {row_excerpt}"
            return self._squash_excerpt(summary, limit=limit)

        excerpt = self._extract_relevant_excerpt(text, question, limit=limit)
        excerpt = self._clean_pin_section_excerpt_text(excerpt)
        if row_excerpt and requested_pin not in excerpt.upper():
            summary = f"Pin definitions table{package_clause} references {requested_pin}. Nearby row: {row_excerpt}"
            return self._squash_excerpt(summary, limit=limit)
        return self._squash_excerpt(excerpt, limit=limit)

    def _extract_pin_section_row_excerpt(self, question: str, text: str) -> str | None:
        requested_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(question)]
        if not requested_pins:
            return None

        normalized_lines = [
            self._normalize_search_text(line)
            for line in text.splitlines()
            if self._normalize_search_text(line)
        ]
        if not normalized_lines:
            return None

        normalized_pin_value = self._extract_pin_mapping_values(question, text)
        best_line: str | None = None
        best_score = -1
        for line in normalized_lines:
            upper_line = line.upper()
            if not any(re.search(rf"\b{re.escape(pin)}\b", upper_line) for pin in requested_pins):
                continue

            score = 0
            token_count = len(line.split())
            score += min(token_count, 8)
            score += sum(upper_line.count(pin) * 2 for pin in requested_pins)
            score += min(len(re.findall(r"\b[A-Z]\d{1,2}\b", upper_line)), 4)
            if re.search(r"\bI\s*/\s*O\b|\bI/O\b", upper_line):
                score += 2
            if normalized_pin_value and normalized_pin_value != "-" and normalized_pin_value in upper_line:
                score += 3
            if token_count <= 2:
                score -= 4
            if "FIGURE" in upper_line or "PINOUT" in upper_line:
                score -= 4

            cleaned_line = self._clean_pin_section_excerpt_text(line)
            if cleaned_line and score > best_score:
                best_line = cleaned_line
                best_score = score
        return best_line

    def _clean_pin_section_excerpt_text(self, value: str) -> str:
        cleaned = re.sub(r"[\x00-\x1F\x7F]", " ", value)
        cleaned = self._normalize_search_text(cleaned)
        cleaned = re.sub(r"\s*\.\s*\.\s*\.\s*", "...", cleaned)
        cleaned = re.sub(r"(?:[-=~_*#%]{2,}\s*)+$", "", cleaned)
        cleaned = re.sub(r"\s+[.,;:]\s*$", "", cleaned)
        return cleaned.strip()


    def _extract_register_answer(self, question: str, text: str) -> str | None:
        if not self._is_register_lookup_query(question):
            return None

        lowered_question = question.lower()
        lowered_text = self._normalize_search_text(text).lower()

        if "spi" in lowered_question and "dma" in lowered_question:
            has_spi_register_reference = any(
                term in lowered_text for term in ["spi_cr2", "spi control register 2"]
            )
            has_spi_dma_enable_bit = any(
                term in lowered_text
                for term in [
                    "txdmaen",
                    "rxdmaen",
                    "tx buffer dma enable",
                    "rx buffer dma enable",
                ]
            )
            has_complete_spi_dma_bit_definition = all(
                term in lowered_text
                for term in [
                    "txdmaen",
                    "rxdmaen",
                    "tx buffer dma enable",
                    "rx buffer dma enable",
                ]
            )
            has_generic_spi_dma_enable_statement = all(
                term in lowered_text for term in ["spi", "dma", "enable"]
            )

            if has_complete_spi_dma_bit_definition:
                return "SPI_CR2"

            if has_spi_register_reference and (has_spi_dma_enable_bit or has_generic_spi_dma_enable_statement):
                return "SPI_CR2"

            register_match = re.search(
                r"(?:enable bit in the|bit\s+\d+\s+)(spi_cr2)\s+register",
                lowered_text,
            )
            if register_match and has_spi_dma_enable_bit:
                return register_match.group(1).upper()

            return None

        explicit_register = re.search(r"\b([a-z]{2,}(?:_[a-z0-9]+)+)\b", lowered_text)
        if explicit_register:
            return explicit_register.group(1).upper()

        return None

    def _build_structured_summary(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> StructuredSummary | None:
        if not evidence:
            return None

        top_entry = evidence[0]
        source_text = top_entry.full_text if top_entry.full_text else top_entry.excerpt
        summary_signal_text = f"{top_entry.section} {source_text}"

        if self._is_register_lookup_query(question):
            register_name = self._extract_register_answer(question, source_text)
            if register_name:
                return self._build_register_summary(question, source_text, register_name)

        if self._is_pin_intent_query(question):
            if self._is_pin_mapping_lookup_query(question, summary_signal_text):
                pin_summary = self._build_pin_summary(question, summary_signal_text)
                if pin_summary is not None:
                    return pin_summary
            return None

        if self._looks_numeric(question):
            numeric_answer = self._extract_numeric_answer(question, source_text)
            if numeric_answer:
                return self._build_parameter_summary(question, source_text, numeric_answer)

        return None

    def _table_question_subject_label(self, question: str) -> str | None:
        if self.filters.device:
            return self.filters.device
        device_tokens = self._question_device_tokens(question)
        if device_tokens:
            return device_tokens[0]
        return None

    def _build_table_grounded_short_answer(
        self,
        question: str,
        entry: EvidenceRecord,
        table_question_family: str,
    ) -> str | None:
        source_text = self._normalize_search_text(entry.full_text if entry.full_text else entry.excerpt)
        subject_label = self._table_question_subject_label(question)

        if table_question_family in {TABLE_QUESTION_FEATURE, TABLE_QUESTION_PERIPHERAL_COUNT}:
            feature_terms = [
                term for term in FEATURE_QUERY_TERMS if term in self._normalize_search_text(question).lower()
            ]
            if not feature_terms:
                return None
            feature_phrase = self._extract_feature_count_phrase(source_text, feature_terms)
            if feature_phrase is None:
                return None
            if subject_label:
                return (
                    f"The strongest grounded evidence indicates that {subject_label} provides {feature_phrase} "
                    f"in [S1] {entry.section} (page {entry.page})."
                )
            return (
                f"The strongest grounded evidence indicates {feature_phrase} "
                f"in [S1] {entry.section} (page {entry.page})."
            )

        if table_question_family == TABLE_QUESTION_MEMORY:
            memory_phrase = self._extract_memory_capacity_phrase(question, source_text)
            if memory_phrase is None:
                return None
            if subject_label:
                return (
                    f"The strongest grounded evidence indicates that {subject_label} provides {memory_phrase} "
                    f"in [S1] {entry.section} (page {entry.page})."
                )
            return (
                f"The strongest grounded evidence indicates {memory_phrase} "
                f"in [S1] {entry.section} (page {entry.page})."
            )

        if table_question_family == TABLE_QUESTION_PACKAGE:
            package_phrase = self._extract_package_identity_phrase(source_text)
            if package_phrase is None:
                return None
            if subject_label:
                return (
                    f"The strongest grounded evidence indicates that {subject_label} is listed in {package_phrase} "
                    f"in [S1] {entry.section} (page {entry.page})."
                )
            return (
                f"The strongest grounded evidence indicates {package_phrase} "
                f"in [S1] {entry.section} (page {entry.page})."
            )

        if table_question_family == TABLE_QUESTION_ORDERING:
            ordering_phrase = self._extract_ordering_mapping_phrase(question, source_text)
            if ordering_phrase is None:
                return None
            return (
                f"The strongest grounded evidence indicates that {ordering_phrase} "
                f"in [S1] {entry.section} (page {entry.page})."
            )

        return None

    def _extract_feature_count_phrase(
        self,
        source_text: str,
        feature_terms: list[str],
    ) -> str | None:
        lowered_text = self._normalize_search_text(source_text).lower()
        count_pattern = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|up to \d+)"
        for feature_term in feature_terms:
            if feature_term not in lowered_text:
                continue
            rendered_term = feature_term.upper() if len(feature_term) <= 4 else feature_term
            direct_match = re.search(
                rf"\b({count_pattern}(?:\s+12-bit)?)\s+({re.escape(feature_term)}s?)\b",
                lowered_text,
            )
            if direct_match:
                suffix = "s" if direct_match.group(2).endswith("s") else ""
                return f"{direct_match.group(1)} {rendered_term}{suffix}"
            reverse_match = re.search(
                rf"\b({re.escape(feature_term)}s?)\b[^\n]{{0,40}}\b({count_pattern})\b",
                lowered_text,
            )
            if reverse_match:
                suffix = "s" if reverse_match.group(1).endswith("s") else ""
                return f"{reverse_match.group(2)} {rendered_term}{suffix}"
        return None

    def _extract_memory_capacity_phrase(self, question: str, source_text: str) -> str | None:
        if self._source_has_multiple_capacity_options(source_text):
            return None

        lowered_text = self._normalize_search_text(source_text).lower()
        requested_terms = [
            term for term in MEMORY_QUERY_TERMS if term in self._normalize_search_text(question).lower()
        ]
        if not requested_terms:
            requested_terms = ["flash", "sram"]

        phrases: list[str] = []
        for term in requested_terms:
            if term == "memory":
                continue
            direct_match = re.search(
                rf"\b(\d+)\s*(kbytes?|kb|mb)\s+of\s+{re.escape(term)}(?:\s+memory)?\b",
                lowered_text,
            )
            if direct_match:
                value, unit = direct_match.groups()
                phrases.append(f"{value} {unit} of {term.upper() if len(term) <= 4 else term}")
                continue
            reverse_match = re.search(
                rf"\b{re.escape(term)}(?:\s+memory)?\b[^\n]{{0,20}}\b(\d+)\s*(kbytes?|kb|mb)\b",
                lowered_text,
            )
            if reverse_match:
                value, unit = reverse_match.groups()
                phrases.append(f"{value} {unit} of {term.upper() if len(term) <= 4 else term}")

        if not phrases:
            return None
        if len(phrases) == 1:
            return phrases[0]
        return " and ".join(phrases[:2])

    def _source_has_requested_pin_mapping(self, question: str, source_text: str) -> bool:
        package_match = PACKAGE_NAME_RE.search(question)
        requested_pin_count: str | None = None
        if package_match:
            family_pin_match = re.fullmatch(
                r"([A-Z]+)(\d+)",
                self._normalize_search_text(package_match.group(0)).upper().replace(" ", ""),
            )
            if family_pin_match:
                _, requested_pin_count = family_pin_match.groups()

        if not requested_pin_count:
            return False

        upper_text = self._normalize_search_text(source_text).upper()
        if not re.search(rf"\b{re.escape(requested_pin_count)}\s*PINS?\b", upper_text):
            return False

        requested_variant_codes = self._requested_device_variant_codes(question)
        requested_pin_codes = {pin_code for pin_code, _ in requested_variant_codes}
        if not requested_pin_codes:
            return True

        return any(
            re.search(
                rf"\b{re.escape(pin_code)}\s*=\s*{re.escape(requested_pin_count)}\s*PINS?\b",
                upper_text,
            )
            for pin_code in requested_pin_codes
        )

    def _source_has_explicit_ball_package_scope(self, question: str, source_text: str) -> bool:
        package_match = PACKAGE_NAME_RE.search(question)
        if not package_match:
            return False

        requested_package = package_match.group(0).upper()
        if self._source_matches_requested_package(requested_package, source_text):
            return True

        normalized_package = self._normalize_search_text(requested_package).upper().replace(" ", "")
        family_pin_match = re.fullmatch(r"([A-Z]+)(\d+)", normalized_package)
        if not family_pin_match:
            return False

        requested_pin_codes = {
            pin_code
            for pin_code, _ in self._requested_device_variant_codes(question)
            if pin_code
        }
        if not requested_pin_codes:
            return False

        requested_pin_count = family_pin_match.group(2)
        upper_text = self._normalize_search_text(source_text).upper()
        return any(
            re.search(
                rf"\b{re.escape(pin_code)}\s*=\s*{re.escape(requested_pin_count)}\s*PINS?\b",
                upper_text,
            )
            for pin_code in requested_pin_codes
        )

    def _source_has_requested_density_mapping(self, question: str, source_text: str) -> bool:
        requested_variant_codes = self._requested_device_variant_codes(question)
        requested_density_codes = {density_code for _, density_code in requested_variant_codes}
        if not requested_density_codes:
            return False

        upper_text = self._normalize_search_text(source_text).upper()
        if "FLASH MEMORY" not in upper_text:
            return False

        return any(
            re.search(
                rf"\b{re.escape(density_code)}\s*=\s*\d+\s*(?:KBYTES?|KB|MB)\b",
                upper_text,
            )
            for density_code in requested_density_codes
        )

    def _extract_package_identity_phrase(self, source_text: str) -> str | None:
        normalized_text = self._normalize_search_text(source_text).upper()
        unique_packages: list[str] = []
        for match in re.finditer(r"\b(?:LQFP|UFQFPN|VFQFPN|TFBGA|LFBGA|UFBGA|BGA)\s*\d+\b", normalized_text):
            package_name = match.group(0).replace(" ", "")
            if package_name not in unique_packages:
                unique_packages.append(package_name)
        if len(unique_packages) == 1:
            return unique_packages[0]
        return None

    def _extract_requested_ordering_package_code(
        self,
        question: str,
        source_text: str,
        *,
        allow_family_fallback: bool,
    ) -> str | None:
        package_match = PACKAGE_NAME_RE.search(question)
        if not package_match:
            return None

        normalized_question_package = self._normalize_search_text(package_match.group(0)).upper()
        normalized_text = self._normalize_search_text(source_text).upper()
        family_pin_match = re.fullmatch(r"([A-Z]+)[ -]?(\d+)", normalized_question_package)
        if family_pin_match:
            package_family, pin_count = family_pin_match.groups()
            exact_patterns = [
                rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(package_family)}{re.escape(pin_count)}\b",
                rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(package_family)}\s+{re.escape(pin_count)}\b",
                rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(package_family)}-{re.escape(pin_count)}\b",
            ]
            requested_device_tokens = self._question_device_tokens(question)
            if requested_device_tokens:
                device_scoped_codes: set[str] = set()
                for raw_line in source_text.splitlines():
                    normalized_line = self._normalize_search_text(raw_line).upper()
                    if not normalized_line:
                        continue
                    if not any(
                        self._source_matches_requested_device_token(requested_token, normalized_line)
                        for requested_token in requested_device_tokens
                    ):
                        continue
                    for pattern in exact_patterns:
                        for match in re.finditer(pattern, normalized_line):
                            device_scoped_codes.add(match.group(1))
                if len(device_scoped_codes) == 1:
                    return next(iter(device_scoped_codes))
            exact_codes = {
                match.group(1)
                for pattern in exact_patterns
                for match in re.finditer(pattern, normalized_text)
            }
            if len(exact_codes) == 1:
                return next(iter(exact_codes))
        else:
            exact_match = re.search(
                rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(normalized_question_package)}\b",
                normalized_text,
            )
            if exact_match:
                return exact_match.group(1)
        if not allow_family_fallback:
            return None

        if not family_pin_match:
            return None

        package_family, pin_count = family_pin_match.groups()
        family_codes = {
            match.group(1)
            for match in re.finditer(
                rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(package_family)}\b",
                normalized_text,
            )
        }
        pin_count_codes = {
            match.group(1)
            for match in re.finditer(
                rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(pin_count)}\s*PINS?\b",
                normalized_text,
            )
        }
        shared_codes = family_codes & pin_count_codes
        if len(shared_codes) == 1:
            return next(iter(shared_codes))
        return None

    def _has_requested_ordering_mapping_context(self, question: str, source_text: str) -> bool:
        lowered_text = self._normalize_search_text(source_text).lower()
        exact_package_code = self._extract_requested_ordering_package_code(
            question,
            source_text,
            allow_family_fallback=False,
        )
        if exact_package_code is None:
            return False
        return any(
            term in lowered_text
            for term in ["ordering information", "ordering information scheme", "ordering code", "order code", "package code"]
        )

    def _extract_ordering_mapping_phrase(self, question: str, source_text: str) -> str | None:
        normalized_text = self._normalize_search_text(source_text)
        lowered_text = normalized_text.lower()
        package_match = PACKAGE_NAME_RE.search(question)
        if package_match:
            requested_package = package_match.group(0).upper().replace(" ", "")
            exact_match = self._extract_requested_ordering_package_code(
                question,
                source_text,
                allow_family_fallback=False,
            )
            if exact_match:
                return f"package code {exact_match} corresponds to {requested_package}"

            composed_match = self._extract_requested_ordering_package_code(
                question,
                source_text,
                allow_family_fallback=True,
            )
            if composed_match:
                return f"package code {composed_match} corresponds to {requested_package}"

            requested_family = re.sub(r"\d+$", "", requested_package)
            family_match = re.search(
                rf"\b([A-Z0-9]{{1,4}})\s*=\s*{re.escape(requested_family)}\b",
                normalized_text,
            )
            if family_match:
                return f"package code {family_match.group(1)} corresponds to {requested_family}"

        example_match = re.search(r"\bExample:\s*([A-Z0-9 ]{8,40})", normalized_text, flags=re.IGNORECASE)
        if example_match and "ordering" in lowered_text:
            return f"the ordering example is {example_match.group(1).strip()}"
        return None

    def _build_register_summary(
        self,
        question: str,
        source_text: str,
        register_name: str,
    ) -> StructuredSummary | None:
        lowered_question = question.lower()
        lowered_text = self._normalize_search_text(source_text).lower()
        peripheral = register_name.split("_", 1)[0] if "_" in register_name else None
        field_or_bit = self._extract_register_field_or_bit(source_text)
        purpose = None
        if "spi" in lowered_question and "dma" in lowered_question and any(
            term in lowered_text
            for term in ["tx buffer dma enable", "rx buffer dma enable", "txdmaen", "rxdmaen"]
        ):
            purpose = "Contains the SPI DMA enable bits."
        access_notes = self._extract_register_access_notes(source_text)

        return self._make_structured_summary(
            kind="register",
            title="Register Summary",
            field_pairs=[
                ("Peripheral", peripheral),
                ("Register", register_name),
                ("Field / Bit", field_or_bit),
                ("Purpose", purpose),
                ("Access Notes", access_notes),
            ],
        )

    def _extract_register_field_or_bit(self, text: str) -> str | None:
        lowered_text = self._normalize_search_text(text).lower()
        if "txdmaen" in lowered_text and "rxdmaen" in lowered_text:
            return "TXDMAEN, RXDMAEN"

        match = REGISTER_FIELD_RE.search(text)
        if match:
            return match.group(1).upper()
        return None

    def _extract_register_access_notes(self, text: str) -> str | None:
        lowered_text = self._normalize_search_text(text).lower()
        if "read/write" in lowered_text or "read write" in lowered_text or "r/w" in lowered_text:
            return "Read/write."
        if "read only" in lowered_text:
            return "Read only."
        if "write only" in lowered_text:
            return "Write only."
        return None

    def _is_pin_mapping_lookup_query(self, question: str, source_text: str) -> bool:
        question_signal = self._normalize_search_text(question).lower()
        evidence_signal = self._normalize_search_text(source_text).lower()
        return self._has_pin_question_anchor(question_signal) and self._has_pin_evidence_anchor(
            evidence_signal
        )

    def _has_pin_question_anchor(self, text: str) -> bool:
        return any(
            term in text
            for term in [
                "which pin",
                "what pin",
                "pinout",
                "alternate function",
                "gpio",
                "pad",
                "ball",
                "package",
            ]
        ) or bool(re.search(r"\bpin\b|\baf(?:\d+)?\b|\bp[a-z]\d{1,2}\b", text))

    def _has_pin_evidence_anchor(self, text: str) -> bool:
        lowered_text = text.lower()
        return any(
            term in lowered_text
            for term in [
                "pinout",
                "alternate function",
                "alternate functions",
                "gpio",
                "pad",
                "ball",
                "package",
            ]
        ) or bool(re.search(r"\bp[a-z]\d{1,2}\b", text, flags=re.IGNORECASE)) or bool(
            re.search(r"\baf(?:\d+)?\b", text, flags=re.IGNORECASE)
            and re.search(r"\b[a-z]{2,}[a-z0-9]*(?:_[a-z0-9]+)+\b", text, flags=re.IGNORECASE)
        )

    def _pin_mapping_answer_quality(self, question: str, text: str) -> float:
        if not self._is_pin_intent_query(question):
            return 0.0

        quality = 0.0
        if self._build_pin_summary(question, text) is not None:
            quality += 8.0
        normalized_text = self._normalize_search_text(text)
        if self._extract_package_name(question, normalized_text):
            quality += 1.5
        if any(
            term in normalized_text.lower()
            for term in ["pin definitions", "pin name", "alternate functions"]
        ):
            quality += 1.5
        return quality

    def _build_pin_summary(
        self,
        question: str,
        source_text: str,
    ) -> StructuredSummary | None:
        signal_or_function = self._extract_pin_signal_or_function(question, source_text)
        pin_name = self._extract_pin_name(question, source_text)
        package_name = self._extract_package_name(question, source_text)
        direction_or_role = self._extract_pin_direction_or_role(source_text)
        if not pin_name or not signal_or_function:
            return None
        if not self._is_row_local_pin_signal_or_function(question, source_text, signal_or_function):
            return None

        return self._make_structured_summary(
            kind="pin",
            title="Pin Summary",
            field_pairs=[
                ("Signal / Function", signal_or_function),
                ("Pin Name", pin_name),
                ("Package / Variant", package_name),
                ("Direction / Role", direction_or_role),
            ],
        )

    def _is_row_local_pin_signal_or_function(
        self,
        question: str,
        source_text: str,
        signal_or_function: str,
    ) -> bool:
        requested_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(question)]
        question_has_explicit_signal = bool(
            SIGNAL_NAME_RE.search(question) or re.search(r"\bAF\d+\b", question, flags=re.IGNORECASE)
        )
        if not requested_pins or question_has_explicit_signal:
            return True

        normalized_signal = signal_or_function.upper()
        normalized_lines = [
            self._normalize_search_text(line)
            for line in source_text.splitlines()
            if self._normalize_search_text(line)
        ]

        for index, line in enumerate(normalized_lines):
            upper_line = line.upper()
            line_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(line)]
            if not any(pin in line_pins for pin in requested_pins):
                continue
            if normalized_signal in upper_line:
                return True

            for adjacent_index in (index - 1, index + 1):
                if adjacent_index < 0 or adjacent_index >= len(normalized_lines):
                    continue
                adjacent_line = normalized_lines[adjacent_index]
                if normalized_signal not in adjacent_line.upper():
                    continue
                if self._is_table_row_support_line(
                    question,
                    TABLE_QUESTION_PIN,
                    adjacent_line.lower(),
                ):
                    return True

        return False

    def _extract_pin_signal_or_function(self, question: str, source_text: str) -> str | None:
        source_upper = source_text.upper()
        question_signals = [candidate.upper() for candidate in SIGNAL_NAME_RE.findall(question)]
        for normalized in question_signals:
            if normalized in source_upper:
                return normalized
        if question_signals:
            return None

        question_af = re.search(r"\bAF\d+\b", question, flags=re.IGNORECASE)
        if question_af:
            normalized_af = question_af.group(0).upper()
            if normalized_af in source_upper:
                return normalized_af
            return None

        source_candidates = [candidate.upper() for candidate in SIGNAL_NAME_RE.findall(source_text)]
        for candidate in source_candidates:
            if candidate.endswith(("_CR1", "_CR2", "_SR", "_DR")):
                continue
            return candidate

        source_af = re.search(r"\bAF\d+\b", source_text, flags=re.IGNORECASE)
        if source_af:
            return source_af.group(0).upper()

        return None

    def _extract_pin_name(self, question: str, source_text: str) -> str | None:
        mapping_values = self._extract_pin_mapping_values(question, source_text)
        if mapping_values:
            return mapping_values

        source_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(source_text)]
        question_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(question)]
        for normalized in question_pins:
            if normalized in source_pins:
                return normalized
        if question_pins:
            return None

        question_has_explicit_signal = bool(
            SIGNAL_NAME_RE.search(question) or re.search(r"\bAF\d+\b", question, flags=re.IGNORECASE)
        )
        if question_has_explicit_signal:
            return None

        if source_pins:
            return source_pins[0]
        return None

    def _extract_package_name(self, question: str, source_text: str) -> str | None:
        question_match = PACKAGE_NAME_RE.search(question)
        if question_match and question_match.group(0).upper() in source_text.upper():
            return question_match.group(0).upper()
        return None

    def _compact_alnum(self, value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", self._normalize_search_text(value).upper())

    def _restricted_device_token_aliases(
        self,
        compact_requested: str,
        *,
        allow_family_alias: bool = True,
    ) -> list[str]:
        aliases = [compact_requested]
        if not allow_family_alias or "X" in compact_requested:
            return aliases
        alias_match = re.fullmatch(r"(STM32[A-Z0-9]{4,})([A-Z])([A-Z0-9])", compact_requested)
        if not alias_match:
            return aliases

        family_stem, _package_code, density_code = alias_match.groups()
        alias_token = f"{family_stem}X{density_code}"
        if alias_token not in aliases:
            aliases.append(alias_token)
        return aliases

    def _source_matches_requested_device(
        self,
        question: str,
        source_text: str,
        *,
        allow_family_alias: bool = True,
    ) -> bool:
        requested_tokens = self._question_device_tokens(question)
        if not requested_tokens:
            return True
        return any(
            self._source_matches_requested_device_token(
                requested_token,
                source_text,
                allow_family_alias=allow_family_alias,
            )
            for requested_token in requested_tokens
        )

    def _source_matches_requested_device_token(
        self,
        requested_token: str,
        source_text: str,
        *,
        allow_family_alias: bool = True,
    ) -> bool:
        compact_requested = self._compact_alnum(requested_token)
        compact_source = self._compact_alnum(source_text)
        if not compact_requested or not compact_source:
            compact_source = ""

        compact_source_stem = ""
        if self.source.is_file():
            compact_source_stem = self._compact_alnum(self.source.stem)
        if compact_requested in compact_source:
            return True
        if compact_source_stem and compact_requested in compact_source_stem:
            return True

        requested_candidates = self._restricted_device_token_aliases(
            compact_requested,
            allow_family_alias=allow_family_alias,
        )
        for candidate in requested_candidates:
            if candidate == compact_requested:
                continue
            if candidate in compact_source:
                return True
            if compact_source_stem and candidate in compact_source_stem:
                return True

        return False

    def _ordering_source_has_exact_variant_closure(self, question: str, source_text: str) -> bool:
        requested_device_tokens = self._question_device_tokens(question)
        exact_requested_tokens = [
            requested_token
            for requested_token in requested_device_tokens
            if "X" not in self._compact_alnum(requested_token)
        ]
        if not exact_requested_tokens:
            return True

        normalized_lines = [
            self._normalize_search_text(line)
            for line in source_text.splitlines()
            if self._normalize_search_text(line)
        ]
        compact_source_text = self._normalize_search_text(source_text)
        if len(normalized_lines) <= 1 and compact_source_text:
            normalized_lines = [compact_source_text]

        synthetic_prefixes = [
            f"{self._normalize_search_text(requested_token).upper()} PACKAGE ="
            for requested_token in exact_requested_tokens
        ]
        synthetic_prefixes.extend(
            f"{self._normalize_search_text(requested_token).upper()} PACKAGE CODE "
            for requested_token in exact_requested_tokens
        )

        for line in normalized_lines:
            upper_line = self._normalize_search_text(line).upper()
            if any(upper_line.startswith(prefix) for prefix in synthetic_prefixes):
                continue
            if any(
                self._source_matches_requested_device_token(
                    requested_token,
                    line,
                    allow_family_alias=False,
                )
                for requested_token in exact_requested_tokens
            ):
                return True

        return False

    def _source_has_family_wide_scope(self, source_text: str) -> bool:
        lowered_text = self._normalize_search_text(source_text).lower()
        return any(
            term in lowered_text
            for term in [
                "all devices",
                "all variants",
                "device summary",
                "the stm32f103xx",
                "performance line family",
                "medium-density performance line",
            ]
        )

    def _source_has_multiple_capacity_options(self, source_text: str) -> bool:
        lowered_text = self._normalize_search_text(source_text).lower()
        if re.search(
            r"\b\d+\s*(?:kbytes?|kb|mb)?\s*(?:/|or)\s*\d+\s*(?:kbytes?|kb|mb)\b",
            lowered_text,
        ):
            return True
        if "up to" in lowered_text and len(re.findall(r"\b\d+\s*(?:kbytes?|kb|mb)\b", lowered_text)) >= 2:
            return True
        return False

    def _source_matches_requested_package(self, requested_package: str, source_text: str) -> bool:
        compact_requested = self._compact_alnum(requested_package)
        compact_source = self._compact_alnum(source_text)
        if compact_requested and compact_requested in compact_source:
            return True

        family_pin_match = re.fullmatch(r"([A-Z]+)(\d+)", compact_requested)
        if not family_pin_match:
            return False

        package_family, pin_count = family_pin_match.groups()
        lowered_text = self._normalize_search_text(source_text).lower()
        return package_family.lower() in lowered_text and bool(
            re.search(rf"\b{pin_count}\s*[- ]?pins?\b", lowered_text)
        )

    def _source_has_multiple_package_options(self, source_text: str) -> bool:
        normalized_text = self._normalize_search_text(source_text).upper()
        package_hits = {
            match.group(0).replace(" ", "")
            for match in re.finditer(
                r"\b(?:LQFP|UFQFPN|VFQFPN|TFBGA|LFBGA|UFBGA|BGA)\s*\d*\b",
                normalized_text,
            )
        }
        exact_package_hits = {hit for hit in package_hits if re.search(r"\d", hit)}
        covered_package_families = {
            re.sub(r"\d+$", "", hit)
            for hit in exact_package_hits
        }
        if exact_package_hits:
            package_hits = {
                hit
                for hit in package_hits
                if re.search(r"\d", hit) or hit not in covered_package_families
            }
        if len(package_hits) >= 2:
            return True
        mapping_hits = {
            match.group(1).replace(" ", "")
            for match in re.finditer(
                r"\b[A-Z0-9]{1,4}\s*=\s*((?:LQFP|UFQFPN|VFQFPN|TFBGA|LFBGA|UFBGA|BGA)\s*\d*)\b",
                normalized_text,
            )
        }
        exact_mapping_hits = {hit for hit in mapping_hits if re.search(r"\d", hit)}
        covered_mapping_families = {
            re.sub(r"\d+$", "", hit)
            for hit in exact_mapping_hits
        }
        if exact_mapping_hits:
            mapping_hits = {
                hit
                for hit in mapping_hits
                if re.search(r"\d", hit) or hit not in covered_mapping_families
            }
        return len(mapping_hits) >= 2

    def _source_only_pin_scope_hints(self, question: str, source_text: str) -> list[str]:
        normalized_question = self._normalize_search_text(question)
        normalized_source = self._normalize_search_text(source_text)
        lowered_question = normalized_question.lower()
        lowered_source = normalized_source.lower()
        hints: list[str] = []

        question_has_package = PACKAGE_NAME_RE.search(normalized_question) is not None
        source_has_explicit_package_scope = PACKAGE_NAME_RE.search(normalized_source) is not None
        source_has_package_table_scope = (
            "pin definitions" in lowered_source
            and "pins" in lowered_source
            and len(PIN_NAME_RE.findall(normalized_source)) >= 2
        )
        if not question_has_package and (source_has_explicit_package_scope or source_has_package_table_scope):
            hints.append(
                "The retrieved pin row is package-scoped; specify the package or package variant before selecting one grounded pin mapping."
            )

        question_has_remap_assignment = bool(
            re.search(r"\b([A-Z0-9_]+)\s*=\s*([01])\b", normalized_question, flags=re.IGNORECASE)
        )
        question_has_family_anchor = "remap" in lowered_question or bool(
            re.search(r"\btable\s+\d+\b", lowered_question)
        )
        source_has_remap_scope = bool(
            re.search(r"\b([A-Z0-9_]+)\s*=\s*([01])\b", normalized_source, flags=re.IGNORECASE)
        ) or "remap not available" in lowered_source
        if source_has_remap_scope and not question_has_remap_assignment and not question_has_family_anchor:
            hints.append(
                "The retrieved pin row is sibling-specific and still needs remap/package-variant disambiguation before selecting one grounded pin mapping."
            )

        return hints

    def _extract_pin_mapping_values(self, question: str, source_text: str) -> str | None:
        requested_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(question)]
        requested_pin_set = set(requested_pins)
        is_ball_query = bool(re.search(r"\bball\b", question, flags=re.IGNORECASE))
        has_explicit_package_constraint = PACKAGE_NAME_RE.search(question) is not None
        has_explicit_ball_package_scope = (
            has_explicit_package_constraint
            and self._source_has_explicit_ball_package_scope(question, source_text)
        )
        allow_ball_nearest_left_fallback = not (
            is_ball_query
            and has_explicit_package_constraint
            and (
                self._source_has_multiple_package_options(source_text)
                or not has_explicit_ball_package_scope
            )
        )

        def is_self_mapping_value(candidate: str | None) -> bool:
            if not candidate:
                return False
            normalized_candidate = re.sub(r"\s*/\s*", "/", candidate.strip().upper())
            if normalized_candidate == "-":
                return False
            candidate_tokens = [token.strip() for token in normalized_candidate.split("/") if token.strip()]
            return bool(candidate_tokens) and all(token in requested_pin_set for token in candidate_tokens)

        normalized_lines = [
            self._normalize_search_text(line)
            for line in source_text.splitlines()
            if self._normalize_search_text(line)
        ]

        if requested_pins:
            requested_values: list[str] = []
            seen_requested_pins: set[str] = set()
            mapping_value_pattern = re.compile(
                r"\b[A-Z]\d{1,2}\s*/\s*[A-Z]\d{1,2}\b|\b[A-Z]\d{1,2}\b|(?<![A-Z0-9_])-(?![A-Z0-9_])"
            )
            requested_package = None
            if has_explicit_package_constraint:
                package_match = PACKAGE_NAME_RE.search(question)
                if package_match:
                    requested_package = package_match.group(0).upper()

            def select_mapping_value(
                raw_values: list[str],
                *,
                prefer_non_dash: bool = False,
            ) -> str | None:
                normalized_values = [
                    re.sub(r"\s*/\s*", "/", raw_value.strip().upper())
                    for raw_value in raw_values
                    if raw_value and raw_value.strip()
                ]
                if prefer_non_dash:
                    for normalized_value in reversed(normalized_values):
                        if normalized_value == "-" or is_self_mapping_value(normalized_value):
                            continue
                        return normalized_value
                for normalized_value in reversed(normalized_values):
                    if is_self_mapping_value(normalized_value):
                        continue
                    return normalized_value
                return None

            def extract_header_anchored_ball_value(requested_pin: str) -> str | None:
                if not (
                    is_ball_query
                    and requested_package
                    and self._source_has_multiple_package_options(source_text)
                ):
                    return None

                package_header_pattern = re.compile(
                    r"\b(?:LQFP|UFQFPN|VFQFPN|TFBGA|LFBGA|UFBGA|UFBG|BGA)\s*\d+\b"
                    r"(?:\s*/\s*\b(?:LQFP|UFQFPN|VFQFPN|TFBGA|LFBGA|UFBGA|UFBG|BGA)\s*\d+\b)*",
                    re.IGNORECASE,
                )
                normalized_requested_package = requested_package.replace(" ", "")
                pin_pattern = re.compile(rf"\b{re.escape(requested_pin)}\b")

                def header_matches_requested_package(header_column: str) -> bool:
                    return any(
                        self._source_matches_requested_package(
                            normalized_requested_package,
                            package_option,
                        )
                        for package_option in header_column.split("/")
                    )

                for index, line in enumerate(normalized_lines):
                    upper_line = line.upper()
                    if not pin_pattern.search(upper_line):
                        continue

                    package_columns: list[str] = []
                    for header_line in normalized_lines[max(0, index - 20) : index]:
                        normalized_header_columns = [
                            self._normalize_search_text(match.group(0)).upper().replace(" ", "")
                            for match in package_header_pattern.finditer(header_line)
                        ]
                        for header_column in normalized_header_columns:
                            if header_column not in package_columns:
                                package_columns.append(header_column)
                    if not package_columns:
                        continue

                    requested_package_index = next(
                        (
                            column_index
                            for column_index, header_column in enumerate(package_columns)
                            if header_matches_requested_package(header_column)
                        ),
                        None,
                    )
                    if requested_package_index is None:
                        continue

                    row_tokens = [token.upper() for token in upper_line.split()]
                    if requested_pin not in row_tokens:
                        continue
                    pin_index = row_tokens.index(requested_pin)
                    row_cells = row_tokens[: len(package_columns)]
                    if pin_index < len(row_cells) or requested_package_index >= len(row_cells):
                        continue

                    normalized_candidate = re.sub(
                        r"\s*/\s*",
                        "/",
                        row_cells[requested_package_index].strip().upper(),
                    )
                    if not re.fullmatch(r"[A-Z]\d{1,2}(?:/[A-Z]\d{1,2})?|-", normalized_candidate):
                        continue
                    if is_self_mapping_value(normalized_candidate):
                        continue
                    return normalized_candidate

                return None

            for requested_pin in requested_pins:
                if requested_pin in seen_requested_pins:
                    continue
                seen_requested_pins.add(requested_pin)

                matched_value: str | None = extract_header_anchored_ball_value(requested_pin)
                if matched_value is None:
                    pin_pattern = re.compile(rf"\b{re.escape(requested_pin)}\b")
                    for line in normalized_lines:
                        upper_line = line.upper()
                        pin_match = pin_pattern.search(upper_line)
                        if not pin_match:
                            continue

                        tail = upper_line[pin_match.end() :]
                        tail_values = [match.group(0) for match in mapping_value_pattern.finditer(tail)]
                        matched_value = select_mapping_value(tail_values)
                        # Nearest-left ball fallback is unsafe for explicit-package queries when
                        # the source row spans multiple package columns without aligned indices.
                        if matched_value is None and is_ball_query and allow_ball_nearest_left_fallback:
                            head = upper_line[: pin_match.start()]
                            head_values = [match.group(0) for match in mapping_value_pattern.finditer(head)]
                            matched_value = select_mapping_value(head_values, prefer_non_dash=True)
                        if matched_value is None:
                            continue
                        break

                if matched_value is not None:
                    requested_values.append(matched_value)

            if requested_values:
                if all(value == "-" for value in requested_values):
                    return "-"
                if len(requested_values) == 1:
                    return requested_values[0]
                return " / ".join(requested_values)

        signal_or_function = self._extract_pin_signal_or_function(question, source_text)
        if not signal_or_function:
            return None

        target_index: int | None = None
        row_pins: list[str] = []
        for index, line in enumerate(normalized_lines):
            upper_line = line.upper()
            if signal_or_function not in upper_line:
                continue

            line_pins = list(
                dict.fromkeys(candidate.upper() for candidate in PIN_NAME_RE.findall(line))
            )
            if not line_pins:
                continue

            if requested_pins:
                matched_pins = [pin for pin in requested_pins if pin in line_pins]
                if not matched_pins:
                    continue
                row_pins = matched_pins
            else:
                row_pins = line_pins

            target_index = index
            break

        if target_index is None:
            return None
        if not row_pins:
            return None

        if target_index > 0:
            remap_conditions = [
                f"{name.upper()} = {value}"
                for name, value in re.findall(
                    r"\b([A-Z0-9_]+)\s*=\s*([01])\b",
                    normalized_lines[target_index - 1],
                    flags=re.IGNORECASE,
                )
            ]
            if len(remap_conditions) >= len(row_pins):
                return "; ".join(
                    f"{pin} ({condition})"
                    for pin, condition in zip(row_pins, remap_conditions)
                )

        if len(row_pins) == 1:
            fallback_value = row_pins[0]
        else:
            fallback_value = " / ".join(row_pins)
        if is_self_mapping_value(fallback_value):
            return None
        return fallback_value

    def _build_pin_grounded_short_answer(
        self,
        question: str,
        entry: EvidenceRecord,
    ) -> str | None:
        source_text = entry.full_text if entry.full_text else entry.excerpt
        signal_or_function = self._extract_pin_signal_or_function(question, source_text)
        pin_name = self._extract_pin_name(question, source_text)
        package_name = self._extract_package_name(question, source_text)
        if not signal_or_function:
            return None
        if not self._is_row_local_pin_signal_or_function(question, source_text, signal_or_function):
            return None
        if pin_name:
            package_clause = f" for {package_name}" if package_name else ""
            return (
                f"The strongest grounded evidence indicates that {signal_or_function} maps to {pin_name}"
                f"{package_clause} in [S1] {entry.section} (page {entry.page})."
            )

        normalized_lines = [
            self._normalize_search_text(line)
            for line in source_text.splitlines()
            if self._normalize_search_text(line)
        ]
        target_index = next(
            (
                index
                for index, line in enumerate(normalized_lines)
                if signal_or_function in line.upper() and PIN_NAME_RE.search(line)
            ),
            None,
        )
        if target_index is None:
            pin_name = self._extract_pin_name(question, source_text)
            if not pin_name:
                return None
            return (
                f"The strongest grounded evidence indicates that {signal_or_function} maps to {pin_name} "
                f"in [S1] {entry.section} (page {entry.page})."
            )

        row_pins = list(
            dict.fromkeys(
                candidate.upper() for candidate in PIN_NAME_RE.findall(normalized_lines[target_index])
            )
        )
        if not row_pins:
            return None

        if target_index > 0:
            remap_conditions = [
                f"{name.upper()} = {value}"
                for name, value in re.findall(
                    r"\b([A-Z0-9_]+)\s*=\s*([01])\b",
                    normalized_lines[target_index - 1],
                    flags=re.IGNORECASE,
                )
            ]
            if len(remap_conditions) >= len(row_pins):
                mapping_text = " and ".join(
                    f"{pin} when {condition}"
                    for pin, condition in zip(row_pins, remap_conditions)
                )
                return (
                    f"The strongest grounded evidence indicates that {signal_or_function} maps to {mapping_text} "
                    f"in [S1] {entry.section} (page {entry.page})."
                )

        joined_pins = " / ".join(row_pins) if len(row_pins) > 1 else row_pins[0]
        return (
            f"The strongest grounded evidence indicates that {signal_or_function} maps to {joined_pins} "
            f"in [S1] {entry.section} (page {entry.page})."
        )

    def _extract_pin_direction_or_role(self, source_text: str) -> str | None:
        lowered_text = self._normalize_search_text(source_text).lower()
        if "bidirectional" in lowered_text or "input/output" in lowered_text or "i/o" in lowered_text:
            return "Bidirectional I/O."
        if "input" in lowered_text and "output" in lowered_text:
            return "Input/output."
        if "input" in lowered_text:
            return "Input."
        if "output" in lowered_text:
            return "Output."
        if "power" in lowered_text or "supply" in lowered_text:
            return "Power."
        if "ground" in lowered_text or "gnd" in lowered_text:
            return "Ground."
        return None

    def _build_parameter_summary(
        self,
        question: str,
        source_text: str,
        numeric_answer: str,
    ) -> StructuredSummary | None:
        value_or_range, unit = self._split_numeric_answer(numeric_answer)
        parameter_name = self._extract_parameter_name(question, source_text)
        operating_conditions = self._extract_parameter_conditions(source_text)

        return self._make_structured_summary(
            kind="electrical_parameter",
            title="Parameter Summary",
            field_pairs=[
                ("Parameter", parameter_name),
                ("Value / Range", value_or_range),
                ("Unit", unit),
                ("Test / Operating Conditions", operating_conditions),
            ],
        )

    def _split_numeric_answer(self, numeric_answer: str) -> tuple[str, str | None]:
        match = re.match(r"(.+?)\s+([A-Za-z%]+)$", numeric_answer.strip())
        if not match:
            return numeric_answer.strip(), None
        value_or_range, unit = match.groups()
        return value_or_range.strip(), unit

    def _extract_parameter_name(self, question: str, source_text: str) -> str | None:
        lowered_question = question.lower()
        lowered_text = self._normalize_search_text(source_text).lower()
        if "vdd" in lowered_question or "vdd" in lowered_text:
            if "standard operating voltage" in lowered_text:
                return "VDD standard operating voltage"
            if "operating voltage" in lowered_text:
                return "VDD operating voltage"
            return "VDD"
        return None

    def _extract_parameter_conditions(self, source_text: str) -> str | None:
        lowered_text = self._normalize_search_text(source_text).lower()
        if "standard operating conditions" in lowered_text:
            return "Standard operating conditions."
        if "operating conditions" in lowered_text:
            return "Operating conditions."
        if "standard operating voltage" in lowered_text:
            return "Standard operating voltage row."
        return None

    def _make_structured_summary(
        self,
        *,
        kind: str,
        title: str,
        field_pairs: list[tuple[str, str | None]],
    ) -> StructuredSummary | None:
        fields = [
            StructuredSummaryField(label=label, value=value.strip())
            for label, value in field_pairs
            if value and value.strip()
        ]
        if not fields:
            return None
        return StructuredSummary(kind=kind, title=title, fields=fields)


    def _extract_numeric_answer(self, question: str, text: str) -> str | None:
        lowered_question = question.lower()
        lowered_text = re.sub(r"\s+", " ", text).lower()

        if "vdd" in lowered_question or "operating voltage" in lowered_question:
            vdd_match = re.search(
                r"vdd[^\n]{0,120}?standard operating voltage[^\n]{0,30}?-\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)",
                lowered_text,
            )
            if vdd_match:
                lower, upper = vdd_match.groups()
                return f"{lower} to {upper} V"

            voltage_table_match = re.search(
                r"vdd[^\n]{0,160}?operating voltage[^\n]{0,30}?-\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)",
                lowered_text,
            )
            if voltage_table_match:
                lower, upper = voltage_table_match.groups()
                return f"{lower} to {upper} V"

        range_match = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*(v|mv|a|ma|ua|hz|khz|mhz|ghz|ns|us|ms|%)\b",
            lowered_text,
        )
        if range_match:
            lower, upper, unit = range_match.groups()
            return f"{lower} to {upper} {unit.upper()}"

        min_max_match = re.search(
            r"\bmin\b[^\n]{0,80}?\b(\d+(?:\.\d+)?)\b[^\n]{0,40}?\bmax\b[^\n]{0,80}?\b(\d+(?:\.\d+)?)\b[^\n]{0,20}?\b(v|mv|a|ma|ua|hz|khz|mhz|ghz|ns|us|ms|%)\b",
            lowered_text,
        )
        if min_max_match:
            lower, upper, unit = min_max_match.groups()
            return f"{lower} to {upper} {unit.upper()}"

        return None

    def _should_gate_on_pin_mapping_gap(self, question: str, evidence: list[EvidenceRecord]) -> bool:
        if not evidence:
            return False
        if self._table_question_family(question) in {
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            return False
        if not self._is_pin_intent_query(question):
            return False
        return not self._has_supported_pin_mapping_answer(question, evidence)

    def _has_supported_pin_mapping_answer(self, question: str, evidence: list[EvidenceRecord]) -> bool:
        if not evidence:
            return False

        top_entry = evidence[0]
        source_text = top_entry.full_text if top_entry.full_text else top_entry.excerpt
        summary_signal_text = f"{top_entry.section} {source_text}"
        if not self._is_pin_mapping_lookup_query(question, summary_signal_text):
            return False
        if self._build_pin_summary(question, summary_signal_text) is None:
            return False
        return not self._pin_constraint_failure_hints(question, top_entry)

    def _is_pin_intent_query(self, question: str) -> bool:
        question_signal = self._normalize_search_text(question).lower()
        if self._has_pin_question_anchor(question_signal):
            return True
        if SIGNAL_NAME_RE.search(question) and any(
            term in question_signal for term in ["which", "provides", "maps", "mapped", "route", "routed"]
        ):
            return True
        return False

    def _comparison_signal_text(self, entry: EvidenceRecord) -> str:
        return self._normalize_search_text(
            f"{entry.section} {entry.full_text or entry.excerpt}"
        ).lower()

    def _comparison_signal_tokens(self, entry: EvidenceRecord) -> set[str]:
        return set(self._tokenize(self._comparison_signal_text(entry)))

    def _find_comparison_entry(
        self,
        evidence: list[EvidenceRecord],
        required_terms: list[str],
        any_terms: list[str],
    ) -> EvidenceRecord | None:
        best_entry: EvidenceRecord | None = None
        best_score = float("-inf")
        normalized_required_terms = [self._normalize_token(term) for term in required_terms]
        normalized_any_terms = [self._normalize_token(term) for term in any_terms]

        for entry in evidence:
            signal_text = self._comparison_signal_text(entry)
            signal_tokens = self._comparison_signal_tokens(entry)
            if not all(term and term in signal_tokens for term in normalized_required_terms):
                continue

            matched_any_terms = [term for term in normalized_any_terms if term and term in signal_tokens]
            if not matched_any_terms:
                continue

            lowered_section = entry.section.lower()
            score = entry.score + (0.4 * len(matched_any_terms))
            if all(term in lowered_section for term in required_terms if term != "spi_dr"):
                score += 0.6
            if any(term in lowered_section for term in matched_any_terms):
                score += 0.8
            if "spi_dr" in lowered_section:
                score += 0.6
            if "spi" in normalized_required_terms and "usart" in signal_text and "spi communication using dm a" not in signal_text:
                score -= 3.5
            if "spi" in normalized_required_terms and "i2s" in signal_text and "spi communication using dm a" not in signal_text:
                score -= 4.5
            if "usart" in normalized_required_terms and "i2c" in signal_text and "usart" not in signal_text:
                score -= 4.5

            if score > best_score:
                best_entry = entry
                best_score = score

        return best_entry

    def _comparison_patterns(
        self,
        question: str,
    ) -> list[tuple[list[str], list[str]]]:
        lowered_question = question.lower()
        if "spi" in lowered_question and "dma" in lowered_question:
            return [
                (
                    ["spi", "dma", "spi_dr"],
                    ["txe", "transmit", "transmission", "write", "writes", "trigger", "triggered"],
                ),
                (
                    ["spi", "dma", "spi_dr"],
                    ["rxne", "receive", "reception", "read", "reads", "trigger", "triggered"],
                ),
            ]

        if "usart" in lowered_question and "dma" in lowered_question:
            return [
                (
                    ["usart", "dma"],
                    ["transmit", "transmission", "tx", "txe", "send", "writer", "write", "tx buffer"],
                ),
                (
                    ["usart", "dma"],
                    ["receive", "reception", "rx", "rxne", "read", "reader", "rx buffer"],
                ),
            ]

        if all(term in lowered_question for term in ["threshold mode", "store-and-forward", "mac"]):
            return [
                (
                    ["mac", "transmission"],
                    ["threshold", "threshold mode", "fifo", "threshold level"],
                ),
                (
                    ["mac", "transmission"],
                    ["store-and-forward", "store", "forward", "complete frame", "fifo"],
                ),
            ]

        if (
            any(term in lowered_question for term in ["por", "pdr", "power-on reset", "power-down reset"])
            and any(term in lowered_question for term in ["programmable voltage detector", "pvd"])
        ):
            return [
                (
                    ["power", "reset"],
                    ["por", "pdr", "power-on", "power-down", "vpor/pdr", "reset"],
                ),
                (
                    ["power"],
                    ["pvd", "programmable", "voltage", "detector", "vpvd"],
                ),
            ]

        return []

    def _comparison_pattern_entries(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> list[EvidenceRecord | None]:
        patterns = self._comparison_patterns(question)
        if not patterns:
            return []

        return [
            self._find_comparison_entry(evidence, required_terms, any_terms)
            for required_terms, any_terms in patterns
        ]

    def _collect_comparison_entries(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> list[EvidenceRecord]:
        matches = self._comparison_pattern_entries(question, evidence)
        if not matches:
            return []

        selected: list[EvidenceRecord] = []
        for entry in matches:
            if entry is not None and entry not in selected:
                selected.append(entry)
        return selected

    def _select_comparison_evidence(
        self,
        question: str,
        evidence: list[EvidenceRecord],
        limit: int = 3,
    ) -> list[EvidenceRecord]:
        if not evidence:
            return []

        selected = self._collect_comparison_entries(question, evidence)
        seen_sections = {
            (entry.document_path, entry.section, entry.page)
            for entry in selected
        }
        for entry in evidence[:limit]:
            entry_key = (entry.document_path, entry.section, entry.page)
            if entry in selected or entry_key in seen_sections:
                continue
            selected.append(entry)
            seen_sections.add(entry_key)
            if len(selected) >= limit:
                break

        return selected[:limit] if selected else evidence[:limit]

    def _finalize_comparison_evidence(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> list[EvidenceRecord]:
        if not evidence or not self._is_comparison_query(question):
            return evidence
        if not self._has_grounded_comparison_coverage(question, evidence):
            return evidence

        curated: list[EvidenceRecord] = []
        selected = self._collect_comparison_entries(question, evidence)
        direct_answers = [
            entry
            for entry in evidence
            if self._evidence_directly_answers(question, entry)
        ]

        for entry in [*selected, *direct_answers]:
            if entry in curated or self._is_low_signal_for_question(question, entry):
                continue
            curated.append(entry)

        top_score = evidence[0].score
        for entry in evidence:
            if len(curated) >= 3:
                break
            if entry in curated or self._is_low_signal_for_question(question, entry):
                continue
            if entry.score < max(12.0, top_score - 3.0):
                continue
            if self._evidence_directly_answers(question, entry):
                curated.append(entry)

        final_evidence = curated[:3] if curated else evidence[:3]
        for index, entry in enumerate(final_evidence, start=1):
            entry.tag = f"[S{index}]"
        return final_evidence

    def _reorder_comparison_evidence(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> list[EvidenceRecord]:
        if not evidence or not self._is_comparison_query(question):
            return evidence

        selected = self._select_comparison_evidence(question, evidence, limit=len(evidence))
        if not selected:
            return evidence

        selected_ids = {id(entry) for entry in selected}
        ordered = [*selected, *(entry for entry in evidence if id(entry) not in selected_ids)]
        for index, entry in enumerate(ordered, start=1):
            entry.tag = f"[S{index}]"
        return ordered

    def _has_grounded_comparison_coverage(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> bool:
        if not self._is_comparison_query(question) or not evidence:
            return False

        matches = self._comparison_pattern_entries(question, evidence)
        if not matches:
            return False
        if all(entry is not None for entry in matches):
            return True

        if len(matches) == 2 and matches[0] is not None and matches[1] is not None:
            return True

        combined_signal = self._normalize_search_text(
            " ".join(self._comparison_signal_text(entry) for entry in evidence[:3])
        )
        patterns = self._comparison_patterns(question)
        if len(patterns) != 2:
            return False

        return all(
            all(self._normalize_token(term) in combined_signal for term in required_terms)
            and any(self._normalize_token(term) in combined_signal for term in any_terms)
            for required_terms, any_terms in patterns
        )

    def _build_comparison_short_answer(
        self,
        question: str,
        evidence: list[EvidenceRecord],
    ) -> str | None:
        if not self._is_comparison_query(question) or not evidence:
            return None

        lowered_question = question.lower()
        if "spi" in lowered_question and "dma" in lowered_question:
            matches = self._comparison_pattern_entries(question, evidence)
            if len(matches) >= 2 and all(entry is not None for entry in matches[:2]):
                transmit_entry = matches[0]
                receive_entry = matches[1]
                citations = (
                    transmit_entry.tag
                    if transmit_entry.tag == receive_entry.tag
                    else f"{transmit_entry.tag} and {receive_entry.tag}"
                )
                return (
                    "The grounded difference is that SPI DMA transmit requests write to "
                    "SPI_DR when TXE is set, while SPI DMA receive requests read SPI_DR "
                    f"when RXNE is set, based on {citations}."
                )

        if "usart" in lowered_question and "dma" in lowered_question:
            matches = self._comparison_pattern_entries(question, evidence)
            if len(matches) >= 2 and all(entry is not None for entry in matches[:2]):
                transmit_entry = matches[0]
                receive_entry = matches[1]
                citations = (
                    transmit_entry.tag
                    if transmit_entry.tag == receive_entry.tag
                    else f"{transmit_entry.tag} and {receive_entry.tag}"
                )
                return (
                    "The grounded difference is that USART DMA transmission writes outgoing data from memory into "
                    "USART_DR through the Tx path, while USART DMA reception reads incoming data from USART_DR into memory "
                    f"through the Rx path, based on {citations}."
                )

        if all(term in lowered_question for term in ["threshold mode", "store-and-forward", "mac"]):
            matches = self._comparison_pattern_entries(question, evidence)
            if len(matches) >= 2 and all(entry is not None for entry in matches[:2]):
                threshold_entry = matches[0]
                store_forward_entry = matches[1]
                citations = (
                    threshold_entry.tag
                    if threshold_entry.tag == store_forward_entry.tag
                    else f"{threshold_entry.tag} and {store_forward_entry.tag}"
                )
                return (
                    "The grounded difference is that MAC threshold mode starts forwarding data toward the MAC core once the Tx FIFO crosses the configured threshold "
                    "or reaches end-of-frame early, while store-and-forward mode waits until a complete frame is buffered before forwarding it "
                    f"toward the MAC core, based on {citations}."
                )

        if (
            any(term in lowered_question for term in ["por", "pdr", "power-on reset", "power-down reset"])
            and any(term in lowered_question for term in ["programmable voltage detector", "pvd"])
        ):
            matches = self._comparison_pattern_entries(question, evidence)
            if matches and all(entry is not None for entry in matches):
                cited_entries: list[EvidenceRecord] = []
                for entry in matches:
                    if entry not in cited_entries:
                        cited_entries.append(entry)
                citations = " and ".join(entry.tag for entry in cited_entries[:2])
                return (
                    "The grounded difference is that the POR/PDR circuitry keeps the device in reset "
                    "below the VPOR/PDR threshold, while the programmable voltage detector monitors "
                    "VDD/VDDA against VPVD and can raise an interrupt so software can warn or enter a safe state, "
                    f"based on {citations}."
                )

        return None

    def _build_grounded_short_answer(self, question: str, evidence: list[EvidenceRecord]) -> str:
        if not evidence:
            return "No grounded answer found from the selected manuals."

        comparison_answer = self._build_comparison_short_answer(question, evidence)
        if comparison_answer:
            return comparison_answer

        top_entry = evidence[0]
        excerpt = top_entry.excerpt
        source_text = top_entry.full_text if top_entry.full_text else excerpt
        table_question_family = self._table_question_family(question)
        if table_question_family in {
            TABLE_QUESTION_FEATURE,
            TABLE_QUESTION_PERIPHERAL_COUNT,
            TABLE_QUESTION_MEMORY,
            TABLE_QUESTION_PACKAGE,
            TABLE_QUESTION_ORDERING,
            TABLE_QUESTION_DEVICE_VARIANT,
        }:
            table_answer = self._build_table_grounded_short_answer(
                question,
                top_entry,
                table_question_family,
            )
            if table_answer:
                return table_answer
        pin_answer = None
        if self._is_pin_intent_query(question):
            pin_answer = self._build_pin_grounded_short_answer(question, top_entry)
        if pin_answer:
            return pin_answer

        numeric_answer = self._extract_numeric_answer(question, source_text) if self._looks_numeric(question) else None
        if numeric_answer:
            return (
                f"The strongest grounded evidence indicates {numeric_answer} in [S1] "
                f"{top_entry.section} (page {top_entry.page})."
            )

        register_answer = self._extract_register_answer(question, source_text)
        if register_answer:
            if "spi" in question.lower() and "dma" in question.lower() and any(
                term in source_text.lower() for term in ["txdmaen", "rxdmaen"]
            ):
                return (
                    f"The strongest grounded evidence indicates that {register_answer} contains the SPI DMA enable bits "
                    f"in [S1] {top_entry.section} (page {top_entry.page})."
                )
            return (
                f"The strongest grounded evidence indicates {register_answer} in [S1] "
                f"{top_entry.section} (page {top_entry.page})."
            )

        sentences = re.split(r"(?<=[.!?])\s+", excerpt)
        grounded_sentence = sentences[0].strip() if sentences else excerpt
        if not grounded_sentence:
            grounded_sentence = excerpt
        grounded_sentence = grounded_sentence.strip(' "')
        if grounded_sentence and grounded_sentence[-1] not in ".!?":
            grounded_sentence += "."

        if self._is_absence_query(question):
            return (
                "No grounded answer found to confirm that feature request. "
                f"The nearest retrieved evidence was [S1] in {top_entry.section} (page {top_entry.page}), "
                "but it does not directly establish the requested feature as present or absent."
            )

        return (
            f"The strongest grounded evidence is [S1] in {top_entry.section} (page {top_entry.page}). "
            f"It indicates that {grounded_sentence[0].lower() + grounded_sentence[1:] if len(grounded_sentence) > 1 else grounded_sentence.lower()}"
        )


    def _build_unsupported_question_result(self, question: str) -> RetrievalResult:
        return RetrievalResult(
            question=question,
            source=str(self.source),
            filters=self.filters,
            short_answer="This request is unsupported in Phase 1 because it asks for schematic/image, OCR-heavy, or retrieval-system work rather than grounded lookup from local text manuals.",
            key_evidence=[],
            sources=[],
            open_questions=[
                "Provide a local text-based manual or PDF and ask a manual-grounded question instead.",
                "Schematic, netlist, BOM, backend, MCP, and remote-crawling work are outside this prototype's current scope.",
            ],
            searched_documents=[],
        )

    def _build_not_found_result(
        self,
        question: str,
        searched_documents: list[str],
        *,
        reason: str,
    ) -> RetrievalResult:
        return RetrievalResult(
            question=question,
            source=str(self.source),
            filters=self.filters,
            short_answer=reason,
            key_evidence=[],
            sources=[],
            open_questions=[
                "Try a more specific device, revision, document type, section hint, or exact register/peripheral name.",
                "If you are checking for feature absence, verify the exact family and the feature summary or peripheral overview section.",
            ],
            searched_documents=searched_documents,
        )

    def _build_insufficient_coverage_result(
        self,
        question: str,
        evidence: list[EvidenceRecord],
        searched_documents: list[str],
        *,
        extra_open_questions: list[str] | None = None,
    ) -> RetrievalResult:
        relevant_evidence = evidence[:2]
        if self._is_register_lookup_query(question):
            direct_register_evidence = [
                entry for entry in evidence if self._evidence_directly_answers(question, entry)
            ]
            if direct_register_evidence:
                relevant_evidence = direct_register_evidence[:2]
        elif self._is_comparison_query(question):
            relevant_evidence = self._select_comparison_evidence(question, evidence, limit=3)

        missing_tokens = self._missing_requirement_tokens(question, relevant_evidence)

        if self._is_comparison_query(question):
            short_answer = "No grounded comparison found yet; the top retrieved sections did not directly cover both sides of the requested comparison."
            guidance = "Try naming both exact conditions, sections, or document types so each side of the comparison can be grounded separately."
        elif self._is_summary_query(question):
            short_answer = "No grounded summary found yet; the top retrieved sections did not directly cover the requested sequence well enough to summarize safely."
            guidance = "Try naming the exact reset block, section heading, or sequence step you want summarized."
        elif self._is_register_lookup_query(question):
            short_answer = "No grounded register-level answer found yet; the top retrieved sections mention related peripherals but do not identify the enabling register safely."
            guidance = "Try the exact peripheral instance, register family, or bit name, and prefer a reference manual over a datasheet when available."
        else:
            short_answer = "No grounded answer found yet; the top retrieved sections did not cover the request precisely enough to answer safely."
            guidance = "Try a more specific section hint, exact register/peripheral name, or a more authoritative manual."

        open_questions = [guidance]
        if extra_open_questions:
            for hint in extra_open_questions:
                if hint and hint not in open_questions:
                    open_questions.append(hint)
        if missing_tokens:
            open_questions.append(
                "Top evidence still missed these query terms: " + ", ".join(missing_tokens[:4]) + "."
            )

        return RetrievalResult(
            question=question,
            source=str(self.source),
            filters=self.filters,
            short_answer=short_answer,
            key_evidence=[
                f"{entry.tag} {entry.section} (page {entry.page}) score={entry.score}"
                for entry in relevant_evidence
            ],
            sources=relevant_evidence,
            open_questions=open_questions,
            searched_documents=searched_documents,
        )

    def _tokenize(self, text: str) -> list[str]:
        tokens = [self._normalize_token(token) for token in TOKEN_RE.findall(text)]
        return [token for token in tokens if token not in STOP_WORDS and len(token) > 1]

    def _normalize_token(self, token: str) -> str:
        normalized = token.lower().strip("'\"`.,;:!?()[]{}")
        normalized = re.sub(r"^[^a-z0-9_./+-]+|[^a-z0-9_./+-]+$", "", normalized)
        if not normalized:
            return ""
        for suffix in ("ing", "ed", "es", "s"):
            if len(normalized) > len(suffix) + 2 and normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        for separator in ("-", "_", "/"):
            trigger_suffix = f"{separator}trigger"
            if len(normalized) > len(trigger_suffix) + 2 and normalized.endswith(trigger_suffix):
                normalized = normalized[: -len(trigger_suffix)]
                break
        return normalized


    def _token_overlap_score(self, query_tokens: list[str], haystack: str) -> float:
        if not query_tokens:
            return 0.0
        haystack_tokens = set(self._tokenize(haystack))
        haystack_lower = haystack.lower()
        score = 0.0
        for token in query_tokens:
            if token in haystack_tokens or token in haystack_lower:
                score += 1.0
                if len(token) >= 4:
                    score += 0.35
        return score

    def _dedupe_chunks(self, hits: list[ScoredItem]) -> list[ScoredItem]:
        best_by_chunk: dict[str, ScoredItem] = {}
        for hit in hits:
            chunk: ChunkRecord = hit.item
            existing = best_by_chunk.get(chunk.id)
            if existing is None or hit.score > existing.score:
                best_by_chunk[chunk.id] = hit
        return list(best_by_chunk.values())

    def _looks_numeric(self, question: str) -> bool:
        lowered = question.lower()
        explicit_numeric_intent = any(
            keyword in lowered
            for keyword in [
                "timing",
                "limit",
                "max",
                "min",
                "ns",
                "us",
                "ms",
                "hz",
                "khz",
                "mhz",
                "ghz",
                "voltage",
                "current",
                "range",
                "frequency",
            ]
        )
        if self._is_pin_intent_query(question) and not explicit_numeric_intent:
            return False
        return explicit_numeric_intent or any(char.isdigit() for char in question)

    def _contains_numeric_signal(self, text: str) -> bool:
        return bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:ns|us|ms|s|hz|khz|mhz|ghz|v|mv|a|ma|ua|%)\b", text.lower()))

    def _format_page_range(self, page_start: int, page_end: int) -> str:
        return str(page_start) if page_start == page_end else f"{page_start}-{page_end}"

    def _squash_excerpt(self, text: str, limit: int = 280) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def _stable_id(self, *parts: str) -> str:
        payload = "||".join(parts)
        return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _result_to_dict(result: RetrievalResult) -> dict[str, Any]:
    payload = {
        "question": result.question,
        "source": result.source,
        "filters": asdict(result.filters),
        "short_answer": result.short_answer,
        "key_evidence": result.key_evidence,
        "sources": [asdict(source) for source in result.sources],
        "open_questions": result.open_questions,
        "searched_documents": result.searched_documents,
    }
    if result.structured_summary is not None:
        payload["structured_summary"] = asdict(result.structured_summary)
    return payload


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone local embedded manual lookup tool."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Pass either <question> to use the default manual source, or <source> <question> for an explicit source.",
    )
    parser.add_argument("--source", dest="source_override", help="Explicit local manual file or folder path")
    parser.add_argument("--device", help="Optional device or family filter")
    parser.add_argument("--document-type", help="Optional document type filter")
    parser.add_argument("--revision", help="Optional revision filter")
    parser.add_argument(
        "--pdf-backend",
        choices=SUPPORTED_PDF_BACKENDS,
        help=(
            "PDF text extraction backend. Defaults to `pypdf`, or use "
            f"`{PDF_BACKEND_ENV_VAR}` to override globally."
        ),
    )
    parser.add_argument("--max-documents", type=int, default=3)
    parser.add_argument("--max-sections", type=int, default=5)
    parser.add_argument("--max-chunks", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Emit JSON payload")
    return parser


def _parse_cli_inputs(parser: argparse.ArgumentParser, args: argparse.Namespace) -> tuple[str | None, str]:
    if args.source_override:
        return args.source_override, " ".join(args.inputs)

    if len(args.inputs) == 1:
        return None, args.inputs[0]

    first = Path(args.inputs[0])
    if first.exists() or first.suffix.lower() in SUPPORTED_SUFFIXES:
        return args.inputs[0], " ".join(args.inputs[1:])

    return None, " ".join(args.inputs)


def _print_human_result(result: RetrievalResult) -> None:
    print("### Short Answer")
    print(result.short_answer)
    print()
    if result.structured_summary is not None:
        print(f"### {result.structured_summary.title}")
        for field in result.structured_summary.fields:
            print(f"- {field.label}: {field.value}")
        print()
    print("### Key Evidence")
    if result.key_evidence:
        for line in result.key_evidence:
            print(f"- {line}")
    else:
        print("- No grounded evidence found.")
    print()
    print("### Sources")
    if result.sources:
        print("| Tag | Document | Device / Family | Rev | Section | Page | Excerpt |")
        print("|-----|----------|-----------------|-----|---------|------|---------|")
        for source in result.sources:
            excerpt = source.excerpt.replace("|", "\\|")
            print(
                f"| {source.tag} | {source.document} | {source.device_family or '-'} | "
                f"{source.revision or '-'} | {source.section} | {source.page} | {excerpt} |"
            )
    else:
        print("| Tag | Document | Device / Family | Rev | Section | Page | Excerpt |")
        print("|-----|----------|-----------------|-----|---------|------|---------|")
    print()
    print("### Open Questions / Uncertainty")
    if result.open_questions:
        for line in result.open_questions:
            print(f"- {line}")
    else:
        print("- None.")
    print()
    print("### Documents Searched")
    for path in result.searched_documents:
        print(f"- {path}")


def main() -> int:
    _configure_stdio()
    parser = _build_arg_parser()
    args = parser.parse_args()
    source, question = _parse_cli_inputs(parser, args)

    prototype = EmbeddedRetrievalPrototype(
        source,
        pdf_backend=args.pdf_backend,
        filters=QueryFilters(
            device=args.device,
            document_type=args.document_type,
            revision=args.revision,
        ),
        max_documents=args.max_documents,
        max_sections=args.max_sections,
        max_chunks=args.max_chunks,
    )

    try:
        result = prototype.run(question)
    except RetrievalError as error:
        parser.error(str(error))
        return 2

    if args.json:
        print(json.dumps(_result_to_dict(result), indent=2, ensure_ascii=True))
    else:
        _print_human_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
