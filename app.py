import os
import re
import sqlite3
import datetime
import urllib.request
import json
from typing import Annotated, TypedDict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environmental configurations
load_dotenv()

# LangChain / LangGraph imports
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from contextlib import asynccontextmanager
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

# CONSTANTS & PATHS
if os.environ.get("VERCEL"):
    DB_DATA_PATH = "/tmp/scheduler_data.db"
    DB_CHECKPOINT_PATH = "/tmp/scheduler_history.db"
else:
    DB_DATA_PATH = "scheduler_data.db"
    DB_CHECKPOINT_PATH = "scheduler_history.db"

# Notification logs in memory for the real-time notification panel
notification_logs = []

# Connection Pool and DB helpers
db_pool = None

def get_database_url() -> Optional[str]:
    # Look for the connection string in multiple environment names for resilience
    for key in ["DATABASE_URL", "POSTGRES_URL", "SUPABASE_DATABASE_URL", "DB_URL", "database_url", "PG_URL", "DB_CONNECTION_STRING", "SUPABASE_CONN", "CONN_STR"]:
        val = os.environ.get(key)
        if val:
            val_str = str(val).strip()
            if not val_str.startswith("postgresql://") and not val_str.startswith("postgres://"):
                val_str = "postgresql://" + val_str
            return val_str
    return None

def disable_database_url():
    for key in ["DATABASE_URL", "POSTGRES_URL", "SUPABASE_DATABASE_URL", "DB_URL", "database_url", "PG_URL", "DB_CONNECTION_STRING", "SUPABASE_CONN", "CONN_STR"]:
        if key in os.environ:
            try:
                del os.environ[key]
            except Exception:
                pass

def is_postgres_mode() -> bool:
    return bool(get_database_url())

def get_placeholder() -> str:
    return "%s" if is_postgres_mode() else "?"

def get_db_connection():
    db_url = get_database_url()
    if db_url:
        global db_pool
        if db_pool is None:
            import psycopg
            return psycopg.connect(db_url)
        return db_pool.getconn()
    else:
        return sqlite3.connect(DB_DATA_PATH, check_same_thread=False)

def release_db_connection(conn):
    db_url = get_database_url()
    if db_url:
        global db_pool
        if db_pool is not None:
            try:
                db_pool.putconn(conn)
                return
            except Exception:
                pass
        conn.close()
    else:
        conn.close()

# Initialize SQLite or Postgres Data Tables
def init_data_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    db_url = get_database_url()
    
    if db_url:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                date VARCHAR(10) NOT NULL,
                time VARCHAR(10) NOT NULL,
                email VARCHAR(255) NOT NULL,
                UNIQUE(date, time)
            )
        """)
        placeholder = "%s"
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                email TEXT NOT NULL,
                UNIQUE(date, time)
            )
        """)
        placeholder = "?"
        
    conn.commit()

    # Seed mock bookings
    cursor.execute("SELECT COUNT(*) FROM bookings")
    if cursor.fetchone()[0] == 0:
        # Pre-book some slots on tomorrow's date for negotiation testing
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        if db_url:
            cursor.execute("INSERT INTO bookings (date, time, email) VALUES (%s, %s, %s) ON CONFLICT (date, time) DO NOTHING", (tomorrow, "10:00 AM", "reserved@atmos.com"))
            cursor.execute("INSERT INTO bookings (date, time, email) VALUES (%s, %s, %s) ON CONFLICT (date, time) DO NOTHING", (tomorrow, "02:00 PM", "taken@atmos.com"))
        else:
            cursor.execute("INSERT OR IGNORE INTO bookings (date, time, email) VALUES (?, ?, ?)", (tomorrow, "10:00 AM", "reserved@atmos.com"))
            cursor.execute("INSERT OR IGNORE INTO bookings (date, time, email) VALUES (?, ?, ?)", (tomorrow, "02:00 PM", "taken@atmos.com"))
        conn.commit()
    cursor.close()
    release_db_connection(conn)

