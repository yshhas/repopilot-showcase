import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os

from tools.file_reader import read_file


def read_folder(path):

    result = ""

    try:

        files = os.listdir(path)

        for file in files:

            filepath = os.path.join(
                path,
                file
            )

            # 只读取文件
            if os.path.isfile(filepath):

                content = read_file(filepath)

                result += "\n\n"
                result += "===== " + file + " =====\n"
                result += content

        return result

    except Exception as e:

        return "读取目录失败：" + str(e)
