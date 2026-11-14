import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.file_reader import read_file
from tools.pdf_reader import read_pdf


def ask_document(path, question):

    # 判断文件类型

    if path.lower().endswith(".pdf"):

        content = read_pdf(path)

    else:

        content = read_file(path)

    prompt = f"""
你现在是一个学习助手。

下面是用户提供的学习资料：

----------------
{content}
----------------

请根据资料回答用户问题：

{question}

要求：
1. 只根据资料回答
2. 如果资料没有相关内容，请说明没有找到
3. 回答要清晰、有条理
"""

    return prompt