# ==========================================================================
# 🛠️ Mock Calendar Tools
# ==========================================================================

def check_availability_func(date: str) -> str:
    """Checks available time slots for calendar booking on a specific date (format YYYY-MM-DD)."""
    # Standard slots
    all_slots = ["09:00 AM", "10:00 AM", "11:00 AM", "01:00 PM", "02:00 PM", "03:00 PM", "04:00 PM"]
    
    placeholder = get_placeholder()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT time FROM bookings WHERE date = {placeholder}", (date,))
    booked = [row[0] for row in cursor.fetchall()]
    cursor.close()
    release_db_connection(conn)
    
    available = [slot for slot in all_slots if slot not in booked]
    if not available:
        return f"No available slots on {date}. All slots are booked."
        
    return f"Available slots on {date}: " + ", ".join(available)

def reserve_slot_func(date: str, time: str, email: str) -> str:
    """Reserves a time slot. Returns success message or conflict error."""
    # Validate date format YYYY-MM-DD
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return f"Error: Invalid date format '{date}'. Must be YYYY-MM-DD."
        
    # Validate email
    if "@" not in email or "." not in email:
        return f"Error: Invalid email address '{email}'."

    placeholder = get_placeholder()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"INSERT INTO bookings (date, time, email) VALUES ({placeholder}, {placeholder}, {placeholder})", (date, time, email))
        conn.commit()
        res = f"Success: Appointment reserved on {date} at {time} for {email}."
    except Exception as e:
        err_msg = str(e).lower()
        if "unique" in err_msg or "duplicate" in err_msg or "integrity" in err_msg or "conflict" in err_msg:
            res = f"Conflict: Slot on {date} at {time} is already booked. Please negotiate alternative slots."
        else:
            res = f"Error: Failed to reserve slot: {e}"
    finally:
        cursor.close()
        release_db_connection(conn)
        
    return res

def send_booking_notification_func(email: str, details: str) -> str:
    """Triggers mock webhook notification and attempts real email delivery via Gmail SMTP if configured."""
    data = json.dumps({"email": email, "details": details, "system": "Atmos Scheduling App"}).encode("utf-8")
    req = urllib.request.Request(
        "https://httpbin.org/post", 
        data=data, 
        headers={"Content-Type": "application/json", "User-Agent": "AtmosSchedulerAgent"}
    )
    
    status = "Sent"
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            res_code = response.getcode()
            if res_code == 200:
                status = "Delivered (HTTP 200)"
                res = f"Notification Sent: Confirmation webhook successfully triggered to simulate email notification to {email}."
            else:
                status = f"Mocked (HTTP {res_code})"
                res = f"Notification Mocked: Webhook endpoint responded with code {res_code}. Notification queued for {email}."
    except Exception as e:
        status = "Mocked (Offline Fallback)"
        res = f"Notification Mocked: Webhook endpoint simulated successfully. Email notification queued for {email}."

    # Real Email Dispatch via Gmail SMTP
    sender_email = os.environ.get("SENDER_EMAIL", "")
    sender_password = os.environ.get("SENDER_PASSWORD", "")

    if sender_email and sender_password:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        try:
            is_cancellation = any(word in details.lower() for word in ["cancel", "cancellation", "remove", "delete"])
            subject = "Atmos Appointment Cancellation" if is_cancellation else "Atmos Appointment Confirmation"
            header = "Your appointment has been cancelled." if is_cancellation else "Your appointment has been successfully scheduled!"

            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = email
            msg['Subject'] = subject

            body = f"""Hi there,

{header}

Details:
{details}

Thank you,
Atmos Scheduling Assistant
"""
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=3.0) as server:
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, email, msg.as_string())
            
            status += " & Email Sent"
            res = f"Success: Webhook triggered and confirmation email sent to {email}."
        except Exception as e:
            status += f" (Email Fail: {e})"
            res = f"Warning: Webhook triggered but email dispatch failed: {e}"
        
    # Log webhook events for real-time visualization on the client sidebar
    notification_logs.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "email": email,
        "details": details,
        "status": status
    })
    return res

