document.addEventListener("DOMContentLoaded", () => {

// ---------------------------------------------------------------------------
// Page navigation
// ---------------------------------------------------------------------------
const pages    = document.querySelectorAll(".page");
const navItems = document.querySelectorAll(".nav-item");

function showPage(pageId) {
    pages.forEach(p => p.classList.remove("active"));
    navItems.forEach(n => n.classList.remove("active"));
    const page = document.getElementById("page-" + pageId);
    if (page) page.classList.add("active");
    const nav  = document.querySelector(`.nav-item[data-page="${pageId}"]`);
    if (nav)   nav.classList.add("active");
    if (pageId === "entries")  loadEntries();
    if (pageId === "quests")   { loadGoals(); generateDailyQuest(); }
    if (pageId === "skills")   loadSkills();
    if (pageId === "habits")   loadStreaks();
    if (pageId === "insights") { loadCharts(); loadInsights(); }
    if (pageId === "review")   {}
    if (pageId === "journal")  { loadProactiveCoaching(); loadTodayStatus(); }
    if (pageId === "domains")  loadDomains();
}

navItems.forEach(item =>
    item.addEventListener("click", e => { e.preventDefault(); showPage(item.dataset.page); })
);

// ---------------------------------------------------------------------------
// XP / Level HUD (shown in sidebar)
// ---------------------------------------------------------------------------
async function loadXPHUD() {
    try {
        const data = await (await fetch("/achievements")).json();
        const info = data.level_info;
        const el   = document.getElementById("xp-hud");
        if (!el) return;
        el.innerHTML = `
            <div class="xp-hud-level">Lv ${info.level}</div>
            <div class="xp-hud-bar-wrap">
                <div class="xp-hud-bar-fill" style="width:${Math.round(info.xp_in_level/5)}%"></div>
            </div>
            <div class="xp-hud-text">${info.xp_in_level} / 500 XP</div>`;
    } catch (_) {}
}

// ---------------------------------------------------------------------------
// Achievement toast
// ---------------------------------------------------------------------------
function showAchievementToast(achievements) {
    if (!achievements || achievements.length === 0) return;
    achievements.forEach((ach, i) => {
        setTimeout(() => {
            const toast = document.createElement("div");
            toast.className = "achievement-toast";
            toast.innerHTML = `🏆 <strong>${ach.name}</strong> unlocked! +${ach.xp} XP`;
            document.body.appendChild(toast);
            setTimeout(() => toast.classList.add("show"), 50);
            setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 3500);
        }, i * 600);
    });
    loadXPHUD();
}

// XP flash when a quest is completed
function showXPFlash(xp, category) {
    const el = document.createElement("div");
    el.className = "xp-flash";
    el.textContent = `+${xp} XP (${category})`;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add("show"), 50);
    setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 400); }, 2000);
    loadXPHUD();
}

// ---------------------------------------------------------------------------
// Entry tabs
// ---------------------------------------------------------------------------
let currentEntryType   = "morning";
let editingId          = null;
let conversationHistory = [];

const entryTabs = document.querySelectorAll(".entry-tab");
const submitBtn = document.getElementById("entry-submit");
const TAB_LABELS = { morning: "Save Morning Entry", night: "Save Night Reflection", free: "Save Entry" };

let todayDone = { morning: false, night: false, free: false };

async function loadTodayStatus() {
    try {
        const data = await (await fetch("/entries/today-status")).json();
        todayDone = { morning: data.morning, night: data.night, free: data.free };
        // Update tab badges
        entryTabs.forEach(tab => {
            const type = tab.dataset.type;
            const done = todayDone[type];
            tab.classList.toggle("entry-tab--done", done);
            // Update label: add checkmark if done
            const base = { morning: "🌅 Morning", night: "🌙 Night", free: "📓 Free" }[type];
            tab.textContent = done ? base + " ✓" : base;
        });
        // Refresh current tab state
        applyTabDoneState(currentEntryType);
    } catch (_) {}
}

function applyTabDoneState(type) {
    const done = !editingId && todayDone[type];
    submitBtn.disabled = done;
    submitBtn.textContent = editingId
        ? "Update Entry"
        : done
            ? `${type.charAt(0).toUpperCase()+type.slice(1)} entry already saved today`
            : (TAB_LABELS[type] || "Save Entry");

    // Show/hide the "edit today's entry" link
    let editLink = document.getElementById("edit-today-link");
    if (done && !editingId) {
        if (!editLink) {
            editLink = document.createElement("div");
            editLink.id = "edit-today-link";
            editLink.className = "edit-today-link";
            submitBtn.parentNode.insertBefore(editLink, submitBtn.nextSibling);
        }
        editLink.innerHTML = `<a href="#" id="edit-today-btn">Edit today's ${type} entry instead →</a>`;
        document.getElementById("edit-today-btn").addEventListener("click", async (e) => {
            e.preventDefault();
            const today = new Date().toISOString().slice(0,10);
            const entries = await (await fetch(`/entries?start_date=${today}T00:00:00Z`)).json();
            const match = entries.find(en => en.entry_type === type);
            if (match) window.editEntry(match.id, match.title, match.content, match.mood, (match.tags||[]).join(","), match.entry_type);
        });
    } else if (editLink) {
        editLink.remove();
    }
}

function switchEntryTab(type) {
    currentEntryType = type;
    document.getElementById("entry-type").value = type;
    entryTabs.forEach(t => t.classList.toggle("active", t.dataset.type === type));
    document.getElementById("fields-morning").classList.toggle("hidden", type !== "morning");
    document.getElementById("fields-night").classList.toggle("hidden",   type !== "night");
    document.getElementById("fields-free").classList.toggle("hidden",    type !== "free");
    if (type === "night") loadNightChecklist();
    applyTabDoneState(type);
}

entryTabs.forEach(tab => tab.addEventListener("click", () => switchEntryTab(tab.dataset.type)));

// Slider wiring
[["m-mood","m-mood-val"],["m-energy","m-energy-val"],["m-focus","m-focus-val"],
 ["n-mood","n-mood-val"],["n-energy","n-energy-val"],["n-focus","n-focus-val"],
 ["f-mood","f-mood-val"],["f-energy","f-energy-val"],["f-focus","f-focus-val"]
].forEach(([sid, vid]) => {
    const slider = document.getElementById(sid), val = document.getElementById(vid);
    if (slider && val) slider.addEventListener("input", () => val.textContent = slider.value);
});

// ---------------------------------------------------------------------------
// Night checklist
// ---------------------------------------------------------------------------
let nightTasks = [];

