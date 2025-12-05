from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity,
    set_access_cookies,
    unset_jwt_cookies,
)
import datetime

app = Flask(__name__)

# --- CONFIG BASE --- tottigol
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = "cambia-questa-chiave-super-segreta"
# --- COOKIE DI PRODUZIONE ---
app.config["JWT_COOKIE_HTTPONLY"] = True    # 🔐 nasconde il JWT a document.cookie
app.config["JWT_COOKIE_SECURE"] = False     # True SOLO con HTTPS (lasciamo False in locale)
app.config["JWT_COOKIE_SAMESITE"] = "Lax"   # evita problemi in sviluppo
# --- CONFIG JWT + COOKIE ---
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_HTTPONLY"] = True    # 🔒 NASCONDE IL JWT
app.config["JWT_COOKIE_SECURE"] = False     # True SOLO in produzione HTTPS
app.config["JWT_COOKIE_SAMESITE"] = "Lax"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False


db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# --- CORS: permette richieste da React con cookie ---
CORS(
    app,
    supports_credentials=True,
    origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
)


# --- MODELLO USER ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)


# --- CREA TABELLE ALL'AVVIO ---
with app.app_context():
    db.create_all()


# --- REGISTRAZIONE ---
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"msg": "Username o password mancanti"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"msg": "Username esistente"}), 400

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({"msg": "Registrazione ok"}), 201


# --- LOGIN: CREA TOKEN E LO METTE NEL COOKIE ---
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"msg": "Credenziali errate"}), 401

    access_token = create_access_token(
        identity=str(user.id),
        expires_delta=datetime.timedelta(hours=1),
    )

    resp = jsonify({"msg": "Login ok"})
    # qui viene impostato il cookie "access_token_cookie"
    set_access_cookies(resp, access_token)
    return resp, 200


# --- LOGOUT: PULISCE IL COOKIE ---
@app.route("/api/logout", methods=["POST"])
def logout():
    resp = jsonify({"msg": "Logout ok"})
    unset_jwt_cookies(resp)
    return resp, 200


# --- ENDPOINT PROTETTO ---
@app.route("/api/me", methods=["GET"])
@jwt_required()
def me():
    uid = get_jwt_identity()  # viene letto dal cookie
    user = User.query.get(int(uid))
    if not user:
        return jsonify({"msg": "Utente non trovato"}), 404

    return jsonify({"id": user.id, "username": user.username}), 200


if __name__ == "__main__":
    app.run(debug=True)
