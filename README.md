# 🧩 cPanel Email Account Auto-Creator

[![CI](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](#-license)
[![Made with Selenium](https://img.shields.io/badge/Made%20with-Selenium-brightgreen)](https://www.selenium.dev/)
[![Dockerized](https://img.shields.io/badge/Docker-Dockerized-informational)](https://www.docker.com/)

Automate the creation of hundreds (or thousands) of cPanel email accounts using **Selenium**, **Python**, and **Docker**.

---

## 🚀 Features

- Automated login and token extraction (`cpsess`)
- Support **Jupiter** (Angular) cPanel theme
- Batch create: `akun001` → `akun1000`
- Stay-on-page mode, retry logic, screenshot logs
- Works on macOS/Windows/Linux via Docker

---

## 🧰 Requirements

- **Docker Desktop** or **Docker Engine 20.10+**
- **Docker Compose**
- Access to cPanel “Email Accounts”

---

## ⚙️ Setup & Usage

### 1️⃣ Clone the repository
```bash
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
2️⃣ Start the Selenium + Chrome environment
bash
Copy code
docker compose up -d
This launches:

s-chromium: Selenium Chrome container

createuser: Python automation container

3️⃣ Create your first batch of accounts
Example: create 100 accounts (akun001–akun100)

bash
Copy code
docker compose exec createuser bash -lc "DOMAIN=mbtech.info EMAIL_PREFIX=akun COUNT=100 QUOTA_MB=1024 python test/createuser.py"
4️⃣ Continue from previous batch
Example: continue from akun101 up to akun1000

bash
Copy code
docker compose exec createuser bash -lc "DOMAIN=mbtech.info EMAIL_PREFIX=akun START=101 COUNT=900 QUOTA_MB=1024 python test/createuser.py"
5️⃣ Check logs
bash
Copy code
docker compose logs -f createuser
All logs and screenshots are stored in:

bash
Copy code
/app/debug/
🧩 Environment Variables
Variable	Description	Example
CPANEL_URL	cPanel login URL	https://cpanel.mbtech.info
CPANEL_USER	cPanel username	admin
CPANEL_PASS	cPanel password	supersecure123
DOMAIN	Email domain (optional)	mbtech.info
EMAIL_PREFIX	Account prefix	akun
START	Starting index	101
COUNT	Number of accounts	100
PASSWORD_STATIC	Fixed password (optional)	P@ssword123!
QUOTA_MB	Mailbox quota (MB)	1024

🧠 Example Log Output
text
Copy code
2025-10-22 06:46:58 | INFO | Isi form: user=akun007
2025-10-22 06:46:58 | INFO | Quota: Unlimited
2025-10-22 06:46:58 | INFO | Klik Create.
2025-10-22 06:47:04 | INFO | [8/100] Proses akun008@mbtech.info
SUMMARY: OK=98, DUPLICATE=2, UNKNOWN=0
🖼️ Demo Screenshots
Cuplikan proses nyata dari container (folder debug/).
Untuk tampilan terbaik, pindahkan contoh screenshot ke assets/screenshots/.

<p align="center"> <img src="assets/screenshots/01_email_list.png" alt="Email Accounts list" width="45%"/> <img src="assets/screenshots/02_create_form.png" alt="Create form detected" width="45%"/> </p> <p align="center"> <img src="assets/screenshots/after_create_unclear.png" alt="Post-create unknown state" width="45%"/> <img src="assets/screenshots/verify_missing_akun008_mbtech.info.png" alt="Verify missing row" width="45%"/> </p>
Move screenshots from runtime folder:

bash
Copy code
mkdir -p assets/screenshots
cp debug/*.png assets/screenshots/
🧱 Folder Structure
text
Copy code
.
├── test/
│   └── createuser.py        # main automation script
├── debug/                   # logs & screenshots (runtime)
├── docker-compose.yml       # environment setup
├── requirements.txt         # dependencies
└── README.md
🛠️ CI/CD
Repo ini menggunakan GitHub Actions untuk:

Linting (flake8) dan format check (black)

Build Docker image (smoke test)

Badge status CI tampil di bagian atas README.

Untuk end-to-end test dengan cPanel sungguhan (opsional, self-hosted runner), tambahkan secrets:
CPANEL_URL, CPANEL_USER, CPANEL_PASS.

Workflow file
Save as: .github/workflows/ci.yml

yaml
Copy code
name: CI

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  lint-and-build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          pip install flake8 black

      - name: Lint (flake8)
        run: flake8 --max-line-length=120 --extend-ignore=E203 .

      - name: Format check (black)
        run: black --check .

      - name: Build Docker image
        run: docker build -t cpanel-email-creator:ci .

      - name: Import check
        run: |
          python - << 'PY'
          import importlib.util, pathlib
          p = pathlib.Path("test/createuser.py")
          spec = importlib.util.spec_from_file_location("createuser", p)
          m = importlib.util.module_from_spec(spec)
          spec.loader.exec_module(m)
          print("✅ Loaded:", m.__name__)
          PY
⚠️ Troubleshooting
❗ TimeoutException on Create button
Form Angular kadang belum siap → naikkan timeout di wait_create_button_ready.

❗ 500 Internal Server Error for API route
Masalah API Docker Desktop Windows — restart Docker & kurangi batch size.

❗ Chrome crash (/dev/shm)
Tambahkan flag berikut di createuser.py:

python
Copy code
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-gpu")
👨‍💻 Author
Developed by: [Your Name or Team]
💡 Automating repetitive admin work with Selenium + Docker + Python.

📜 License
Licensed under the MIT License.