async function loadNightChecklist() {
    let el = document.getElementById("night-plan-checklist");
    if (!el) {
        el = document.createElement("div");
        el.id = "night-plan-checklist";
        el.className = "field-group";
        const fn = document.getElementById("fields-night");
        fn.insertBefore(el, fn.firstChild);
    }
    el.innerHTML = "<p class='plan-loading'>Loading today's plan…</p>";
    try {
        // Fetch plan and habits independently so one failure doesn't kill the other
        let data = { plan: null }, streaks = {};
        try {
            const planRes = await fetch("/plans/today");
            if (planRes.ok) data = await planRes.json();
        } catch (_) {}
        try {
            const streaksRes = await fetch("/habits/balance");
            if (streaksRes.ok) {
                const habData = await streaksRes.json();
                streaks = habData.streaks || {};
            }
        } catch (_) {}
        // Habit checklist
        const habitNames = Object.keys(streaks);
        let habitSection = "";
        if (habitNames.length) {
            habitSection = `
                <div class="ms-label" style="margin-top:.75rem">Today's Habits</div>
                ${habitNames.map(name => {
                    const s = streaks[name];
                    const cat = s.category || "Productivity";
                    return `<label class="night-task-row">
                        <input type="checkbox" class="night-habit-check" data-name="${name}" data-cat="${cat}">
                        <span>${name} <em style="font-size:.75rem;color:var(--ink-faint)">${s.current_streak}-day streak</em></span>
                    </label>`;
                }).join("")}`;
        }

        if (!data.plan || (!data.plan.main_goal && !(data.plan.tasks || []).length)) {
            el.innerHTML = `<p class='plan-loading'>No morning plan found.</p>${habitSection}`;
            nightTasks = [];
        } else {
            nightTasks = (data.plan.tasks || []).map(t => ({ ...t, completed: t.completed || false }));
            const goalLine = data.plan.main_goal
                ? `<div class="night-main-goal">🎯 <strong>${data.plan.main_goal}</strong></div>` : "";
            const taskRows = nightTasks.map((t, i) => `
                <label class="night-task-row">
                    <input type="checkbox" class="night-check" data-index="${i}" ${t.completed ? "checked" : ""}>
                    <span>${t.title}</span>
                </label>`).join("");
            el.innerHTML = `<label class="field-label">Today's Plan — How Did It Go?</label>${goalLine}
                ${taskRows || "<p class='plan-loading'>No tasks were planned.</p>"}
                ${habitSection}`;
        }
        el.querySelectorAll(".night-check").forEach(cb =>
            cb.addEventListener("change", () => { nightTasks[+cb.dataset.index].completed = cb.checked; })
        );
        // Quick-log habits from night reflection
        el.querySelectorAll(".night-habit-check").forEach(cb => {
            cb.addEventListener("change", async () => {
                if (cb.checked) {
                    await fetch("/habits", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ name: cb.dataset.name, category: cb.dataset.cat, difficulty: "Normal" }),
                    });
                }
            });
        });
    } catch (_) {
        el.innerHTML = "<p class='plan-loading'>Error rendering night checklist. Check the console.</p>";
    }
}

// ---------------------------------------------------------------------------
// Entry form submit
// ---------------------------------------------------------------------------
const entryForm = document.getElementById("entry-form");
const gv = id => { const e = document.getElementById(id); return e ? e.value : ""; };
const gi = (id, fallback=3) => { const v = parseInt(gv(id)); return isNaN(v) ? fallback : v; };

entryForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    let entryData;

    if (currentEntryType === "morning") {
        const tasks = [gv("morning-task-1"), gv("morning-task-2"), gv("morning-task-3")]
            .map(s => s.trim()).filter(Boolean)
            .map((title, i) => ({ id: `t${i}`, title, completed: false }));
        entryData = {
            title:         gv("morning-main-goal").trim() || "Morning Entry",
            content:       [gv("morning-main-goal"),
                            gv("morning-obstacles") ? `Obstacles: ${gv("morning-obstacles")}` : "",
                            gv("morning-counterattack") ? `Plan: ${gv("morning-counterattack")}` : ""]
                           .filter(Boolean).join("\n"),
            mood: gi("m-mood"),
            energy: gi("m-energy"), focus: gi("m-focus"), tags: [], entry_type: "morning",
        };
        if (gv("morning-main-goal").trim() || tasks.length) {
            await fetch("/plans", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ main_goal: gv("morning-main-goal").trim(), tasks }),
            });
        }
    } else if (currentEntryType === "night") {
        const parts = [
            gv("night-win")      ? `Win: ${gv("night-win")}` : "",
            gv("night-learned")  ? `Learned: ${gv("night-learned")}` : "",
            gv("night-well")     ? `Went well: ${gv("night-well")}` : "",
            gv("night-poorly")   ? `Went poorly: ${gv("night-poorly")}` : "",
            gv("night-grateful") ? `Grateful for: ${gv("night-grateful")}` : "",
            gv("night-tomorrow") ? `Tomorrow: ${gv("night-tomorrow")}` : "",
        ].filter(Boolean);
        entryData = {
            title: gv("night-win").trim().slice(0, 60) || "Night Reflection",
            content: parts.join("\n"),
            mood: gi("n-mood"),
            energy: gi("n-energy"), focus: gi("n-focus"), tags: [], entry_type: "night",
        };
        if (nightTasks.length) {
            await fetch("/plans/today/reflect", {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ tasks: nightTasks, reflection_note: gv("night-win") }),
            });
        }
    } else {
        const tagsRaw = gv("free-tags");
        entryData = {
            title: gv("free-title").trim() || "Journal Entry",
            content: gv("free-content"),
            mood: gi("f-mood"),
            energy: gi("f-energy"), focus: gi("f-focus"),
            tags: tagsRaw ? tagsRaw.split(",").map(t => t.trim()).filter(Boolean) : [],
            entry_type: "free",
        };
    }

    let res;
    if (editingId) {
        res = await fetch(`/entries/${editingId}`, {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(entryData),
        });
    } else {
        res = await fetch("/entries", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(entryData),
        });
    }
    if (!res.ok) return;
    const saved = await res.json();

    // Guard: already written today — offer to edit instead
    if (saved.status === "already_exists") {
        const toast = document.createElement("div");
        toast.className = "achievement-toast show";
        toast.style.background = "#e65100";
        toast.innerHTML = `📝 ${saved.message}`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 4000);
        loadTodayStatus();
        return;
    }

    // Show achievement toasts from the entry creation response
    if (saved.new_achievements) showAchievementToast(saved.new_achievements);

    // Run action engine in background
    fetch("/action-engine", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            mood: entryData.mood,
            content: entryData.content, energy: entryData.energy || 3,
            focus: entryData.focus || 3, entry_type: currentEntryType,
        }),
    }).then(r => r.json()).then(data => {
        if (data.triggered && data.action) showActionBanner(data);
    }).catch(() => {});

    // Auto-generate quests from this entry (non-blocking)
    if (!editingId) {
        fetch("/journal/generate-quests", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: entryData.content, mood: entryData.mood, entry_type: currentEntryType }),
        }).then(r => r.json()).then(data => {
            if (data.quests && data.quests.length) showQuestSuggestions(data.quests);
        }).catch(() => {});
    }

    resetEntryForm();
    loadTodayStatus();
    loadAIInsight();
    loadXPHUD();
    loadProactiveCoaching();
});

// ---------------------------------------------------------------------------
// Action engine banner
// ---------------------------------------------------------------------------
function showActionBanner(data) {
    let banner = document.getElementById("action-banner");
    if (!banner) {
        banner = document.createElement("div");
        banner.id = "action-banner";
        banner.className = "action-banner";
        const form = document.getElementById("entry-form");
        form.parentNode.insertBefore(banner, form.nextSibling);
    }
    const a = data.action;
    banner.innerHTML = `
        <div class="action-banner-header">
            <span class="action-banner-label">⚡ Action Engine</span>
            <button class="action-banner-close" onclick="this.closest('.action-banner').remove()">✕</button>
        </div>
        <div class="action-banner-body"><strong>${a.action}</strong>
            <span style="font-size:.85rem;color:var(--ink-soft)"> — ${a.reason}</span></div>
        <div class="action-banner-footer">
            <span class="dq-chip">${a.category}</span>
            <span class="dq-chip">⏱ ${a.duration_minutes}m</span>
            <span class="dq-chip">+${a.xp} XP</span>
            ${data.quest_created ? '<span class="dq-chip dq-chip--success">✓ Added to Quests</span>' : ''}
        </div>`;
    banner.classList.add("show");
}