# Define LangChain Tool Schemas for LLM binding
tools = [
    {
        "name": "check_availability",
        "description": "Checks available time slots for calendar booking on a specific date (format YYYY-MM-DD).",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date to check in YYYY-MM-DD format."
                }
            },
            "required": ["date"]
        }
    },
    {
        "name": "reserve_slot",
        "description": "Reserves a specific time slot on a YYYY-MM-DD date for an email address.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "The date in YYYY-MM-DD format."},
                "time": {"type": "string", "description": "The time slot (e.g. '10:00 AM' or '03:00 PM')."},
                "email": {"type": "string", "description": "User email address."}
            },
            "required": ["date", "time", "email"]
        }
    },
    {
        "name": "send_booking_notification",
        "description": "Triggers a booking confirmation notification webhook for the user's email.",
        "parameters": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Recipient email address."},
                "details": {"type": "string", "description": "Summary of appointment details (date, time, action)."}
            },
            "required": ["email", "details"]
        }
    }
]

# ==========================================================================
# 🧠 LangGraph State Machine Definition
# ==========================================================================

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    current_agent: str
    client_time: str
    model_type: str
    api_key: str

def get_llm(model_type: str, api_key: str):
    if model_type == "huggingface":
        key = api_key or os.environ.get("HF_TOKEN", "")
        if not key:
            raise ValueError("Hugging Face Token is not set. Please configure it in the Settings panel.")
        return ChatOpenAI(
            model="meta-llama/Llama-3.3-70B-Instruct",
            openai_api_key=key,
            openai_api_base="https://router.huggingface.co/v1",
            temperature=0.0
        )
    else:
        return None

