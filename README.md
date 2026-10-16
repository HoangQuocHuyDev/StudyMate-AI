# StudyMate AI

StudyMate AI là website tiếng Việt hỗ trợ sinh viên quản lý, tóm tắt và tra cứu tài liệu học tập. Hệ thống sử dụng Gemini API kết hợp kỹ thuật Retrieval-Augmented Generation (RAG): nội dung tài liệu được trích xuất, chia thành các đoạn nhỏ, lập chỉ mục trong ChromaDB và truy xuất làm nguồn cho câu trả lời của AI.

## Chức năng chính

### Người dùng

- Đăng ký, đăng nhập, đăng xuất và xác thực JWT Bearer.
- Quản lý tài liệu PDF/DOCX: tải lên, xử lý, tìm kiếm, lọc, phân trang, xem PDF, tải xuống và xóa an toàn.
- Lập chỉ mục tài liệu bằng Gemini Embedding và ChromaDB.
- Tạo bản tóm tắt `SHORT`, `STANDARD` hoặc `DETAILED`; kết quả đã tạo được lưu để tái sử dụng.
- Hỏi đáp trên tài liệu bằng RAG, kèm trích dẫn đến đoạn và trang nguồn khi có.
- Xem lại lịch sử hội thoại, tải thêm tin nhắn cũ và mở lại đúng phiên chat.
- Dashboard hiển thị thống kê và tài liệu gần đây từ dữ liệu thật.
- Settings: cập nhật họ tên, đổi mật khẩu và chuyển Light/Dark Mode.

### Quản trị viên

- Dashboard toàn hệ thống: người dùng, tài liệu, phiên hội thoại và hoạt động gần đây.
- Danh sách người dùng, tìm kiếm/lọc và khóa hoặc mở khóa tài khoản.
- Danh sách tài liệu toàn hệ thống, tìm kiếm/lọc và xem metadata an toàn.
- Phân quyền USER/ADMIN được kiểm tra lại từ PostgreSQL ở Backend.

> Admin Documents hiện chỉ hỗ trợ xem metadata. Hệ thống chưa cung cấp chức năng ADMIN xem nội dung, tải xuống hoặc xóa tài liệu của người dùng.

## Công nghệ

### Frontend

- React 19 và React DOM.
- Vite 8.
- `react-markdown` 10 để hiển thị Markdown an toàn trong Chat và Summary.
- Oxlint.
- Node.js test runner (`node --test`).

### Backend

- Python 3.12, FastAPI và Uvicorn.
- SQLAlchemy 2.x, PostgreSQL và Psycopg 3.
- Alembic để quản lý migration.
- Pydantic (thông qua FastAPI) để validate request/response.
- PyJWT với HS256, issuer, audience và `token_version` để thu hồi token.
- `pwdlib[argon2]` để băm mật khẩu.
- `pypdf` và `python-docx` để trích xuất nội dung PDF/DOCX.
- ChromaDB 1.5.9 với cosine distance.
- Google Gen AI SDK 2.29.0 cho embedding, tóm tắt và trả lời RAG.

## Kiến trúc xử lý tài liệu

```text
PDF/DOCX
   │
   ├─► kiểm tra định dạng, MIME và cấu trúc tệp
   ├─► trích xuất văn bản
   ├─► chia chunks và lưu PostgreSQL
   ├─► Gemini Embedding (768 chiều)
   ├─► lập chỉ mục ChromaDB
   └─► Summary hoặc RAG Chat + citation
```

PostgreSQL là nguồn xác thực quyền sở hữu và nội dung chunk. Metadata từ ChromaDB không được dùng để tự cấp quyền truy cập. Các tài liệu đang trong quy trình xóa được loại khỏi truy vấn bằng tombstone; cleanup vector, tệp và dữ liệu quan hệ được theo dõi qua deletion job có lease/retry.

## Yêu cầu hệ thống