// ---------------------------------------------------------------------------
// Quest suggestions from journal
// ---------------------------------------------------------------------------
function showQuestSuggestions(quests) {
    let panel = document.getElementById("quest-suggestions");
    if (!panel) {
        panel = document.createElement("div");
        panel.id = "quest-suggestions";
        panel.className = "quest-suggestions";
        const form = document.getElementById("entry-form");
        form.parentNode.insertBefore(panel, form.nextSibling);
    }
    panel.innerHTML = `
        <div class="qs-header">
            <span class="qs-label">✦ Quests from your entry</span>
            <button class="action-banner-close" onclick="this.closest('.quest-suggestions').remove()">✕</button>
        </div>
        ${quests.map((q, i) => `
            <div class="qs-item">
                <div class="qs-title">${q.title}</div>
                <div class="qs-meta"><span class="dq-chip">${q.category}</span>
                    <span class="dq-chip">${q.difficulty}</span>
                    <span class="dq-chip">⏱ ${q.time_minutes}m</span>
                    <span style="font-size:.8rem;color:var(--ink-soft)">${q.reason}</span></div>
                <button class="qs-add-btn" onclick="addQuestFromSuggestion('${q.title.replace(/'/g,"\\'")}', '${q.category}', this)">
                    + Add Quest</button>
            </div>`).join("")}`;
    panel.classList.add("show");
}

