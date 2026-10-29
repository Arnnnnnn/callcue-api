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