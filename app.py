from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity,
)
from datetime import datetime, date, timedelta
import requests

# -------------------------------------------------
# CONFIG APP
# -------------------------------------------------
app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = "cambia-questa-chiave-super-segreta"

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# React gira su 3000 / 3001 → abilitiamo CORS
CORS(
    app,
    supports_credentials=True,
    origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
)

# -------------------------------------------------
# CONFIG TCGdex (NUOVO PROVIDER UNICO)
# -------------------------------------------------
# Docs base: https://api.tcgdex.net/v2/en/cards
TCGDEX_BASE_URL = "https://api.tcgdex.net/v2/en"


def tcgdex_request(path: str, params: dict | None = None):
    """
    Helper per chiamare la TCGdex REST API.
    Esempio:
      GET https://api.tcgdex.net/v2/en/cards?name=pikachu
    """
    url = f"{TCGDEX_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        resp = requests.get(url, params=params, timeout=10)
    except requests.RequestException as e:
        return None, {
            "msg": "Errore di connessione verso TCGdex API.",
            "detail": str(e),
        }

    if resp.status_code != 200:
        return None, {
            "msg": "Errore dalla TCGdex API.",
            "status": resp.status_code,
            "body": resp.text,
        }

    try:
        data = resp.json()
    except Exception:
        return None, {"msg": "Risposta TCGdex API non valida."}

    return data, None


# -------------------------------------------------
# MODELLI
# -------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)


class Collectible(db.Model):
    __tablename__ = "collectibles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Tipo: pokemon_card, funko_pop, ecc.
    type = db.Column(db.String(50), nullable=False)

    name = db.Column(db.String(255), nullable=False)
    set_name = db.Column(db.String(255))
    number = db.Column(db.String(50))
    rarity = db.Column(db.String(100))
    condition = db.Column(db.String(100))
    language = db.Column(db.String(50))

    purchase_price = db.Column(db.Numeric(10, 2))
    estimated_market_price = db.Column(db.Numeric(10, 2))

    acquisition_date = db.Column(db.Date)
    location = db.Column(db.String(255))
    notes = db.Column(db.Text)

    external_id = db.Column(db.String(255))   # id su TCGdex/Cardmarket
    image_url = db.Column(db.String(500))

    extra_data = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "type": self.type,
            "name": self.name,
            "setName": self.set_name,
            "number": self.number,
            "rarity": self.rarity,
            "condition": self.condition,
            "language": self.language,
            "purchasePrice": float(self.purchase_price) if self.purchase_price is not None else None,
            "estimatedMarketPrice": float(self.estimated_market_price) if self.estimated_market_price is not None else None,
            "acquisitionDate": self.acquisition_date.isoformat() if self.acquisition_date else None,
            "location": self.location,
            "notes": self.notes,
            "externalId": self.external_id,
            "imageUrl": self.image_url,
            "extraData": self.extra_data,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


# -------------------------------------------------
# CREAZIONE TABELLE
# -------------------------------------------------
with app.app_context():
    db.create_all()


# -------------------------------------------------
# AUTH
# -------------------------------------------------
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


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"msg": "Username o password mancanti"}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"msg": "Credenziali errate"}), 401

    access_token = create_access_token(
        identity=str(user.id),
        expires_delta=timedelta(hours=1),
    )

    return jsonify({"access_token": access_token}), 200


@app.route("/api/me", methods=["GET"])
@jwt_required()
def me():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user:
        return jsonify({"msg": "Utente non trovato"}), 404

    return jsonify({"id": user.id, "username": user.username}), 200


# -------------------------------------------------
# API WALLET COLLECTIBLES
# -------------------------------------------------
@app.route("/api/collectibles", methods=["GET"])
@jwt_required()
def get_collectibles():
    uid = int(get_jwt_identity())
    ctype = request.args.get("type")  # es: ?type=pokemon_card

    query = Collectible.query.filter_by(user_id=uid)
    if ctype:
        query = query.filter_by(type=ctype)

    items = query.order_by(Collectible.created_at.desc()).all()
    return jsonify([item.to_dict() for item in items]), 200


