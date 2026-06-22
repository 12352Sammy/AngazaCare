import json
import os
import random
from datetime import date, datetime, timedelta
try:
    import google.generativeai as genai
except Exception:
    genai = None
from dotenv import load_dotenv

from flask import Flask, flash, redirect, render_template, request, url_for, jsonify, session
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
import bcrypt
from functools import wraps
from sqlalchemy import text

from models import Assessment, ChatMessage, MoodEntry, Recommendation, User, db, BreathingSession

load_dotenv()
if genai is not None:
    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
    except Exception:
        genai = None

app = Flask(__name__)
app.config["SECRET_KEY"] = "angazacare_secret_key_2026"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///angazacare.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

PHQ9_QUESTIONS = [
    "Little interest or pleasure in doing things",
    "Feeling down, depressed, or hopeless",
    "Trouble falling or staying asleep, or sleeping too much",
    "Feeling tired or having little energy",
    "Poor appetite or overeating",
    "Feeling bad about yourself — or that you are a failure or have let yourself or your family down",
    "Trouble concentrating on things, such as reading the newspaper or watching television",
    "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual",
    "Thoughts that you would be better off dead, or of hurting yourself in some way",
    "How difficult have these problems made it for you to do your work, take care of things at home, or get along with other people?"
]

DAILY_QUOTES = [
    "A small step each day can create a meaningful change.",
    "Rest is a vital part of progress, not a luxury.",
    "You are more resilient than you believe.",
    "Notice the good, even on the hardest days.",
    "Breathe slowly. You deserve calm.",
    "Kindness to yourself is a powerful act.",
    "Today is an opportunity to support your wellbeing.",
    "Every moment is a chance to reset and move forward.",
    "Trust your instincts and honor your feelings.",
    "Healthy habits begin with one mindful choice.",
]

BREATHING_TECHNIQUES = {
    "box": {"inhale": 4, "hold": 4, "exhale": 4, "name": "Box Breathing"},
    "478": {"inhale": 4, "hold": 7, "exhale": 8, "name": "4-7-8 Breathing"},
    "deep": {"inhale": 4, "hold": 2, "exhale": 6, "name": "Deep Breathing"}
}

ASSESSMENT_LEVELS = [
    (0, 4, "Minimal", "You are doing well. Keep supporting your mental health with healthy habits.", "#64ffda"),
    (5, 9, "Mild", "Some stress may be present. Light self-care and reflection can help.", "#ffc864"),
    (10, 14, "Moderate", "Consider sharing your feelings with a trusted person or professional.", "#ff8a64"),
    (15, 30, "Severe", "Urgent support is recommended. Reach out to a mental health professional.", "#ff6464"),
]

RECOMMENDATION_RULES = [
    {
        "score_min": 0,
        "score_max": 4,
        "title": "Positive mood support",
        "tips": [
            "Keep a consistent sleep schedule.",
            "Try light exercise like walking or stretching.",
            "Practice gratitude by noting three good moments today.",
        ],
    },
    {
        "score_min": 5,
        "score_max": 9,
        "title": "Mild support",
        "tips": [
            "Try deep breathing or guided meditation for 5 minutes.",
            "Write a short journal entry about how you feel.",
            "Stay connected with a friend or family member.",
        ],
    },
    {
        "score_min": 10,
        "score_max": 14,
        "title": "Moderate support",
        "tips": [
            "Consider talking to a counselor or therapist.",
            "Use a stress-management technique like progressive muscle relaxation.",
            "Set small achievable goals and celebrate your progress.",
        ],
    },
    {
        "score_min": 15,
        "score_max": 30,
        "title": "Urgent support",
        "tips": [
            "Reach out to a trusted professional or crisis line.",
            "Keep emergency contacts handy and share your needs with someone close.",
            "Practice grounding exercises when anxiety or stress rises.",
        ],
    },
]

EMERGENCY_CONTACTS = [
    {"name": "Befrienders Kenya", "role": "Crisis Support", "phone": "0800 723 253", "email": "support@befrienders.org"},
    {"name": "Mathare Hospital Mental Health", "role": "Counseling Unit", "phone": "020 2084040", "email": "info@matharehospital.co.ke"},
    {"name": "Kenyatta National Hospital", "role": "Psychiatric Services", "phone": "020 2726300", "email": "psychiatry@knh.or.ke"},
    {"name": "Emergency", "role": "Immediate Help", "phone": "999 / 112", "email": ""},
]


def get_daily_quote():
    today = date.today()
    index = (today.year + today.month + today.day) % len(DAILY_QUOTES)
    return DAILY_QUOTES[index]