window.addQuestFromSuggestion = async function(title, category, btn) {
    // Find or create a goal in that category
    const goalsRes  = await fetch("/goals");
    const goals     = await goalsRes.json();
    let goal        = goals.find(g => g.category === category);
    if (!goal) {
        const newGoal = await fetch("/goals", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: `${category} Goals`, category }),
        }).then(r => r.json());
        goal = newGoal.goal;
    }
    await fetch(`/goals/${goal.id}/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    btn.textContent = "✓ Added";
    btn.disabled    = true;
};

// ---------------------------------------------------------------------------
// Proactive coaching alert on Journal page
// ---------------------------------------------------------------------------
async function loadProactiveCoaching() {
    try {
        const data = await (await fetch("/coaching/proactive")).json();
        let el     = document.getElementById("proactive-coaching");
        if (!el) return;
        if (!data.needs_attention) {
            el.style.display = "none";
            return;
        }
        el.style.display = "";
        el.innerHTML = `
            <div class="proactive-label">🔔 Coach Alert</div>
            <div class="proactive-nudge">${data.nudge}</div>
            <div class="proactive-alerts">
                ${data.alerts.map(a => `<span class="proactive-chip">${a}</span>`).join("")}
            </div>`;
    } catch (_) {}
}

// ---------------------------------------------------------------------------
// Form reset
// ---------------------------------------------------------------------------
function resetEntryForm() {
    editingId = null;
    entryForm.reset();
    ["m-mood-val","m-energy-val","m-focus-val","n-mood-val",
     "n-energy-val","n-focus-val","f-mood-val","f-energy-val","f-focus-val"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = "3";
    });
    nightTasks = [];
    switchEntryTab("morning");
}

// ---------------------------------------------------------------------------
// Entries page
// ---------------------------------------------------------------------------
const entriesDiv = document.getElementById("entries");
const TYPE_BADGE = { morning: "🌅 Morning", night: "🌙 Night", free: "📓 Free" };

async function loadEntries(filters = {}) {
    const params = new URLSearchParams();
    if (filters.tag)     params.append("tag",     filters.tag);
    if (filters.keyword) params.append("keyword", filters.keyword);
    const entries = await (await fetch(`/entries?${params}`)).json();
    entriesDiv.innerHTML = entries.map(e => {
        const type  = e.entry_type || "free";
        const badge = TYPE_BADGE[type] || type;
        return `<div class="entry-card">
            <div class="entry-card-header">
                <strong>${e.title}</strong>
                <span class="entry-type-badge entry-type-badge--${type}">${badge}</span>
            </div>
            <p>${e.content.replace(/\n/g, "<br>")}</p>
            <div class="meta">${e.created_at.slice(0,10)} | Mood: ${e.mood}/5</div>
            ${e.tags && e.tags.length ? `<div class="tags">${e.tags.map(t => `<span>${t}</span>`).join("")}</div>` : ""}
            <div class="actions">
                <button onclick="window.editEntry(${e.id},'${e.title.replace(/'/g,"\\'")}',
                    '${e.content.replace(/'/g,"\\'").replace(/\n/g,"\\n")}',
                    ${e.mood},'${(e.tags||[]).join(",")}','${type}')">Edit</button>
                <button class="delete-btn" onclick="window.deleteEntry(${e.id})">Delete</button>
            </div>
        </div>`;
    }).join("") || "<p style='color:var(--ink-faint);font-style:italic'>No entries yet.</p>";
}

window.editEntry = async function(id, title, content, mood, tags, entryType) {
    editingId = id;
    showPage("journal");
    switchEntryTab(entryType || "free");
    if (entryType === "morning") {
        document.getElementById("morning-main-goal").value = title || "";
        const lines   = content.split("\\n");
        const obsLine = lines.find(l => l.startsWith("Obstacles:"));
        const planLine= lines.find(l => l.startsWith("Plan:"));
        if (obsLine)  document.getElementById("morning-obstacles").value    = obsLine.replace("Obstacles: ","");
        if (planLine) document.getElementById("morning-counterattack").value = planLine.replace("Plan: ","");
        document.getElementById("m-mood").value = mood;
        document.getElementById("m-mood-val").textContent = mood;
    } else if (entryType === "night") {
        const lines   = content.split("\\n");
        const get     = (p) => (lines.find(l => l.startsWith(p)) || "").replace(p,"");
        document.getElementById("night-win").value       = get("Win: ");
        document.getElementById("night-learned").value   = get("Learned: ");
        document.getElementById("night-well").value      = get("Went well: ");
        document.getElementById("night-poorly").value    = get("Went poorly: ");
        document.getElementById("night-grateful").value  = get("Grateful for: ");
        document.getElementById("night-tomorrow").value  = get("Tomorrow: ");
        document.getElementById("n-mood").value          = mood;
        document.getElementById("n-mood-val").textContent = mood;
    } else {
        document.getElementById("free-title").value   = title || "";
        document.getElementById("free-content").value = content.replace(/\\n/g,"\n");
        document.getElementById("free-tags").value    = tags || "";
        document.getElementById("f-mood").value       = mood;
        document.getElementById("f-mood-val").textContent = mood;
    }
    submitBtn.textContent = "Update Entry";
    document.getElementById("entry-form").scrollIntoView({ behavior: "smooth" });
};

window.deleteEntry = async function(id) {
    if (!confirm("Delete this entry?")) return;
    if ((await fetch(`/entries/${id}`, { method: "DELETE" })).ok) loadEntries();
};

document.getElementById("filter-btn").addEventListener("click", () =>
    loadEntries({ keyword: document.getElementById("filter-keyword").value,
                  tag:     document.getElementById("filter-tag").value }));
document.getElementById("clear-btn").addEventListener("click", () => {
    document.getElementById("filter-keyword").value = "";
    document.getElementById("filter-tag").value     = "";
    loadEntries();
});

// ---------------------------------------------------------------------------
// Habits — enhanced
// ---------------------------------------------------------------------------
const streaksDiv = document.getElementById("streaks");
const habitForm  = document.getElementById("habit-form");

const CATEGORY_ICONS = {
    Physical: "🏃", Learning: "📚", Mind: "🧘",
    Social: "👥", Productivity: "⚡", Creativity: "🎨",
};
const DIFF_COLORS = { Easy: "#4caf50", Normal: "#f7a94b", Hard: "#ff7043", Elite: "#9c27b0" };
const MASTERY_COLORS = ["#c9a8b0","#d98aa0","#b8617c","#8b2252","#4a0e2a"];

async function loadStreaks() {
    // Fetch balance (new endpoint) with fallback to legacy streaks endpoint
    let streaks = {}, atRisk = [], balanceData = { balance: null, streaks: {} };
    try {
        const [balanceRes, riskRes] = await Promise.all([
            fetch("/habits/balance"),
            fetch("/analytics/predictive"),
        ]);
        if (balanceRes.ok) balanceData = await balanceRes.json();
        if (riskRes.ok)    atRisk = (await riskRes.json()).streak_at_risk || [];
    } catch (_) {}

    // If balance endpoint failed or returned no streaks, fall back to /habits/streaks
    streaks = balanceData.streaks && Object.keys(balanceData.streaks).length
        ? balanceData.streaks
        : await fetch("/habits/streaks").then(r => r.json()).catch(() => ({}));

    // Life balance bars
    const hbBars = document.getElementById("hb-bars");
    if (hbBars && balanceData.balance && balanceData.balance.length) {
        hbBars.innerHTML = balanceData.balance.map(b => `
            <div class="hb-bar-col">
                <div class="hb-bar-wrap">
                    <div class="hb-bar-fill" style="height:${b.rate}%;background:${b.rate >= 70 ? 'var(--accent)' : b.rate >= 40 ? '#f7a94b' : '#ef5350'}"></div>
                </div>
                <div class="hb-bar-cat">${CATEGORY_ICONS[b.category] || ''} ${b.category}</div>
                <div class="hb-bar-pct">${b.rate}%</div>
            </div>`).join("");
    }

    // Habit cards
    const entries = Object.entries(streaks);
    streaksDiv.innerHTML = entries.length === 0
        ? "<p class='empty-state'>No habits yet — add your first one above!</p>"
        : entries.map(([name, data]) => {
            const risk    = atRisk.includes(name);
            const mLevel  = data.mastery_level || 1;
            const mLabel  = data.mastery_label || "Beginner";
            const cat     = data.category || "Productivity";
            const diff    = data.difficulty || "Normal";
            const tokens  = data.recovery_tokens || {available: 0};
            const streak  = data.current_streak || 0;
            const total   = data.total_logs || 0;
            const xpp     = data.xp_per_log || 10;

            // Progress ring SVG (mastery: level/5)
            const pct    = (mLevel - 1) / 4;
            const radius = 18;
            const circ   = 2 * Math.PI * radius;
            const dash   = circ * pct;

            return `<div class="habit-card ${risk ? 'habit-card--risk' : ''}">
                <div class="hc-top">
                    <div class="hc-ring-wrap">
                        <svg width="44" height="44" viewBox="0 0 44 44">
                            <circle cx="22" cy="22" r="${radius}" fill="none" stroke="var(--line-strong)" stroke-width="3"/>
                            <circle cx="22" cy="22" r="${radius}" fill="none"
                                stroke="${MASTERY_COLORS[mLevel-1]}"
                                stroke-width="3"
                                stroke-dasharray="${dash} ${circ - dash}"
                                stroke-dashoffset="${circ / 4}"
                                stroke-linecap="round"/>
                            <text x="22" y="26" text-anchor="middle" font-size="11" font-weight="700" fill="var(--ink)">${mLevel}</text>
                        </svg>
                    </div>
                    <div class="hc-main">
                        <div class="hc-name">${name} ${risk ? '<span class="risk-badge">⚠️ at risk</span>' : ''}</div>
                        <div class="hc-badges">
                            <span class="hc-badge" style="background:${DIFF_COLORS[diff]}20;color:${DIFF_COLORS[diff]};border-color:${DIFF_COLORS[diff]}40">${diff}</span>
                            <span class="hc-badge hc-badge--cat">${CATEGORY_ICONS[cat] || ''} ${cat}</span>
                            ${data.linked_skill ? `<span class="hc-badge hc-badge--skill">→ ${data.linked_skill}</span>` : ''}
                        </div>
                        <div class="hc-meta">
                            <span class="hc-streak">🔥 ${streak}-day streak</span>
                            <span class="hc-total">${total} total</span>
                            <span class="hc-mastery">${mLabel}</span>
                            <span class="hc-xp">+${xpp} XP</span>
                        </div>
                    </div>
                    <button class="hc-log-btn" onclick="quickLogHabit('${name.replace(/'/g,"\\'")}','${cat}')">Log Today</button>
                </div>
                ${tokens.available > 0 ? `
                    <div class="hc-tokens">
                        <span class="hc-token-label">🛡️ ${tokens.available} recovery token${tokens.available > 1 ? 's' : ''}</span>
                        <button class="hc-token-btn" onclick="useRecoveryToken('${name.replace(/'/g,"\\'")}')">Restore missed day</button>
                    </div>` : ''}
            </div>`;
        }).join("");

    // Load heatmap
    loadHeatmap();

    // Load AI insight (lazy)
    const insightCard = document.getElementById("habit-ai-insight-card");
    if (insightCard && entries.length >= 2) {
        insightCard.style.display = "";
        fetch("/habits/ai-insights").then(r => r.json()).then(d => {
            document.getElementById("habit-ai-insight").textContent = d.insight;
        }).catch(() => {});
    }
}

async function loadHeatmap() {
    const el = document.getElementById("habit-heatmap");
    if (!el) return;
    try {
        const data  = await (await fetch("/habits/heatmap?days=365")).json();
        const today = new Date();
        const cells = [];
        // Build map
        const countMap = {};
        data.forEach(d => { countMap[d.date] = d.count; });
        // Last 52 weeks
        for (let w = 51; w >= 0; w--) {
            const col = [];
            for (let d = 0; d < 7; d++) {
                const dt   = new Date(today);
                dt.setDate(dt.getDate() - (w * 7 + d));
                const key  = dt.toISOString().slice(0, 10);
                const cnt  = countMap[key] || 0;
                const opacity = cnt === 0 ? 0.08 : Math.min(0.2 + cnt * 0.2, 1);
                col.push(`<div class="hm-cell" title="${key}: ${cnt} habits" style="background:rgba(217,138,160,${opacity})"></div>`);
            }
            cells.push(`<div class="hm-col">${col.join("")}</div>`);
        }
        el.innerHTML = cells.join("");
    } catch (_) { el.innerHTML = "<p style='color:var(--ink-faint);font-style:italic'>No data yet.</p>"; }
}

window.quickLogHabit = async function(name, category) {
    const diff   = "Normal";
    const res    = await fetch("/habits", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category, difficulty: diff }),
    });
    const data = await res.json();
    if (data.status === "already_logged") {
        const toast = document.createElement("div");
        toast.className = "achievement-toast show";
        toast.innerHTML = `✓ Already logged today`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 2000);
        return;
    }
    if (data.new_achievements) showAchievementToast(data.new_achievements);
    if (data.xp_earned) showXPFlash(data.xp_earned, category);
    if (data.evolution) {
        const t = document.createElement("div");
        t.className = "achievement-toast show";
        t.innerHTML = `🌟 ${data.evolution.message}`;
        document.body.appendChild(t);
        setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 400); }, 4000);
    }
    loadStreaks();
    loadXPHUD();
};

window.useRecoveryToken = async function(name) {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const date = yesterday.toISOString().slice(0, 10);
    if (!confirm(`Restore '${name}' for ${date}? This uses 1 recovery token.`)) return;
    const res = await fetch("/habits/recover", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, date }),
    });
    if (res.ok) {
        showXPFlash(0, "Streak Restored!");
        loadStreaks();
    }
};

habitForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name       = document.getElementById("habit-name").value.trim();
    const category   = document.getElementById("habit-category").value;
    const difficulty = document.getElementById("habit-difficulty").value;
    const skill      = document.getElementById("habit-skill").value || null;
    if (!name) return;
    const data = await (await fetch("/habits", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category, difficulty, linked_skill: skill }),
    })).json();
    if (data.new_achievements) showAchievementToast(data.new_achievements);
    if (data.xp_earned)        showXPFlash(data.xp_earned, category);
    if (data.evolution) {
        const t = document.createElement("div");
        t.className = "achievement-toast show";
        t.innerHTML = `🌟 ${data.evolution.message}`;
        document.body.appendChild(t);
        setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 400); }, 4000);
    }
    habitForm.reset();
    loadStreaks();
    loadXPHUD();
});

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
const chatMessages = document.getElementById("chat-messages");
const chatForm     = document.getElementById("chat-form");

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input   = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    chatMessages.innerHTML += `<div class="chat-msg user">${message}</div>`;
    chatMessages.scrollTop  = chatMessages.scrollHeight;
    const data = await (await fetch("/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history: conversationHistory }),
    })).json();
    conversationHistory.push({ role: "user",      content: message });
    conversationHistory.push({ role: "assistant", content: data.response });
    chatMessages.innerHTML += `<div class="chat-msg assistant">${data.response}</div>`;
    chatMessages.scrollTop  = chatMessages.scrollHeight;
});

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------
async function loadCharts() {
    const [trendsRes, corrRes] = await Promise.all([
        fetch("/entries/trends?days=30"), fetch("/entries/correlations"),
    ]);
    const trends = await trendsRes.json(), correlations = await corrRes.json();

    new Chart(document.getElementById("trends-chart").getContext("2d"), {
        type: "line",
        data: {
            labels: trends.map(t => t.date),
            datasets: [
                { label: "Mood (1-5)",   data: trends.map(t => t.avg_mood),   borderColor: "#d98aa0", backgroundColor: "rgba(217,138,160,0.1)", tension: 0.3 },
                { label: "Energy (1-5)", data: trends.map(t => t.avg_energy), borderColor: "#b8617c", backgroundColor: "rgba(184,97,124,0.1)",   tension: 0.3 },
                { label: "Focus (1-5)",  data: trends.map(t => t.avg_focus),  borderColor: "#82b366", backgroundColor: "rgba(130,179,102,0.1)",   tension: 0.3 },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { y: { min: 1, max: 5, title: { display: true, text: "Rating (1–5)" } } },
        },
    });

    new Chart(document.getElementById("correlation-chart").getContext("2d"), {
        type: "bar",
        data: {
            labels: correlations.map(c => c.day),
            datasets: [{ label: "Avg Mood", data: correlations.map(c => c.avg_mood), backgroundColor: "rgba(217,138,160,0.6)" }],
        },
        options: { responsive: true, maintainAspectRatio: false,
            scales: { y: { min: 0, max: 5, title: { display: true, text: "Avg Mood" } } }},
    });
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------
async function loadInsights() {
    const data = await (await fetch("/insights")).json();
    document.getElementById("insights").innerHTML = data.insights.map(i => `
        <div class="insight-card ${i.type}">
            <h3>${i.title}</h3><p>${i.message}</p>
            <small>💡 ${i.recommendation}</small>
        </div>`).join("");
}

async function loadAIInsight() {
    const data = await (await fetch("/ai-insight")).json();
    document.getElementById("ai-insight").textContent = data.insight;
}

// ---------------------------------------------------------------------------
// Monthly review
// ---------------------------------------------------------------------------
document.getElementById("generate-review").addEventListener("click", async () => {
    const el = document.getElementById("monthly-review");
    el.textContent = "Generating…";
    const data = await (await fetch("/monthly-review")).json();
    el.innerHTML = data.review.replace(/\n/g, "<br>");
});

// ---------------------------------------------------------------------------
// Goals & Quests
// ---------------------------------------------------------------------------
const goalsDiv = document.getElementById("goals");
const goalForm = document.getElementById("goal-form");

async function loadGoals() {
    const goals = await (await fetch("/goals")).json();
    goalsDiv.innerHTML = goals.map(g => {
        // Task list with toggle checkboxes
        const taskList = g.tasks && g.tasks.length
            ? `<div class="task-list">
                ${g.tasks.map(t => `
                    <label class="task-row ${t.is_completed ? 'task-done' : ''}">
                        <input type="checkbox" class="task-check"
                            onchange="toggleTask(${t.id}, this, ${g.id})"
                            ${t.is_completed ? 'checked' : ''}>
                        <span class="task-title">${t.title}</span>
                    </label>`).join("")}
               </div>`
            : `<p class="task-empty">No tasks yet — add one below.</p>`;

        // Inline add-task form
        const addTaskForm = `
            <div class="add-task-row">
                <input type="text" class="add-task-input" id="task-input-${g.id}"
                    placeholder="Add a task…" onkeydown="if(event.key==='Enter'){addTask(${g.id});event.preventDefault();}">
                <button class="add-task-btn" onclick="addTask(${g.id})">+ Add</button>
            </div>`;

        // Milestone list
        const msSection = g.milestones && g.milestones.length
            ? `<div class="ms-section">
                <div class="ms-label">🏁 Milestones (${g.milestones_done}/${g.milestones_total})</div>
                ${g.milestones.map(m => `
                    <label class="ms-item ${m.is_completed ? 'ms-done' : ''}">
                        <input type="checkbox" onchange="toggleMilestone(${m.id}, this)" ${m.is_completed ? 'checked' : ''}>
                        <span>${m.title}${m.target_date ? ` <em class="ms-date">by ${m.target_date}</em>` : ""}</span>
                    </label>`).join("")}
               </div>` : "";

        // Inline add-milestone form
        const addMsForm = `
            <div class="add-ms-row" id="ms-form-${g.id}" style="display:none">
                <input type="text" id="ms-title-${g.id}" placeholder="Milestone title…">
                <input type="date" id="ms-date-${g.id}">
                <button onclick="addMilestone(${g.id})">Add</button>
                <button class="btn-ghost" onclick="document.getElementById('ms-form-${g.id}').style.display='none'">Cancel</button>
            </div>`;

        return `<div class="goal-card" id="goal-${g.id}">
            <div class="goal-header">
                <div>
                    <strong class="goal-title">${g.title}</strong>
                    <span class="goal-category">${g.category}</span>
                </div>
                <span class="goal-level-badge">Lv ${g.level} · ${g.xp} XP</span>
            </div>
            <div class="goal-stats">
                <span>${g.completed_tasks}/${g.total_tasks} tasks complete</span>
                <span class="goal-pct">${g.progress}%</span>
            </div>
            <div class="progress-bar"><div class="progress-fill" style="width:${g.progress}%"></div></div>

            <div class="goal-section-label">Tasks</div>
            ${taskList}
            ${addTaskForm}

            ${msSection}
            ${addMsForm}

            <div class="goal-actions">
                <button class="btn-ghost goal-ms-btn" onclick="
                    const f=document.getElementById('ms-form-${g.id}');
                    f.style.display=f.style.display==='none'?'flex':'none'">
                    + Milestone
                </button>
                <button class="btn-ghost goal-delete-btn" onclick="deleteGoal(${g.id})">Delete goal</button>
            </div>
        </div>`;
    }).join("") || "<p class='empty-state'>No goals yet — add one above to get started.</p>";
}

goalForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await fetch("/goals", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            title:    document.getElementById("goal-title").value,
            category: document.getElementById("goal-category").value,
        }),
    });
    goalForm.reset();
    loadGoals();
});

// Milestone toggle
window.toggleMilestone = async function(id, cb) {
    cb.disabled = true;
    const data = await (await fetch(`/milestones/${id}`, { method: "PUT" })).json();
    if (data.is_completed) showXPFlash(75, "Milestone");
    loadGoals();
    loadXPHUD();
};

// Inline add milestone
window.addMilestone = async function(goalId) {
    const title  = document.getElementById(`ms-title-${goalId}`).value.trim();
    if (!title) return;
    const target = document.getElementById(`ms-date-${goalId}`).value || null;
    await fetch(`/goals/${goalId}/milestones`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, target_date: target }),
    });
    loadGoals();
};

// Toggle task completion
window.toggleTask = async function(taskId, cb, goalId) {
    cb.disabled = true;
    const data = await (await fetch(`/tasks/${taskId}`, { method: "PUT" })).json();
    if (data.xp_earned) showXPFlash(data.xp_earned, data.category || "Goal");
    if (data.new_achievements) showAchievementToast(data.new_achievements);
    if (data.skill_completion && data.skill_completion.skill_completed) {
        showSkillCompleteModal(data.skill_completion);
    }
    loadGoals();
    loadXPHUD();
};

// Add a new task to a goal
window.addTask = async function(goalId) {
    const input = document.getElementById(`task-input-${goalId}`);
    const title = input.value.trim();
    if (!title) return;
    await fetch(`/goals/${goalId}/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    loadGoals();
};

