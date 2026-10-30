# CallCue™

© 2026 Aryan Khanna. Open source under the [MIT License](LICENSE).

CallCue is a live cold-call assistant for salespeople. While you are on a call it shows what to say at each stage, suggests calm, short replies to objections, and logs how every call went so you can see which objections come up most. The whole page can be rearranged to fit the way you work.

## Features

### During the call
- **Call stages:** Opening, Discovery, Pitch and Close, each with a suggested line to say.
- **Personalised lines:** AI rewrites the playbook line using the prospect's name, company and your notes, without inventing facts. It can be switched off to use the plain playbook and save AI quota.
- **Objection handling:** tap an objection or type what the prospect said and get an approved reply plus a follow-up question, adapted to what they just said.
- **Prospect details and call notes:** name, company, contact and what you know, saved with the call.
- **Call timer.**

### After the call
- **Outcome logging:** record how the call went, along with the objection that came up.
- **Custom outcome buttons:** set your own list (for example Booked demo, Send info, Callback, Not interested). Calls saved with an outcome that is no longer on the list are grouped under Other.
- **Call history and stats:** review past calls and see outcome and objection counts.

### Make it your own
- **Drag-and-drop layout:** click **Arrange**, drag any card by its handle to a new position or to the other column, then click **Done**. Works with mouse and touch, and the page scrolls when you drag near the edges.
- **Page layout:** two columns or one column. On a phone the page is always one column, and your two-column arrangement is kept for larger screens.
- **Sections:** show or hide Who you are calling, Call stage and lines, Objection replies, Call notes and Call history.
- **Appearance:** dark or light theme, accent colour, text size, compact mode.
- **Reset to default** restores the original layout, sections and outcomes.

Preferences are saved in the browser, so each person gets their own setup that persists between visits.

### Account
- **Google sign-in** through Supabase Auth. Each user only sees their own calls.

## Tech stack

| Part | Technology | Hosted on |
|------|-----------|-----------|
| Frontend | Single-page `index.html` (vanilla JS, Supabase JS client) | Vercel |
| Backend | FastAPI (`main.py`) | Render |
| Database and auth | Supabase (Postgres and Google OAuth) | Supabase |
| AI | Groq API (default model `openai/gpt-oss-20b`) | Groq |

## How it works

1. The user signs in with Google and the frontend gets a Supabase session token.
2. The frontend calls the FastAPI backend with that token as a Bearer header. The backend checks it against Supabase before doing anything.
3. The backend reads the **playbook** table (approved lines per stage and objection), asks Groq to tailor the wording, and falls back to the approved text or keyword matching if the AI call fails.
4. Call outcomes are stored in the **calls** table, tagged with the user's id.

## API endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/` | No | Health check |
| GET | `/playbook` | No | Approved lines and objection replies |
| POST | `/reply` | Yes | Match what the prospect said to an objection and return a reply and follow-up |
| POST | `/say` | Yes | Personalised line for a call stage |
| POST | `/adapt` | Yes | Adapt an objection reply to what the prospect just said |
| POST | `/calls` | Yes | Log a call outcome |
| GET | `/calls` | Yes | List the user's calls |
| GET | `/stats` | Yes | Outcome and objection counts |

## Database

Supabase tables:

- `playbook`: `id`, `stage`, `objection`, `reply`, `follow_up`
- `calls`: `outcome`, `objection`, `user_id`, `created_at`, plus optional `notes`, `prospect_name`, `prospect_company`, `prospect_contact`

If the optional columns are missing, the backend still saves the core call record and tells the frontend that details were not stored.

## Running locally

### Backend

```bash
pip install fastapi uvicorn requests python-dotenv pydantic
```

Create a `.env` file:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key
GROQ_API_KEY=your-groq-key
GROQ_MODEL=openai/gpt-oss-20b   # optional
```

Start the server:

```bash
uvicorn main:app --reload
```

### Frontend

Open `index.html` in a browser or serve it with any static server. In `index.html`, set:

- `API` to your backend URL (for example `http://localhost:8000` locally)
- `SB_URL` and `SB_KEY` to your Supabase project URL and publishable key

Add your site URL to the allowed redirect URLs in Supabase (Authentication, URL Configuration) so Google sign-in can return to it.

## Deployment

- **Frontend:** push to GitHub and Vercel redeploys automatically. Hard reload (Ctrl+Shift+R) afterwards to skip the cached page.
- **Backend:** deploy `main.py` on Render as a web service with start command `uvicorn main:app --host 0.0.0.0 --port $PORT`, and add the environment variables above.
- **CORS** is currently open to all origins. Restrict `allow_origins` in `main.py` to your Vercel domain for production.

## Project structure

```
CallCue/
├── callcue-web/
│   └── index.html   # frontend
├── main.py          # FastAPI backend
└── README.md
```

Adjust this to match your actual folders.

## Roadmap

**Live transcript and suggestions** (planned, not built yet):

- A transcript panel with a mic button that records short audio chunks and sends them to the API for transcription with Whisper on Groq.
- Automatic objection detection from what the prospect says, showing the matching reply and follow-up.
- Auto-filled notes, stage suggestions and an end-of-call summary with a suggested outcome.
- The audio source decides what is possible. Calls made through the computer can separate "You" from "Prospect"; a phone on speaker only gives one mixed stream; calls on the phone alone cannot be captured by a web page.
- Recording or transcribing a call can have legal requirements that vary by country and state, so a consent notice and a check of local rules come first.
- Suggestions should be throttled to keep AI cost and latency down.

## Notes

- Keep API keys in environment variables and out of the repo. The Supabase publishable key in `index.html` is meant for the browser, but the Groq key and any Supabase secret key must stay on the backend.

## License

CallCue is open source under the [MIT License](LICENSE). © 2026 [Aryan Khanna](https://github.com/Arnnnnnn/).

You are free to use, copy, modify and distribute the code, as long as the copyright notice and license text are kept in copies. The software is provided as is, with no warranty.

The CallCue™ name is used by the author to identify the original project.
