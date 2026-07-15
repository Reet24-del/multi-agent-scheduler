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

2. Run Tests:
   Verify the LangGraph architecture compiles and passes database tests:
   ```bash
   python test_graph.py
   ```

3. Run Dev Server:
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
4. Expand the Environment Variables section and add:
   * DATABASE_URL: Your Supabase URI connection string.
   * HF_TOKEN: Your Hugging Face API Token (to enable Llama 3.3 70B).
   * SENDER_EMAIL: reet2402singh@gmail.com
   * SENDER_PASSWORD: mggxghbthgypwqdj
5. Click Deploy. Vercel will automatically package your FastAPI app as a serverless function and expose it on a public domain.

---

## Environment Configurations

| Variable | Description | Local Value (SQLite) | Production Value (Vercel) |
|---|---|---|---|
| DATABASE_URL | PostgreSQL connection string | Omitted (falls back to SQLite) | postgresql://... (Supabase Pooler) |
| HF_TOKEN | Hugging Face Hub API token | hf_... (from settings/env) | hf_... |
| PORT | Local web server port | 8501 (default) | Managed by Vercel |