// Delete a goal
window.deleteGoal = async function(goalId) {
    if (!confirm("Delete this goal and all its tasks?")) return;
    await fetch(`/goals/${goalId}`, { method: "DELETE" });
    loadGoals();
};

// Daily quest
async function generateDailyQuest() {
    const body   = document.getElementById("dq-body");
    const footer = document.getElementById("dq-footer");
    body.textContent = "Generating your quest…";
    footer.textContent = "";
    try {
        const data = await (await fetch("/daily-quest", { method: "POST" })).json();
        if (!data.task) {
            body.textContent = data.message || "All quests complete!";
            return;
        }
        body.innerHTML = `<strong>${data.task}</strong><br>
            <span style="font-size:.88rem;opacity:.8">${data.why}</span>`;
        footer.innerHTML = `<span class="dq-chip">${data.category}</span>
            <span class="dq-chip">${data.difficulty}</span>
            <span class="dq-chip">⏱ ${data.time}m</span>
            <span class="dq-chip">+${data.xp} XP</span>`;
    } catch (_) { body.textContent = "Could not generate quest."; }
}
window.generateDailyQuest = generateDailyQuest;

// ---------------------------------------------------------------------------
// Skills — Skill-Driven Quest System
// ---------------------------------------------------------------------------

const DIFF_ICONS = { Beginner: "🟢", Intermediate: "🟡", Advanced: "🔴" };

