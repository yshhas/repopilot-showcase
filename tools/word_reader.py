from docx import Document



def read_word(path):

    doc = Document(path)

    text = ""


    for paragraph in doc.paragraphs:

        text += paragraph.text + "\n"


    return text