- Windows 11 hoặc môi trường tương đương có PowerShell.
- Python 3.12.
- Node.js `^20.19.0` hoặc `>=22.12.0` (yêu cầu của Vite 8) và npm.
- PostgreSQL 18 chạy tại `127.0.0.1:5432`.
- Gemini API key hợp lệ để dùng Embedding, Summary và RAG Chat.

## Cài đặt trên Windows

### 1. Lấy source code

```powershell
git clone https://github.com/QuocHuyVipPro/StudyMate-AI.git
Set-Location "StudyMate-AI"
```

Nếu thư mục clone có tên khác, hãy thay đường dẫn trong các lệnh tiếp theo cho phù hợp.

### 2. Chuẩn bị PostgreSQL

Cấu hình hiện tại yêu cầu database `studymate_ai_db`, PostgreSQL user `postgres`, host `127.0.0.1` và port `5432`.

Tạo database bằng công cụ quản trị PostgreSQL hoặc lệnh sau:

```powershell
createdb -h 127.0.0.1 -p 5432 -U postgres studymate_ai_db
```

Không đưa mật khẩu PostgreSQL vào source code hoặc Git.

### 3. Cài đặt Backend

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` bao gồm dependencies chạy ứng dụng trong `requirements.txt` và các công cụ test Backend.

### 4. Cấu hình Backend

Repository hiện chưa có `backend/.env.example`. Hãy tự tạo `backend/.env` với tối thiểu các biến sau; thay các placeholder bằng giá trị riêng trên máy và không commit file này:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:<POSTGRES_PASSWORD>@127.0.0.1:5432/studymate_ai_db
JWT_SECRET_KEY=<RANDOM_SECRET_AT_LEAST_32_CHARACTERS>
GEMINI_API_KEY=<GEMINI_API_KEY>
```

Có thể tạo JWT secret ngẫu nhiên bằng Python:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Các biến tùy chọn đã được Backend hỗ trợ:

| Biến | Mặc định | Mục đích |
|---|---:|---|
| `JWT_ALGORITHM` | `HS256` | Thuật toán ký JWT; cấu hình hiện chỉ chấp nhận HS256. |
| `JWT_ISSUER` | `studymate-ai` | Issuer của access token. |
| `JWT_AUDIENCE` | `studymate-ai-api` | Audience của access token. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Thời hạn access token. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Danh sách origin, phân tách bằng dấu phẩy. |
| `STORAGE_ROOT` | `backend/storage/documents` | Nơi lưu tài liệu gốc. |
| `MAX_UPLOAD_SIZE_BYTES` | `10485760` | Dung lượng upload tối đa (10 MiB). |
| `CHROMA_PERSIST_DIRECTORY` | `backend/storage/chroma` | Thư mục dữ liệu ChromaDB. |
| `CHROMA_COLLECTION_NAME` | `studymate_document_chunks_gemini2_768_v1` | Collection lưu vector chunks. |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | Model embedding. |
| `GEMINI_EMBEDDING_DIMENSIONS` | `768` | Số chiều vector. |
| `GEMINI_CHAT_MODEL` | `gemini-3.5-flash-lite` | Model dùng cho Chat và Summary. |
| `GEMINI_CHAT_TIMEOUT_SECONDS` | `30` | Timeout tối đa của từng request Gemini. |
| `RAG_MAX_CONTEXT_CHARS` | `12000` | Giới hạn context RAG. |
| `RAG_MAX_COSINE_DISTANCE` | không bật | Ngưỡng cosine distance tùy chọn (`0..2` hoặc `off`). |
| `SUMMARY_GLOBAL_CONCURRENCY` | `4` | Số tác vụ Summary đồng thời toàn hệ thống. |
| `SUMMARY_USER_CONCURRENCY` | `1` | Số tác vụ Summary đồng thời trên mỗi user. |
| `CHAT_GLOBAL_CONCURRENCY` | `4` | Số tác vụ Chat đồng thời toàn hệ thống. |
| `CHAT_USER_CONCURRENCY` | `1` | Số tác vụ Chat đồng thời trên mỗi user. |
| `SUMMARY_DEADLINE_SECONDS` | `120` | Deadline tổng thể cho Summary. |
| `CHAT_DEADLINE_SECONDS` | `60` | Deadline tổng thể cho một lượt Chat. |
| `DOCUMENT_DELETION_LEASE_SECONDS` | `60` | Thời hạn lease của deletion job. |
| `DOCUMENT_DELETION_RECOVERY_ENABLED` | `false` | Recovery tự động; mặc định tắt. |

