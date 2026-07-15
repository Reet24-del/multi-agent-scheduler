import os
import datetime
from app import graph, check_availability_func, reserve_slot_func

def test_local_logic():
    print("==========================================================================")
    print("🧪 Running Local Graph & Database Tests...")
    print("==========================================================================")
    
    # 1. Test Availability Function
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Checking slot availability for tomorrow ({tomorrow}):")
    avail_res = check_availability_func(tomorrow)
    print(f"Result: {avail_res}")
    assert "Available slots" in avail_res
    
    # 2. Test Booking Conflict Logic
    print("\nTesting reservation on a free slot (tomorrow at 11:00 AM):")
    res_success = reserve_slot_func(tomorrow, "11:00 AM", "success@gmail.com")
    print(f"Result: {res_success}")
    assert "Success" in res_success
    
    print("\nTesting booking conflict on the same slot (tomorrow at 11:00 AM):")
    res_conflict = reserve_slot_func(tomorrow, "11:00 AM", "second@gmail.com")
    print(f"Result: {res_conflict}")
    assert "Conflict" in res_conflict
    
    # 3. Verify LangGraph structure compiles
    print("\nVerifying LangGraph structure compilation:")
    print(graph.get_graph().draw_ascii())
    print("Graph structure compiled and verified successfully!")
    print("==========================================================================")

if __name__ == "__main__":
    # Temporarily set mock Groq key for compilation verification if not set
    if "GROQ_API_KEY" not in os.environ:
        os.environ["GROQ_API_KEY"] = "gsk_mock_test_key_for_compilation"
    test_local_logic()
