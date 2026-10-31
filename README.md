# CallCue

A live guide for cold calls. CallCue walks a caller through the eight stages of a first call, suggests a polite reply at each stage using AI, and records every call by the stage it reached, so you can see where your calls actually end.

**Live demo:** https://callcue-api-callcue-web.vercel.app/
**API:** https://callcue-api.onrender.com (free tier, so the first request after a quiet spell can take up to a minute while it wakes up)

<!-- Add screenshots to a docs/ folder and uncomment:
![Call screen](docs/call-screen.png)
![Past calls](docs/past-calls.png)
![Sign in](docs/sign-in.png)
-->

## What it does

- **Eight-stage call guide.** One stage on screen at a time: Opening, Purpose, Permission, Their business, Their need, Objection, Next step, Close. Each stage shows what it is for, three things prospects tend to say, and four taps for what happened.
- **Their words.** One free-text box per stage for the prospect's own words, which is the only typing a call needs.
- **AI coach.** A separate panel on the right reads the stage, your taps, what the prospect said and everything that happened earlier in the call, then returns a short **read** of the situation and a **suggested reply** in formal, slightly friendly business English. Buttons say what you need right now (answer their question, they are hesitant, ask a follow-up, move to the next stage), and a note box lets you tell the AI what is happening.
- **Save screen.** At the end of a call it suggests an outcome from what you tapped, and you can change it.
- **Past calls.** Expandable rows with search, five calls per page, and swipe or buttons to turn pages. A bar chart shows how many of your calls ended at each stage, and you can filter by stage.
- **Customise.** Theme (dark, light, warm), accent colour, text size, compact spacing, show or hide the "They may say" lines and the timer, and the name the AI uses for you. Saved in the browser.
- **Google sign-in.** Each user sees only their own calls.

## The eight stages

| # | Stage | What it is for |
|---|-------|----------------|
| 1 | Opening | Reach the right person and say who you are |
| 2 | Purpose | Say why you called, in words they could repeat to a colleague |
| 3 | Permission | Find out whether they will talk now |
| 4 | Their business | Ask about their company before saying anything about yours |
| 5 | Their need | Hear what they are trying to do or struggling with, in their own words |
| 6 | Objection | Hear the reason for a no and understand it |
| 7 | Next step | Agree one concrete thing, with a time or a channel |
| 8 | Close | End clearly and record the outcome, the next step and their words |

The lines under "They may say" and the AI's per-stage rules were written from patterns in a set of reference cold-call transcripts. **The transcripts are not part of this repository and must not be published.**

## Tech stack

- **Frontend:** a single `index.html` (vanilla JavaScript and CSS, no build step), hosted on Vercel
- **Backend:** Python with FastAPI, hosted on Render
- **Database and auth:** Supabase (PostgreSQL and Google sign-in)
- **AI:** Groq API (`openai/gpt-oss-120b` for suggestions, with `openai/gpt-oss-20b` as a fallback)

```
Browser (Vercel)  --Google sign-in-->  Supabase Auth
       |
       | Bearer token
       v
FastAPI (Render) --verifies token--> Supabase Auth
       |                |
       |                +--> Supabase (calls table)
       +--> Groq (suggestions)
```

## Repository layout

```
.
├── main.py            FastAPI app
├── requirements.txt   Python dependencies
├── .env.example       Names of the environment variables
├── callcue-web/
│   └── index.html     The whole frontend
├── LICENSE
└── README.md
```

## Set it up yourself

### 1. Supabase

Create a project, then run this in the SQL editor:

```sql
create table if not exists calls (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(),
  user_id uuid,
  outcome text not null,
  objection text,
  notes text,
  prospect_name text,
  prospect_company text,
  prospect_contact text,
  prospect_role text,
  stage_reached smallint,
  taps jsonb,
  words jsonb,
  next_step text,
  duration_seconds integer
);
```

If you already have a `calls` table, add any missing columns with `alter table calls add column if not exists ...`.

The current frontend does not read the `playbook` table. The API still contains older routes for it (`/playbook`, `/reply`, `/say`, `/adapt`, `/stats`) that the interface no longer calls.

