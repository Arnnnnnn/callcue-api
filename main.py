import os, json, random, requests
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
    notes: str | None = None
    prospect_name: str | None = None
    prospect_company: str | None = None
    prospect_contact: str | None = None


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
        "25 words so it fits what the prospect said. Speak as the caller to the prospect, stay calm, "
        "never celebrate the objection and use no exclamation marks. "
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
    url = f"{SB_URL}/rest/v1/calls"
    body = {"outcome": o.outcome, "objection": o.objection}
    notes = {"notes": o.notes} if o.notes else {}
    who = {k: v for k, v in {"prospect_name": o.prospect_name,
                              "prospect_company": o.prospect_company,
                              "prospect_contact": o.prospect_contact}.items() if v}
    attempts = [{**body, **notes, **who}]
    if who and notes:
        attempts.append({**body, **notes})
    if who or notes:
        attempts.append(body)
    r = None
    for i, payload in enumerate(attempts):
        r = requests.post(url, headers=H, timeout=15, json=payload)
        if r.ok:
            return {**r.json()[0], "details_saved": i == 0}
    r.raise_for_status()


@app.get("/calls")
def list_calls(limit: int = 300):
    r = requests.get(f"{SB_URL}/rest/v1/calls?select=*&order=created_at.desc&limit={min(limit, 500)}",
                     headers=H, timeout=15)
    r.raise_for_status()
    return r.json()


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
    call_notes: str | None = None
    avoid: list[str] = []


STAGE_GUIDE = {
    "opening": ("Greet them by name, introduce the caller, admit it is a cold call, and give a short "
                "reason for calling that fits their business. End with a light permission question."),
    "discovery": ("Ask ONE open question that helps the caller learn how they handle the problem hinted in "
                  "the notes today and what hurts most. Make it specific to their business, do not state "
                  "the problem as fact, and do not pitch."),
    "pitch": ("In one sentence connect a benefit to the problem the prospect described (see what they said "
              "and the notes). Use only what they said, with no invented features, numbers or results. "
              "End by asking if a short walkthrough would be useful."),
    "close": ("Sum up their problem in a few words and propose one specific next step: a 15-minute call "
              "this week, offering two time options. Use their name."),
}
STYLES = ["warm and casual", "direct and brief", "curious and friendly",
          "confident and professional", "relaxed and conversational"]


def groq_chat(messages, temperature=0.8, max_tokens=900):
    payload = {"model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
               "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    for extra in ({"reasoning_effort": "low"}, {}):
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {GROQ_KEY}"},
                          json={**payload, **extra}, timeout=20)
        if r.ok:
            text = (r.json()["choices"][0]["message"].get("content") or "").strip()
            if text:
                return text
        else:
            print("GROQ SAY ERROR:", r.status_code, r.text[:200])
    return None


@app.post("/say")
def say(b: SayIn):
    facts = (f"Prospect name: {b.name or 'unknown'}. Company: {b.company or 'unknown'}. "
             f"What the caller already knows: {b.notes or 'nothing yet'}. "
             f"What the prospect said on this call: {b.call_notes or 'nothing yet'}.")
    guide = STAGE_GUIDE.get(b.stage.lower(), "Write the next natural line the caller can say.")
    system = ("You write the next line a salesperson says on a live phone call. "
              "The name, company and notes describe the PERSON BEING CALLED, never the caller, so the "
              "caller must never say they are from that company. The example line contains the caller's "
              "own name; keep it exactly as written. Use only the facts given and never invent details, "
              "numbers or results. Do not claim to already know their situation; ask or hint instead. "
              f"Stage: {b.stage}. {guide} Tone: {random.choice(STYLES)}. "
              "Write 1 or 2 short sentences that sound natural when spoken. Return only the line.")
    user = f"{facts}\nExample line (for intent only, rewrite it, do not copy it): {b.base}"
    if b.avoid:
        user += "\nDo not reuse the wording of these earlier lines:\n" + "\n".join(f"- {a}" for a in b.avoid[-3:])
    try:
        line = groq_chat([{"role": "system", "content": system},
                          {"role": "user", "content": user}])
        return {"line": line or b.base}
    except Exception as e:
        print("SAY ERROR:", repr(e))
        return {"line": b.base}


