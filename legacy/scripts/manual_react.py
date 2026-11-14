"""Manual ReAct smoke script — run directly, not via pytest."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from react_agent import react_agent


def main():
    question = input("请输入:")
    answer, _memory = react_agent(question)
    print("最终回答:", answer)


if __name__ == "__main__":
    main()
