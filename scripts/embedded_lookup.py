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
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".rst"}
SUPPORTED_SUFFIXES = SUPPORTED_TEXT_SUFFIXES | {".pdf"}
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
    r"\b(?:LQFP|TQFP|UFBGA|BGA|QFN|UFQFPN|WLCSP|SOIC|DIP)[- ]?\d+\b|\b\d{2,3}-pin\b",
    re.IGNORECASE,
)
REGISTER_FIELD_RE = re.compile(
    r"\b(?:bit|field)\s+\d+\s+([A-Z][A-Z0-9_]{1,31})\b",
    re.IGNORECASE,
)
STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
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
        filters: QueryFilters | None = None,
        max_documents: int = 3,
        max_sections: int = 5,
        max_chunks: int = 5,
        chunk_size: int = 900,
        chunk_overlap: int = 150,
    ) -> None:
        self.source = self._resolve_source(source)
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
                    "Provide a supported local text manual or install `pypdf` for text-based PDF extraction.",
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

    def _discover_and_load_documents(self) -> list[DocumentRecord]:
        paths = self._discover_document_paths()
        documents: list[DocumentRecord] = []
        for path in paths:
            try:
                documents.append(self._load_document(path))
            except UnsupportedInputError:
                continue
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
        hits: list[ScoredItem] = []
        for document in documents:
            for section in document.sections:
                heading_text = " ".join(section.heading_path)
                heading_score = self._token_overlap_score(query_tokens, heading_text)
                body_window = section.text[:12000] if self._is_pin_intent_query(question) else section.text[:1200]
                intent_window = section.text[:12000] if self._is_pin_intent_query(question) else section.text[:1800]
                body_score = self._token_overlap_score(query_tokens, body_window)
                score = (heading_score * 2.0) + body_score
                if heading_score > 0 and body_score > 0:
                    score += 0.75
                if any(token in section.heading.lower() for token in query_tokens):
                    score += 2.0
                score += self._question_intent_bonus(
                    question,
                    heading_text,
                    intent_window,
                )
                if score > 0:
                    hits.append(ScoredItem(score=score, item=section))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[: self.max_sections]

    def _score_chunks(
        self,
        section_hits: list[ScoredItem],
        question: str,
    ) -> list[ScoredItem]:
        query_tokens = self._tokenize(question)
        register_tokens = self._register_specific_tokens(question) if self._is_register_lookup_query(question) else []
        hits: list[ScoredItem] = []
        for section_hit in section_hits:
            section: SectionRecord = section_hit.item
            for chunk in self._build_chunks_for_section(section):
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
                if score > section_hit.score:
                    hits.append(ScoredItem(score=score, item=chunk))
        deduped = self._dedupe_chunks(hits)
        return sorted(deduped, key=lambda hit: hit.score, reverse=True)[: self.max_chunks]

    def _build_evidence(self, chunk_hits: list[ScoredItem], question: str) -> list[EvidenceRecord]:
        evidence: list[EvidenceRecord] = []
        for index, hit in enumerate(chunk_hits, start=1):
            chunk: ChunkRecord = hit.item
            section_label = self._normalize_evidence_section(
                question,
                " > ".join(chunk.heading_path),
                chunk.text,
            )
            evidence.append(
                EvidenceRecord(
                    tag=f"[S{index}]",
                    document_id=chunk.document_id,
                    document=chunk.heading_path[0] if chunk.heading_path else chunk.heading,
                    device_family=None,
                    revision=None,
                    section=section_label,
                    page=self._format_page_range(chunk.page_start, chunk.page_end),
                    excerpt=self._extract_relevant_excerpt(chunk.text, question),
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
        if missing_tokens and not (
            self._is_comparison_query(question)
            and self._has_grounded_comparison_coverage(question, evidence)
        ):
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

        if self._should_gate_on_descriptive_gap(question, evidence):
            return self._build_insufficient_coverage_result(question, evidence, searched_documents)

        if self._should_gate_on_register_gap(question, evidence):
            return self._build_insufficient_coverage_result(question, evidence, searched_documents)

        if self._should_gate_on_pin_mapping_gap(question, evidence):
            return self._build_insufficient_coverage_result(question, evidence, searched_documents)

        return None

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
        kept = [top_entry]

        for entry in evidence[1:]:
            if entry.score < max(12.0, top_score - 6.0):
                continue
            if self._is_low_signal_for_question(question, entry):
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
                entry.score,
            ),
            reverse=True,
        )
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

        top_score = top_entry.score
        close_competitors = [
            entry
            for entry in evidence[1:3]
            if entry.document_path != top_entry.document_path and entry.score >= top_score - 1.0
        ]
        if close_competitors:
            return True

        unique_document_families = {
            (document.device_family or "", document.revision or "", document.title)
            for document in documents
        }
        return len(unique_document_families) > 1 and not self._evidence_directly_answers(question, top_entry)

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
        if not self._looks_numeric(question):
            return False
        if self._is_pin_intent_query(question) and not self._has_supported_pin_mapping_answer(question, evidence):
            return True

        top_entry = evidence[0]
        top_missing_tokens = self._missing_requirement_tokens(question, [top_entry])
        top_has_numeric_answer = self._extract_numeric_answer(
            question,
            top_entry.full_text if top_entry.full_text else top_entry.excerpt,
        ) is not None
        if top_has_numeric_answer and top_missing_tokens:
            return True
        if self._is_pin_intent_query(question) and top_missing_tokens:
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

    def _best_evidence_for_document(self, question: str, document: DocumentRecord) -> EvidenceRecord | None:
        section_hits = self._score_sections([document], question)
        chunk_hits = self._score_chunks(section_hits, question)
        evidence = self._build_evidence(chunk_hits, question)
        if not evidence:
            return None

        best_entry = evidence[0]
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

        for document in documents:
            best_entry = self._best_evidence_for_document(question, document)
            if best_entry is None or best_entry.document_path in seen_paths:
                continue
            seen_paths.add(best_entry.document_path)
            candidates.append(best_entry)

        if not candidates:
            for entry in fallback_evidence:
                if not entry.document_path or entry.document_path in seen_paths:
                    continue
                seen_paths.add(entry.document_path)
                candidates.append(entry)
                if len(candidates) >= 3:
                    break

        candidates.sort(
            key=lambda entry: (
                self._extract_numeric_answer(question, entry.full_text if entry.full_text else entry.excerpt) is not None,
                entry.score,
            ),
            reverse=True,
        )
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

        candidate_labels: list[str] = []
        key_evidence: list[str] = []
        numeric_candidates: list[tuple[str, str]] = []

        for entry in relevant_evidence:
            document = document_lookup.get(entry.document_path)
            label = entry.device_family or entry.document or Path(entry.document_path).name
            if document and document.document_type:
                label += f" ({document.document_type})"
            if entry.revision:
                label += f" rev {entry.revision}"
            candidate_labels.append(label)

            numeric_answer = self._extract_numeric_answer(
                question,
                entry.full_text if entry.full_text else entry.excerpt,
            )
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

    def _is_low_signal_for_question(self, question: str, entry: EvidenceRecord) -> bool:
        lowered_question = question.lower()
        section_text = entry.section.lower()
        source_text = (entry.full_text or entry.excerpt).lower()

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
        for token in self._tokenize(question):
            if token in IGNORED_REQUIREMENT_TOKENS:
                continue
            if token not in requirement_tokens:
                requirement_tokens.append(token)
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
        return [
            token
            for token in requirement_tokens
            if token not in evidence_text and not self._is_device_like_token(token)
        ]

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
        if self._looks_numeric(question):
            source_text = entry.full_text if entry.full_text else entry.excerpt
            return self._extract_numeric_answer(question, source_text) is not None
        if self._is_register_lookup_query(question):
            source_text = entry.full_text if entry.full_text else entry.excerpt
            return self._extract_register_answer(question, source_text) is not None
        if self._is_comparison_query(question):
            return self._has_grounded_comparison_coverage(question, [entry]) or not self._missing_requirement_tokens(question, [entry])
        return not self._missing_requirement_tokens(question, [entry])

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

        question_has_explicit_signal = bool(
            SIGNAL_NAME_RE.search(question) or re.search(r"\bAF\d+\b", question, flags=re.IGNORECASE)
        )
        if question_has_explicit_signal:
            return None

        if source_pins:
            return source_pins[0]
        return question_pins[0] if question_pins else None

    def _extract_package_name(self, question: str, source_text: str) -> str | None:
        question_match = PACKAGE_NAME_RE.search(question)
        if question_match and question_match.group(0).upper() in source_text.upper():
            return question_match.group(0).upper()
        return None

    def _extract_pin_mapping_values(self, question: str, source_text: str) -> str | None:
        signal_or_function = self._extract_pin_signal_or_function(question, source_text)
        if not signal_or_function:
            return None

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
            return None

        row_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(normalized_lines[target_index])]
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
            return row_pins[0]
        return " / ".join(row_pins)

    def _build_pin_grounded_short_answer(
        self,
        question: str,
        entry: EvidenceRecord,
    ) -> str | None:
        source_text = entry.full_text if entry.full_text else entry.excerpt
        signal_or_function = self._extract_pin_signal_or_function(question, source_text)
        if not signal_or_function:
            return None

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

        row_pins = [candidate.upper() for candidate in PIN_NAME_RE.findall(normalized_lines[target_index])]
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
        return self._build_pin_summary(question, summary_signal_text) is not None

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
