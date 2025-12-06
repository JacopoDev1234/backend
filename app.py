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

# React gira su 3000 → abilitiamo CORS
CORS(
    app,
    supports_credentials=True,
    origins=[
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
)


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

    external_id = db.Column(db.String(255))   # id su Cardmarket o altri marketplace
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


if __name__ == "__main__":
    app.run(debug=True)
