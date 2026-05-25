# Rizq-Rescue

**Autonomous Surplus Food Redistribution Network**

Rizq-Rescue is an agentic AI system that proactively redistributes surplus food from university messes, wedding halls, and local restaurants to NGOs and volunteer networks. Instead of waiting for donors to open an app, the agent calls venues at closing time, confirms quantity and food safety, and coordinates pickup with nearby volunteers—reducing nightly waste without manual phone coordination.

**Track:** Social Impact / AI Agents / SDG 2 (Zero Hunger)  
**Pilot:** GIKI Campus (Mess & Cafes), Topi & Swabi wedding halls

---

## The Problem

Every night, edible food is discarded by venues such as GIKI Mess, wedding halls, and restaurants because coordinating donations is logistically difficult. NGOs exist but lack the capacity to call every venue nightly to check for leftovers.

## The Solution

Rizq-Rescue bridges that gap with scheduled, autonomous outreach:

- **Automated logistics** — Eliminates repeated manual calls between venues and NGOs.
- **Real-time action** — Food is rescued while it is still fresh.
- **Data-driven impact** — Tracks rescued quantities (e.g., kilograms saved) over time.

---

## How It Works

The agent runs on venue-specific schedules (cron triggers), not passive chat.

| Phase | What happens |
|-------|----------------|
| **Trigger** | Calls registered points of contact at closing time (e.g., 22:00 messes, 23:30 wedding halls). |
| **Negotiation** | Voice AI checks availability, estimates portions, verifies safety (cook date, refrigeration), and tags food as perishable or stable. |
| **Match & dispatch** | Confirmed donations are logged; the system matches an active volunteer, calls to confirm pickup, and sends SMS/WhatsApp with contacts and location. |

**Safety guardrails:** Rejects food cooked on a prior day; flags meat left at room temperature too long; pickup messages remind volunteers to verify smell and texture before accepting.

---

## Technical Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Orchestrator | Python / Node.js | Triggers, state, and workflow |
| Voice | Twilio + Vapi / Bland AI | Low-latency outbound calls |
| Intelligence | Gemini | Conversation, extraction, decisions |
| Database | Firebase / Supabase | Venues, volunteers, live donations |
| Notifications | Twilio SMS / WhatsApp | Confirmations and location handoff |

---

## Setup

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Add your API keys to .env
python app/main.py
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

---

## API Keys Needed

- Soniox: https://soniox.com/
- Google AI (Gemini): https://aistudio.google.com/app/apikey
- ElevenLabs: https://elevenlabs.io/app/settings/api-keys
