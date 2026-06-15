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

moodSlider.addEventListener("input", () => {
    moodValue.textContent = moodSlider.value;
});

goalSlider.addEventListener("input", () => {
    goalValue.textContent = goalSlider.value;
});

async function loadEntries() {
    const res = await fetch("/entries");
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
        </div>
    `
        )
        .join("");
}

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
    const data = {
        title: document.getElementById("title").value,
        content: document.getElementById("content").value,
        mood: parseInt(moodSlider.value),
        goal_progress: parseInt(goalSlider.value),
    };

    const res = await fetch("/entries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });

    if (res.ok) {
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
        body: JSON.stringify({ message }),
    });

    const data = await res.json();
    chatMessages.innerHTML += `<div class="chat-msg assistant">${data.response}</div>`;
    chatMessages.scrollTop = chatMessages.scrollHeight;
});

loadEntries();
loadStreaks();
