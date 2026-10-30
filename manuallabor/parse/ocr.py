"""OCR engines (Tesseract CLI, RapidOCR v3) and OcrPage -> PageParse (design section 7)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, Protocol

from manuallabor.contracts.block import OcrWord
from manuallabor.contracts.enums import OcrEngine
from manuallabor.parse.geometry import q, union
from manuallabor.parse.types import Line, OcrPage, PageParse, RawBlock

EngineName = Literal["tesseract", "rapidocr"]

_WS = re.compile(r"\s+")


class OcrEngineAdapter(Protocol):
    engine: OcrEngine

    def available(self) -> bool: ...

    def version(self) -> str: ...

    def ocr_page(self, png: Path, page: int, size_pt: tuple[float, float], dpi: int) -> OcrPage: ...


# --------------------------------------------------------------------------- helpers


def px_to_pt(px: float, dpi: int) -> float:
    """Exact pixel -> PDF point conversion: pt = px * 72 / dpi."""
    return px * 72.0 / dpi


def _clamp_box(box: Sequence[float], w: float, h: float) -> list[float]:
    x0 = min(max(box[0], 0.0), w)
    y0 = min(max(box[1], 0.0), h)
    x1 = min(max(box[2], 0.0), w)
    y1 = min(max(box[3], 0.0), h)
    return [q(min(x0, x1)), q(min(y0, y1)), q(max(x0, x1)), q(max(y0, y1))]


def _unit(x: float) -> float:
    return min(1.0, max(0.0, float(x)))


def _median_height(words: Sequence[OcrWord]) -> float | None:
    hs = [w.bbox[3] - w.bbox[1] for w in words if w.bbox is not None]
    return q(statistics.median(hs)) if hs else None


def _make_line(words: list[OcrWord], native_id: str, text: str | None = None) -> Line:
    boxes = [w.bbox for w in words if w.bbox is not None]
    return Line(
        text=text if text is not None else " ".join(w.text for w in words),
        bbox=union(boxes) if boxes else [0.0, 0.0, 0.0, 0.0],
        size=_median_height(words),
        words=words,
        native_id=native_id,
    )


# --------------------------------------------------------------------------- Tesseract


def _tesseract_bin() -> str | None:
    return shutil.which("tesseract")


# A 300 dpi page takes 2 to 15 s on the reference machine; the timeout only catches a wedged
# process, which otherwise hangs an OCR pool worker forever (design 07 section 15, F13).
TESSERACT_PAGE_TIMEOUT_ENV = "MANUALLABOR_TESSERACT_TIMEOUT"
TESSERACT_PAGE_TIMEOUT_DEFAULT_S = 600
TESSERACT_PROBE_TIMEOUT_S = 30  # `--version`, `--list-langs`


def tesseract_page_timeout() -> int:
    """Seconds one `tesseract` page run may take: $MANUALLABOR_TESSERACT_TIMEOUT or 600."""
    raw = os.environ.get(TESSERACT_PAGE_TIMEOUT_ENV, "").strip()
    if not raw:
        return TESSERACT_PAGE_TIMEOUT_DEFAULT_S
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ValueError(
            f"{TESSERACT_PAGE_TIMEOUT_ENV} must be a positive number of seconds, got {raw!r}"
        )
    return value


def _run_probe(exe: str, flag: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [exe, flag],
            capture_output=True,
            text=True,
            check=False,
            timeout=TESSERACT_PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"tesseract {flag} timed out after {TESSERACT_PROBE_TIMEOUT_S} s ({exe})"
        ) from exc


class TesseractAdapter:
    engine = OcrEngine.tesseract

    def available(self) -> bool:
        return _tesseract_bin() is not None

    def version(self) -> str:
        exe = _tesseract_bin()
        if exe is None:
            return "unavailable"
        first = _run_probe(exe, "--version")
        out = (first.stdout or first.stderr).splitlines()
        head = out[0].strip() if out else "tesseract"
        return f"{head}; eng={self._traineddata_hash(exe)}"

    @staticmethod
    def _traineddata_hash(exe: str) -> str:
        langs = _run_probe(exe, "--list-langs")
        text = (langs.stdout or "") + (langs.stderr or "")
        m = re.search(r'"([^"]+)"', text)
        candidates = []
        if m:
            candidates.append(Path(m.group(1)) / "eng.traineddata")
        if os.environ.get("TESSDATA_PREFIX"):
            candidates.append(Path(os.environ["TESSDATA_PREFIX"]) / "eng.traineddata")
        for c in candidates:
            if c.is_file():
                h = hashlib.sha256()
                with open(c, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                return h.hexdigest()[:12]
        return "unknown"

    def ocr_page(self, png: Path, page: int, size_pt: tuple[float, float], dpi: int) -> OcrPage:
        exe = _tesseract_bin()
        if exe is None:
            raise RuntimeError("tesseract binary not found on PATH")
        env = dict(os.environ)
        env["OMP_THREAD_LIMIT"] = "1"
        timeout = tesseract_page_timeout()
        try:
            proc = subprocess.run(
                [
                    exe,
                    str(png),
                    "stdout",
                    "--dpi",
                    str(dpi),
                    "-l",
                    "eng",
                    "--oem",
                    "1",
                    "--psm",
                    "3",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            # subprocess.run has killed the child; the page fails instead of hanging the worker
            raise RuntimeError(
                f"tesseract timed out after {timeout} s on page {page} ({png}); "
                f"raise {TESSERACT_PAGE_TIMEOUT_ENV} if this page is just slow"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(f"tesseract failed on {png}: {proc.stderr.strip()[:300]}")
        return tesseract_tsv_to_page(proc.stdout, page, size_pt, dpi)


def tesseract_tsv_to_page(tsv: str, page: int, size_pt: tuple[float, float], dpi: int) -> OcrPage:
    """Parse tesseract TSV output (pixels) into an OcrPage in PDF points."""
    w_pt, h_pt = size_pt
    grouped: dict[tuple[int, int, int], list[tuple[int, OcrWord]]] = {}
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        try:
            if int(row["level"]) != 5:
                continue
            text = (row.get("text") or "").strip()
            conf = float(row["conf"])
            if not text or conf < 0:
                continue
            left, top = float(row["left"]), float(row["top"])
            wd, ht = float(row["width"]), float(row["height"])
            key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
            wn = int(row["word_num"])
        except (KeyError, ValueError, TypeError):
            continue
        box = _clamp_box(
            [
                px_to_pt(left, dpi),
                px_to_pt(top, dpi),
                px_to_pt(left + wd, dpi),
                px_to_pt(top + ht, dpi),
            ],
            w_pt,
            h_pt,
        )
        grouped.setdefault(key, []).append(
            (wn, OcrWord(text=text, confidence=_unit(conf / 100.0), bbox=box))
        )
    lines = []
    for key in sorted(grouped):
        words = [w for _, w in sorted(grouped[key], key=lambda t: t[0])]
        lines.append(_make_line(words, f"t{key[0]}.{key[1]}.{key[2]}"))
    return OcrPage(
        page=page,
        engine=OcrEngine.tesseract,
        dpi=dpi,
        width=w_pt,
        height=h_pt,
        lines=lines,
    )


# --------------------------------------------------------------------------- RapidOCR

_RAPID: dict[str, Any] = {}


def _rapid_engine() -> Any:
    if "engine" not in _RAPID:
        from rapidocr import RapidOCR

        from manuallabor.telemetry import disable_library_telemetry

        disable_library_telemetry()  # onnxruntime is imported now (design 06 section 4)
        _RAPID["engine"] = RapidOCR(
            params={
                "Global.log_level": "error",
                "EngineConfig.onnxruntime.intra_op_num_threads": 1,
            }
        )
    return _RAPID["engine"]


def _quad_bbox(quad: Any) -> list[float]:
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return [min(xs), min(ys), max(xs), max(ys)]


def map_rapid_words(
    line_text: str, fragments: Sequence[tuple[str, float, Sequence[float]]]
) -> list[tuple[str, float, list[float]]]:
    """Map RapidOCR fragments onto whitespace tokens of the line text.

    ``fragments`` are (text, score, [x0, y0, x1, y1]). Each token takes the min score and the
    union box of the fragments overlapping its character range (offsets in the line with spaces
    removed). If the fragment concatenation does not equal the line without spaces, the
    fragments themselves are returned as the words.
    """
    tokens = line_text.split()
    stripped = "".join(tokens)
    concat = "".join(f[0] for f in fragments)
    if not fragments or concat != stripped:
        return [(f[0], float(f[1]), list(f[2])) for f in fragments if f[0].strip()]
    spans: list[tuple[int, int]] = []
    pos = 0
    for f in fragments:
        spans.append((pos, pos + len(f[0])))
        pos += len(f[0])
    out: list[tuple[str, float, list[float]]] = []
    start = 0
    for tok in tokens:
        end = start + len(tok)
        hit = [i for i, (s, e) in enumerate(spans) if s < end and e > start]
        if hit:
            boxes = [fragments[i][2] for i in hit]
            box = [
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            ]
            out.append((tok, min(float(fragments[i][1]) for i in hit), box))
        start = end
    return out


class RapidOcrAdapter:
    engine = OcrEngine.rapidocr

    def available(self) -> bool:
        try:
            import rapidocr  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str:
        try:
            return f"rapidocr=={metadata.version('rapidocr')}"
        except metadata.PackageNotFoundError:
            return "rapidocr==unknown"

    def ocr_page(self, png: Path, page: int, size_pt: tuple[float, float], dpi: int) -> OcrPage:
        result = _rapid_engine()(str(png), return_word_box=True)
        txts = list(result.txts) if result.txts is not None else []
        scores = list(result.scores) if result.scores is not None else []
        boxes = result.boxes if result.boxes is not None else []
        frags_all = result.word_results if getattr(result, "word_results", None) is not None else []
        return rapid_to_page(txts, scores, list(boxes), list(frags_all), page, size_pt, dpi)


def rapid_to_page(
    txts: Sequence[str],
    scores: Sequence[float],
    boxes: Sequence[Any],
    word_results: Sequence[Any],
    page: int,
    size_pt: tuple[float, float],
    dpi: int,
) -> OcrPage:
    """Convert RapidOCR line results (pixels) into an OcrPage (PDF points)."""
    w_pt, h_pt = size_pt

    def to_pt(box: Sequence[float]) -> list[float]:
        return _clamp_box([px_to_pt(v, dpi) for v in box], w_pt, h_pt)

    lines: list[Line] = []
    for i, text in enumerate(txts):
        text = _WS.sub(" ", str(text)).strip()
        if not text:
            continue
        score = float(scores[i]) if i < len(scores) else 0.0
        line_box = _quad_bbox(boxes[i]) if i < len(boxes) else None
        frags: list[tuple[str, float, list[float]]] = []
        if i < len(word_results) and word_results[i]:
            frags = [(str(t), float(s), _quad_bbox(b)) for t, s, b in word_results[i]]
        mapped = map_rapid_words(text, frags) if frags else []
        if not mapped and line_box is not None:
            mapped = [(text, score, line_box)]
        words = [
            OcrWord(text=t, confidence=_unit(s), bbox=to_pt(b)) for t, s, b in mapped if t.strip()
        ]
        if not words:
            continue
        line = _make_line(words, f"r{i}", text=text)
        lines.append(line)
    return OcrPage(
        page=page,
        engine=OcrEngine.rapidocr,
        dpi=dpi,
        width=w_pt,
        height=h_pt,
        lines=lines,
    )


# --------------------------------------------------------------------------- roles


def resolve_engine(config_value: str | OcrEngine) -> EngineName:
    """Resolve the configured engine to the one that will actually run as primary.

    ``auto`` picks Tesseract when its binary is on PATH, else RapidOCR. An explicit
    ``tesseract`` falls back to RapidOCR when the binary is missing.
    """
    value = str(getattr(config_value, "value", config_value)).lower()
    have_tess = _tesseract_bin() is not None
    if value == "rapidocr":
        return "rapidocr"
    if value in ("auto", "tesseract"):
        return "tesseract" if have_tess else "rapidocr"
    raise ValueError(f"unknown ocr engine: {config_value!r}")


def _adapter(name: EngineName) -> OcrEngineAdapter:
    return TesseractAdapter() if name == "tesseract" else RapidOcrAdapter()


def _default_warn(message: str) -> None:
    sys.stdout.write(
        json.dumps({"stage": "ocr", "status": "warning", "detail": message}, sort_keys=True) + "\n"
    )


def build_engines(
    config: Any, warn: Callable[[str], None] | None = None
) -> tuple[OcrEngineAdapter, OcrEngineAdapter | None]:
    """Return ``(ocr, ocr_alt)``: the configured engine and the other one, if available.

    Roles swap when the configured engine is unavailable. When only one engine exists,
    ``ocr_alt`` is None and ``warn`` is called once.
    """
    emit = warn or _default_warn
    primary_name = resolve_engine(getattr(config, "ocr_engine", "auto"))
    other_name: EngineName = "rapidocr" if primary_name == "tesseract" else "tesseract"
    primary = _adapter(primary_name)
    other = _adapter(other_name)
    if not primary.available():
        raise RuntimeError("no OCR engine available (install tesseract or rapidocr)")
    if not other.available():
        emit(f"OCR engine {other_name} unavailable; no second reader for scanned pages")
        return primary, None
    return primary, other


def engine_versions(ocr: OcrEngineAdapter, ocr_alt: OcrEngineAdapter | None) -> dict[str, str]:
    """``parser_versions`` entries for the OCR roles."""
    return {
        "ocr": f"{ocr.engine.value}:{ocr.version()}",
        "ocr_alt": f"{ocr_alt.engine.value}:{ocr_alt.version()}" if ocr_alt else "unavailable",
    }


# --------------------------------------------------------------------------- OcrPage -> PageParse


def ocr_page_to_parse(op: OcrPage, role: str, body_size: float | None = None) -> PageParse:
    """Group OCR lines into blocks and guess kinds (design 7.1)."""
    from manuallabor.parse.classify import body_size_of, resolve_kind_guess
    from manuallabor.parse.layout import group_lines_into_blocks

    if body_size is None:
        body_size = body_size_of(op.lines)
    groups = group_lines_into_blocks(op.lines, float(op.width))
    blocks: list[RawBlock] = []
    for order, lines in enumerate(groups):
        if not lines:
            continue
        sizes = [ln.size for ln in lines if ln.size is not None]
        blocks.append(
            RawBlock(
                parser=role,
                page=op.page,
                order=order,
                bbox=union([ln.bbox for ln in lines]),
                kind=resolve_kind_guess(lines, body_size),
                text="\n".join(ln.text for ln in lines),
                lines=list(lines),
                size=q(statistics.median(sizes)) if sizes else None,
                bold=False,
            )
        )
    return PageParse(
        page=op.page,
        width=op.width,
        height=op.height,
        has_text_layer=False,
        blocks=blocks,
    )