# Date parser helper for Simulation Mode
def resolve_relative_date(text: str, reference_date_str: str) -> str:
    try:
        ref_date = datetime.datetime.strptime(reference_date_str, "%Y-%m-%d").date()
    except Exception:
        ref_date = datetime.date.today()
        
    text_lower = text.lower()
    
    # 1. Match YYYY-MM-DD format
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        return date_match.group(1)
        
    # 2. Check today / tomorrow / day after
    if "today" in text_lower:
        return ref_date.strftime("%Y-%m-%d")
    if "tomorrow" in text_lower:
        return (ref_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if "day after tomorrow" in text_lower:
        return (ref_date + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
        
    # 3. Check days of the week
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    for day_name, day_idx in weekdays.items():
        if day_name in text_lower:
            current_idx = ref_date.weekday()
            days_ahead = day_idx - current_idx
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in text_lower:
                if day_idx <= current_idx:
                    pass
                else:
                    days_ahead += 7
            return (ref_date + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            
    # Default fallback date is tomorrow if the message indicates booking
    return (ref_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# 1. Triage Node
def triage_node(state: AgentState):
    # Bypass Triage if we are already in the booking conversation flow
    is_booking_active = False
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage):
            content_lower = msg.content.lower()
            if "[route_to_booking]" in msg.content or "routing you to" in content_lower:
                is_booking_active = True
                break
            if any(phrase in content_lower for phrase in [
                "time would you prefer", 
                "provide your email", 
                "taken", 
                "available standard slots",
                "which of these times works best",
                "reserve the slot",
                "booking confirmed",
                "calendar reservation"
            ]):
                is_booking_active = True
                break
            is_booking_active = False
            break

    if is_booking_active or state.get("current_agent") == "booking":
        return {
            "current_agent": "booking"
        }
        
    model_type = state.get("model_type", "simulation")
    api_key = state.get("api_key", "")
    
    # Fetch user input message
    user_msg = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break
            
    # --- Simulation Mode ---
    if model_type == "simulation":
        text = user_msg.lower()
        scheduling_keywords = ["book", "schedule", "reserve", "slot", "appointment", "check", "availability", "time", "date", "calendar"]
        is_scheduling = any(kw in text for kw in scheduling_keywords)
        
        if is_scheduling:
            return {
                "messages": [AIMessage(content="[ROUTE_TO_BOOKING] Routing you to our Booking Specialist...")],
                "current_agent": "booking"
            }
        else:
            content = "Hello! I am the Triage Agent (Simulation Mode). I can assist you with general inquiries or route you to the Booking Specialist when you ask to check calendar availability or book a slot."
            if "who are you" in text:
                content = "I am the Triage Agent. I classify requests and route booking-related tasks to the Booking Specialist."
            elif "hi" in text or "hello" in text or "hey" in text:
                content = "Hello! Welcome to Atmos. How can I help you today? You can ask me to check slots for tomorrow or schedule a booking."
            return {
                "messages": [AIMessage(content=content)],
                "current_agent": "triage"
            }
            
    # --- Real LLM Mode ---
    try:
        llm = get_llm(model_type, api_key)
    except Exception as e:
        return {
            "messages": [AIMessage(content=f"⚠️ **Configuration Error**: {str(e)}")],
            "current_agent": "triage"
        }
        
    triage_system_prompt = """You are the Triage Agent for the Atmos Scheduling Assistant.
Your job is to analyze the user's message.
- If the user wants to check availability, book an appointment, reserve a slot, schedule a meeting, or change calendar slots, respond with: "[ROUTE_TO_BOOKING]" as the first word, and then politely state that you are routing them to the Booking Specialist.
- For general queries (greetings, small talk, asking what you do, unrelated topics), respond directly and helpfully. Do NOT output "[ROUTE_TO_BOOKING]".
"""
    messages = [SystemMessage(content=triage_system_prompt)] + state["messages"]
    try:
        response = llm.invoke(messages)
        content_lower = response.content.lower()
        if "route_to_booking" in content_lower or "[route_to_booking]" in content_lower:
            return {
                "messages": [AIMessage(content="[ROUTE_TO_BOOKING] Routing you to our Booking Specialist...")],
                "current_agent": "booking"
            }
        return {
            "messages": [response],
            "current_agent": "triage"
        }
    except Exception as e:
        return {
            "messages": [AIMessage(content=f"Error running Triage LLM: {str(e)}")],
            "current_agent": "triage"
        }

# 2. Booking Specialist Node
def booking_node(state: AgentState):
    model_type = state.get("model_type", "simulation")
    api_key = state.get("api_key", "")
    client_time_str = state.get("client_time", "")
    
    # Resolve reference time timezone-safe
    if client_time_str:
        try:
            ref_date_str = client_time_str.split("T")[0]
            ref_date = datetime.datetime.strptime(ref_date_str, "%Y-%m-%d").date()
        except Exception:
            ref_date = datetime.date.today()
    else:
        ref_date = datetime.date.today()
        
    day_name = ref_date.strftime("%A")
    today_str = ref_date.strftime("%Y-%m-%d")
    
    # --- Simulation Mode ---
    if model_type == "simulation":
        # Extract variables from message history
        email = None
        date = None
        time = None
        
        for msg in state["messages"]:
            if isinstance(msg, HumanMessage):
                content = msg.content
                # Parse Email
                email_match = re.search(r"([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9_-]+)", content)
                if email_match:
                    email = email_match.group(1)
                
                # Parse Time
                time_match = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))", content)
                if time_match:
                    time = time_match.group(1).upper()
                elif re.search(r"\b(9|10|11)\s*(?:am)\b", content, re.IGNORECASE):
                    h = re.search(r"\b(9|10|11)\b", content, re.IGNORECASE).group(1)
                    time = f"{int(h):02d}:00 AM"
                elif re.search(r"\b(1|2|3|4)\s*(?:pm)\b", content, re.IGNORECASE):
                    h = re.search(r"\b(1|2|3|4)\b", content, re.IGNORECASE).group(1)
                    time = f"{int(h):02d}:00 PM"
                
                # Parse Date
                resolved = resolve_relative_date(content, today_str)
                if resolved:
                    date = resolved
                    
        # Check tools result
        last_msg = state["messages"][-1]
        
        if isinstance(last_msg, ToolMessage):
            parent_tool_name = ""
            for msg in reversed(state["messages"][:-1]):
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if tc["id"] == last_msg.tool_call_id:
                            parent_tool_name = tc["name"]
                            break
                    if parent_tool_name:
                        break
            
            if parent_tool_name == "reserve_slot":
                if "Success" in last_msg.content:
                    email_val = email or "user@example.com"
                    details_val = f"Booking confirmed on {date or today_str} at {time or '11:00 AM'}."
                    return {
                        "messages": [AIMessage(
                            content="",
                            tool_calls=[{
                                "name": "send_booking_notification",
                                "args": {"email": email_val, "details": details_val},
                                "id": "call_notif"
                            }]
                        )],
                        "current_agent": "booking"
                    }
                elif "Conflict" in last_msg.content:
                    date_val = date or today_str
                    return {
                        "messages": [AIMessage(
                            content="Slot was taken. Let me look up the availability board.",
                            tool_calls=[{
                                "name": "check_availability",
                                "args": {"date": date_val},
                                "id": "call_check"
                            }]
                        )],
                        "current_agent": "booking"
                    }
            elif parent_tool_name == "check_availability":
                avail_info = last_msg.content
                return {
                    "messages": [AIMessage(content=f"That slot was taken. {avail_info}. Which of these times works best for you?")],
                    "current_agent": "booking"
                }
            elif parent_tool_name == "send_booking_notification":
                return {
                    "messages": [AIMessage(content=f"🎉 **Booking Confirmed!** I have reserved the slot on **{date or today_str}** at **{time or '11:00 AM'}** for **{email or 'user@example.com'}** and sent a mock webhook confirmation.")],
                    "current_agent": "booking"
                }
                
        # Multi-turn state tracking for Simulation Mode
        booking_intent = False
        check_intent = False
        
        for msg in state["messages"]:
            if isinstance(msg, HumanMessage):
                content = msg.content.lower()
                if any(w in content for w in ["book", "reserve", "schedule", "appoint"]):
                    booking_intent = True
                    check_intent = False
                elif any(w in content for w in ["check", "avail", "slot", "free", "show"]):
                    check_intent = True
                    booking_intent = False
                if booking_intent and any(w in content for w in ["check", "avail"]):
                    booking_intent = False
                    check_intent = True

        user_msg = last_msg.content.lower() if isinstance(last_msg, HumanMessage) else ""
        
        # Determine user intent
        if check_intent or "check" in user_msg or "avail" in user_msg or "slot" in user_msg:
            date_val = date or today_str
            return {
                "messages": [AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "check_availability",
                        "args": {"date": date_val},
                        "id": "call_check_init"
                    }]
                )],
                "current_agent": "booking"
            }
            
        if booking_intent or "book" in user_msg or "reserve" in user_msg or "schedule" in user_msg or (time and email):
            if not date:
                date = today_str
            if not time:
                return {
                    "messages": [AIMessage(content="I'd be happy to book that for you. What time would you prefer? Available standard slots: 9am, 10am, 11am, 1pm, 2pm, 3pm, 4pm.")],
                    "current_agent": "booking"
                }
            if not email:
                return {
                    "messages": [AIMessage(content=f"Perfect. Booking for {date} at {time}. Could you please provide your email address to send the booking confirmation?")],
                    "current_agent": "booking"
                }
                
            return {
                "messages": [AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "reserve_slot",
                        "args": {"date": date, "time": time, "email": email},
                        "id": "call_reserve_init"
                    }]
                )],
                "current_agent": "booking"
            }
            
        return {
            "messages": [AIMessage(content="I am the Booking Specialist. Let me know the date, time, and your email so I can complete your calendar reservation.")],
            "current_agent": "booking"
        }
        
    # --- Real LLM Mode ---
    try:
        llm = get_llm(model_type, api_key).bind_tools(tools)
    except Exception as e:
        return {
            "messages": [AIMessage(content=f"⚠️ **Configuration Error**: {str(e)}")],
            "current_agent": "booking"
        }
        
    booking_system_prompt = f"""You are the Booking Specialist for the Atmos Scheduling Assistant.
Today is: {today_str} ({day_name})

You help users check availability, book slots, and send notifications.
You have access to these calendar tools:
1. check_availability(date) - Date MUST be in YYYY-MM-DD format.
2. reserve_slot(date, time, email) - Date MUST be YYYY-MM-DD. Time is e.g. "10:00 AM".
3. send_booking_notification(email, details) - Triggers a mock email webhook.

Instructions:
- If the user mentions a relative date (like "tomorrow", "next Monday", "this Friday"), you MUST resolve it mathematically using "Today is: {today_str} ({day_name})" to the exact YYYY-MM-DD string before calling any tools.
  * Example: If today is Sunday 2026-07-12, "tomorrow" is 2026-07-13.
- If the user asks to book but you are missing their email, desired time, or date, ask them for the missing details politely.
- CRITICAL: You MUST NOT invent, guess, or use placeholders (like "user@example.com", "user@gmail.com", or "placeholder@example.com") for the email address. If the user has not explicitly provided their email address in the conversation history, you MUST NOT call the reserve_slot tool. Instead, you MUST ask the user to provide their email address.
- If a tool returns a conflict error (slot is taken), negotiate alternative slots by calling check_availability(date) first, and then suggesting other available hours. Do not fail silently.
- Once a slot is successfully reserved, ALWAYS call the send_booking_notification tool.
"""
    messages = [SystemMessage(content=booking_system_prompt)] + state["messages"]
    try:
        response = llm.invoke(messages)
        return {
            "messages": [response],
            "current_agent": "booking"
        }
    except Exception as e:
        return {
            "messages": [AIMessage(content=f"Error running Booking LLM: {str(e)}")],
            "current_agent": "booking"
        }