@app.route("/api/collectibles", methods=["POST"])
@jwt_required()
def create_collectible():
    uid = int(get_jwt_identity())
    data = request.get_json() or {}

    ctype = data.get("type")
    name = data.get("name")

    if not ctype:
        return jsonify({"msg": "Field 'type' is required"}), 400
    if not name:
        return jsonify({"msg": "Field 'name' is required"}), 400

    acquisition_date = None
    acq_str = data.get("acquisitionDate")
    if acq_str:
        try:
            acquisition_date = date.fromisoformat(acq_str)
        except ValueError:
            acquisition_date = None

    collectible = Collectible(
        user_id=uid,
        type=ctype,
        name=name,
        set_name=data.get("setName"),
        number=data.get("number"),
        rarity=data.get("rarity"),
        condition=data.get("condition"),
        language=data.get("language"),
        purchase_price=data.get("purchasePrice"),
        estimated_market_price=data.get("estimatedMarketPrice"),
        acquisition_date=acquisition_date,
        location=data.get("location"),
        notes=data.get("notes"),
        external_id=data.get("externalId"),
        image_url=data.get("imageUrl"),
        extra_data=data.get("extraData"),
    )

    db.session.add(collectible)
    db.session.commit()

    return jsonify(collectible.to_dict()), 201


@app.route("/api/collectibles/<int:item_id>", methods=["DELETE"])
@jwt_required()
def delete_collectible(item_id):
    uid = int(get_jwt_identity())

    collectible = Collectible.query.filter_by(id=item_id, user_id=uid).first()
    if not collectible:
        return jsonify({"msg": "Item not found"}), 404

    db.session.delete(collectible)
    db.session.commit()

    return jsonify({"msg": "Deleted"}), 200


# -------------------------------------------------
# RICERCA CARTE POKÉMON (TCGdex)
# -------------------------------------------------
@app.route("/api/pokemon/search", methods=["GET"])
@jwt_required()
def search_pokemon_cards():
    """
    Cerca carte Pokémon tramite TCGdex.
    Parametri (query string):
      - name (obbligatorio; alias q)
      - setName (opzionale)
      - rarity (opzionale)
      - page (opzionale, default 1)
      - pageSize (opzionale, default 20, max 100)
    """
    name = (request.args.get("name") or request.args.get("q") or "").strip()
    if not name:
        return jsonify({"msg": "Parametro 'name' obbligatorio"}), 400

    set_name = (request.args.get("setName") or "").strip()
    rarity = (request.args.get("rarity") or "").strip()

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    try:
        page_size = int(request.args.get("pageSize", 20))
    except ValueError:
        page_size = 20

    page_size = max(1, min(page_size, 100))

    params = {
        "name": name,
        "pagination:page": page,
        "pagination:itemsPerPage": page_size,
    }

    if set_name and set_name.lower() != "all":
        params["set.name"] = set_name

    if rarity:
        params["rarity"] = rarity

    data, err = tcgdex_request("cards", params=params)
    if err:
        return jsonify(err), 502

    cards_raw = data or []

    cards = []
    for card in cards_raw:
        pricing = (card.get("pricing") or {}).get("cardmarket") or {}
        estimated_market_price = (
            pricing.get("trend")
            or pricing.get("avg")
            or pricing.get("avg30")
        )

        set_obj = card.get("set") or {}

        # sistemiamo l'URL immagine: TCGdex espone base, noi aggiungiamo /low.webp
        image_raw = card.get("image")
        image_url = None
        if image_raw:
            image_url = f"{image_raw}/low.webp"

        cards.append({
            "externalId": card.get("id"),
            "name": card.get("name"),
            "setName": set_obj.get("name"),
            "number": card.get("localId") or card.get("number"),
            "rarity": card.get("rarity"),
            "imageUrl": image_url,
            "estimatedMarketPrice": float(estimated_market_price) if estimated_market_price is not None else None,
        })

    return jsonify({
        "total": len(cards),
        "count": len(cards),
        "cards": cards,
    }), 200


# -------------------------------------------------
# AVVIO APP
# -------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
