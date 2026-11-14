import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.file_reader import read_file
from tools.pdf_reader import read_pdf
from tools.summarizer import summarize


def analyze_file(path):

    # 判断文件类型

    if path.lower().endswith(".pdf"):

        content = read_pdf(path)

    else:

        content = read_file(path)

    result = summarize(content)

    return result
