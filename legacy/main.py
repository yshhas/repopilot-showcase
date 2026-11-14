"""Keyword-routing demo — not the ReAct main entry."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.calculator import calculate
from tools.weather import weather

# 保存聊天记录
history = []


def main():
    global history

    while True:
        question = input("请输入:").strip()

        # 退出
        if question == "exit":
            print("程序结束")
            break

        # 查看历史记录
        if question == "history":
            print("\n===== 聊天记录 =====")

            if len(history) == 0:
                print("暂无聊天记录")
            else:
                for chat in history:
                    print("用户:", chat["user"])
                    print("AI:", chat["assistant"])
                    print("----------------")

            print("==================\n")
            continue

        # 天气工具
        if "天气" in question:
            answer = weather("北京")
            print(answer)
            history.append({"user": question, "assistant": answer})

        # 计算工具
        elif "计算" in question:
            a = int(input("请输入第一个数字:"))
            b = int(input("请输入第二个数字:"))
            answer = calculate(a, b)
            print(answer)
            history.append({"user": question, "assistant": answer})

        # 不知道的问题
        else:
            answer = "我不知道"
            print(answer)
            history.append({"user": question, "assistant": answer})


if __name__ == "__main__":
    main()
