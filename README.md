# 🌐 TallyPilot: Intelligent Bank Statement & Accounting Automation Platform

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-000000?style=flat&logo=flask&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=black)
![MySQL](https://img.shields.io/badge/MySQL-8.0+-4479A1?style=flat&logo=mysql&logoColor=white)
![Tally Prime](https://img.shields.io/badge/Tally_Prime-XML_HTTP-00529B?style=flat)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

An enterprise-grade accounting automation platform designed to ingest bank statements (Excel / CSV), categorize transactions using intelligent accounting rules and local LLMs (Ollama), manage human clarification workflows for ambiguous entries, and synchronize verified double-entry accounting vouchers directly with **Tally Prime** via XML-over-HTTP.

---

## 🛠️ Tech Stack & Key Technologies

- **Frontend:** Premium single-page application built with **React 18**, **TypeScript**, **Vite**, **Tailwind CSS**, **Recharts**, and **Lucide React** icons.
- **Backend Server:** **Flask (Python)** with **SQLAlchemy (MySQL)**, scoped session lifecycle hooks, and structured REST endpoints.
- **Accounting Engine:** Double-entry ledger validator ensuring debits equal credits, correct voucher typing (*Payment*, *Receipt*, *Contra*, *Journal*), and balance tracking.
- **Categorization Engine:** Contextual categorization using local LLMs (*Mistral via Ollama*) paired with a deterministic rule fallback engine for 100% offline reliability.
- **Tally Integration:** Synchronous XML HTTP client communicating directly with Tally Prime's local server (Port 9000), equipped with a realistic simulation mode for offline testing.
- **Audit & Compliance:** Durable tracking records, SHA-256 payload hashing for idempotency, and full chronological audit logging.

---

## 💎 Features

- **Multi-Format Statement Ingestion:** Parses bank statements from `.xlsx`, `.xls`, and `.csv` formats with automatic column normalization and SHA-256 duplicate file detection.
- **Intelligent Transaction Categorization:** Automatically maps narrations to Tally master ledgers (*Indirect Expenses*, *Sundry Creditors*, *Sundry Debtors*, *Bank Accounts*) with confidence scoring.
- **Human-in-the-Loop Clarification Queue:** Flags low-confidence or ambiguous entries (e.g., unknown UPI transfers), allowing finance teams to select correct ledgers with one click.
- **Double-Entry Balance & Approval Queue:** Verifies accounting balance and enables authorized users to review and approve vouchers individually or via batch authorization.
- **Direct Tally Prime XML HTTP Integration:** Builds Tally-compliant XML envelopes and posts them directly to Tally Prime, capturing generated GUIDs into database logs.
- **Simulation & Mock Mode:** Enables development and testing without requiring a live Tally Prime instance by generating realistic GUID responses.
- **Complete Audit Trail & CSV Export:** Chronologically records all ingestion, clarification, approval, and posting events with instant CSV export capabilities.
- **Adaptive Appearance:** Supports seamless Dark Mode and Light Mode with real-time KPI metrics and status distribution charts.

---

## 📐 Project Architecture

```mermaid
flowchart TD
    A[Bank Statement .xlsx / .csv] --> B[File Ingestion & Parsing]
    B --> C[Duplicate Check SHA-256]
    C --> D[Categorization Engine]
    D -->|High Confidence >= 80%| E[Accounting Balance Validator]
    D -->|Low Confidence / Ambiguous| F[Human Clarification Queue]
    F -->|User Selects Ledger| E
    E --> G[Pending Approval Queue]
    G -->|Authorized Approval| H[Tally XML Voucher Builder]
    H --> I[Tally Prime HTTP Server :9000]
    I --> J[Tally Day Book / Vouchers Created]
    I -.->|Simulation Mode Active| K[Realistic Mock GUID Response]
```

---

## 🚀 Setup & Installation

### 1. Clone the Repository
```cmd
git clone https://github.com/your-username/TallyPilot_BE.git
cd TallyPilot_BE
```

### 2. Configure Virtual Environment
```cmd
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```cmd
pip install -r requirements.txt
```

### 4. Setup MySQL Database
Open your MySQL client (Workbench, DBeaver, or CLI) and execute the schema file:
```cmd
mysql -u your_db_username -p < schema.sql
```
*(This creates the `TallyPilot` database along with all 10 tables and initial seed ledgers)*

### 5. Setup Environment Variables
Configure `.env` in the backend directory:

```env
# Application Settings
APP_NAME=TallyPilot
APP_ENV=development
APP_PORT=8000
APP_HOST=0.0.0.0

# Database Settings
DB_HOST=localhost
DB_PORT=3306
DB_NAME=TallyPilot
DB_USER=your_db_username
DB_PASSWORD=your_db_password

# Database URL
DATABASE_URL=mysql+pymysql://your_db_username:your_db_password@localhost:3306/TallyPilot?charset=utf8mb4

# Tally Prime XML HTTP Configuration
TALLY_URL=http://localhost:9000
TALLY_COMPANY_NAME="Demo Company (FY 2026-27)"
TALLY_TIMEOUT=10
TALLY_SIMULATION_MODE=True

# Categorization Thresholds
AI_CONFIDENCE_THRESHOLD=0.80

# CORS Allowed Origins
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### 6. Start the Backend Application
```cmd
python app.py
```
*(API will be live at: `http://localhost:8000`)*

---

## 📁 Directory Structure

```text
├── controller/             # Flask request controllers (Dashboard, Files, Transactions, Tally, Logs, Settings)
├── database/               # SQLAlchemy connection, session pooling, and repository abstraction
├── helper/                 # Business services (Excel reader, accounting validator, voucher builder, Tally client)
├── model/                  # SQLAlchemy ORM database models and Pydantic validation schemas
├── tests/                  # Pytest automated test suite
├── utils/                  # Centralized configuration, logger, and security hashing
├── app.py                  # Main application runner and explicit route definitions
├── init_db.py              # Database initialization and seed script
├── schema.sql              # MySQL DDL table schema script
├── requirements.txt        # Python backend dependencies
└── README.md               # Project documentation
```

---

## 📝 License

Distributed under the MIT License. See `LICENSE` for more information.