class AdaptIn(BaseModel):
    said: str
    reply: str
    follow_up: str | None = None
    objection: str | None = None
    name: str | None = None
    company: str | None = None
    notes: str | None = None
    call_notes: str | None = None


OBJ_HINTS = [
    (["email", "send me", "send details"],
     "They want something sent. Agree, then make it specific by asking one short question about their "
     "business that also gets their email address or a time to follow up. Do not ask what details they want."),
    (["expensive", "price", "cost", "budget", "afford"],
     "Do not discuss price yet. Acknowledge it, then shift to what the problem costs their business today."),
    (["not interested", "no thanks", "not looking"],
     "Stay calm and do not push. Admit the call was unexpected and ask one low-pressure question to see "
     "whether the problem exists for them."),
    (["later", "busy", "call back", "call me", "not now"],
     "Respect their time. Offer to call back and get a specific time."),
    (["vendor", "already", "current provider", "existing"],
     "Do not criticise what they use. Say you are not asking them to switch and ask what they would improve."),
    (["boss", "manager", "partner", "decision"],
     "Ask who else is involved and offer a short joint call or a short summary they can forward."),
    (["my number", "where did you get", "how did you get"],
     "Answer honestly and briefly (their business is publicly listed), offer to stop calling, then ask for 20 seconds."),
]


@app.post("/adapt")
def adapt(b: AdaptIn):
    facts = (f"Prospect name: {b.name or 'unknown'}. Company: {b.company or 'unknown'}. "
             f"What the caller already knows: {b.notes or 'nothing'}. "
             f"What the prospect said earlier on this call: {b.call_notes or 'nothing'}.")
    probe = f"{b.objection or ''} {b.said}".lower()
    hints = " ".join(h for keys, h in OBJ_HINTS if any(k in probe for k in keys))
    system = ("You coach a salesperson on a live phone call. The prospect just pushed back, and you write "
              "what the CALLER says next, spoken to the prospect. Rewrite the approved reply and follow-up so "
              "they fit this prospect and what they just said. The name, company and notes describe the "
              "prospect, never the caller. Rules: stay calm, respectful and brief; never celebrate or praise "
              "the objection (no 'Great to hear', 'Awesome', 'Absolutely'); no exclamation marks; use the "
              "prospect's name at most once; use only the facts given and never invent numbers, prices, "
              "results or features; do not claim to know their situation, hint or ask instead. "
              "REPLY: one or two short sentences (under 35 words) that acknowledge what they said and give "
              "one reason to keep talking, tied to their business if the facts allow. "
              "ASK: one short question the caller asks the prospect that moves toward a next step; it must be "
              "about the prospect's situation or a time to talk, never what the caller should send or do. "
              + hints + " Output exactly two lines and nothing else:\nREPLY: <text>\nASK: <text>")
    user = (f"{facts}\nProspect said: {b.said}\n"
            f"Approved reply: {b.reply}\nApproved follow-up: {b.follow_up or ''}")
    try:
        text = groq_chat([{"role": "system", "content": system},
                          {"role": "user", "content": user}], temperature=0.6) or ""
        reply, ask = b.reply, b.follow_up
        for line in text.splitlines():
            if line.upper().startswith("REPLY:"):
                reply = line.split(":", 1)[1].strip() or reply
            elif line.upper().startswith("ASK:"):
                ask = line.split(":", 1)[1].strip() or ask
        return {"reply": reply.replace("!", "."), "follow_up": (ask or "").replace("!", ".")}
    except Exception as e:
        print("ADAPT ERROR:", repr(e))
        return {"reply": b.reply, "follow_up": b.follow_up}
