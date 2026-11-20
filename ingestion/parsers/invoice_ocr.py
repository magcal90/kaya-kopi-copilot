#!/usr/bin/env python3
"""OCR images into provenance-rich JSON sidecars.

The defaults assume this module lives at ``ingestion/parsers/invoice_ocr.py``:

* input:  ``data/images``
* output: ``runtime/ocr``

PaddleOCR and its PaddlePaddle runtime must be installed in the Python environment.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    root = project_root()
    parser = argparse.ArgumentParser(
        description="OCR images recursively and write .ocr.json sidecars."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=root / "data" / "images",
        help="image directory to scan recursively (default: data/images)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "runtime" / "ocr",
        help="output root (default: runtime/ocr)",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="PaddleOCR language/model code, such as en or ch (default: en)",
    )
    parser.add_argument(
        "--write-text",
        action="store_true",
        help="also write a human-readable .ocr.txt sidecar",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing OCR output instead of skipping it",
    )
    return parser.parse_args()


def discover_images(input_dir: Path) -> Iterable[Path]:
    return (
        path
        for path in sorted(input_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def prepare_image(source: Path, destination: Path) -> tuple[int, int]:
    """Normalize orientation and contrast before OCR, without changing the source."""
    from PIL import Image, ImageOps

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("L")
        image = ImageOps.autocontrast(image)
        width, height = image.size
        image.save(destination, format="PNG")
    return width, height


def _result_payload(result: Any) -> dict[str, Any]:
    """Return the serializable payload exposed by a PaddleOCR 3.x result."""
    payload = getattr(result, "json", result)
    if callable(payload):
        payload = payload()
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected PaddleOCR result type: {type(payload).__name__}")
    nested = payload.get("res")
    return nested if isinstance(nested, dict) else payload


def run_paddleocr(ocr: Any, image: Path) -> tuple[str, list[dict[str, Any]]]:
    results = list(ocr.predict(input=str(image)))
    if not results:
        return "", []

    payload = _result_payload(results[0])
    texts = payload.get("rec_texts", [])
    scores = payload.get("rec_scores", [])
    polygons = payload.get("rec_polys", payload.get("dt_polys", []))
    regions: list[dict[str, Any]] = []
    for line_number, (text, score, polygon) in enumerate(
        zip(texts, scores, polygons), start=1
    ):
        text = str(text).strip()
        if not text:
            continue
        points = [[int(round(float(x))), int(round(float(y)))] for x, y in polygon]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        regions.append(
            {
                "text": text,
                # Keep the existing 0-100 confidence scale used by the sidecars.
                "confidence": round(float(score) * 100, 2),
                "bbox": {
                    "left": min(xs),
                    "top": min(ys),
                    "width": max(xs) - min(xs),
                    "height": max(ys) - min(ys),
                },
                "polygon": points,
                "page": 1,
                "block": 1,
                "paragraph": 1,
                "line": line_number,
            }
        )
    return "\n".join(region["text"] for region in regions), regions


def output_paths(source: Path, input_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    relative = source.relative_to(input_dir)
    base = output_dir / relative.parent / relative.name
    return Path(f"{base}.ocr.json"), Path(f"{base}.ocr.txt")


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    try:
        import PIL  # noqa: F401
        from paddleocr import PaddleOCR
    except ModuleNotFoundError:
        print(
            "error: OCR dependencies are not installed; run "
            "'python3 -m pip install -r ingestion/requirements-ocr.txt'",
            file=sys.stderr,
        )
        return 2
    if not input_dir.is_dir():
        print(f"error: input directory does not exist: {input_dir}", file=sys.stderr)
        return 2
    if input_dir == output_dir or input_dir in output_dir.parents:
        print("error: output directory must not be inside the input directory", file=sys.stderr)
        return 2

    images = list(discover_images(input_dir))
    if not images:
        print(f"No supported images found under {input_dir}")
        return 0

    # Disable optional document preprocessing models: invoice images only need the
    # text detector and recognizer, which keeps startup and downloads smaller.
    ocr = PaddleOCR(
        lang=args.language,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        # PaddlePaddle 3.3's oneDNN executor cannot run PP-OCRv6's array
        # attributes on some CPUs (ConvertPirAttribute2RuntimeAttribute).
        enable_mkldnn=False,
    )

    succeeded = skipped = failed = 0
    for source in images:
        json_path, text_path = output_paths(source, input_dir, output_dir)
        if json_path.exists() and not args.overwrite:
            print(f"SKIP {source.relative_to(input_dir)}")
            skipped += 1
            continue

        json_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="ocr-") as temp_dir:
                prepared = Path(temp_dir) / "prepared.png"
                width, height = prepare_image(source, prepared)
                text, words = run_paddleocr(ocr, prepared)

            confidences = [word["confidence"] for word in words]
            payload = {
                "schema_version": "1.0",
                "source": source.relative_to(input_dir).as_posix(),
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "engine": "paddleocr",
                "language": args.language,
                "image": {"width": width, "height": height},
                "text": text,
                "mean_word_confidence": (
                    round(sum(confidences) / len(confidences), 2) if confidences else None
                ),
                "words": words,
            }
            json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if args.write_text:
                text_path.write_text(text + ("\n" if text else ""), encoding="utf-8")
            print(f"OK   {source.relative_to(input_dir)} -> {json_path.relative_to(output_dir)}")
            succeeded += 1
        except (OSError, RuntimeError, ValueError) as error:
            print(f"FAIL {source.relative_to(input_dir)}: {error}", file=sys.stderr)
            failed += 1

    print(f"Processed: {succeeded}; skipped: {skipped}; failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
