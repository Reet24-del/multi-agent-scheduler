# Atmos: Multi-Agent Scheduling Console

A multi-agent calendar scheduling assistant built with FastAPI, LangGraph, and Vanilla JS. It coordinates a Triage Agent and a Booking Specialist to manage appointments, handle slot conflicts, negotiate alternative times, and trigger webhooks.

This application is configured to run in Dual-Database Mode:
* Development (Local): Falls back to local SQLite databases automatically.
* Production (Deployed): Connects to a hosted Supabase PostgreSQL instance for production-ready persistence.

---

## Local Development

1. Install Dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables. The app reads secrets from the environment. On startup, `app.py` calls `load_dotenv()`, so a local `.env` file is loaded automatically. `.env` is listed in `.gitignore` and must not be committed.
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and replace the placeholders. The variables the app reads are:

   | Variable | Required | Purpose |
   |---|---|---|
   | `SENDER_EMAIL` | For outbound email | Gmail address used as the From address |
   | `SENDER_PASSWORD` | For outbound email | Gmail app password for `SENDER_EMAIL` |
   | `HF_TOKEN` | For Llama 3.3 70B | Hugging Face Hub token |
   | `DATABASE_URL` or `SUPABASE_URL` | Production database only | PostgreSQL connection URI. Omit both to use SQLite |
   | `PORT` | No | Local web server port. Defaults to 8501 |

   Create the Gmail app password under Google Account > Security > App passwords, and put that value in `SENDER_PASSWORD`. Use an app password, not the normal Gmail password. Set these only in `.env` or in the host's environment variable settings.

3. Run Tests:
   Verify the LangGraph architecture compiles and passes database tests:
   ```bash
   python test_graph.py
   ```

4. Run Dev Server:
   ```bash
   python app.py
   ```
   Open http://localhost:8501 in your browser.

---

## Supabase Setup (PostgreSQL)

To support persistent session history and bookings on Vercel's serverless environment, you need a PostgreSQL database.

1. Go to Supabase (https://supabase.com) and create a new project.
2. Retrieve your URI connection string from Project Settings > Database > Connection string (select the URI tab).
   * It should look like: postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   * Replace [YOUR-PASSWORD] with the database password you chose.
3. The app will automatically run all migrations (creating bookings, checkpoints, and writes tables) during startup. No manual SQL scripts are required.

---

## Vercel Deployment

Deploying the FastAPI app to Vercel is streamlined using the pre-configured vercel.json file in the root.

1. Push your project folder to a GitHub repository.
2. Log in to Vercel (https://vercel.com) and click Add New > Project.
3. Import your GitHub repository.
4. Expand the Environment Variables section and set the same names as `.env.example`. Enter the values in the Vercel dashboard only. Do not commit them:
   * `DATABASE_URL`: Your Supabase URI connection string.
   * `HF_TOKEN`: Your Hugging Face API token (to enable Llama 3.3 70B).
   * `SENDER_EMAIL`: The Gmail address that sends booking mail.
   * `SENDER_PASSWORD`: The Gmail app password for that address.
5. Click Deploy. Vercel will automatically package your FastAPI app as a serverless function and expose it on a public domain.

`render.yaml` declares `SUPABASE_URL`, `HF_TOKEN`, `SENDER_EMAIL`, and `SENDER_PASSWORD` with `sync: false`. Set those values in the Render dashboard as well. They are not stored in this repository.

---

## Environment Configurations

| Variable | Description | Local Value (SQLite) | Production Value (Vercel) |
|---|---|---|---|
| DATABASE_URL | PostgreSQL connection string | Omitted (falls back to SQLite) | postgresql://... (Supabase Pooler) |
| HF_TOKEN | Hugging Face Hub API token | Set in `.env` | Set in the host dashboard |
| SENDER_EMAIL | Gmail From address | Set in `.env` | Set in the host dashboard |
| SENDER_PASSWORD | Gmail app password | Set in `.env` | Set in the host dashboard |
| PORT | Local web server port | 8501 (default) | Managed by Vercel |