async function loadSkills() {
    const [trees, achData] = await Promise.all([
        fetch("/skills").then(r => r.json()),
        fetch("/achievements").then(r => r.json()),
    ]);

    const container = document.getElementById("skill-trees");
    const info = achData.level_info;

    container.innerHTML = `
        <div class="skill-level-banner">
            <div class="slb-level">Level ${info.level}</div>
            <div class="slb-xp-bar-wrap">
                <div class="slb-xp-bar-fill" style="width:${Math.round(info.xp_in_level / 5)}%"></div>
            </div>
            <div class="slb-xp-text">${info.xp_in_level} / 500 XP · ${info.xp_to_next} to next level</div>
        </div>
        <div class="skill-how-it-works">
            <strong>How it works:</strong>
            Click <em>Start Learning</em> on any available node → a goal with structured tasks is created →
            complete every task → the node is automatically mastered → XP is awarded → new nodes unlock.
        </div>`;

    trees.forEach(tree => {
        const treeEl = document.createElement("div");
        treeEl.className = "skt-tree";
        treeEl.innerHTML = `
            <div class="skt-tree-header">
                <span class="skt-tree-icon">${tree.icon}</span>
                <span class="skt-tree-name">${tree.label}</span>
                <span class="skt-tree-xp">${tree.category_xp} XP</span>
            </div>
            <div class="skt-nodes" id="nodes-${tree.category}"></div>`;
        container.appendChild(treeEl);

        const nodesEl = treeEl.querySelector(".skt-nodes");
        tree.nodes.forEach(node => {
            nodesEl.appendChild(buildNodeCard(node, tree));
        });
    });

    // Achievements
    const earned = achData.earned || [];
    if (earned.length) {
        const achEl = document.createElement("div");
        achEl.className = "achievements-section";
        achEl.innerHTML = `
            <h3 style="font-family:var(--font-display);margin-bottom:.75rem">🏆 Achievements</h3>
            <div class="achievements-grid">
                ${earned.map(a => `<div class="achievement-badge">
                    <strong>${a.name}</strong>
                    <small>${a.earned_at.slice(0,10)}</small>
                </div>`).join("")}
            </div>`;
        container.appendChild(achEl);
    }
}