**Security.** Use your project's **secret** key on the server only, never in the browser, and turn on row level security for `calls` if your server uses the secret key (it bypasses RLS). The browser only needs the **publishable** key, which is meant to be public.

### 2. Google sign-in

1. In Google Cloud Console, set up the OAuth consent screen and create an OAuth client ID of type **Web application**. For the authorised redirect URI, use the callback address shown on Supabase's Google provider page (`https://<project>.supabase.co/auth/v1/callback`).
2. In Supabase, go to Authentication, then Sign In / Providers, then Google. Enable it and paste the client ID and secret.
3. In Authentication, then URL Configuration, set the **Site URL** and add a **Redirect URL** for your deployed frontend.

While the consent screen is in Testing mode, only accounts you add as test users can sign in.

### 3. Groq

Create an API key at console.groq.com. Free-tier limits apply, and the larger model has tighter limits than the smaller one.

### 4. Backend on Render

1. Create a **Web Service** from this repository.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add the environment variables below.

| Variable | Required | Purpose |
|----------|----------|---------|
| `SUPABASE_URL` | yes | Your Supabase project URL |
| `SUPABASE_KEY` | yes | Supabase key used by the server |
| `GROQ_API_KEY` | yes | Groq API key |
| `GROQ_SUGGEST_MODEL` | no | Model for suggestions (default `openai/gpt-oss-120b`) |
| `GROQ_MODEL` | no | Fallback model (default `openai/gpt-oss-20b`) |

Copy `.env.example` to `.env` for local runs. Never commit `.env`.

### 5. Frontend on Vercel

1. Import the repository and set the **Root Directory** to `callcue-web`. The framework is "Other", and there is nothing to build.
2. At the top of the script in `callcue-web/index.html`, set the API address and your Supabase project URL and **publishable** key.

### 6. Run locally

```bash
python -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in the values
uvicorn main:app --reload
```

Open `callcue-web/index.html` through any static server, with the API address in the script pointed at `http://localhost:8000`, and add that origin to your Supabase redirect URLs.

## API

Every route except `/` and `/playbook` needs a Supabase access token in an `Authorization: Bearer ...` header. The server checks the token with Supabase on each request.

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Health check |
| POST | `/suggest` | AI read and suggested reply for the current stage (used by the interface) |
| POST | `/calls` | Save a call. Falls back to a smaller record if the new columns are missing |
| GET | `/calls` | List the signed-in user's calls, newest first |
| GET | `/stats` | Outcome counts for the signed-in user |
| GET | `/playbook` | Playbook rows (older interface) |
| POST | `/reply`, `/say`, `/adapt` | Older objection and stage-line routes, not used by the current interface |

## How the AI suggestions work

`POST /suggest` builds a different prompt for each stage:

- a **stage plan** with the job of the stage, the shape of the line to say, and what not to do (for example, no pitching before stage 5)
- **coaching for each tap**, such as answering the "where did you get my number" question briefly and honestly, or confirming the channel and a follow-up time when someone says "send it on WhatsApp"
- the **context so far**: earlier stages, what the prospect said, and the caller's own note
- the **earlier suggestions**, so it does not repeat itself, with one automatic retry if a new suggestion is too similar
- rules for voice and safety: formal and slightly friendly, no exclamation marks, no invented facts about your offer, replies in the language the prospect used (English, Hindi or Hinglish)

The response has two lines, `READ` and `SAY`. The model tries `GROQ_SUGGEST_MODEL` first and falls back to `GROQ_MODEL`.

The suggestion is an aid. The caller chooses what to say.

## Privacy

- Calls are stored with the signed-in user's ID, and the API only returns a user's own calls.
- Signing in shares only the Google name and email.
- Notes, prospect details and the prospect's words are stored in your own Supabase project.
- Check the recording and consent rules where you and your prospects are before saving anything about a real call.

## Limitations

- On the free Render tier the API sleeps when idle, so the first load after a quiet period is slow. A free uptime monitor that pings `/` every 10 to 14 minutes avoids this.
- The AI only knows what you tap and type, so a short note about what the prospect said gives much better suggestions.
- There is no live transcription yet. Suggestions use the words you type.
- Groq's free tier has rate limits.

## Author and licence

Created by **Aryan Khanna**. Released under the MIT License, see `LICENSE`.
