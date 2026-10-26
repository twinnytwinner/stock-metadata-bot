#!/usr/bin/env python3
"""Generate stock-photo titles and up to 50 keywords with Claude, then
write them to CSV files (Adobe Stock, Shutterstock) and/or into the
images' IPTC/XMP metadata with exiftool.

Usage:
    python stock_keywords.py PHOTOS_DIR [--embed] [--hint "Bangkok, Thailand"]
"""

import argparse
import base64
import csv
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import anthropic
from PIL import Image

MODEL = "claude-opus-5-5"
MAX_KEYWORDS = 50
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
# The API downsizes anything larger, so shrink locally to save upload time.
MAX_EDGE = 1568

SYSTEM = """You write metadata for microstock photos (Adobe Stock, Shutterstock, Getty/iStock).

Rules:
- title: one natural, descriptive sentence, 70-200 characters. No keyword stuffing, no brand names, no trademarks.
- description: one or two sentences, max 200 characters.
- keywords: exactly 50 if the image supports that many, otherwise fewer. Never pad with unrelated words.
  - Order by importance: main subject first, then setting, actions, concepts, mood, colors, composition.
  - One concept per keyword (single words or short phrases like "hot air balloon").
  - Lowercase, singular form unless plural is the natural term, no duplicates or near-duplicates.
  - Only describe what is actually visible or clearly implied. Do not guess locations, species,
    landmarks or people's identities unless the user hint states them.
  - No brand names, trademarks, or camera/technical terms like "jpeg" or "high resolution".
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "description", "keywords"],
    "additionalProperties": False,
}


def encode_image(path: Path) -> tuple[str, str]:
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_EDGE, MAX_EDGE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def clean_keywords(keywords: list[str]) -> list[str]:
    seen = set()
    out = []
    for kw in keywords:
        kw = " ".join(kw.strip().lower().split()).strip(",.;")
        if kw and kw not in seen:
            seen.add(kw)
            out.append(kw)
    return out[:MAX_KEYWORDS]


def generate(client: anthropic.Anthropic, path: Path, hint: str, effort: str) -> dict:
    media_type, data = encode_image(path)
    prompt = "Write the title, description and keywords for this photo."
    if hint:
        prompt += f"\nFacts from the photographer (treat as true): {hint}"
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined this image")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("response was cut off (max_tokens)")
    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)
    result["keywords"] = clean_keywords(result["keywords"])
    return result


def embed(path: Path, meta: dict) -> None:
    args = [
        "exiftool", "-overwrite_original", "-codedcharacterset=utf8",
        f"-XMP-dc:Title={meta['title']}",
        f"-IPTC:ObjectName={meta['title'][:64]}",
        f"-IPTC:Headline={meta['title']}",
        f"-XMP-photoshop:Headline={meta['title']}",
        f"-XMP-dc:Description={meta['description']}",
        f"-IPTC:Caption-Abstract={meta['description']}",
        "-XMP-dc:Subject=", "-IPTC:Keywords=",  # clear old keywords first
    ]
    for kw in meta["keywords"]:
        args += [f"-XMP-dc:Subject={kw}", f"-IPTC:Keywords={kw}"]
    args.append(str(path))
    subprocess.run(args, check=True, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="folder with images")
    parser.add_argument("--hint", default="", help="facts the AI can't see, e.g. location or species")
    parser.add_argument("--embed", action="store_true", help="write metadata into JPEG files with exiftool")
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high"],
                        help="lower = cheaper and faster (default: medium)")
    parser.add_argument("--out", type=Path, default=None, help="output folder for CSVs (default: the image folder)")
    args = parser.parse_args()

    if args.embed and not shutil.which("exiftool"):
        sys.exit("--embed needs exiftool: https://exiftool.org")

    images = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        sys.exit(f"No images found in {args.folder}")

    out_dir = args.out or args.folder
    out_dir.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()
    results = []

    for i, path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {path.name} ... ", end="", flush=True)
        try:
            meta = generate(client, path, args.hint, args.effort)
        except Exception as e:  # keep going with the rest of the batch
            print(f"FAILED: {e}")
            continue
        n = len(meta["keywords"])
        print(f"{n} keywords" + ("" if n == MAX_KEYWORDS else "  (fewer than 50, check it)"))
        if args.embed and path.suffix.lower() in {".jpg", ".jpeg"}:
            embed(path, meta)
        results.append((path.name, meta))

    with open(out_dir / "adobe_stock.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Filename", "Title", "Keywords"])
        for name, m in results:
            w.writerow([name, m["title"], ", ".join(m["keywords"])])

    with open(out_dir / "shutterstock.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Filename", "Description", "Keywords"])
        for name, m in results:
            w.writerow([name, m["title"], ",".join(m["keywords"])])

    with open(out_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump({name: m for name, m in results}, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {len(results)}/{len(images)} images. Files saved in {out_dir}")


if __name__ == "__main__":
    main()