def get_assessment_level(score):
    for minimum, maximum, label, message, color in ASSESSMENT_LEVELS:
        if minimum <= score <= maximum:
            return {"label": label, "message": message, "color": color}
    return ASSESSMENT_LEVELS[-1]


def init_db():
    with app.app_context():
        # Always ensure tables are created
        db.create_all()
        
        # Only seed if no users exist
        if User.query.count() == 0:
            seed_database()
        
        # Ensure admin user exists
        ensure_admin_user()


def ensure_schema():
    """Ensure required database columns exist for both SQLite and PostgreSQL."""
    try:
        db_url = app.config["SQLALCHEMY_DATABASE_URI"]
        with db.engine.connect() as conn:
            if db_url.startswith("sqlite"):
                # SQLite: use PRAGMA table_info
                result = conn.execute(text("PRAGMA table_info('user');")).fetchall()
                columns = [row[1] for row in result]
                if "is_admin" not in columns:
                    conn.execute(text("ALTER TABLE \"user\" ADD COLUMN is_admin BOOLEAN DEFAULT 0;"))
                    conn.commit()
            elif db_url.startswith("postgresql"):
                # PostgreSQL: use information_schema
                result = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='user' AND column_name='is_admin';"
                )).fetchall()
                if not result:
                    conn.execute(text("ALTER TABLE \"user\" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE;"))
                    conn.commit()
    except Exception as e:
        app.logger.warning(f"Schema update attempted or not needed: {e}")