# 3. Custom Tools Node
def tools_node(state: AgentState):
    last_msg = state["messages"][-1]
    new_messages = []
    
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tool_call in last_msg.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]
            
            # Execute tool logic
            if tool_name == "check_availability":
                res = check_availability_func(tool_args.get("date", ""))
            elif tool_name == "reserve_slot":
                res = reserve_slot_func(
                    tool_args.get("date", ""), 
                    tool_args.get("time", ""), 
                    tool_args.get("email", "")
                )
            elif tool_name == "send_booking_notification":
                res = send_booking_notification_func(
                    tool_args.get("email", ""), 
                    tool_args.get("details", "")
                )
            else:
                res = f"Tool '{tool_name}' not implemented."
                
            new_messages.append(ToolMessage(content=str(res), tool_call_id=tool_id))
            
    return {"messages": new_messages}

# 4. Routing Conditional Edges
def route_after_triage(state: AgentState):
    if state["current_agent"] == "booking":
        return "booking"
    return END

def route_after_booking(state: AgentState):
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END

# Construct LangGraph State Graph
workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("triage", triage_node)
workflow.add_node("booking", booking_node)
workflow.add_node("tools", tools_node)

# Set Entry Point
workflow.set_entry_point("triage")

# Add Conditional Edges
workflow.add_conditional_edges("triage", route_after_triage, {
    "booking": "booking",
    END: END
})

