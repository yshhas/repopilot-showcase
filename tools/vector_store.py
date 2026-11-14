import chromadb
from chromadb.utils import embedding_functions


# 创建数据库

client = chromadb.PersistentClient(
    path="./database"
)



# 使用默认embedding模型

embedding_func = embedding_functions.DefaultEmbeddingFunction()



collection = client.get_or_create_collection(
    name="knowledge",
    embedding_function=embedding_func
)



# =========================
# 添加文档
# =========================

def add_documents(chunks):


    ids = []


    for i in range(len(chunks)):

        ids.append(
            "doc_" + str(i)
        )


    collection.add(

        documents=chunks,

        ids=ids

    )



# =========================
# 搜索
# =========================

def search(query, n=3):


    result = collection.query(

        query_texts=[
            query
        ],

        n_results=n

    )


    # 关键！！
    # 只返回文本列表

    return result["documents"][0]
