# LiAInne — AI-Powered Journal & Personal Growth System

![License](https://img.shields.io/badge/status-active-success)
![Frontend](https://img.shields.io/badge/frontend-HTML%20%7C%20CSS%20%7C%20JavaScript-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI-green)
![Database](https://img.shields.io/badge/database-Supabase-orange)
![AI](https://img.shields.io/badge/AI-Groq%20%2B%20Embeddings-purple)

## Overview

**LiAInne** is an AI-powered personal growth platform designed to help users reflect, improve, and stay consistent.

Unlike traditional journaling apps, LiAInne combines:

* 📝 Smart journaling
* 🤖 AI coaching
* 🔥 Habit streak tracking
* ⚔️ RPG-style goals and quests
* 📊 Analytics and insights
* 🗓️ Monthly reviews

The goal is to turn self-improvement into an engaging and data-driven experience.

---

## Features

### 📝 Journal Entries

Create daily journal entries with:

* Title
* Content
* Mood rating (1–5)
* Goal progress tracking
* Tags

Every entry is stored and embedded for semantic search and AI analysis.

---

### 🤖 AI Coach

LiAInne includes an AI coach that can:

* Analyze journal history
* Identify patterns
* Answer questions about past entries
* Give personalized advice
* Track long-term progress

The AI uses:

* Semantic search
* Trend analysis
* Historical context
* Habit data

to generate meaningful responses.

---

### ⚔️ RPG Goal System

Transform goals into quests.

Features:

* Goal categories
* Task breakdowns
* XP rewards
* Level progression
* Progress tracking
* Daily quest generation

Categories include:

* 📚 Study
* 💪 Fitness
* 💼 Career
* ❤️ Relationships
* 💰 Finance
* 🎨 Creativity
* 🌱 Personal Growth

---

### 🔥 Habit Tracker

Track habits and maintain streaks.

Features:

* Daily habit logging
* Current streak calculation
* Total completion counts
* Habit consistency tracking

---

### 📊 Insights Dashboard

Automatically discover patterns from journal data.

Examples:

* Mood trends
* Goal progress trends
* Day-of-week performance
* Behavioral observations
* Personalized recommendations

Built with Chart.js visualizations.

---

### 🗓️ Monthly Reviews

Generate AI-powered monthly reflections including:

* Mood averages
* Goal progress averages
* Habit performance
* Strongest areas
* Areas needing attention
* Personalized recommendations

---

## Screenshots

### Dashboard / Journal Page with AI Coach

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/25a234b6-bcb1-4e95-8f5c-47897b8e3eb3" />


---

### Quest & Goal System

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/5b61d918-debb-4f97-8086-490a04d23b06" />


---

### Habit Tracker

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/a4abfba1-a4a4-478f-8934-47ec52faf260" />


---

### Insights Dashboard

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/1c00cd8b-eea0-4273-872f-3dc4865a5d9d" />


---

### Monthly Review

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/9ed7fa62-4616-47e3-917c-5d7d26d8b22c" />


---

## Tech Stack

### Frontend

* HTML5
* CSS3
* JavaScript
* Chart.js

### Backend

* FastAPI
* Python

### AI

* Groq API
* Sentence Transformers
* Semantic Search
* Embeddings

### Database

* Supabase

---

## Architecture

```text
Frontend (HTML/CSS/JS)
        │
        ▼
     FastAPI
        │
 ┌──────┼────────┐
 ▼      ▼        ▼
AI    Supabase  Analytics
Coach Database  Engine
```

---

## Future Roadmap

### Planned Features

* [ ] User authentication
* [ ] Achievement system
* [ ] XP leaderboards
* [ ] Calendar heatmap
* [ ] Daily notifications
* [ ] Mobile version
* [ ] Dark mode
* [ ] AI-generated growth plans
* [ ] Advanced life analytics
* [ ] Real-life leveling system

---

## Why I Built This

Most productivity apps focus on tasks.

Most journaling apps focus on reflection.

LiAInne aims to combine both.

The vision is to create a system that acts like a personal AI mentor—one that understands your history, tracks your growth, identifies patterns, and helps you become a better version of yourself over time.

---

## Installation

### Clone Repository

```bash
git clone [https://github.com/yourusername/liainne.git](https://github.com/Nomeed21/journal-app.git)
cd liainne
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

```env
SUPABASE_URL=
SUPABASE_KEY=
GROQ_API_KEY=
```

### Run Backend

```bash
uvicorn main:app --reload
```

### Open Application

```text
http://localhost:8000
```

---

## Project Status

🚧 Active Development

LiAInne is currently being developed as a personal growth platform and learning project focused on:

* Software Engineering
* AI Integration
* FastAPI Development
* Data Analytics
* Human-Centered Design

---

## Author

Developed by Nurmid J. Mayo a Computer Science student passionate about:

* AI
* Self-improvement
* Productivity systems
* Human-computer interaction
* Building tools that help people grow