def ensure_admin_user():
    """Create an admin user if none exists."""
    if not User.query.filter_by(email="admin@angazacare.com").first():
        admin = User(
            name="Admin Counselor",
            email="admin@angazacare.com",
            password_hash=hash_password("admin123"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()


def hash_password(password):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def check_password(password, hashed):
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def seed_database():
    demo_users = [
        {"name": "Demo User", "email": "demo@angazacare.com", "password": "password123"},
        {"name": "Test User", "email": "test@angazacare.com", "password": "test123"},
    ]

    for user_data in demo_users:
        # Only add demo user if the email is not already present
        if not User.query.filter_by(email=user_data["email"]).first():
            user = User(
                name=user_data["name"],
                email=user_data["email"],
                password_hash=hash_password(user_data["password"]),
            )
            db.session.add(user)
    db.session.commit()

    for user in User.query.all():
        for day_offset in range(1, 15):
            entry_date = date.today() - timedelta(days=day_offset)
            mood_score = 1 + ((user.id + day_offset) % 5)
            stress_level = 1 + ((user.id + day_offset * 2) % 10)
            note = "Reflecting on my day." if day_offset % 3 == 0 else "Maintaining healthy habits."
            mood_entry = MoodEntry(
                user_id=user.id,
                mood_score=mood_score,
                stress_level=stress_level,
                note=note,
                date=entry_date,
            )
            db.session.add(mood_entry)

        assessments = [
            {"score": 3, "answers": [0] * 10},
            {"score": 8, "answers": [1] * 8 + [0, 0]},
            {"score": 16, "answers": [2] * 8 + [0, 0]},
        ]
        for assessment_data in assessments:
            severity = get_assessment_level(assessment_data["score"])["label"]
            assessment = Assessment(
                user_id=user.id,
                score=assessment_data["score"],
                severity=severity,
                answers_json=json.dumps(assessment_data["answers"]),
            )
            db.session.add(assessment)

    for rule in RECOMMENDATION_RULES:
        recommendation = Recommendation(
            score_range_min=rule["score_min"],
            score_range_max=rule["score_max"],
            tips=json.dumps(rule["tips"]),
        )
        db.session.add(recommendation)

    db.session.commit()


def get_mood_chart_data(user):
    today = date.today()
    labels = []
    mood_values = []
    stress_values = []
    for offset in reversed(range(7)):
        day = today - timedelta(days=offset)
        labels.append(day.strftime("%b %d"))
        entry = MoodEntry.query.filter_by(user_id=user.id, date=day).first()
        mood_values.append(entry.mood_score if entry else 0)
        stress_values.append(entry.stress_level if entry else 0)
    return labels, mood_values, stress_values


def get_streak(user):
    streak = 0
    day = date.today()
    while True:
        entry = MoodEntry.query.filter_by(user_id=user.id, date=day).first()
        if entry:
            streak += 1
            day -= timedelta(days=1)
        else:
            break
    return streak

def check_crisis_flag(user):
    today = date.today()
    low_mood_count = 0
    for day_offset in range(3):
        entry = MoodEntry.query.filter_by(user_id=user.id, date=today - timedelta(days=day_offset)).first()
        if entry and entry.mood_score == 1:
            low_mood_count += 1
    last_assessment = Assessment.query.filter_by(user_id=user.id).order_by(Assessment.created_at.desc()).first()
    high_score = last_assessment and last_assessment.score >= 20
    return low_mood_count == 3 or high_score


def generate_supportive_reply(user_message, lang="en"):
    """Generate a message-aware fallback reply when the AI backend cannot be used."""
    text = (user_message or "").strip()
    text_lower = text.lower()

    if lang == "sw":
        categories = {
            "sleep": ["kulala", "usingizi", "nimechoka", "malalia", "usiku", "ndoto"],
            "stress": ["msongo", "wasiwasi", "hofu", "shinikizo", "pressa", "msongo wa mawazo"],
            "mood": ["huzuni", "samahani", "upweke", "buri", "siwezi", "mood"],
            "relationships": ["rafiki", "familia", "mume", "mke", "wazazi", "mwalimu"],
            "work": ["kazi", "shule", "mtihani", "mwanafunzi", "boss", "mafunzo"],
        }
        responses = {
            "sleep": [
                "Jaribu kuunda utaratibu wa kupumzika kabla ya kulala, kama kunywa chai ya moto au kusoma kwa sekunde chache.",
                "Ikiwa usingizi ni mgumu, jaribu kupumua kwa mfululizo wa 4-4-6 na kuweka mazingira tulivu.",
                "Hatua ndogo kabla ya kulala inaweza kusaidia mwili wako kuanza kupumzika.",
            ],
            "stress": [
                "Ninaona msongo. Chukua sekunde 60 za kupumua kwa kina na andika moja ya hisia zako.",
                "Jaribu kuzungumza na mtu unaemwamini au fanya mazoezi ya kupumua taratibu.",
                "Punguza mawazo kwa kumwanga fursa moja ndogo ya kufanya kitu cha kuvutia leo.",
            ],
            "mood": [
                "Ni sawa kuhisi hivi. Jaribu kutunza nafsi yako kwa hatua ndogo kama kunywa maji au kutembea kidogo.",
                "Hisia zako ni muhimu. Pata wakati wa kuuliza 'Ninaweza kufanya nini kidogo sasa?' na kujibu kwa upole.",
                "Jaribu kushirikiana hisia zako kwa mtu unayemwamini, hata kama ni kitu kimoja tu leo.",
            ],
            "relationships": [
                "Kuzungumza na mtu anaweza kufanya mzigo uwe mwepesi. Anza kwa kuzungumza kuhusu jambo moja tu.",
                "Mahusiano ni magumu, na hisia zako zinastahili kusikika. Jipe nafasi ya kuelezea unavyohisi.",
                "Ikiwa unashindwa, jaribu kuelezea kwa uwazi kunaweza kusaidia kujisikia mbali kidogo.",
            ],
            "work": [
                "Kazi na masomo vinaweza kuwa mzigo. Pumzika kwa dakika chache na utaone tofauti.",
                "Tumia kidogo cha muda kutulia, kisha rudi kwa kazi kwa hatua ndogo ndogo.",
                "Unafanya vizuri. Jaribu kujipa ruhusa ya kupumzika na kisha uendelee polepole.",
            ],
        }
        general = [
            "Niko hapa kukusaidia. Tueleze zaidi ili tuone hatua ndogo ya kufanya leo.",
            "Ni sawa kuchukua hatua ndogo kuelekea kujisikia vizuri. Hisia zako zinastahili.",
            "Jipe urahisi kwa kujali nafsi yako kwa hatua ndogo leo.",
            "Usihisi kuwa peke yako. Chukua muda wa kupumua na kujali nafsi yako kwa upole.",
        ]
    else:
        categories = {
            "sleep": ["sleep", "insomnia", "tired", "rest", "awake", "night"],
            "stress": ["stress", "anxiety", "worried", "panic", "pressure", "overwhelmed"],
            "mood": ["sad", "depressed", "down", "hopeless", "low", "lonely"],
            "relationships": ["friend", "family", "partner", "boyfriend", "girlfriend", "husband", "wife", "parent", "boss"],
            "work": ["work", "job", "school", "exam", "study", "college", "career"],
        }
        responses = {
            "sleep": [
                "If sleep is hard tonight, try a calm routine like lowering the lights and breathing slowly for a minute.",
                "Rest can feel far away, but a gentle bedtime routine and keeping your phone away may help.",
                "Sometimes the smallest change—like quieting your thoughts for one minute—helps your body relax.",
            ],
            "stress": [
                "It sounds like stress is building. Focus on one small thing you can do right now to feel lighter.",
                "Your feelings matter. Try writing down one worry and then setting it aside for a while.",
                "A grounding step, such as feeling your feet on the floor and breathing slowly, can help you feel steadier.",
            ],
            "mood": [
                "I hear you. When your mood dips, a tiny act of kindness toward yourself can help you hold on to hope.",
                "It's okay to feel this way. Keep listening to what you need and take one manageable step.",
                "Your emotions are real and important. A gentle moment of self-care can make a difference.",
            ],
            "relationships": [
                "Relationships can be complicated. Talking with someone you trust about one thing on your mind may help.",
                "You deserve to feel heard. Consider sharing how you're feeling with a friend or family member.",
                "If this is about someone else, focus on what you can control and keep your well-being first.",
            ],
            "work": [
                "Work and school pressure can feel heavy. Take a short break and do one small thing for yourself.",
                "A busy schedule is draining. Give yourself permission to breathe, even if it's just for one minute.",
                "You are doing your best. A small pause can help you feel more grounded.",
            ],
        }
        general = [
            "I'm here to listen and support you. Tell me more if you'd like, and we can find one small step together.",
            "You don't have to carry this alone. Let's focus on something manageable right now.",
            "A kind act for yourself can matter a lot. What is one easy thing you can do today?",
            "Take one small step forward, even if it's just recognizing that your feelings are real and worth caring for.",
        ]

    for category, keywords in categories.items():
        if any(kw in text_lower for kw in keywords):
            return random.choice(responses[category])

    if any(phrase in text_lower for phrase in ["how can i", "what should i", "any advice", "help me", "what do i", "what can i", "what now"]):
        if lang == "sw":
            return random.choice([
                "Jaribu kuanza na hatua ndogo ambayo inafaa kwako, kama kupumua taratibu au kuzungumza na rafiki.",
                "Panga hatua ndogo ya kwanza, kisha ujaribu kufanya hiyo kabla ya kuelekea hatua inayofuata.",
            ])
        return random.choice([
            "A good first step is one small, manageable action—like a short breath break or sharing how you feel with someone.",
            "Try choosing one simple thing you can do right now to feel a little better and build from there.",
        ])

    if any(phrase in text_lower for phrase in ["thank", "thanks", "appreciate", "asante"]):
        if lang == "sw":
            return random.choice([
                "Ni furaha yangu kusaidia. Endelea kujali hisia zako kwa hatua ndogo ndogo.",
                "Asante kwa kushiriki. Niko hapa kila unapohitaji msaada.",
            ])
        return random.choice([
            "You're welcome. I'm here to support you whenever you need it.",
            "Glad to be here for you. Keep checking in with yourself and take it one step at a time.",
        ])

    return random.choice(general)


def get_supportive_fallback(user_message=None, lang="en"):
    """Get bilingual fallback responses that are tailored to the user's message."""
    return generate_supportive_reply(user_message, lang=lang)


def get_recent_mood_summary(user, days=7):
    today = date.today()
    start_date = today - timedelta(days=days)
    entries = MoodEntry.query.filter(
        MoodEntry.user_id == user.id,
        MoodEntry.date >= start_date,
        MoodEntry.date <= today
    ).all()

    if not entries:
        return None

    mood_total = sum(entry.mood_score for entry in entries)
    stress_total = sum(entry.stress_level for entry in entries)
    notes = [entry.note for entry in entries if entry.note]
    return {
        "days": len(entries),
        "average_mood": round(mood_total / len(entries), 1),
        "average_stress": round(stress_total / len(entries), 1),
        "recent_note": notes[-1] if notes else None,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("Email already registered.", "warning")
        else:
            new_user = User(
                name=name,
                email=email,
                password_hash=hash_password(password),
            )
            db.session.add(new_user)
            db.session.commit()
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            email = request.form.get("email")
            password = request.form.get("password")
            user = User.query.filter_by(email=email).first()
            if user and check_password(password, user.password_hash):
                login_user(user)
                return redirect(url_for("dashboard"))
            flash("Invalid email or password.", "danger")
        except Exception as e:
            app.logger.exception("Login error")
            flash("An error occurred during login. Please try again.", "danger")

    return render_template("login.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin_dashboard"))
        flash("You are already logged in as a user.", "warning")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            email = request.form.get("email")
            password = request.form.get("password")
            user = User.query.filter_by(email=email).first()
            if user and check_password(password, user.password_hash) and getattr(user, "is_admin", False):
                login_user(user)
                return redirect(url_for("admin_dashboard"))
            flash("Invalid admin email or password.", "danger")
        except Exception as e:
            app.logger.exception("Admin login error")
            flash("An error occurred during admin login. Please try again.", "danger")

    return render_template("admin_login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            flash("Admin access required.", "danger")
            return redirect(url_for("admin_login"))
        return func(*args, **kwargs)
    return wrapper


@app.route("/admin")
@admin_required
def admin_dashboard():
    total_messages = ChatMessage.query.count()
    crisis_count = ChatMessage.query.filter_by(is_crisis=True).count()
    flagged_count = ChatMessage.query.filter_by(is_flagged=True).count()
    open_count = ChatMessage.query.filter_by(status="open").count()
    reviewed_count = ChatMessage.query.filter_by(status="reviewed").count()
    resolved_count = ChatMessage.query.filter_by(status="resolved").count()
    latest_crisis = ChatMessage.query.filter_by(is_crisis=True).order_by(ChatMessage.created_at.desc()).limit(5).all()
    messages = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(200).all()
    return render_template(
        "admin_dashboard.html",
        chat_messages=messages,
        total_messages=total_messages,
        crisis_count=crisis_count,
        flagged_count=flagged_count,
        open_count=open_count,
        reviewed_count=reviewed_count,
        resolved_count=resolved_count,
        latest_crisis=latest_crisis,
        current_lang=get_language(),
        t=TRANSLATIONS[get_language()],
    )


@app.route("/admin/message/<int:message_id>/update", methods=["POST"])
@admin_required
def admin_update_message(message_id):
    message = ChatMessage.query.get_or_404(message_id)
    status = request.form.get("status")
    flag = request.form.get("flag") == "on"
    flag_reason = request.form.get("flag_reason")
    if status in ["open", "reviewed", "resolved"]:
        message.status = status
    message.is_flagged = flag
    message.flag_reason = flag_reason if flag else None
    db.session.commit()
    flash("Chat message updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/set_language/<lang>")
def set_language(lang):
    """Set the user's language preference."""
    if lang in ["en", "sw"]:
        session["language"] = lang
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    last_assessment = Assessment.query.filter_by(user_id=current_user.id).order_by(Assessment.created_at.desc()).first()
    today_entry = MoodEntry.query.filter_by(user_id=current_user.id, date=date.today()).first()
    streak = get_streak(current_user)
    labels, mood_data, stress_data = get_mood_chart_data(current_user)
    crisis_detected = check_crisis_flag(current_user)
    
    return render_template(
        "dashboard.html",
        daily_quote=get_daily_quote(),
        last_assessment=last_assessment,
        today_entry=today_entry,
        streak=streak,
        chart_labels=json.dumps(labels),
        mood_chart=json.dumps(mood_data),
        stress_chart=json.dumps(stress_data),
        crisis_detected=crisis_detected,
        current_lang=get_language(),
        t=TRANSLATIONS[get_language()],
    )


@app.route("/assessment", methods=["GET", "POST"])
@login_required
def assessment():
    result = None
    radar_data = None
    if request.method == "POST":
        answers = []
        score = 0
        domains = {"mood": 0, "sleep": 0, "energy": 0, "concentration": 0, "appetite": 0, "self_worth": 0, "motivation": 0}
        
        domain_map = [
            ("mood", [0, 1]),
            ("sleep", [2]),
            ("energy", [3]),
            ("appetite", [4]),
            ("self_worth", [5]),
            ("concentration", [6]),
            ("motivation", [7, 8]),
        ]
        
        for i in range(10):
            value = int(request.form.get(f"q{i}", 0))
            answers.append(value)
            score += value
        
        for domain, indices in domain_map:
            for idx in indices:
                if idx < len(answers):
                    domains[domain] += answers[idx]
        
        severity_data = get_assessment_level(score)
        assessment = Assessment(
            user_id=current_user.id,
            score=score,
            severity=severity_data["label"],
            answers_json=json.dumps(answers),
        )
        db.session.add(assessment)
        db.session.commit()
        
        result = {
            "score": score,
            "label": severity_data["label"],
            "message": severity_data["message"],
            "color": severity_data["color"],
        }
        
        radar_data = {
            "labels": list(domains.keys()),
            "values": list(domains.values()),
        }
    
    return render_template("assessment.html", questions=PHQ9_QUESTIONS, result=result, radar_data=json.dumps(radar_data) if radar_data else None)


@app.route("/mood_tracker", methods=["GET", "POST"])
@login_required
def mood_tracker():
    today_entry = MoodEntry.query.filter_by(user_id=current_user.id, date=date.today()).first()
    if request.method == "POST":
        mood_score = int(request.form.get("mood_score", 3))
        stress_level = int(request.form.get("stress_level", 5))
        note = request.form.get("note", "")
        if today_entry:
            today_entry.mood_score = mood_score
            today_entry.stress_level = stress_level
            today_entry.note = note
        else:
            today_entry = MoodEntry(
                user_id=current_user.id,
                mood_score=mood_score,
                stress_level=stress_level,
                note=note,
                date=date.today(),
            )
            db.session.add(today_entry)
        db.session.commit()
        flash("Today’s mood has been recorded.", "success")
        return redirect(url_for("mood_tracker"))

    labels, mood_data, stress_data = get_mood_chart_data(current_user)
    return render_template(
        "mood_tracker.html",
        today_entry=today_entry,
        chart_labels=json.dumps(labels),
        mood_chart=json.dumps(mood_data),
        stress_chart=json.dumps(stress_data),
    )


@app.route("/recommendations")
@login_required
def recommendations():
    last_assessment = Assessment.query.filter_by(user_id=current_user.id).order_by(Assessment.created_at.desc()).first()
    if last_assessment:
        recommendation = Recommendation.query.filter(
            Recommendation.score_range_min <= last_assessment.score,
            Recommendation.score_range_max >= last_assessment.score,
        ).first()
        tips = json.loads(recommendation.tips) if recommendation else []
    else:
        tips = []
    return render_template("recommendations.html", tips=tips, assessment=last_assessment)


@app.route("/emergency")
@login_required
def emergency():
    return render_template("emergency.html", contacts=EMERGENCY_CONTACTS)

@app.route("/breathing", methods=["GET", "POST"])
@login_required
def breathing():
    if request.method == "POST":
        technique = request.form.get("technique", "box")
        duration = int(request.form.get("duration", 5))
        session_entry = BreathingSession(
            user_id=current_user.id,
            technique=BREATHING_TECHNIQUES[technique]["name"],
            duration_minutes=duration,
            date=date.today(),
        )
        db.session.add(session_entry)
        db.session.commit()
        flash(f"Breathing session saved! {duration} minutes of {BREATHING_TECHNIQUES[technique]['name']}.", "success")
        return redirect(url_for("breathing"))
    
    return render_template("breathing.html", techniques=BREATHING_TECHNIQUES)


KIRAYA_KB = {
    "crisis_keywords_en": ["hurt myself", "kill myself", "suicide", "want to die", "end it", "can't take it"],
    "crisis_keywords_sw": ["nidhuru", "kufa", "jiuapo", "kumalizia", "haiwezi"],
    "befrienders": "0800 720 177",
}


# Language translations for UI
TRANSLATIONS = {
    "en": {
        "dashboard": "Dashboard",
        "assessment": "Assessment",
        "mood_tracker": "Mood Tracker",
        "recommendations": "Recommendations",
        "emergency": "Emergency",
        "logout": "Logout",
        "login": "Login",
        "register": "Register",
        "language": "Language",
        "english": "English",
        "kiswahili": "Kiswahili",
        "good_day": "Good day",
        "todays_wellness": "Today's wellness snapshot",
        "last_assessment": "Last assessment",
        "todays_mood": "Today's mood",
        "current_streak": "Current streak",
        "days_of_checkins": "days of daily check-ins",
        "no_assessment": "No assessment yet.",
        "record_feelings": "Record your feelings in the mood tracker.",
        "mood_label": "mood",
        "stress_label": "stress",
        "weekly_mood_chart": "Weekly mood chart",
        "check_mental_health": "Check in with a quick mental health survey.",
        "share_mood": "Share your mood, stress, and reflections.",
        "get_support_tips": "Get support tips based on your latest score.",
        "access_support": "Access urgent Kenya-specific support contacts.",
        "ai_assistant": "AngazaCare AI",
        "type_message": "Type a message...",
        "send": "Send",
        "ai_resting": "AngazaCare AI is resting, please try again",
        "footer": "AngazaCare © 2026 — Mental health support that feels personal.",
        "positive_mood": "Positive mood support",
        "mild_support": "Mild support",
        "moderate_support": "Moderate support",
        "severe_support": "Severe support",
        "email": "Email",
        "password": "Password",
        "name": "Name",
        "submit": "Submit",
        "create_account": "Create Account",
        "sign_in": "Sign In",
        "account_created": "Account created successfully. Please log in.",
        "email_registered": "Email already registered.",
        "invalid_credentials": "Invalid email or password.",
        "logged_out": "You have been logged out.",
        "admin": "Admin",
    },
    "sw": {
        "dashboard": "Dashibodi",
        "assessment": "Tathmini",
        "mood_tracker": "Kufuatilia Hali ya Jini",
        "recommendations": "Mapendekezo",
        "emergency": "Dharura",
        "logout": "Ondoka",
        "login": "Ingia",
        "register": "Jiandikishe",
        "language": "Lugha",
        "english": "English",
        "kiswahili": "Kiswahili",
        "good_day": "Habari",
        "todays_wellness": "Picha ya afya yako leo",
        "last_assessment": "Tathmini ya mwisho",
        "todays_mood": "Hali ya jini leo",
        "current_streak": "Kamba ya sasa",
        "days_of_checkins": "siku za ukaguzi wa kila siku",
        "no_assessment": "Hakuna tathmini bado.",
        "record_feelings": "Rekodi hisia zako katika kufuatilia hali ya jini.",
        "mood_label": "hali ya jini",
        "stress_label": "msongo wa mawazo",
        "weekly_mood_chart": "Chati ya hali ya jini ya kila wiki",
        "check_mental_health": "Jaribu tathmini ya haraka ya afya ya akili.",
        "share_mood": "Shiriki hali yako, msongo wa mawazo, na mawazo yako.",
        "get_support_tips": "Pata vidokezo vya msaada kulingana na alama yako ya mwisho.",
        "access_support": "Fikirini rasilimali za dharura za Kenya.",
        "ai_assistant": "AI ya AngazaCare",
        "type_message": "Andika ujumbe...",
        "send": "Tuma",
        "ai_resting": "AI ya AngazaCare inapumzika, tafadhali jaribu tena",
        "footer": "AngazaCare © 2026 — Msaada wa afya ya akili ambao unajisikia binafsi.",
        "positive_mood": "Msaada wa hali chanya",
        "mild_support": "Msaada sawa",
        "moderate_support": "Msaada wa kawaida",
        "severe_support": "Msaada muhimu",
        "email": "Barua pepe",
        "password": "Nenosiri",
        "name": "Jina",
        "submit": "Wasilisha",
        "create_account": "Unda Akaunti",
        "sign_in": "Ingia",
        "account_created": "Akaunti imefungua kwa mafanikio. Tafadhali ingia.",
        "email_registered": "Barua pepe tayari imejisajili.",
        "invalid_credentials": "Barua pepe au nenosiri batili.",
        "logged_out": "Umebadilishwa kutoka.",
    },
}

def get_language():
    """Get the current language from session, default to English."""
    return session.get("language", "en")

def get_text(key):
    """Get translated text for a key in the current language."""
    lang = get_language()
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS["en"].get(key, key))


def detect_language(text):
    """Detect if text is primarily Kiswahili or English."""
    sw_patterns = ["ni ", "na ", "wa ", "ku", "la ", "ta ", "za ", "ni\u0144", "jina"]
    sw_count = sum(text.lower().count(p) for p in sw_patterns)
    return "sw" if sw_count > 2 else "en"


def has_crisis_markers(text):
    """Check if message contains crisis indicators."""
    text_lower = text.lower()
    crisis_en = KIRAYA_KB["crisis_keywords_en"]
    crisis_sw = KIRAYA_KB["crisis_keywords_sw"]
    return any(kw in text_lower for kw in crisis_en + crisis_sw)


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({"reply": "Please enter a message."}), 400

    # Check for crisis markers first
    is_crisis = has_crisis_markers(user_message)
    if is_crisis:
        crisis_msg = (
            f"I hear you and I care. Please reach Befrienders Kenya: {KIRAYA_KB['befrienders']} (24/7, free)\\n\\n"
            f"Nakuona na nakujali. Tafadhali wasiliana Befrienders Kenya: {KIRAYA_KB['befrienders']} (24/7, bure)"
        )
        if current_user.is_authenticated:
            chat = ChatMessage(
                user_id=current_user.id,
                user_message=user_message,
                ai_response=crisis_msg,
                is_crisis=True,
                status="open",
            )
            db.session.add(chat)
            db.session.commit()
        return jsonify({"reply": crisis_msg}), 200

    preferred_lang = get_language()
    if not genai or not os.getenv("GEMINI_API_KEY"):
        fallback_reply = get_supportive_fallback(user_message=user_message, lang=preferred_lang)
        if current_user.is_authenticated:
            chat = ChatMessage(
                user_id=current_user.id,
                user_message=user_message,
                ai_response=fallback_reply,
                is_crisis=False,
                status="open",
            )
            db.session.add(chat)
            db.session.commit()
        return jsonify({"reply": fallback_reply}), 200

    # Use session language preference, or detect from message
    user_lang = preferred_lang  # Gets preferred language from session
    if user_lang == "en":
        lang_instruction = "Respond in English."
    else:
        lang_instruction = "Respond in Kiswahili."

    system_prompt = (
        "You are AngazaCare AI, a compassionate mental health companion for Kenyans. "
        f"{lang_instruction} "
        "Be empathetic, non-judgmental, and practical. Never diagnose. "
        "Use fresh phrasing each time so your response does not sound repetitive. "
        "When relevant, suggest one small action the user can take today. "
        "Make the answer specific to the user's question and remind them they are not alone."
    )

    user_context = []
    if current_user.is_authenticated:
        last_assessment = Assessment.query.filter_by(user_id=current_user.id).order_by(Assessment.created_at.desc()).first()
        today_entry = MoodEntry.query.filter_by(user_id=current_user.id, date=date.today()).first()
        mood_summary = get_recent_mood_summary(current_user)
        user_context.append(f"User: {current_user.name}")
        if today_entry:
            user_context.append(
                f"Today's mood: {today_entry.mood_score}/5, stress: {today_entry.stress_level}/10."
            )
            if today_entry.note:
                user_context.append(f"Today note: {today_entry.note}")
        if last_assessment:
            user_context.append(
                f"Latest assessment: {last_assessment.score} ({last_assessment.severity})."
            )
        if mood_summary:
            user_context.append(
                f"Last 7 days average mood: {mood_summary['average_mood']}/5, stress: {mood_summary['average_stress']}/10."
            )
            if mood_summary.get('recent_note'):
                user_context.append(f"Recent note: {mood_summary['recent_note']}")

    if user_context:
        system_prompt = f"{system_prompt}\n\n" + "\n".join(user_context)

    messages = [
        {"role": "system", "parts": [system_prompt]},
        {"role": "user", "parts": [user_message]},
    ]

    try:
        model = genai.GenerativeModel(model_name="models/gemini-flash-latest")
        response = model.generate_content(messages)
        ai_response = response.text.strip() if response and getattr(response, "text", None) else get_supportive_fallback(user_message=user_message, lang=preferred_lang)
    except Exception as exc:
        app.logger.exception("AI chat failed")
        ai_response = get_supportive_fallback(user_message=user_message, lang=preferred_lang)

    if current_user.is_authenticated:
        chat = ChatMessage(
            user_id=current_user.id,
            user_message=user_message,
            ai_response=ai_response,
            is_crisis=False,
            status="open",
        )
        db.session.add(chat)
        db.session.commit()

    return jsonify({"reply": ai_response})

@app.route("/api/mood-history")
@login_required
def mood_history():
    today = date.today()
    ninety_days_ago = today - timedelta(days=90)
    
    entries = MoodEntry.query.filter(
        MoodEntry.user_id == current_user.id,
        MoodEntry.date >= ninety_days_ago,
        MoodEntry.date <= today
    ).all()
    
    mood_dict = {}
    for entry in entries:
        mood_dict[entry.date.isoformat()] = {
            "mood": entry.mood_score,
            "stress": entry.stress_level
        }
    
    current = ninety_days_ago
    heatmap = []
    while current <= today:
        day_data = mood_dict.get(current.isoformat(), {"mood": 0, "stress": 0})
        heatmap.append({
            "date": current.isoformat(),
            "mood": day_data["mood"],
            "stress": day_data["stress"]
        })
        current += timedelta(days=1)
    
    return jsonify(heatmap)

@app.route("/api/weekly-report")
@login_required
def weekly_report():
    if not genai or not os.getenv("GEMINI_API_KEY"):
        return jsonify({"error": "AI is resting, try again"}), 500
    
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    mood_entries = MoodEntry.query.filter(
        MoodEntry.user_id == current_user.id,
        MoodEntry.date >= week_ago,
        MoodEntry.date <= today
    ).all()
    
    assessments = Assessment.query.filter(
        Assessment.user_id == current_user.id,
        Assessment.created_at >= datetime.combine(week_ago, datetime.min.time())
    ).all()
    
    mood_avg = sum(e.mood_score for e in mood_entries) / len(mood_entries) if mood_entries else 0
    stress_avg = sum(e.stress_level for e in mood_entries) / len(mood_entries) if mood_entries else 0
    notes = "\n".join([e.note for e in mood_entries if e.note])
    
    data_summary = f"""
    Last 7 Days Summary:
    - Average mood: {mood_avg:.1f}/5
    - Average stress: {stress_avg:.1f}/10
    - Mood entries: {len(mood_entries)}
    - Assessments: {len(assessments)}
    - Recent notes: {notes if notes else 'None'}
    """

    prompt = (
        "You are a wellness coach in AngazaCare. Respond in both English and Kiswahili and keep the tone warm, direct, and practical. "
        "Use simple, encouraging language that feels culturally grounded and supportive. "
        "Based on this user's 7-day data, include one clear trend, one concern or support need, and three actionable recommendations. "
        "Keep the response under 200 words."
    )

    prompt = prompt + f"\n\nUser data:\n{data_summary}"

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        report = response.text if response else "Unable to generate report at this time."
        return jsonify({"report": report})
    except Exception as e:
        app.logger.exception("Weekly report generation failed")
        return jsonify({"report": get_supportive_fallback()}), 200


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
