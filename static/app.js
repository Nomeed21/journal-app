const entryForm = document.getElementById("entry-form");
const chatForm = document.getElementById("chat-form");
const habitForm = document.getElementById("habit-form");
const entriesDiv = document.getElementById("entries");
const chatMessages = document.getElementById("chat-messages");
const streaksDiv = document.getElementById("streaks");
const moodSlider = document.getElementById("mood");
const goalSlider = document.getElementById("goal-progress");
const moodValue = document.getElementById("mood-value");
const goalValue = document.getElementById("goal-value");

let conversationHistory = [];

moodSlider.addEventListener("input", () => {
    moodValue.textContent = moodSlider.value;
});

goalSlider.addEventListener("input", () => {
    goalValue.textContent = goalSlider.value;
});

async function loadEntries(filters = {}) {
    // Build query string from filter parameters
    const params = new URLSearchParams();
    if (filters.tag) params.append("tag", filters.tag);
    if (filters.keyword) params.append("keyword", filters.keyword);

    const res = await fetch(`/entries?${params.toString()}`);
    const entries = await res.json();
    entriesDiv.innerHTML = entries
        .map(
            (e) => `
        <div class="entry-card">
            <strong>${e.title}</strong>
            <p>${e.content}</p>
            <div class="meta">
                ${e.created_at.slice(0, 10)} | Mood: ${e.mood}/5 | Goal: ${e.goal_progress}%
            </div>
            ${e.tags && e.tags.length > 0 ? `<div class="tags">${e.tags.map((t) => `<span>${t}</span>`).join("")}</div>` : ""}
            <div class="actions">
                <button onclick="editEntry(
  ${e.id},
  '${e.title.replace(/'/g, "\\'")}',
  '${e.content.replace(/'/g, "\\'").replace(/\n/g, "\\n")}',
  ${e.mood},
  ${e.goal_progress},
  '${(e.tags || []).join(",")}'
)">Edit</button>

                <button class="delete-btn" onclick="deleteEntry(${e.id})">Delete</button>
            </div>
        </div>
    `
        )
        .join("");
}

let editingId = null;

function editEntry(id, title, content, mood, goalProgress, tags) {
    // Pre-fill the form with existing entry data
    editingId = id;
    document.getElementById("title").value = title;
    document.getElementById("content").value = content;
    moodSlider.value = mood;
    goalSlider.value = goalProgress;
    moodValue.textContent = mood;
    goalValue.textContent = goalProgress;
    document.getElementById("tags").value = tags;
    // Scroll to the form
    document.querySelector(".journal-form").scrollIntoView({ behavior: "smooth" });
}

async function deleteEntry(id) {
    if (!confirm("Are you sure you want to delete this entry?")) return;
    const res = await fetch(`/entries/${id}`, { method: "DELETE" });
    if (res.ok) loadEntries();
}

// Filter button handlers
document.getElementById("filter-btn").addEventListener("click", () => {
    const keyword = document.getElementById("filter-keyword").value;
    const tag = document.getElementById("filter-tag").value;
    loadEntries({ keyword, tag });
});

document.getElementById("clear-btn").addEventListener("click", () => {
    document.getElementById("filter-keyword").value = "";
    document.getElementById("filter-tag").value = "";
    loadEntries();
});


async function loadStreaks() {
    const res = await fetch("/habits/streaks");
    const streaks = await res.json();
    const entries = Object.entries(streaks);
    if (entries.length === 0) {
        streaksDiv.innerHTML = "<p>No habits logged yet.</p>";
        return;
    }
    streaksDiv.innerHTML = entries
        .map(([name, data]) => `<div class="entry-card"><strong>${name}</strong> — ${data.current_streak}-day streak (${data.total_logs} total logs)</div>`)
        .join("");
}

entryForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const tagsRaw = document.getElementById("tags").value;
    const tags = tagsRaw ? tagsRaw.split(",").map((t) => t.trim()).filter(Boolean) : [];

    const data = {
        title: document.getElementById("title").value,
        content: document.getElementById("content").value,
        mood: parseInt(moodSlider.value),
        goal_progress: parseInt(goalSlider.value),
        tags: tags,
    };

    let res;
    if (editingId) {
        // Update existing entry
        res = await fetch(`/entries/${editingId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
    } else {
        // Create new entry
        res = await fetch("/entries", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
    }

    if (res.ok) {
        editingId = null;
        entryForm.reset();
        moodSlider.value = 3;
        goalSlider.value = 50;
        moodValue.textContent = "3";
        goalValue.textContent = "50";
        loadEntries();
    }
});

habitForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("habit-name").value;
    const res = await fetch("/habits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
    });
    if (res.ok) {
        document.getElementById("habit-name").value = "";
        loadStreaks();
    }
});

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value;
    input.value = "";

    chatMessages.innerHTML += `<div class="chat-msg user">${message}</div>`;
    chatMessages.scrollTop = chatMessages.scrollHeight;



    const res = await fetch("/chat", {
	method: "POST",
	headers: { "Content-Type": "application/json" },
	    body: JSON.stringify({
	    message,
	    history: conversationHistory
        }),
    });
    const data = await res.json();
    
    conversationHistory.push({
        role: "user",
        content: message
    });

    conversationHistory.push({
        role: "assistant",
        content: data.response
    });
        chatMessages.innerHTML += `<div class="chat-msg assistant">${data.response}</div>`;
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });

async function loadCharts() {
    // Fetch trends data for the last 30 days
    const trendsRes = await fetch("/entries/trends?days=30");
    const trends = await trendsRes.json();

    // Fetch day-of-week correlation data
    const corrRes = await fetch("/entries/correlations");
    const correlations = await corrRes.json();

    // Render the mood/goal trends line chart
    const trendsCtx = document.getElementById("trends-chart").getContext("2d");
    new Chart(trendsCtx, {
        type: "line",
        data: {
            labels: trends.map((t) => t.date),
            datasets: [
                {
                    label: "Mood (1-5)",
                    data: trends.map((t) => t.avg_mood),
                    borderColor: "#3498db",
                    backgroundColor: "rgba(52, 152, 219, 0.1)",
                    yAxisID: "y",
                    tension: 0.3,
                },
                {
                    label: "Goal Progress (%)",
                    data: trends.map((t) => t.avg_goal),
                    borderColor: "#2ecc71",
                    backgroundColor: "rgba(46, 204, 113, 0.1)",
                    yAxisID: "y1",
                    tension: 0.3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { min: 1, max: 5, position: "left", title: { display: true, text: "Mood" } },
                y1: { min: 0, max: 100, position: "right", title: { display: true, text: "Goal %" }, grid: { drawOnChartArea: false } },
            },
        },
    });

    // Render the day-of-week bar chart
    const corrCtx = document.getElementById("correlation-chart").getContext("2d");
    new Chart(corrCtx, {
        type: "bar",
        data: {
            labels: correlations.map((c) => c.day),
            datasets: [
                {
                    label: "Avg Mood",
                    data: correlations.map((c) => c.avg_mood),
                    backgroundColor: "rgba(52, 152, 219, 0.6)",
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { min: 0, max: 5, title: { display: true, text: "Avg Mood" } },
            },
        },
    });
}

loadCharts();
loadEntries();
loadStreaks();
