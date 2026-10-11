"""Trang tài liệu cho trình đọc (Không gian Nghiên cứu): ảnh PNG, lớp chữ, ô trích dẫn.

Hàm thuần trên một tệp PDF, không chạm cơ sở dữ liệu — router tra tệp gốc rồi
gọi vào đây. Mọi toạ độ trả về là tỉ lệ 0..1 theo trang ĐÃ XOAY (đúng như ảnh
`get_pixmap` vẽ), nên frontend đặt chồng lớp chữ lên ảnh ở bất kỳ zoom nào mà
không cần biết dpi.
"""
from __future__ import annotations

import os
from pathlib import Path

import fitz

MIN_DPI, MAX_DPI, DEFAULT_DPI = 50, 220, 110


class PageNotFoundError(Exception):
    """Số trang ngoài khoảng, hoặc tệp không phải PDF."""


def clamp_dpi(dpi: int | None) -> int:
    if dpi is None:
        return DEFAULT_DPI
    return max(MIN_DPI, min(MAX_DPI, int(dpi)))


def _open(source: Path) -> fitz.Document:
    if source.suffix.lower() != ".pdf" or not source.is_file():
        raise PageNotFoundError(str(source))
    try:
        return fitz.open(str(source))
    except Exception as error:  # fitz raises its own error types
        raise PageNotFoundError(str(source)) from error


def page_count(source: Path) -> int | None:
    """Số trang của một PDF; None nếu không phải PDF hay không mở được."""
    try:
        document = _open(source)
    except PageNotFoundError:
        return None
    try:
        return len(document)
    finally:
        document.close()


def _page(document: fitz.Document, number: int) -> fitz.Page:
    if number < 1 or number > len(document):
        raise PageNotFoundError(str(number))
    return document[number - 1]


def render_page_png(source: Path, number: int, dpi: int, cache_dir: Path | None) -> bytes:
    """PNG của trang `number` (1-based). Cache đĩa `<cache_dir>/<n>@<dpi>.png` nếu
    có; ghi qua tệp tạm rồi đổi tên để hai yêu cầu song song không đọc nửa tệp."""
    dpi = clamp_dpi(dpi)
    cached = cache_dir / f"{number}@{dpi}.png" if cache_dir is not None else None
    if cached is not None and cached.is_file():
        return cached.read_bytes()
    document = _open(source)
    try:
        page = _page(document, number)
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        png = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB).tobytes("png")
    finally:
        document.close()
    if cached is not None:
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            temporary = cached.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_bytes(png)
            os.replace(temporary, cached)
        except OSError:
            pass  # cache là tiện ích, không phải điều kiện
    return png


def normalize_words(raw_words: list[tuple], width: float, height: float, matrix: fitz.Matrix | None = None) -> list[dict[str, object]]:
    """`get_text("words")` → [{x0,y0,x1,y1,text,block,line}] tỉ lệ 0..1.

    `matrix` (page.rotation_matrix) đưa toạ độ chữ sang hệ trang đã xoay — trang
    quét ngang lưu với rotation 90 có chữ ở hệ chưa xoay, ảnh thì đã xoay.
    """
    if width <= 0 or height <= 0:
        return []
    words: list[dict[str, object]] = []
    for item in raw_words:
        x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], str(item[4])
        block = int(item[5]) if len(item) > 5 else 0
        line = int(item[6]) if len(item) > 6 else 0
        if not text.strip():
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        if matrix is not None:
            rect = rect * matrix
        words.append({
            "x0": round(max(0.0, min(1.0, rect.x0 / width)), 5),
            "y0": round(max(0.0, min(1.0, rect.y0 / height)), 5),
            "x1": round(max(0.0, min(1.0, rect.x1 / width)), 5),
            "y1": round(max(0.0, min(1.0, rect.y1 / height)), 5),
            "text": text,
            "block": block,
            "line": line,
        })
    return words


def page_words(source: Path, number: int) -> dict[str, object]:
    document = _open(source)
    try:
        page = _page(document, number)
        rect = page.rect  # đã tính rotation
        width, height = float(rect.width), float(rect.height)
        raw = page.get_text("words")
        matrix = page.rotation_matrix if page.rotation else None
        words = normalize_words(raw, width, height, matrix)
    finally:
        document.close()
    return {"page": number, "width": width, "height": height, "has_text": bool(words), "words": words}


def chunk_boxes(locations: list[dict[str, object]] | None, page: int) -> list[dict[str, float]]:
    """Ô {x,y,w,h} 0..1 của một chunk trên trang `page`, lấy từ `DocumentChunk.locations`.

    Chunker hiện lưu {page,start,end} (độ lệch ký tự), không có bbox, nên hàm trả
    [] cho mọi chunk thật hôm nay; nhánh bbox có sẵn cho khi locations mang x/y/w/h.
    """
    boxes: list[dict[str, float]] = []
    for location in locations or []:
        if not isinstance(location, dict) or location.get("page") != page:
            continue
        if all(key in location for key in ("x", "y", "w", "h")):
            boxes.append({key: float(location[key]) for key in ("x", "y", "w", "h")})
        elif "bbox" in location and isinstance(location["bbox"], (list, tuple)) and len(location["bbox"]) == 4:
            x0, y0, x1, y1 = (float(value) for value in location["bbox"])
            boxes.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return boxes
