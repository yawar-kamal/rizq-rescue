# Rizq-Rescue MVP

AI-Powered Food Rescue Demo

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

## API Keys Needed
- Soniox: https://soniox.com/
- Google AI (Gemini): https://aistudio.google.com/app/apikey
- ElevenLabs: https://elevenlabs.io/app/settings/api-keys