function buildNodeCard(node, tree) {
    const el = document.createElement("div");

    // Determine state
    let state;
    if (node.completed)                  state = "completed";
    else if (node.active_goal)           state = "active";
    else if (node.unlocked)              state = "available";
    else                                 state = "locked";

    el.className = `skt-node skt-node--${state}`;

    // Prerequisites display
    const prereqNames = (node.prerequisites || []).map(pid => {
        const found = tree.nodes.find(n => n.id === pid);
        return found ? found.name : pid;
    });

    // What this unlocks
    const unlocksNames = (node.leads_to || []).map(uid => {
        const found = tree.nodes.find(n => n.id === uid);
        return found ? found.name : uid;
    });

    // Progress bar for active node
    const ag = node.active_goal;
    const progressHtml = ag
        ? `<div class="skt-progress-wrap">
               <div class="skt-progress-bar">
                   <div class="skt-progress-fill" style="width:${ag.progress}%"></div>
               </div>
               <span class="skt-progress-label">${ag.completed_tasks}/${ag.total_tasks} tasks · ${ag.progress}%</span>
           </div>`
        : "";

    // CTA button
    let ctaHtml = "";
    if (state === "completed") {
        ctaHtml = `<div class="skt-done-badge">✓ Mastered</div>`;
    } else if (state === "active") {
        ctaHtml = `<button class="skt-btn skt-btn--active"
            onclick="showPage('quests')">View Tasks →</button>`;
    } else if (state === "available") {
        ctaHtml = `<button class="skt-btn skt-btn--start"
            onclick="startLearning('${node.id}','${tree.category}',this)">▶ Start Learning</button>`;
    } else {
        // Locked — show what's needed
        const needsXP = !node.xp_met ? `${node.xp_required} XP in ${tree.label}` : "";
        const needsNodes = !node.prereqs_met && prereqNames.length
            ? `Complete: ${prereqNames.join(", ")}` : "";
        const reqs = [needsXP, needsNodes].filter(Boolean).join(" · ");
        ctaHtml = `<div class="skt-locked-msg">🔒 ${reqs || "Complete prerequisites"}</div>`;
    }

    el.innerHTML = `
        <div class="skt-node-head">
            <div class="skt-node-state-dot skt-dot--${state}"></div>
            <div class="skt-node-title">${node.name}</div>
            <div class="skt-node-badges">
                <span class="skt-badge">${DIFF_ICONS[node.difficulty] || ""} ${node.difficulty || ""}</span>
                <span class="skt-badge">⏱ ~${node.estimated_hours || "?"}h</span>
                <span class="skt-badge skt-badge--xp">+${node.xp_reward || node.xp_required} XP</span>
            </div>
        </div>
        <div class="skt-node-desc">${node.description}</div>
        ${prereqNames.length ? `<div class="skt-node-meta">Requires: ${prereqNames.map(n => `<span class="skt-req">${n}</span>`).join("")}</div>` : ""}
        ${unlocksNames.length ? `<div class="skt-node-meta">Unlocks: ${unlocksNames.map(n => `<span class="skt-unlocks">${n}</span>`).join("")}</div>` : ""}
        ${progressHtml}
        <div class="skt-node-foot">${ctaHtml}</div>`;

    return el;
}

// Start Learning — creates goal + tasks then redirects to Quests
window.startLearning = async function(nodeId, category, btn) {
    btn.textContent = "Starting…";
    btn.disabled = true;
    try {
        const data = await (await fetch(
            `/skills/${nodeId}/start?category=${encodeURIComponent(category)}`,
            { method: "POST" }
        )).json();

        if (data.status === "already_active") {
            showPage("quests");
            return;
        }
        if (data.status === "started") {
            showXPFlash(0, "Quest Created!");
            // Show a brief toast then go to quests
            const toast = document.createElement("div");
            toast.className = "achievement-toast show";
            toast.innerHTML = `📚 <strong>Learning started!</strong> ${data.task_count} tasks added to Quests.`;
            document.body.appendChild(toast);
            setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 3000);
            setTimeout(() => showPage("quests"), 600);
        }
    } catch (_) {
        btn.textContent = "▶ Start Learning";
        btn.disabled = false;
    }
};

// Skill complete celebration modal
function showSkillCompleteModal(sc) {
    let modal = document.getElementById("skill-complete-modal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "skill-complete-modal";
        modal.className = "skill-complete-overlay";
        document.body.appendChild(modal);
    }
    modal.innerHTML = `
        <div class="skill-complete-box">
            <div class="skill-complete-star">⭐</div>
            <h2 class="skill-complete-title">Skill Mastered!</h2>
            <p class="skill-complete-name">${sc.node_name}</p>
            <div class="skill-complete-xp">+${sc.xp_earned} XP</div>
            ${sc.newly_unlocked && sc.newly_unlocked.length
                ? `<div class="skill-complete-unlocks">
                    🔓 Now unlocked: <strong>${sc.newly_unlocked.join(", ")}</strong>
                   </div>` : ""}
            <div style="display:flex;gap:.75rem;margin-top:1.25rem;justify-content:center">
                <button class="skt-btn skt-btn--start" onclick="
                    document.getElementById('skill-complete-modal').style.display='none';
                    showPage('skills');
                    loadSkills();">View Skill Tree</button>
                <button style="background:var(--paper);color:var(--ink-soft);border:1px solid var(--line);padding:.55rem 1rem;border-radius:10px;cursor:pointer"
                    onclick="document.getElementById('skill-complete-modal').style.display='none'">
                    Close</button>
            </div>
        </div>`;
    modal.style.display = "flex";
    // Also show XP flash
    showXPFlash(sc.xp_earned, sc.category);
}

// ---------------------------------------------------------------------------
// Life Domains — full page logic
// ---------------------------------------------------------------------------

async function loadDomains() {
    const container = document.getElementById("domain-cards");
    container.innerHTML = "<p class='empty-state'>Loading domains…</p>";
    try {
        const domains = await (await fetch("/domains")).json();
        if (!domains.length) { container.innerHTML = "<p class='empty-state'>No domain data yet.</p>"; return; }
        container.innerHTML = domains.map(d => buildDomainCard(d)).join("");
    } catch (_) {
        container.innerHTML = "<p class='empty-state'>Could not load domains.</p>";
    }
    loadActionEngine();
    loadCurrentBosses();
}

function buildDomainCard(d) {
    const pct      = Math.round(d.xp_in_level / 5);  // xp_in_level out of 500
    const habits   = (d.habits || []).slice(0, 4);
    const skills   = (d.skill_trees || []);
    const goals    = (d.goals || []).filter(g => g.progress < 100).slice(0, 3);
    const boss     = d.weekly_boss;

    const habitPills = habits.map(h =>
        `<span class="dom-pill ${h.done_today ? 'dom-pill--done' : ''}">${h.done_today ? '✓' : '○'} ${h.name} (${h.streak}🔥)</span>`
    ).join("") || `<span class="dom-pill dom-pill--empty">No habits linked</span>`;

    const skillBars = skills.map(s =>
        `<div class="dom-skill-row">
            <span class="dom-skill-name">${s.label}</span>
            <div class="dom-skill-bar"><div class="dom-skill-fill" style="width:${s.pct}%;background:${d.color}"></div></div>
            <span class="dom-skill-pct">${s.completed}/${s.total}</span>
         </div>`
    ).join("") || `<span style="font-size:.8rem;color:var(--ink-faint)">No skill trees</span>`;

    const goalList = goals.map(g =>
        `<div class="dom-goal-row">
            <span class="dom-goal-title">${g.title}</span>
            <div class="dom-goal-bar"><div class="dom-goal-fill" style="width:${g.progress}%;background:${d.color}"></div></div>
            <span class="dom-goal-pct">${g.progress}%</span>
         </div>`
    ).join("") || `<span style="font-size:.8rem;color:var(--ink-faint)">No active goals</span>`;

    const bossHtml = boss
        ? `<div class="dom-boss ${boss.completed ? 'dom-boss--done' : ''}">
               <span class="dom-boss-icon">${boss.completed ? '✅' : '⚔️'}</span>
               <span class="dom-boss-name">${boss.name}</span>
               ${!boss.completed ? `<button class="dom-boss-btn" onclick="defeatBoss(${boss.id}, this)">Defeat</button>` : '<span class="dom-boss-defeated">Defeated!</span>'}
           </div>`
        : `<span style="font-size:.8rem;color:var(--ink-faint)">No boss this week</span>`;

    return `<div class="domain-card" style="--dom-color:${d.color}">
        <div class="dom-header">
            <span class="dom-icon">${d.icon}</span>
            <div class="dom-title-block">
                <div class="dom-name">${d.name}</div>
                <div class="dom-desc">${d.description}</div>
            </div>
            <div class="dom-level-badge">Lv ${d.level}</div>
        </div>
        <div class="dom-xp-row">
            <div class="dom-xp-bar-wrap">
                <div class="dom-xp-bar-fill" style="width:${pct}%;background:${d.color}"></div>
            </div>
            <span class="dom-xp-text">${d.xp_in_level}/500 XP · ${d.xp_to_next} to next</span>
        </div>
        <div class="dom-progress-pct">${d.progress}% quest completion · ${d.active_goals} active goal${d.active_goals !== 1 ? 's' : ''}</div>

        <div class="dom-section-label">Habits</div>
        <div class="dom-pills">${habitPills}</div>

        <div class="dom-section-label">Skill Trees</div>
        ${skillBars}

        <div class="dom-section-label">Active Goals</div>
        ${goalList}

        <div class="dom-section-label">This Week's Boss</div>
        ${bossHtml}
    </div>`;
}