### 5. Chạy migration

Từ thư mục `backend` và khi virtual environment đang được kích hoạt:

```powershell
python -m alembic upgrade head
```

Migration lấy `DATABASE_URL` qua `app/core/config.py`; credentials không được đặt trong `alembic.ini`.

### 6. Khởi động Backend

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Kiểm tra nhanh tại `http://127.0.0.1:8000/health`. Tài liệu OpenAPI của FastAPI có tại `http://127.0.0.1:8000/docs`.

### 7. Cài đặt và khởi động Frontend

Mở một cửa sổ PowerShell khác tại thư mục gốc:

```powershell
Set-Location frontend
Copy-Item .env.example .env
npm ci
npm run dev
```

`frontend/.env.example` đang cấu hình:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Mở địa chỉ Vite hiển thị trên terminal (mặc định thường là `http://localhost:5173`).

## Tạo tài khoản và phân quyền ADMIN

1. Mở trang đăng ký và tạo tài khoản. Tài khoản mới luôn có role `USER`.
2. Đăng nhập để sử dụng Dashboard, Documents, Summary, Chat, History và Settings.
3. Nếu cần tài khoản quản trị, chạy CLI sau từ thư mục `backend`:

```powershell
.\.venv\Scripts\python.exe -m scripts.promote_admin <username>
```

CLI yêu cầu nhập lại chính xác username, xác minh đang kết nối `studymate_ai_db` và chỉ nâng quyền một tài khoản USER hiện có. Không có API công khai để tự cấp role ADMIN.

## Quy trình sử dụng cơ bản

1. Tải lên PDF hoặc DOCX có dung lượng không quá 10 MiB.
2. Chọn **Xử lý tài liệu** để trích xuất văn bản và tạo chunks.
3. Với RAG Chat, chọn **Lập chỉ mục AI** và chờ trạng thái `READY`.
4. Mở **Tóm tắt tài liệu** để tạo một trong ba loại tóm tắt. Summary chỉ yêu cầu tài liệu đã xử lý, không yêu cầu RAG index.
5. Mở **Hỏi đáp AI** để đặt câu hỏi, xem câu trả lời và nguồn trích dẫn.

## Chạy kiểm thử

### Backend

Từ thư mục `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -ra
.\.venv\Scripts\python.exe -m compileall -q app scripts migrations
.\.venv\Scripts\python.exe -m pip check
```

Lần kiểm tra gần nhất của repository: **858 passed, 10 skipped, 0 failed**. Mười test bị skip là các trường hợp cần PostgreSQL test database độc lập hoặc concurrency PostgreSQL thực tế.

### Frontend

Từ thư mục `frontend`:

```powershell
npm test
npm run lint
npm run build
```

Lần kiểm tra gần nhất: **313 passed, 0 failed**; lint và production build đều thành công. Build hiện cảnh báo bundle JavaScript lớn hơn 500 kB nhưng không thất bại.

### PostgreSQL integration tests

Integration suite có thao tác cleanup và được thiết kế fail-closed. Chỉ chạy trên database riêng `studymate_ai_test` với role riêng `studymate_ai_test_runner`, PostgreSQL 18, host `127.0.0.1`, port `5432`. Role test không được có `SUPERUSER`, `CREATEDB`, `CREATEROLE` hoặc `REPLICATION`.

Không dùng `studymate_ai_db`, `tiem_chung_db`, production `DATABASE_URL` hoặc PostgreSQL superuser cho suite này. Database và role test phải được quản trị viên tạo thủ công trước; harness không tự tạo/drop database.

