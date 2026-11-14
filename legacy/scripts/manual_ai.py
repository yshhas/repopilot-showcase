"""Manual LLM smoke script — run directly, not via pytest."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from llm import ask_ai


def main():
    question = input("请输入:")
    answer = ask_ai(question)
    print("\nAI回答:")
    print(answer)


if __name__ == "__main__":
    main()
