from pypdf import PdfReader



def read_pdf(path):


    try:


        reader = PdfReader(path)


        content = ""


        for page in reader.pages:


            text = page.extract_text()


            if text:


                content += text + "\n"



        if content == "":


            return "PDF没有提取到文字，可能是扫描图片PDF"



        return content



    except Exception as e:


        return "PDF读取失败：" + str(e)
