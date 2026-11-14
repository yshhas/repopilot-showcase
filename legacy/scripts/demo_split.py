"""Text-splitting demo — needs a local PDF path (edit below)."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.pdf_reader import read_pdf
from tools.text_splitter import split_text

content = read_pdf("高数下册期末复习卷.pdf")

chunks = split_text(content)

print("总片段数量:", len(chunks))

for i, c in enumerate(chunks):
    print("\n第", i, "段:")
    print(c[:200])
