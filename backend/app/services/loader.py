from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterable
import logging

from docx import Document
from PIL import Image
import pdfplumber
from pypdf import PdfReader
import pytesseract

try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


class DocumentLoadError(Exception):
    pass


def iter_supported_files(path: Path) -> Iterable[Path]:
    if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
        yield path
        return

    if path.is_dir():
        for file in path.rglob("*"):
            if file.is_file() and file.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield file


def load_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()

    try:
        if suffix in {".txt", ".md"}:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            return _load_pdf_text(file_path)
        if suffix == ".docx":
            doc = Document(str(file_path))
            return "\n".join([p.text for p in doc.paragraphs])
    except Exception as exc:
        raise DocumentLoadError(f"Failed to parse {file_path}: {exc}") from exc

    raise DocumentLoadError(f"Unsupported file type: {file_path.suffix}")


def _load_pdf_text(file_path: Path) -> str:
    text_sections: list[str] = []
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            for page_index, page in enumerate(pdf.pages):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    text_sections.append(f"[PAGE {page_index + 1} TEXT]\n{page_text}")
                else:
                    ocr_page_text = _ocr_full_pdf_page(file_path, page_index + 1)
                    if ocr_page_text:
                        text_sections.append(f"[PAGE {page_index + 1} OCR]\n{ocr_page_text}")
                    else:
                        text_sections.append(f"[PAGE {page_index + 1}] OCR fallback unavailable or no readable text.")

                tables = page.extract_tables() or []
                for table_index, table in enumerate(tables):
                    normalized_rows: list[str] = []
                    for row in table:
                        cells = [str(cell).strip() if cell is not None else "" for cell in row]
                        if any(cells):
                            normalized_rows.append(" | ".join(cells))

                    if normalized_rows:
                        table_blob = "\n".join(normalized_rows)
                        text_sections.append(f"[PAGE {page_index + 1} TABLE {table_index + 1}]\n{table_blob}")
    except Exception as exc:
        logger.warning("pdfplumber extraction failed for %s: %s", file_path, exc)

    try:
        reader = PdfReader(str(file_path))
        for page_index, page in enumerate(reader.pages):
            page_images = list(page.images)
            if page_images:
                text_sections.append(f"[PAGE {page_index + 1}] Found {len(page_images)} embedded image(s).")

            for image_index, image in enumerate(page_images):
                image_note = _extract_image_ocr(image.data, page_index + 1, image_index + 1)
                if image_note:
                    text_sections.append(image_note)
    except Exception as exc:
        logger.warning("pypdf image extraction failed for %s: %s", file_path, exc)

    final_text = "\n\n".join([section for section in text_sections if section.strip()]).strip()
    if not final_text:
        raise DocumentLoadError(
            "No text extracted from PDF. Ensure tesseract and poppler are installed for OCR fallback.",
        )

    return final_text


def _ocr_full_pdf_page(file_path: Path, page_number: int) -> str:
    if convert_from_path is None:
        return ""

    try:
        images = convert_from_path(
            str(file_path),
            first_page=page_number,
            last_page=page_number,
            dpi=300,
        )
    except Exception as exc:
        logger.warning("full-page OCR render failed for %s page %s: %s", file_path, page_number, exc)
        return ""

    if not images:
        return ""

    try:
        image = images[0]
        if image.mode != "RGB":
            image = image.convert("RGB")
        return pytesseract.image_to_string(image).strip()
    except Exception as exc:
        logger.warning("full-page OCR failed for %s page %s: %s", file_path, page_number, exc)
        return ""


def _extract_image_ocr(image_bytes: bytes, page_number: int, image_number: int) -> str | None:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            ocr_text = pytesseract.image_to_string(img).strip()
    except Exception as exc:
        return f"[PAGE {page_number} IMAGE {image_number}] Embedded image present, OCR unavailable or failed: {exc}"

    if not ocr_text:
        return f"[PAGE {page_number} IMAGE {image_number}] Embedded image present, no readable text detected."

    return f"[PAGE {page_number} IMAGE {image_number} OCR]\n{ocr_text}"
