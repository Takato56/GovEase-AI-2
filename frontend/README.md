# GovEase AI Frontend

React prototype cho khung chatbot AI lấy cảm hứng từ Cổng Dịch vụ công Quốc gia. Nội dung hội thoại dùng Markdown, có thể nạp prompt từ file `.md` và xuất transcript `.md`.

## Chạy thử

```powershell
cd frontend
pnpm install
pnpm dev
```

Nếu muốn kết nối backend FastAPI hiện có:

```powershell
uvicorn main:app --reload --port 8000
```

Vite proxy sẽ chuyển request `/bot/ask` sang `http://127.0.0.1:8000`.

## Cấu trúc

- `src/App.jsx`: giao diện portal và logic chatbot.
- `src/lib/markdown.js`: render, strip và export Markdown.
- `public/chat-samples/*.md`: prompt mẫu cho khung chat.
- `public/assets/*`: visual assets nội bộ cho giao diện.
