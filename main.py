import os, re, json, random, requests
from collections import Counter
from fastapi import FastAPI, Depends, Header, HTTPException
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

def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Log in required")
    r = requests.get(f"{SB_URL}/auth/v1/user", timeout=10,
                     headers={"apikey": SB_KEY, "Authorization": authorization})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    return r.json()


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
    prospect_role: str | None = None
    stage_reached: int | None = None
    taps: dict | None = None
    words: dict | None = None
    next_step: str | None = None
    duration_seconds: int | None = None


@app.get("/")
def health():
    return {"ok": True}


@app.get("/playbook")
def playbook():
    return get_playbook()


@app.post("/reply")
def reply(s: Said, user=Depends(current_user)):
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
def log_call(o: Outcome, user=Depends(current_user)):
    url = f"{SB_URL}/rest/v1/calls"
    core = {"outcome": o.outcome, "objection": o.objection, "user_id": user["id"]}
    for k in ("prospect_name", "prospect_company", "prospect_contact"):
        if getattr(o, k):
            core[k] = getattr(o, k)
    extra = {k: getattr(o, k) for k in ("notes", "prospect_role", "stage_reached", "taps",
                                        "words", "next_step", "duration_seconds")
             if getattr(o, k) not in (None, "", {})}
    attempts = [{**core, **extra}, core] if extra else [core]
    r = None
    for i, payload in enumerate(attempts):
        r = requests.post(url, headers=H, timeout=15, json=payload)
        if r.ok:
            return {**r.json()[0], "details_saved": i == 0}
    r.raise_for_status()


@app.get("/calls")
def list_calls(limit: int = 300, user=Depends(current_user)):
    r = requests.get(f"{SB_URL}/rest/v1/calls?select=*&user_id=eq.{user['id']}&order=created_at.desc&limit={min(limit, 500)}",
                     headers=H, timeout=15)
    r.raise_for_status()
    return r.json()


