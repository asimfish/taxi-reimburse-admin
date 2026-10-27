#!/usr/bin/env bash
# 用 uv 在临时环境中运行检查程序：run.sh check|summary|verify|template ...
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
cache="${TAXI_OCR_CACHE:-${TMPDIR:-/tmp}/taxi_reimburse_ocr_cache}"
if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --no-project --python 3.10 \
    --with pymupdf --with openpyxl --with rapidocr_onnxruntime --with pillow --with pypinyin \
    python -m reimburse --cache "$cache" "$@"
fi
exec python3 -m reimburse --cache "$cache" "$@"
