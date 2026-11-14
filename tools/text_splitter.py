import re


def split_text(text):


    # 按题号切割

    parts = re.split(
        r'\n\d+\.',
        text
    )


    chunks = []


    for part in parts:


        part = part.strip()


        if len(part) > 50:

            chunks.append(part)



    return chunks