workflow.add_conditional_edges("booking", route_after_booking, {
    "tools": "tools",
    END: END
})

# Add Standard Edges
workflow.add_edge("tools", "booking")

# Setup Checkpoint Savers
# Fallback global checkpointer for CLI commands/offline test scripts
conn_fallback = sqlite3.connect(DB_CHECKPOINT_PATH, check_same_thread=False)
fallback_saver = SqliteSaver(conn_fallback)
graph = workflow.compile(checkpointer=fallback_saver)

def compile_graph_with_conn(conn):
    db_url = get_database_url()
    if db_url:
        saver = PostgresSaver(conn)
    else:
        saver = fallback_saver
    return workflow.compile(checkpointer=saver)

# ==========================================================================
# 🔌 FastAPI Server
# ==========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    db_url = get_database_url()
    if db_url:
        try:
            # Set a 3.0s timeout to verify database accessibility
            db_pool = ConnectionPool(db_url, min_size=1, max_size=10, open=True, timeout=3.0, kwargs={"connect_timeout": 3})
            conn = db_pool.getconn()
            try:
                init_data_db()
                checkpointer = PostgresSaver(conn)
                checkpointer.setup()
                conn.commit()
                print("Successfully connected to Supabase PostgreSQL.")
            finally:
                db_pool.putconn(conn)
        except Exception as e:
            print(f"Warning: Failed to connect to Supabase PostgreSQL ({e}). Falling back to SQLite mode.")
            if db_pool:
                try:
                    db_pool.close()
                except Exception:
                    pass
            db_pool = None
            # Disable database URL variable for the active process to trigger SQLite paths
            disable_database_url()
            init_data_db()
    else:
        init_data_db()
    yield
    if db_pool:
        db_pool.close()

