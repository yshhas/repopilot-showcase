"""RAG vector-store demo — needs a local PDF path (edit below)."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.pdf_reader import read_pdf
from tools.text_splitter import split_text
from tools.vector_store import add_documents, search

# 读取 PDF（请改为本机存在的 PDF 路径）
text = read_pdf("高数下册期末复习卷.pdf")

# 切片
chunks = split_text(text)

print("切片数量:", len(chunks))

# 加入数据库
add_documents(chunks)

print("数据库建立完成")

# 测试搜索
result = search("有没有二重积分")

print("\n搜索结果:")
for r in result:
    print("----------------")
    print(r)
