import json
import os
from datetime import date, datetime, timedelta
import google.generativeai as genai
from dotenv import load_dotenv

from flask import Flask, flash, redirect, render_template, request, url_for, jsonify, session
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
import bcrypt

from models import Assessment, MoodEntry, Recommendation, User, db, BreathingSession

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

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
        if not os.path.exists("angazacare.db"):
            db.create_all()
            seed_database()
        else:
            db.create_all()
            if User.query.count() == 0:
                seed_database()


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
        email = request.form.get("email")
        password = request.form.get("password")
        user = User.query.filter_by(email=email).first()
        if user and check_password(password, user.password_hash):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


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

@app.route("/api/chat", methods=["POST"])
def chat():
    if not os.getenv("GEMINI_API_KEY"):
        return jsonify({"reply": get_supportive_fallback()}), 200

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({"reply": "Please enter a message."}), 400

    system_prompt = (
        "You are AngazaCare AI, a compassionate mental health companion. Respond with empathy and care. "
        "Never diagnose. Always encourage professional help for serious concerns. Keep responses under 100 words."
    )

    user_context = []
    if current_user.is_authenticated:
        last_assessment = Assessment.query.filter_by(user_id=current_user.id).order_by(Assessment.created_at.desc()).first()
        today_entry = MoodEntry.query.filter_by(user_id=current_user.id, date=date.today()).first()
        user_context.append(f"User: {current_user.name}")
        user_context.append(f"Today's mood score: {today_entry.mood_score if today_entry else 'Not tracked'}")
        if last_assessment:
            user_context.append(
                f"Latest assessment score: {last_assessment.score} ({last_assessment.severity})"
            )

    if user_context:
        system_prompt = f"{system_prompt}\n\n" + "\n".join(user_context)

    messages = [
        {"role": "system", "parts": [system_prompt]},
        {"role": "user", "parts": [user_message]},
    ]

    try:
        model = genai.GenerativeModel(model_name="models/gemini-flash-latest")
        response = model.generate_content(messages)
        ai_response = response.text.strip() if response and getattr(response, "text", None) else get_supportive_fallback()
        return jsonify({"reply": ai_response})
    except Exception as exc:
        app.logger.exception("AI chat failed")
        return jsonify({"reply": get_supportive_fallback()}), 200

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
    if not os.getenv("GEMINI_API_KEY"):
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
    
    prompt = f"""You are a wellness coach. Based on this user's 7-day data:
    {data_summary}
    
    Write a warm, encouraging 3-paragraph wellness report covering:
    1. Overall emotional trends this week
    2. Notable patterns or concerns (gently)
    3. Three specific actionable recommendations
    
    Keep it under 200 words. Be warm and human."""
    
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        report = response.text if response else "Unable to generate report at this time."
        return jsonify({"report": report})
    except Exception as e:
        return jsonify({"error": "AI is resting, try again"}), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
