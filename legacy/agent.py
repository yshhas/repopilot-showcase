"""Early RAG learning assistant — not the ReAct main entry."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import json
import os

from llm import ask_ai
from tools.calculator import calculate
from tools.pdf_reader import read_pdf
from tools.summarizer import summarize
from tools.text_reader import read_text
from tools.text_splitter import split_text
from tools.vector_store import add_documents, search
from tools.word_reader import read_word

# ==========================
# 配置
# ==========================

memory_file = str(Path(__file__).resolve().parent / "memory.json")

rag_ready = False

current_file = None


# ==========================
# 加载记忆
# ==========================

def normalize_memory(raw):

    normalized = []

    for item in raw:

        if "role" in item and "content" in item:

            normalized.append(item)

        elif "user" in item and "assistant" in item:

            normalized.append(
                {
                    "role": "user",
                    "content": item["user"]
                }
            )

            normalized.append(
                {
                    "role": "assistant",
                    "content": item["assistant"]
                }
            )

    return normalized


def load_memory():

    if os.path.exists(memory_file):

        try:

            with open(
                memory_file,
                "r",
                encoding="utf-8"
            ) as f:

                raw = json.load(f)

            return normalize_memory(raw)

        except:

            return []

    return []


memory = load_memory()


# ==========================
# 保存记忆
# ==========================

def save_memory():

    with open(
        memory_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            memory,
            f,
            ensure_ascii=False,
            indent=2
        )


# ==========================
# 建立知识库
# ==========================

def load_pdf(path):

    global rag_ready
    global current_file

    try:

        print("正在读取文件...")

        if path.endswith(".pdf"):

             text = read_pdf(path)

        elif path.endswith(".docx"):

             text = read_word(path)

        elif path.endswith(".txt"):

             text = read_text(path)

        else:

             print("暂不支持该文件类型")

             return

        chunks = split_text(
            text
        )

        if len(chunks)==0:

            print(
                "没有读取到文本"
            )

            return

        add_documents(
            chunks
        )

        rag_ready = True

        current_file = path

        print(
            "知识库建立完成，共",
            len(chunks),
            "个片段"
        )

    except Exception as e:

        print(
            "PDF读取失败:",
            e
        )


# ==========================
# RAG回答
# ==========================

def rag_chat(question):

    try:

        docs = search(
            question,
            n=3
        )

        if not docs:

            return None

        # 防止返回字典导致错误

        if isinstance(
            docs[0],
            dict
        ):

            context = "\n\n".join(
                [
                    x.get(
                        "text",
                        ""
                    )
                    for x in docs
                ]
            )

        else:

            context = "\n\n".join(
                docs
            )

        prompt = f"""

你是一名资料分析助手。

当前资料：

{current_file}

资料内容：

====================

{context}

====================

用户问题：

{question}

回答要求：

1. 优先使用资料内容
2. 不要编造资料没有的信息
3. 如果资料没有答案，明确说明
4. 给出详细解释

"""

        return ask_ai(
            prompt
        )

    except Exception as e:

        print(
            "RAG错误:",
            e
        )

        return None


# ==========================
# 主程序
# ==========================

if __name__ == "__main__":

    while True:

        question = input(
            "请输入:"
        )

        if question=="exit":

            break

        # ----------------------
        # PDF加载
        # ----------------------

        if question.startswith("读取"):

            path = question.replace(
                "读取",
                ""
            ).strip()

            if not os.path.exists(path):

                print(
                    "文件不存在:",
                    path
                )

                continue

            load_pdf(
                path
            )

            continue

        # ----------------------
        # RAG模式
        # ----------------------

        if rag_ready:

            answer = rag_chat(
                question
            )

            if answer:

                print(
                    "AI:",
                    answer
                )

                memory.append(
                    {
                        "role": "user",
                        "content": question
                    }
                )

                memory.append(
                    {
                        "role": "assistant",
                        "content": answer
                    }
                )

                save_memory()

                continue

        # ----------------------
        # 普通聊天
        # ----------------------

        memory.append(
            {
                "role":"user",
                "content":question
            }
        )

        answer = ask_ai(
            memory
        )

        print(
            "AI:",
            answer
        )

        memory.append(
            {
                "role":"assistant",
                "content":answer
            }
        )

        save_memory()
