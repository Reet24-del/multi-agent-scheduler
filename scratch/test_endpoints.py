import os
import sqlite3
from fastapi.testclient import TestClient

# Delete previous database for a clean verification
DB_DATA_PATH = "scheduler_data.db"
if os.path.exists(DB_DATA_PATH):
    try:
        os.remove(DB_DATA_PATH)
    except Exception:
        pass

from app import app, init_data_db
init_data_db()

client = TestClient(app)

def test_endpoints():
    print("==========================================================================")
    print("🧪 Running API Endpoints Verification Tests...")
    print("==========================================================================")
    
    # 1. Test Slots endpoint
    print("1. Testing GET /slots...")
    response = client.get("/slots")
    assert response.status_code == 200
    slots_data = response.json()
    assert "slots" in slots_data
    assert "date" in slots_data
    print("   ✅ GET /slots passed!")

    # 2. Test Triage Chat endpoint
    print("\n2. Testing POST /chat (General Query -> Triage)...")
    thread_id = "test_endpoints_thread_999"
    payload = {
        "message": "Hi, who are you?",
        "thread_id": thread_id,
        "model_type": "simulation"
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    chat_data = response.json()
    print(f"   Agent response: {chat_data['answer']}")
    assert chat_data["agent"] == "Triage Agent"
    print("   ✅ General Query / Triage passed!")

    # 3. Test Booking Router
    print("\n3. Testing POST /chat (Booking query -> route to Booking Specialist)...")
    payload = {
        "message": "Check availability tomorrow",
        "thread_id": thread_id,
        "model_type": "simulation"
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    chat_data = response.json()
    print(f"   Agent response: {chat_data['answer']}")
    assert chat_data["agent"] == "Booking Specialist"
    print("   ✅ Scheduling intent routing passed!")

    # 4. Test History retrieval
    print("\n4. Testing GET /history/{thread_id}...")
    response = client.get(f"/history/{thread_id}")
    assert response.status_code == 200
    history_data = response.json()
    assert "history" in history_data
    assert history_data["agent"] == "Booking Specialist"
    assert len(history_data["history"]) >= 2
    print(f"   Retrieved {len(history_data['history'])} messages from checkpoint storage.")
    print("   ✅ History recovery passed!")

    # 5. Test Webhook notifications log
    print("\n5. Testing GET /notifications...")
    response = client.get("/notifications")
    assert response.status_code == 200
    notif_data = response.json()
    assert isinstance(notif_data, list)
    print("   ✅ GET /notifications passed!")
    
    print("\n==========================================================================")
    print("🎉 All API Endpoints Verification Tests Passed successfully!")
    print("==========================================================================")

if __name__ == "__main__":
    test_endpoints()
