from openai import OpenAI
from dotenv import load_dotenv
import os


load_dotenv()


_client = None



def _get_client():

    global _client

    if _client is None:

        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:

            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set (required for summarizer)"
            )

        _client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )

    return _client



def summarize(text):


    client = _get_client()


    response = client.chat.completions.create(

        model="deepseek-chat",


        messages=[

            {
                "role": "system",
                "content": "你是一个专业的信息总结助手，请简洁准确地总结用户提供的内容。"
            },


            {
                "role": "user",
                "content": text
            }

        ]

    )


    result = response.choices[0].message.content


    return result