@app.get("/stats")
def stats(user=Depends(current_user)):
    r = requests.get(f"{SB_URL}/rest/v1/calls?select=outcome,objection&user_id=eq.{user['id']}",
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


def groq_chat(messages, temperature=0.8, max_tokens=900, effort="low", models=None):
    models = models or [os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")]
    for model in models:
        for extra in ({"reasoning_effort": effort}, {}):
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {GROQ_KEY}"},
                              json={"model": model, "messages": messages, "temperature": temperature,
                                    "max_tokens": max_tokens, **extra}, timeout=25)
            if r.ok:
                text = (r.json()["choices"][0]["message"].get("content") or "").strip()
                if text:
                    return text
            else:
                print("GROQ ERROR:", model, r.status_code, r.text[:200])
    return None


@app.post("/say")
def say(b: SayIn, user=Depends(current_user)):
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
def adapt(b: AdaptIn, user=Depends(current_user)):
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


STAGE_COACH = {
    1: "Reach the right person and say who you are in one line. If someone else answered, ask for the person by name.",
    2: "Say in one or two plain sentences why you called, in words they could repeat to a colleague.",
    3: "Ask whether they can talk now. Accept a yes, a no or a callback time. A question back is not a yes: answer it in one line, then ask again.",
    4: "Ask ONE open question about their company and their work. Do not talk about your own company yet.",
    5: "Ask ONE follow-up that draws out what they are trying to do or struggling with, in their own words. Do not pitch.",
    6: "Show you understood the reason for the no by saying it back in a few words, then ask ONE question about it. Do not argue or talk over it.",
    7: "Agree ONE concrete next step with a channel or a time. A time they name is better than one you propose.",
    8: "End clearly: repeat the next step, thank them and say goodbye. If the answer was no, close warmly without pushing.",
}
TAP_COACH = {
    "Switchboard or assistant": "Ask for the person by name and give a one-line reason a receptionist can pass on.",
    "Wrong person": "Thank them, ask who handles this (growth, marketing or the owner) and for a name or number.",
    "Person has left": "Ask who has taken over that role and for their name or number.",
    "Asked what we do": "Answer in one plain sentence, then ask if that is relevant to them.",
    "Asked who we are": "Say your name and company once, then give the reason for the call.",
    "Asked where we got the number": "Answer honestly and briefly (a public business listing), offer to stop calling, and ask for twenty seconds.",
    "Said it is not relevant": "Do not argue. Ask what would make it relevant, or whether someone else handles it.",
    "Asked who or what first": "Answer in one line, then ask again whether now is a good time.",
    "Busy, call later": "Thank them and get a specific time to call back.",
    "No": "Accept it politely and ask if you may send a short note.",
    "One-line answer": "Ask a second, easier question about the same topic.",
    "Corrected us": "Thank them for the correction and ask the same question about the right thing.",
    "Asked about us first": "Give one short sentence about you, then turn it back to them.",
    "Said nothing is needed": "Accept it and ask one light question about how they handle growth today.",
    "Asked what we can do": "Ask what they are trying to achieve before answering, in one sentence only.",
    "Handled in-house": "Do not criticise their team. Ask what they would still want from outside.",
    "Send it in writing": "Agree, but ask one short question so what you send is relevant, and confirm the channel.",
    "Report on WhatsApp": "Confirm the number and ask when you may follow up.",
    "Report by email": "Confirm the address and ask when you may follow up.",
    "Call at a time they named": "Repeat the time back and confirm the number.",
    "Referred to a colleague": "Ask for the colleague's name and number and whether you may mention them.",
}


class SuggestIn(BaseModel):
    stage: str
    n: int
    tap: str | None = None
    words: str | None = None
    name: str | None = None
    company: str | None = None
    role: str | None = None
    me: str | None = None
    offer: str | None = None
    earlier: str | None = None
    intent: str | None = None
    ask: str | None = None
    previous: list[str] = []
    avoid: list[str] = []


STAGE_NAMES = {1: "Opening", 2: "Purpose", 3: "Permission", 4: "Their business",
               5: "Their need", 6: "Objection", 7: "Next step", 8: "Close"}
STAGE_PLAN = {
    1: ("Reach the right person and say who you are.",
        "Greet, give your name, and ask for the person by name if someone else answered. No pitch.",
        "explaining the service, asking for a long conversation, asking about their business"),
    2: ("Give the reason for the call in one or two plain sentences they could repeat to a colleague.",
        "The reason for calling, in terms of outcomes and not a label. At most a short check at the end.",
        "asking about their business, listing features, asking for a meeting"),
    3: ("Find out whether they can talk now.",
        "A short, courteous request for a minute, or a callback time. If they asked a question, answer it in one line first, then ask again.",
        "describing the service at length, asking about their business, proposing a meeting"),
    4: ("Learn about their company before saying more about yours.",
        "One open question about what the company does, sells or how it is run, starting from anything they said.",
        "pitching, asking about problems or needs, repeating the purpose, asking permission again"),
    5: ("Draw out what they are trying to do or struggling with, in their own words.",
        "One follow-up question about a goal or difficulty they mentioned, using their own words. No solutions.",
        "pitching, proposing a meeting, asking basic company questions again"),
    6: ("Understand the reason behind the no.",
        "Acknowledge the reason in a few words, then ask one question that helps you understand it. No rebuttal.",
        "arguing, listing benefits, repeating the purpose, pushing for a meeting"),
    7: ("Agree ONE concrete next step.",
        "Propose or confirm a single step with a channel or a time, ask which time suits them, and confirm the number or address.",
        "re-pitching, asking discovery questions again, offering several options"),
    8: ("End the call clearly.",
        "Repeat the agreed next step in one sentence, thank them and say goodbye. If it was a no, close warmly without pushing.",
        "new questions, a new pitch, reopening objections"),
}


INTENT_COACH = {
    "What do I say now?": "Decide the single best next thing to say at this point.",
    "Answer their question": "Answer the prospect's last question or concern plainly in one or two sentences, then stop or ask one short follow-up.",
    "They are hesitant": "The prospect is hesitant. Acknowledge it calmly, lower the pressure and offer a small, easy next move.",
    "Ask a follow-up": "Ask one sharp follow-up question that builds directly on their last words.",
    "Wrap up politely": "Close the call politely and clearly, without pushing.",
}


def _words(t):
    return set(re.findall(r"[a-z]{4,}", (t or "").lower()))


def _similar(line, others):
    w = _words(line)
    return any(w and _words(o) and len(w & _words(o)) / len(w | _words(o)) > 0.5 for o in others)


@app.post("/suggest")
def suggest(b: SuggestIn, user=Depends(current_user)):
    job, shape, dont = STAGE_PLAN.get(b.n, STAGE_PLAN[1])
    tap = TAP_COACH.get(b.tap or "", "")
    offer = b.offer or "not stated, so say nothing about the offer beyond why you called"
    trail = "; ".join(f"{k} {v}" for k, v in STAGE_NAMES.items())
    system = (
        "You are a calm, experienced sales call coach helping a caller during a live cold call to a business "
        "owner or senior manager in India. "
        f"The caller is {b.me or 'the caller'}. What the caller offers: {offer}. "
        "Voice: formal, polite and slightly friendly Indian business English. Use 'please' and 'may I' naturally; "
        "no slang, no exclamation marks, no flattery, no pressure. "
        "Rules: respond directly to what the prospect actually said, using their own words, and answer any question "
        "they asked before asking your own. Ask at most one question. Never invent facts about the offer, results, "
        "numbers, clients or the prospect. The name, company and role describe the PROSPECT, never the caller. "
        "Use the prospect's name at most once. Reply in the language the prospect used (English, Hindi or Hinglish), "
        "English if unclear. "
        "What real calls showed: 'send it on WhatsApp or email' is common and often a polite brush-off, so accept it, "
        "confirm the channel and ask when you may follow up. A question back at the permission stage is not a yes. "
        "People often ask what you do twice because the first answer was only a label, so answer in plain outcomes. "
        "If the person is the wrong one or has left, ask who handles this and for a number. A time the prospect "
        "names is worth more than one you propose. "
        f"The call has eight stages in this order: {trail}. The caller is now at stage {b.n}, {b.stage}. "
        f"Everything you write must belong to this stage only. JOB OF THIS STAGE: {job} "
        f"SHAPE OF THE SAY LINE: {shape} DO NOT: {dont}. "
        + (f"What just happened: {b.tap}. {tap} " if b.tap else "")
        + (f"The caller asked for help with: {b.intent}. "
           + (f"Bridge naturally toward the next stage, {STAGE_NAMES.get(b.n + 1, 'the end of the call')}. "
              if b.intent == "Move to next stage" else INTENT_COACH.get(b.intent, "") + " ") if b.intent else "")
        + ("The caller's own note about what is happening right now is the freshest information, so use it. " if b.ask else "")
        + "Earlier suggestions are listed below. Do not repeat their ideas or wording, and do not redo a stage "
        "that is already finished. "
        "Output exactly two lines and nothing else:\n"
        "READ: what the prospect means or wants and what the caller should aim for (under 25 words)\n"
        "SAY: what the caller says next (one to three short sentences)"
    )
    said = b.words or ("nothing written yet." if b.tap else
                       "nothing yet. Nothing has happened at this stage, so READ says what to listen for "
                       "and SAY is how to begin this stage only.")
    base_user = (f"Prospect: {b.name or 'unknown'}, {b.role or 'role unknown'}, {b.company or 'company unknown'}.\n"
                 f"Earlier in the call: {b.earlier or 'nothing yet'}.\n"
                 f"What the prospect just said: {said}")
    if b.ask:
        base_user += f"\nCaller's note about what is happening right now: {b.ask}"
    seen = [x for x in (b.previous + b.avoid) if x]
    if seen:
        base_user += "\nEarlier suggestions (do not repeat):\n" + "\n".join(f"- {x}" for x in seen[-6:])
    models = [os.environ.get("GROQ_SUGGEST_MODEL", "openai/gpt-oss-120b"),
              os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")]

    def run(extra=""):
        text = groq_chat([{"role": "system", "content": system},
                          {"role": "user", "content": base_user + extra}],
                         temperature=0.5, max_tokens=1400, effort="medium", models=models) or ""
        read, say = "", ""
        for line in text.splitlines():
            if line.upper().startswith("READ:"):
                read = line.split(":", 1)[1].strip()
            elif line.upper().startswith("SAY:"):
                say = line.split(":", 1)[1].strip()
        if not say and text and "READ:" not in text.upper():
            say = text.strip()
        return read, say

    try:
        read, say = run()
        if say and _similar(say, seen):
            read2, say2 = run("\nYour last attempt repeated an earlier line. Write a clearly different line that fits "
                              f"stage {b.n} ({b.stage}) only.")
            if say2:
                read, say = read2 or read, say2
        return {"line": say.replace("!", "."), "read": read}
    except Exception as e:
        print("SUGGEST ERROR:", repr(e))
        return {"line": "", "read": ""}
