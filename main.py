import json
import os
import sys
from typing import Optional

from fastapi import FastAPI, HTTPException
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from pydantic import BaseModel


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


app = FastAPI(title="GovEase AI Bot API")


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    source: Optional[str] = None
    confidence_score: Optional[float] = None

# 1. Khai báo đường dẫn tới 2 file JSON của ông
json_files = ["data_khai_sinh.json", "data_tam_tru.json"]
raw_data = []

# Vòng lặp đọc và gom data từ cả 2 file
for file_path in json_files:
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            file_data = json.load(f)
            # Nếu file data là list thì dùng extend để nối vào list tổng
            if isinstance(file_data, list):
                raw_data.extend(file_data)
                print(f"-> Đã load thành công {len(file_data)} sample từ {file_path}")
            else:
                print(f"[Cảnh báo] File {file_path} không đúng định dạng list.")
    else:
        print(f"[Lỗi] Không tìm thấy file: {file_path}")

print(f"==> Tổng số lượng data thu thập được: {len(raw_data)} câu")

# 2. Khởi tạo Embedding Model (Hệ tiếng Việt siêu mượt)
embedding_model = HuggingFaceEmbeddings(model_name="keepitreal/vietnamese-sbert")

# 3. Đóng gói data thành dạng Document của Langchain
documents = []
for idx, item in enumerate(raw_data):
    # Kết hợp instruction và context để tăng độ chính xác khi search ngữ nghĩa
    page_content = f"Câu hỏi: {item.get('instruction', '')}\nNội dung: {item.get('context', '')}"

    # Đẩy response và source vào metadata để tí bốc ra xài luôn cho đỡ hallucination
    metadata = {
        "id": idx,
        "response": item.get("response", "Không có câu trả lời chuẩn."),
        "source_url": item.get("source_url", "Không có nguồn.")
    }
    documents.append(Document(page_content=page_content, metadata=metadata))

# 4. Khởi tạo và lưu vào ChromaDB local
db_dir = "./chroma_db"
if os.path.exists(os.path.join(db_dir, "chroma.sqlite3")):
    vector_db = Chroma(
        persist_directory=db_dir,
        embedding_function=embedding_model,
    )
    db_status = "Loaded existing VectorDB"
else:
    vector_db = Chroma.from_documents(
        documents=documents,
        embedding=embedding_model,
        persist_directory=db_dir
    )
    db_status = f"Indexed {len(documents)} documents into VectorDB"
print(f"==> {db_status} at: {db_dir}")



# 5. Hàm Query chuẩn chỉ, bốc thẳng response (Hallucination = 0%)
def ask_bot(user_question: str):
    # Tìm kiếm thằng khớp nhất (k=1)
    docs_with_score = vector_db.similarity_search_with_score(user_question, k=1)

    if not docs_with_score:
        return "Xin lỗi, hệ thống không tìm thấy thông tin phù hợp."

    best_doc, score = docs_with_score[0]

    # Lấy data từ metadata ra trả về luôn, không thèm qua LLM chế cháo
    response = best_doc.metadata["response"]
    source_url = best_doc.metadata["source_url"]

    return {
        "answer": response,
        "source": source_url,
        "confidence_score": float(score)  # Score càng thấp càng chuẩn
    }


# --- FASTAPI ROUTES ---
@app.get("/")
def health_check():
    return {"message": "GovEase AI Bot API is running"}


@app.post("/bot/ask", response_model=AskResponse)
def ask_bot_route(request: AskRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    result = ask_bot(question)
    if isinstance(result, str):
        return AskResponse(answer=result)

    return AskResponse(**result)


# --- CLI TEST ---
if __name__ == "__main__":

    print("\n--- TEST BOT ---")
    question = "Cần chuẩn bị giấy tờ gì để làm lại khai sinh có yếu tố nước ngoài hả ông?"
    res = ask_bot(question)

    print(f"User: {question}")
    print(f"Bot: {res['answer']}")
    print(f"Nguồn: {res['source']}")
    print(f'Confident Score: {res["confidence_score"]:.2f}')