app = FastAPI(title="Multi-Agent Scheduling Assistant", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

class ChatPayload(BaseModel):
    message: str
    thread_id: str
    client_time: Optional[str] = None
    model_type: str = "simulation"
    api_key: Optional[str] = None

@app.get("/", response_class=FileResponse)
async def get_index():
    return FileResponse("templates/index.html")

@app.get("/version")
async def get_version():
    return {"version": "1.2.5"}

@app.get("/env-keys")
async def get_env_keys():
    # Safely scan for any environment keys that contain database keywords in their values
    db_keys = []
    for k, v in os.environ.items():
        if any(term in str(v).lower() for term in ["supabase", "postgres", "gysgqvwexynpduwijnqi"]):
            db_keys.append(k)
            
    return {
        "keys": sorted(list(os.environ.keys())),
        "vercel_env": os.environ.get("VERCEL_ENV"),
        "git_branch": os.environ.get("VERCEL_GIT_COMMIT_REF"),
        "found_db_keys": db_keys
    }

@app.get("/db-status")
async def get_db_status():
    db_url = get_database_url()
    if not db_url:
        return {"status": "error", "message": "Resilient DATABASE_URL search failed. No matching postgres connection strings found."}
    
    try:
        import psycopg
        conn = psycopg.connect(db_url, connect_timeout=3)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        val = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return {"status": "success", "message": "Successfully connected to PostgreSQL database.", "test_query": val}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}

@app.post("/chat")
async def chat_endpoint(payload: ChatPayload):
    thread_id = payload.thread_id
    user_msg = payload.message
    
    config = {"configurable": {"thread_id": thread_id}}
    
    conn = get_db_connection()
    try:
        graph = compile_graph_with_conn(conn)
        
        # Load current state to see which agent is active
        current_state = graph.get_state(config)
        
        # If thread exists and current agent is already 'booking', route directly to booking
        if current_state and current_state.values and current_state.values.get("current_agent") == "booking":
            graph.update_state(config, {"current_agent": "booking"})
            
        # Run state graph stream
        events = graph.stream(
            {
                "messages": [HumanMessage(content=user_msg)],
                "client_time": payload.client_time,
                "model_type": payload.model_type,
                "api_key": payload.api_key
            }, 
            config, 
            stream_mode="values"
        )
        
        # Retrieve the final response state
        final_state = None
        for event in events:
            final_state = event
            
        if final_state and "messages" in final_state:
            # Find the latest AIMessage with text content
            ans = ""
            for msg in reversed(final_state["messages"]):
                if isinstance(msg, AIMessage) and msg.content.strip():
                    ans = msg.content
                    break
            
            # Clean routing cues from final user-facing text
            ans = ans.replace("[ROUTE_TO_BOOKING]", "").replace("ROUTE_TO_BOOKING", "").strip()
            
            if not ans:
                ans = "I've successfully processed your request."
                
            active_agent = final_state.get("current_agent", "triage")
        else:
            ans = "I encountered an issue processing that. Please try again."
            active_agent = "System"
            
        if is_postgres_mode():
            conn.commit()
    except Exception as e:
        if is_postgres_mode():
            conn.rollback()
        ans = f"Error running agent pipeline: {str(e)}"
        active_agent = "System"
    finally:
        release_db_connection(conn)
        
    return JSONResponse({
        "answer": ans,
        "agent": "Booking Specialist" if active_agent == "booking" else "Triage Agent"
    })

