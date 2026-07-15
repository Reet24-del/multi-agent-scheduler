document.addEventListener("DOMContentLoaded", () => {
    const chatForm = document.getElementById("chat-form");
    const userInput = document.getElementById("user-input");
    const messageFeed = document.getElementById("message-feed");
    const clearThreadBtn = document.getElementById("clear-thread-btn");
    const testQueryBtns = document.querySelectorAll(".test-query-btn");
    const agentIndicator = document.getElementById("active-agent-indicator");
    const agentPipeline = document.getElementById("agent-pipeline");

    // Sidebar mobile toggle elements
    const toggleBtn = document.getElementById("sidebar-toggle-btn");
    const closeBtn = document.getElementById("sidebar-close-btn");
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebar-overlay");

    // Engine configuration elements
    const modelSelector = document.getElementById("model-selector");

    // Calendar board elements
    const datePicker = document.getElementById("calendar-date-picker");
    const slotsList = document.getElementById("calendar-slots-list");

    // Webhook feed elements
    const webhookLogsList = document.getElementById("webhook-logs-list");

    // 1. Mobile sidebar drawer controls
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            sidebar.classList.add("open");
            overlay.classList.add("active");
        });
    }
    const closeSidebar = () => {
        sidebar.classList.remove("open");
        overlay.classList.remove("active");
    };
    if (closeBtn) closeBtn.addEventListener("click", closeSidebar);
    if (overlay) overlay.addEventListener("click", closeSidebar);

    // 2. Settings management: persistence
    const loadSettings = () => {
        const savedModel = localStorage.getItem("scheduler_model") || "simulation";
        modelSelector.value = savedModel;
    };

    modelSelector.addEventListener("change", (e) => {
        const model = e.target.value;
        localStorage.setItem("scheduler_model", model);
    });

    // 3. Calendar date picker default (tomorrow)
    const setTomorrowDate = () => {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const yyyy = tomorrow.getFullYear();
        const mm = String(tomorrow.getMonth() + 1).padStart(2, '0');
        const dd = String(tomorrow.getDate()).padStart(2, '0');
        datePicker.value = `${yyyy}-${mm}-${dd}`;
    };

    datePicker.addEventListener("change", () => {
        fetchCalendarSlots(datePicker.value);
    });

    // 4. Retrieve or generate thread ID
    let threadId = localStorage.getItem("scheduler_thread_id");
    if (!threadId) {
        threadId = "thread_" + Math.random().toString(36).substring(2, 15) + "_" + Date.now();
        localStorage.setItem("scheduler_thread_id", threadId);
    }

    // 5. Fetch calendar slots from server
    async function fetchCalendarSlots(dateStr) {
        try {
            const res = await fetch(`/slots?date=${dateStr}`);
            if (res.ok) {
                const data = await res.json();
                renderCalendarSlots(data.slots);
            }
        } catch (err) {
            console.error("Error fetching slots:", err);
        }
    }

    function renderCalendarSlots(slots) {
        slotsList.innerHTML = "";
        if (!slots || slots.length === 0) {
            slotsList.innerHTML = '<li class="slot-empty">No slots configured for this date.</li>';
            return;
        }

        slots.forEach(slot => {
            const li = document.createElement("li");
            const isBooked = slot.status === "booked";
            li.className = `slot-chip ${isBooked ? "booked" : "free"}`;

            const time = document.createElement("span");
            time.className = "slot-time";
            time.textContent = slot.time;

            const state = document.createElement("span");
            state.className = "slot-state";
            state.textContent = isBooked ? slot.email : "Open";
            if (isBooked) state.title = slot.email;

            li.append(time, state);
            slotsList.appendChild(li);
        });
    }

    // 6. Fetch webhook notification log
    async function fetchWebhookLogs() {
        try {
            const res = await fetch("/notifications");
            if (res.ok) {
                const data = await res.json();
                renderWebhookLogs(data);
            }
        } catch (err) {
            console.error("Error fetching webhooks:", err);
        }
    }

    function renderWebhookLogs(logs) {
        webhookLogsList.innerHTML = "";
        if (!logs || logs.length === 0) {
            webhookLogsList.innerHTML = '<li class="no-webhooks">No notifications sent yet. Confirm a booking to trigger one.</li>';
            return;
        }

        // Newest first
        logs.slice().reverse().forEach(log => {
            const li = document.createElement("li");
            const isMocked = log.status.toLowerCase().includes("mocked");
            li.className = `webhook-item ${isMocked ? 'mocked' : ''}`;

            const header = document.createElement("div");
            header.className = "webhook-item-header";
            header.innerHTML = `<span>POST /webhook</span><span class="webhook-item-time">${log.timestamp}</span>`;

            const details = document.createElement("div");
            details.className = "webhook-item-details";
            details.textContent = `to: ${log.email} | ${log.details}`;

            const status = document.createElement("span");
            status.className = "webhook-item-status";
            status.textContent = log.status;

            li.append(header, details, status);
            webhookLogsList.appendChild(li);
        });
    }

    // 7. Load chat thread history from the SQLite checkpointer
    async function loadThreadHistory() {
        try {
            const res = await fetch(`/history/${threadId}`);
            if (res.ok) {
                const data = await res.json();
                updateAgentIndicator(data.agent);

                if (data.history && data.history.length > 0) {
                    messageFeed.innerHTML = "";
                    data.history.forEach(msg => {
                        appendMessage(msg.role, msg.sender, msg.content);
                    });
                } else {
                    appendIntroMessage();
                }
            } else {
                appendIntroMessage();
            }
        } catch (err) {
            console.error("Error restoring history:", err);
            appendIntroMessage();
        }
        scrollToBottom();
    }

    function appendIntroMessage() {
        appendMessage(
            "assistant",
            "Triage Agent",
            "Hello! Welcome to the **Atmos scheduling console**. I am the Triage Agent.\n\nAsk me anything, or say something like `Check tomorrow's availability` and I will route you to the Booking Specialist."
        );
    }

    function updateAgentIndicator(agentName) {
        agentIndicator.innerText = `${agentName} active`;
        if (agentName === "Booking Specialist") {
            agentIndicator.style.color = "var(--booking)";
            agentPipeline.dataset.active = "booking";
        } else {
            agentIndicator.style.color = "var(--triage)";
            agentPipeline.dataset.active = "triage";
        }
    }

    function setPipelineWorking(isWorking) {
        agentPipeline.classList.toggle("working", isWorking);
    }

    // 8. Reset thread and logs
    clearThreadBtn.addEventListener("click", async () => {
        if (confirm("Reset this conversation? This clears the checkpointed thread history and the notification log.")) {
            try {
                const response = await fetch("/clear", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ message: "", thread_id: threadId })
                });
                if (response.ok) {
                    messageFeed.innerHTML = "";
                    updateAgentIndicator("Triage Agent");
                    appendMessage("assistant", "System", "Thread reset. The Triage Agent is ready. Ask to check slot availability or schedule an appointment.");
                    fetchWebhookLogs();
                    fetchCalendarSlots(datePicker.value);
                }
            } catch (err) {
                console.error("Error resetting thread:", err);
            }
        }
    });

    // 9. Scenario buttons
    testQueryBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const queryText = btn.getAttribute("data-query");
            if (queryText) {
                sendUserQuery(queryText);
                if (window.innerWidth <= 768) {
                    closeSidebar();
                }
            }
        });
    });

    // 10. Chat form submission
    chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = userInput.value.trim();
        if (text) {
            sendUserQuery(text);
            userInput.value = "";
        }
    });

    // Send user query to the backend
    async function sendUserQuery(query) {
        appendMessage("user", "You", query);

        const typingIndicator = appendTypingIndicator();
        setPipelineWorking(true);
        scrollToBottom();

        const activeModel = modelSelector.value;
        const apiKey = null;

        try {
            const response = await fetch("/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: query,
                    thread_id: threadId,
                    client_time: new Date().toISOString(),
                    model_type: activeModel,
                    api_key: apiKey
                })
            });

            typingIndicator.remove();

            if (response.ok) {
                const data = await response.json();
                updateAgentIndicator(data.agent);
                appendMessage("assistant", data.agent, data.answer);
                fetchCalendarSlots(datePicker.value);
                fetchWebhookLogs();
            } else {
                appendMessage("assistant", "System", "Something went wrong processing that request. Check the server logs and try again.");
            }
        } catch (err) {
            typingIndicator.remove();
            console.error("Network error:", err);
            appendMessage("assistant", "System", "Connection lost. Check that the FastAPI server is running, then resend your message.");
        }

        setPipelineWorking(false);
        scrollToBottom();
    }

    // Agent name to style key
    function agentKey(senderName) {
        if (senderName === "Booking Specialist") return "booking";
        if (senderName === "Triage Agent") return "triage";
        return "system";
    }

    // Append a message bubble
    function appendMessage(role, senderName, text) {
        const row = document.createElement("div");
        row.className = `message-row ${role}`;

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";

        if (role === "assistant") {
            const key = agentKey(senderName);
            bubble.classList.add(`from-${key}`);

            const tag = document.createElement("span");
            tag.className = `agent-tag tag-${key}`;
            tag.innerText = senderName;
            bubble.appendChild(tag);
        }

        const contentDiv = document.createElement("div");
        contentDiv.innerHTML = marked.parse(text);
        bubble.appendChild(contentDiv);

        row.appendChild(bubble);
        messageFeed.appendChild(row);
        scrollToBottom();
    }

    // Typing indicator
    function appendTypingIndicator() {
        const row = document.createElement("div");
        row.className = "message-row assistant";

        const bubble = document.createElement("div");
        bubble.className = "message-bubble from-system";

        const tag = document.createElement("span");
        tag.className = "agent-tag tag-system";
        tag.innerText = "Routing";
        bubble.appendChild(tag);

        const dots = document.createElement("div");
        dots.className = "typing-dots";
        dots.innerHTML = `
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        `;
        bubble.appendChild(dots);
        row.appendChild(bubble);
        messageFeed.appendChild(row);
        return row;
    }

    function scrollToBottom() {
        messageFeed.scrollTop = messageFeed.scrollHeight;
    }

    // --- Initialization ---
    loadSettings();
    setTomorrowDate();
    fetchCalendarSlots(datePicker.value);
    fetchWebhookLogs();
    loadThreadHistory();

    // Poll the board and webhook feed for near-real-time updates
    setInterval(() => {
        fetchCalendarSlots(datePicker.value);
        fetchWebhookLogs();
    }, 4000);
});
