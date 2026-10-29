import os, json, requests
from collections import Counter
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_KEY"]
GROQ_KEY = os.environ["GROQ_API_KEY"]
H = {
    "apikey": SB_KEY,
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
if not SB_KEY.startswith("sb_"):
    H["Authorization"] = f"Bearer {SB_KEY}"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

KEYWORDS = {
    "Not interested": ["not interested", "no thanks", "no thank", "don't need",
                       "dont need", "not looking", "not for us"],
    "Send me details": ["send me", "send details", "email me", "mail me",
                        "send info", "brochure", "details"],
    "Too expensive": ["expensive", "costly", "cost", "price", "pricey",
                      "budget", "afford", "cheap", "too much"],
    "Call me later": ["later", "busy", "not a good time", "call back",
                      "call me next", "next week", "in a meeting"],
    "Send me an email": ["send me", "send details", "email me", "mail me",
                         "send info", "brochure", "details", "email"],
    "Call me back later": ["later", "call back", "call me next", "next week",
                           "tomorrow", "not now"],
    "Already have a vendor": ["already have", "current vendor", "existing",
                              "we use", "happy with", "tried this"],
    "I need to ask my boss": ["boss", "manager", "partner", "owner",
                              "decision maker", "not my call", "team"],
    "How did you get my number": ["my number", "where did you get",
                                  "who gave you", "how did you get"],
    "I am busy right now": ["busy", "in a meeting", "driving", "no time",
                            "not a good time", "with a patient"],
}


def get_playbook():
    r = requests.get(f"{SB_URL}/rest/v1/playbook?select=*&order=id",
                     headers=H, timeout=15)
    r.raise_for_status()
    return r.json()


class Said(BaseModel):
    text: str


class Outcome(BaseModel):
    outcome: str
    objection: str | None = None


@app.get("/")
def health():
    return {"ok": True}


@app.get("/playbook")
def playbook():
    return get_playbook()


@app.post("/reply")
def reply(s: Said):
    rows = [p for p in get_playbook() if p["stage"] == "objection"]
    menu = "\n".join(f'- {p["objection"]}: {p["reply"]}' for p in rows)
    prompt = (
        "A salesperson is on a live cold call. The prospect just said:\n"
        f'"{s.text}"\n\nKnown objections and approved replies:\n{menu}\n\n'
        "Pick the closest objection. Rewrite its approved reply in at most "
        "25 words so it fits what the prospect said. "
        'Return only JSON: {"objection": "<exact name or none>", "reply": "<text>"}'
    )
    match, text = None, None
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={
                "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            },
            timeout=20,
        )
        print("GROQ STATUS:", r.status_code, r.text[:300])
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        match, text = data.get("objection"), data.get("reply")
    except Exception as e:
        print("GROQ ERROR:", repr(e))

    row = next((p for p in rows if p["objection"] == match), None)
    if row is None:
        low = s.text.lower()
        for p in rows:
            words = KEYWORDS.get(p["objection"], [])
            if any(w in low for w in words):
                row = p
                break
    if row is None:
        return {"objection": None,
                "reply": "Thanks for being direct. What's the main concern behind that?",
                "follow_up": "What would you need to see to feel comfortable?"}
    return {"objection": row["objection"],
            "reply": text or row["reply"],
            "follow_up": row["follow_up"]}


@app.post("/calls")
def log_call(o: Outcome):
    r = requests.post(f"{SB_URL}/rest/v1/calls", headers=H, timeout=15,
                      json={"outcome": o.outcome, "objection": o.objection})
    r.raise_for_status()
    return r.json()[0]


@app.get("/stats")
def stats():
    r = requests.get(f"{SB_URL}/rest/v1/calls?select=outcome,objection",
                     headers=H, timeout=15)
    r.raise_for_status()
    rows = r.json()
    return {
        "total": len(rows),
        "outcomes": dict(Counter(x["outcome"] for x in rows)),
        "objections": dict(Counter(x["objection"] for x in rows if x["objection"])),
    }

class SayIn(BaseModel):
    stage: str
    base: str
    name: str | None = None
    company: str | None = None
    notes: str | None = None

@app.post("/say")
def say(b: SayIn):
    facts = f"Name: {b.name or 'unknown'}. Company: {b.company or 'unknown'}. Notes: {b.notes or 'none'}."
    system = ("You help a salesperson on a live phone call. Rewrite the base line for the "
              f"'{b.stage}' stage of the call so it fits the PERSON BEING CALLED. "
              "The name, company and notes describe the person being called, never the caller, "
              "so the caller must not say they are from that company. "
              "Keep the caller's own introduction and the intent of the base line unchanged. "
              "Use only the facts given and never invent details. "
              "Do not claim to already know the person's situation; ask or hint instead, for example 'I imagine' or 'a lot of clinics tell us'. "
              "Write 1 or 2 short sentences that sound natural when spoken. Return only the line.")
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
            json={"model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": f"{facts}\nBase line: {b.base}"}],
                  "temperature": 0.4, "max_tokens": 500},
            timeout=15)
        r.raise_for_status()
        line = r.json()["choices"][0]["message"]["content"].strip()
        return {"line": line or b.base}
    except Exception:
        return {"line": b.base}


class AdaptIn(BaseModel):
    said: str
    reply: str
    follow_up: str | None = None
    name: str | None = None
    company: str | None = None
    notes: str | None = None


@app.post("/adapt")
def adapt(b: AdaptIn):
    facts = f"Name: {b.name or 'unknown'}. Company: {b.company or 'unknown'}. Notes: {b.notes or 'none'}."
    system = ("You help a salesperson on a live phone call. The prospect just pushed back. "
              "Rewrite the approved reply and the follow-up question so they fit the PERSON BEING CALLED. "
              "The name, company and notes describe the prospect, never the caller. "
              "Keep the intent of the approved reply. Use only the facts given, and never invent "
              "numbers, prices, results or claims. Do not claim to already know their situation; "
              "hint or ask instead, for example 'I imagine'. "
              "Reply in at most 2 short sentences that sound natural when spoken, and the follow-up "
              "must be one short question. Output exactly two lines and nothing else:\n"
              "REPLY: <text>\nASK: <text>")
    user = (f"{facts}\nProspect said: {b.said}\n"
            f"Approved reply: {b.reply}\nApproved follow-up: {b.follow_up or ''}")
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "temperature": 0.4, "max_tokens": 600},
            timeout=15)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        reply, ask = b.reply, b.follow_up
        for line in text.splitlines():
            if line.upper().startswith("REPLY:"):
                reply = line.split(":", 1)[1].strip() or reply
            elif line.upper().startswith("ASK:"):
                ask = line.split(":", 1)[1].strip() or ask
        return {"reply": reply, "follow_up": ask}
    except Exception:
        return {"reply": b.reply, "follow_up": b.follow_up}