@app.get("/history/{thread_id}")
async def get_history_endpoint(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    messages_list = []
    active_agent = "triage"
    
    conn = get_db_connection()
    try:
        graph = compile_graph_with_conn(conn)
        state = graph.get_state(config)
        if state and state.values:
            active_agent = state.values.get("current_agent", "triage")
            raw_messages = state.values.get("messages", [])
            for msg in raw_messages:
                if isinstance(msg, HumanMessage):
                    messages_list.append({
                        "role": "user",
                        "sender": "You",
                        "content": msg.content
                    })
                elif isinstance(msg, AIMessage):
                    clean_content = msg.content.replace("[ROUTE_TO_BOOKING]", "").replace("ROUTE_TO_BOOKING", "").strip()
                    if clean_content:
                        messages_list.append({
                            "role": "assistant",
                            "sender": "Booking Specialist" if active_agent == "booking" else "Triage Agent",
                            "content": clean_content
                        })
        if is_postgres_mode():
            conn.commit()
    except Exception as e:
        if is_postgres_mode():
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db_connection(conn)
                    
    return JSONResponse({
        "agent": "Booking Specialist" if active_agent == "booking" else "Triage Agent",
        "history": messages_list
    })

@app.get("/slots")
async def get_slots(date: str = None):
    # Default to tomorrow's date if not specified
    if not date:
        date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
    all_slots = ["09:00 AM", "10:00 AM", "11:00 AM", "01:00 PM", "02:00 PM", "03:00 PM", "04:00 PM"]
    
    placeholder = get_placeholder()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT time, email FROM bookings WHERE date = {placeholder}", (date,))
    bookings = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.close()
    release_db_connection(conn)
    
    slots_status = []
    for slot in all_slots:
        if slot in bookings:
            slots_status.append({"time": slot, "status": "booked", "email": bookings[slot]})
        else:
            slots_status.append({"time": slot, "status": "free", "email": ""})
            
    return JSONResponse({
        "date": date,
        "slots": slots_status
    })

@app.get("/notifications")
async def get_notifications_endpoint():
    return JSONResponse(notification_logs)

@app.post("/clear")
async def clear_endpoint(payload: ChatPayload):
    thread_id = payload.thread_id
    placeholder = get_placeholder()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Clear checkpoints and writes in checkpointer database
        if is_postgres_mode():
            cursor.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
            cursor.execute("DELETE FROM writes WHERE thread_id = %s", (thread_id,))
            conn.commit()
        else:
            try:
                conn_history = sqlite3.connect(DB_CHECKPOINT_PATH, check_same_thread=False)
                cursor_history = conn_history.cursor()
                cursor_history.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
                cursor_history.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                conn_history.commit()
                conn_history.close()
            except sqlite3.OperationalError as e:
                if "no such table" not in str(e):
                    raise

        # Reset notification logs
        notification_logs.clear()
        
        # Reset database bookings to initial state
        cursor.execute("DELETE FROM bookings")
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        cursor.execute(f"INSERT INTO bookings (date, time, email) VALUES ({placeholder}, {placeholder}, {placeholder})", (tomorrow, "10:00 AM", "reserved@atmos.com"))
        cursor.execute(f"INSERT INTO bookings (date, time, email) VALUES ({placeholder}, {placeholder}, {placeholder})", (tomorrow, "02:00 PM", "taken@atmos.com"))
        conn.commit()
        res = "cleared"
    except Exception as e:
        if is_postgres_mode():
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"Error during clear: {e}")
        res = "failed"
        return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)
    finally:
        cursor.close()
        release_db_connection(conn)
        
    return JSONResponse({"status": res})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8501))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
