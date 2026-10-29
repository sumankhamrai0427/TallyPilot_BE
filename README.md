# TallyPilot AI — Intelligent Accounting Automation Agent

TallyPilot AI is an enterprise-grade Proof of Concept (POC) designed to automate bank statement ingestion, transaction categorization using local LLMs (Ollama) with deterministic rule-based fallbacks, human clarification workflows, and double-entry voucher synchronization with **Tally Prime** via XML-over-HTTP.

---

## 🏗 Architecture Overview

Following the clean layered architecture pattern (controllers, services, repositories, models):

```text
TallyPilot/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI application entrypoint
│   │   ├── core/                    # Security, hashing & settings
│   │   ├── api/                     # Controllers & REST endpoints
│   │   ├── database/                # SQLAlchemy session & Base
│   │   ├── models/                  # SQLAlchemy ORM models
│   │   ├── schemas/                 # Strict Pydantic schemas
│   │   ├── repositories/            # Data-access layer
│   │   ├── services/                # Ingestion, LLM, Validator, Voucher builder, Tally client
│   │   └── workers/                 # Folder watcher (watchdog)
│   ├── tests/                       # Pytest automated test suite
│   ├── init_db.py                   # Python DB initialization script
│   └── requirements.txt
├── frontend/                        # React + Vite + TypeScript + Tailwind CSS
│   ├── src/
│   │   ├── components/              # Navbar, Sidebar, UI cards
│   │   ├── pages/                   # Dashboard, Import, Queue, Approvals, Tally, Logs, Settings
│   │   ├── services/api.ts          # Axios client connecting to /api
│   │   └── types/                   # TypeScript interfaces
├── scripts/
│   ├── schema_mysql.sql             # Full DDL Script for database: tallyprime
│   └── generate_sample_excel.py     # Synthetic bank statement generator
├── input/                           # Watcher folder for Excel statements (.xlsx, .xls)
├── processed/                       # Successfully processed statements archive
├── rejected/                        # Invalid / rejected statements
├── run_backend.bat                  # One-click backend startup script
├── run_frontend.bat                 # One-click frontend startup script
├── run_watcher.bat                  # One-click folder watcher startup script
└── .env.example                     # Environment configuration template
```

---

## 🗄️ Database Setup (MySQL — `tallyprime`)

The user requested manual management for database queries. The complete DDL script is located at:
`scripts/schema_mysql.sql`

### Option A: Run manually via MySQL CLI
```bash
mysql -u root -p < scripts/schema_mysql.sql
```

### Option B: Run via MySQL Workbench / DBeaver / Navicat
1. Open MySQL Workbench.
2. Open file: `scripts/schema_mysql.sql`.
3. Execute the script. It will create database `tallyprime` and all 10 tables:
   - `import_batches`
   - `bank_transactions`
   - `transaction_classifications`
   - `human_reviews`
   - `approval_records`
   - `tally_submissions`
   - `tally_ledgers`
   - `ledger_mappings`
   - `audit_logs`
   - `application_settings`

### Option C: Run using Python init script
```bash
.venv\Scripts\python.exe backend/init_db.py
```

---

## ⚙️ Environment Configuration (`.env`)

Create a `.env` file in the project root:

```env
# Application Settings
APP_NAME="TallyPilot AI"
APP_ENV=development
DEBUG=True

# MySQL Connection (database: tallyprime)
DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/tallyprime

# Local LLM / Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
AI_CONFIDENCE_THRESHOLD=0.80
AI_FALLBACK_RULE_ENGINE=True

# Tally Prime XML HTTP Configuration
TALLY_HOST=localhost
TALLY_PORT=9000
TALLY_COMPANY=Demo Company
TALLY_TIMEOUT=15
TALLY_MOCK_MODE=True
```

*(Note: When Tally Prime is not running on port 9000, `TALLY_MOCK_MODE=True` provides realistic simulation with generated voucher IDs).*

---

## 🚀 Running the Application

### 1. Start the Backend (FastAPI)
Double-click `run_backend.bat` or run in terminal:
```powershell
.venv\Scripts\python.exe backend\app\main.py
```
Backend API will be live at: **http://localhost:8000**
API Documentation (Swagger): **http://localhost:8000/docs**

### 2. Start the Frontend (React + Vite)
Double-click `run_frontend.bat` or run:
```powershell
cd frontend
npm run dev
```
Frontend Dashboard will be live at: **http://localhost:5173**

### 3. (Optional) Start Background Folder Watcher
```powershell
.venv\Scripts\python.exe backend\app\workers\folder_watcher.py
```

---

## 🧪 Automated Test Suite

Run unit and integration tests:
```powershell
cmd.exe /c .venv\Scripts\pytest.exe backend\tests
```
8 tests covering Excel ingestion, accounting validation, voucher XML building, and fallback classification pass automatically.

---

## 📋 End-to-End Demonstration Workflow

1. **Generate Sample Data**:
   A sample statement is already ready at `./input/sample_bank_statement.xlsx` (or run `python scripts/generate_sample_excel.py`).
2. **Import Statement**:
   Open **http://localhost:5173**, navigate to **Import Statements**, and upload `./input/sample_bank_statement.xlsx`.
3. **Clarification Queue**:
   Transactions with low AI confidence or unknown ledgers appear in **Clarification Queue**. Select a valid Tally ledger (e.g. *ABC Suppliers Ltd*) and click **Submit & Revalidate**.
4. **Approval Queue**:
   Review proposed double-entry voucher balance (Debit vs Credit). Click **Post to Tally** (or batch authorize).
5. **Audit Logs & Tally Page**:
   Inspect generated GUIDs, XML payloads, and export audit logs to CSV.