async function loadActionEngine() {
    const el = document.getElementById("aep-content");
    try {
        const data = await (await fetch("/action-engine")).json();
        if (!data.needs_attention) {
            el.innerHTML = `<div class="aep-ok">✦ ${data.summary}</div>`;
            return;
        }
        const primary = data.primary;
        el.innerHTML = `
            <div class="aep-primary">
                <div class="aep-severity aep-sev--${primary.severity}">${primary.severity.toUpperCase()}</div>
                <div class="aep-problem-title">${primary.title}</div>
                <div class="aep-action">→ ${primary.action}</div>
            </div>
            ${data.problems.length > 1 ? `<div class="aep-other-list">
                ${data.problems.slice(1).map(p =>
                    `<div class="aep-other-item"><span class="aep-sev--${p.severity} aep-severity">${p.severity.toUpperCase()}</span> ${p.title}</div>`
                ).join("")}
            </div>` : ""}`;
    } catch (_) {
        el.innerHTML = `<div class="aep-ok">Action Engine unavailable.</div>`;
    }
}

async function loadBottleneck() {
    const el = document.getElementById("bottleneck-content");
    el.innerHTML = "<span style='color:var(--ink-faint);font-style:italic'>Analyzing…</span>";
    try {
        const data = await (await fetch("/bottleneck")).json();
        if (!data.bottleneck) {
            el.innerHTML = `<p style="color:var(--ink-soft)">${data.message}</p>`;
            return;
        }
        const scores = (data.all_scores || []).slice(0, 4);
        el.innerHTML = `
            <div class="btn-primary-block">
                <div class="btn-bottleneck-name">${data.bottleneck}</div>
                <div class="btn-confidence">Confidence: ${data.confidence}%</div>
                ${data.ai_message ? `<div class="btn-ai-msg">${data.ai_message}</div>` : ""}
            </div>
            <div class="btn-evidence">
                <div class="btn-sub-label">Evidence</div>
                ${data.evidence.map(e => `<div class="btn-ev-item">• ${e}</div>`).join("")}
            </div>
            <div class="btn-recovery">
                <div class="btn-sub-label">Recovery Plan</div>
                ${(data.recovery_plan || []).map((r, i) =>
                    `<div class="btn-rec-item"><span class="btn-rec-num">${i + 1}</span>${r}</div>`
                ).join("")}
            </div>
            ${scores.length > 1 ? `<div class="btn-scores">
                ${scores.map(s =>
                    `<div class="btn-score-row">
                        <span class="btn-score-name">${s.name}</span>
                        <div class="btn-score-bar-wrap"><div class="btn-score-bar" style="width:${Math.min(s.score, 100)}%"></div></div>
                     </div>`
                ).join("")}
            </div>` : ""}`;
    } catch (_) {
        el.innerHTML = "<p style='color:var(--ink-soft)'>Could not run analysis.</p>";
    }
}
window.loadBottleneck = loadBottleneck;

// Weekly Boss Battles
async function loadCurrentBosses() {
    const el = document.getElementById("boss-battles");
    try {
        const data = await (await fetch("/bosses/current")).json();
        if (!data.bosses || !data.bosses.length) {
            el.innerHTML = `<div class="boss-empty">No boss battles this week yet. <button class="btn-ghost btn-sm" onclick="generateBosses()">Generate Now</button></div>`;
            return;
        }
        el.innerHTML = data.bosses.map(b => buildBossCard(b)).join("");
    } catch (_) {
        el.innerHTML = `<div class="boss-empty">Could not load boss battles.</div>`;
    }
}

function buildBossCard(b) {
    const req  = Array.isArray(b.requirements) ? b.requirements : [];
    const done = b.completed;
    return `<div class="boss-card ${done ? 'boss-card--done' : ''}">
        <div class="boss-card-header">
            <span class="boss-icon">${done ? '☠️' : '👹'}</span>
            <div class="boss-title-block">
                <div class="boss-name">${b.name}</div>
                <div class="boss-domain">${b.domain}</div>
            </div>
            <div class="boss-xp">+${b.xp_reward} XP</div>
        </div>
        <div class="boss-desc">${b.description || ''}</div>
        ${req.length ? `<div class="boss-reqs">
            ${req.map(r => `<div class="boss-req-item">☐ ${r.label}</div>`).join("")}
        </div>` : ""}
        <div class="boss-deadline">Deadline: ${b.deadline}</div>
        ${done
            ? `<div class="boss-defeated-badge">✅ Defeated!</div>`
            : `<button class="boss-defeat-btn" onclick="defeatBoss(${b.id}, this)">⚔️ Mark Defeated</button>`}
    </div>`;
}

window.generateBosses = async function() {
    const el = document.getElementById("boss-battles");
    el.innerHTML = "<p style='color:var(--ink-faint);font-style:italic'>Generating boss battles…</p>";
    try {
        const data = await (await fetch("/bosses/generate", { method: "POST" })).json();
        loadCurrentBosses();
        const toast = document.createElement("div");
        toast.className = "achievement-toast show";
        toast.innerHTML = `⚔️ ${data.bosses.length} Boss Battles generated for ${data.week_key}!`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 3500);
    } catch (_) {
        el.innerHTML = "<p style='color:var(--ink-soft)'>Boss generation failed.</p>";
    }
};

window.defeatBoss = async function(bossId, btn) {
    btn.disabled = true;
    btn.textContent = "Processing…";
    try {
        const data = await (await fetch(`/bosses/${bossId}/complete`, { method: "POST" })).json();
        if (data.xp_earned) showXPFlash(data.xp_earned, data.domain);
        if (data.new_achievements) showAchievementToast(data.new_achievements);
        loadCurrentBosses();
        loadDomains();
        loadXPHUD();
    } catch (_) {
        btn.disabled = false;
        btn.textContent = "⚔️ Mark Defeated";
    }
};

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
loadAIInsight();
loadXPHUD();
loadTodayStatus();
switchEntryTab("morning");
loadProactiveCoaching();

}); // end DOMContentLoaded