Sau khi môi trường test độc lập đã được chuẩn bị, đặt hai biến chỉ trong terminal test:

```powershell
$env:STUDYMATE_RUN_POSTGRES_INTEGRATION = "1"
$env:STUDYMATE_INTEGRATION_DATABASE_URL = "postgresql+psycopg://studymate_ai_test_runner:<TEST_PASSWORD>@127.0.0.1:5432/studymate_ai_test"
```

Áp dụng migration vào đúng database test đã qua preflight:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_integration_migrations
```

Sau đó chạy integration suite, không dùng `pytest-xdist`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration -m postgresql_integration -ra
```

Nếu không opt-in, integration tests tự động được skip. Nếu opt-in nhưng URL, database, role, phiên bản PostgreSQL hoặc quyền role không đúng, suite dừng an toàn trước cleanup.

## Cấu trúc thư mục

```text
StudyMate AI/
├── backend/
│   ├── app/
│   │   ├── core/          # Cấu hình và bảo mật
│   │   ├── db/            # SQLAlchemy engine/session
│   │   ├── dependencies/  # JWT, database và dependency injection
│   │   ├── models/        # SQLAlchemy models
│   │   ├── routers/       # FastAPI endpoints
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   └── services/      # Documents, Summary, RAG, Admin...
│   ├── migrations/        # Alembic migrations
│   ├── scripts/           # CLI quản trị và integration harness
│   ├── tests/             # Unit/API/integration tests
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── components/    # Giao diện USER và ADMIN
│   │   ├── contexts/      # Authentication context
│   │   ├── navigation/    # Điều hướng phía client
│   │   ├── services/      # REST API clients
│   │   └── theme/         # Light/Dark Mode
│   ├── tests/
│   ├── package.json
│   └── .env.example
├── .gitignore
└── README.md
```

`backend/storage/`, `.env`, virtual environments, `node_modules`, build artifacts và dữ liệu tạm được Git ignore; không đưa tài liệu người dùng, ChromaDB hoặc secrets lên repository.

## Giới hạn hiện tại

- Chỉ hỗ trợ PDF có text layer và DOCX. Chưa có OCR cho PDF scan/ảnh.
- Không hỗ trợ upload TXT.
- DOCX hiện được tải xuống nhưng không có trình xem trực tiếp hoặc chuyển đổi sang PDF.
- Admin Documents chỉ xem metadata; chưa có ADMIN DELETE và không cho quản trị viên xem nội dung riêng tư của tài liệu.
- PostgreSQL integration/concurrency tests đã có harness an toàn nhưng chưa được chạy thực tế trên database test độc lập trong lần kiểm tra cuối.
- Gemini API cần API key hợp lệ, quyền truy cập đúng model và quota còn khả dụng; tốc độ hoặc khả năng phục vụ phụ thuộc nhà cung cấp và kết nối mạng.
- ChromaDB dùng persistent local storage, phù hợp đồ án/chạy cục bộ; triển khai nhiều máy cần thiết kế hạ tầng lưu trữ riêng.
- Rate limiting đăng nhập/đăng ký hiện dùng bộ nhớ tiến trình, nên không đồng bộ giữa nhiều worker và bị reset khi server khởi động lại.
- Bundle JavaScript production hiện vượt ngưỡng cảnh báo 500 kB; có thể tối ưu bằng code splitting trong giai đoạn sau.

## Lưu ý bảo mật

- Không commit `.env`, API key, JWT secret, mật khẩu PostgreSQL, `backend/storage/` hoặc tài liệu người dùng.
- Frontend giữ access token trong React memory, không lưu vào `localStorage`, `sessionStorage` hoặc cookie.
- Sau khi đổi mật khẩu, đăng xuất hoặc khóa tài khoản, `token_version` được tăng để thu hồi các JWT cũ.
- Chỉ sử dụng CLI quản trị trên máy tin cậy và luôn xác minh đúng database trước thao tác.
