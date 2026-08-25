import os
import sqlite3
import hashlib
import hmac
import base64
import json
import time
from pathlib import Path

import stripe
from flask import Flask, render_template, request, redirect, send_from_directory, abort

BASE = Path(__file__).parent
DB = BASE / "autoincome.db"

app = Flask(__name__, template_folder="templates")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Use the Stripe secret as the signing secret when no separate
# SECRET_KEY has been configured.
app.secret_key = os.getenv(
    "SECRET_KEY",
    os.getenv("STRIPE_SECRET_KEY", "autoincome-development-secret")
)


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            filename TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    count = conn.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]

    if count == 0:
        conn.execute(
            """
            INSERT INTO products
            (name, slug, description, price_cents, filename)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "30-Day Content Planner",
                "30-day-content-planner",
                "A practical 30-day social-content planning template for small businesses and creators.",
                1900,
                "30-day-content-planner.txt",
            ),
        )

    conn.commit()
    conn.close()


def make_download_token(filename, session_id):
    """Create a short-lived signed download token."""
    secret = os.getenv("STRIPE_SECRET_KEY")

    if not secret:
        return None

    payload = {
        "filename": filename,
        "session_id": session_id,
        "expires": int(time.time()) + 3600,
    }

    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()

    signature = hmac.new(
        secret.encode(),
        encoded.encode(),
        hashlib.sha256,
    ).hexdigest()

    return encoded + "." + signature


def verify_download_token(token):
    """Verify a download token and return its payload."""
    secret = os.getenv("STRIPE_SECRET_KEY")

    if not secret or not token or "." not in token:
        return None

    encoded, signature = token.rsplit(".", 1)

    expected = hmac.new(
        secret.encode(),
        encoded.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        return None

    try:
        payload = json.loads(
            base64.urlsafe_b64decode(encoded.encode()).decode()
        )
    except Exception:
        return None

    if payload.get("expires", 0) < int(time.time()):
        return None

    return payload


@app.route("/")
def home():
    conn = get_db()

    products = conn.execute(
        "SELECT * FROM products WHERE active=1"
    ).fetchall()

    conn.close()

    return render_template(
        "home.html",
        products=products
    )


@app.route("/product/<slug>")
def product(slug):
    conn = get_db()

    product = conn.execute(
        "SELECT * FROM products WHERE slug=? AND active=1",
        (slug,)
    ).fetchone()

    conn.close()

    if not product:
        abort(404)

    return render_template(
        "product.html",
        p=product
    )


@app.route("/buy/<slug>", methods=["POST"])
def buy(slug):
    conn = get_db()

    product = conn.execute(
        "SELECT * FROM products WHERE slug=? AND active=1",
        (slug,)
    ).fetchone()

    conn.close()

    if not product:
        abort(404)

    if not stripe.api_key:
        abort(
            500,
            description="Stripe is not configured."
        )

    try:
        checkout = stripe.checkout.Session.create(
            mode="payment",

            line_items=[
                {
                    "price_data": {
                        "currency": "usd",

                        "product_data": {
                            "name": product["name"],
                            "description": product["description"],
                            "tax_code": "txcd_10302000",
                        },

                        "unit_amount": product["price_cents"],
                    },

                    "quantity": 1,
                }
            ],

            success_url=(
                request.host_url
                + "success?session_id={CHECKOUT_SESSION_ID}"
            ),

            cancel_url=(
                request.host_url
                + "product/"
                + product["slug"]
            ),
        )

        return redirect(
            checkout.url,
            code=303
        )

    except Exception:
        app.logger.exception(
            "STRIPE CHECKOUT ERROR"
        )

        abort(
            500,
            description="Stripe checkout failed."
        )


@app.route("/success")
def success():
    session_id = request.args.get("session_id")

    if not session_id:
        abort(400)

    if not stripe.api_key:
        abort(500)

    try:
        session = stripe.checkout.Session.retrieve(
            session_id
        )

        if session.payment_status != "paid":
            abort(403)

        items = stripe.checkout.Session.list_line_items(
            session_id,
            limit=1
        )

        if not items.data:
            abort(404)

        purchased_name = items.data[0].description

    except Exception:
        app.logger.exception(
            "STRIPE SESSION ERROR"
        )

        abort(500)

    conn = get_db()

    product = conn.execute(
        """
        SELECT * FROM products
        WHERE name=? AND active=1
        """,
        (purchased_name,)
    ).fetchone()

    conn.close()

    if not product:
        abort(404)

    download_token = make_download_token(
        product["filename"],
        session_id
    )

    if not download_token:
        abort(500)

    download_url = url_for(
        "download",
        filename=product["filename"],
        token=download_token
    )

    return render_template(
        "success.html",
        p=product,
        download_url=download_url
    )


@app.route("/download/<filename>")
def download(filename):
    token = request.args.get("token")

    payload = verify_download_token(token)

    if not payload:
        abort(403)

    requested_filename = Path(filename).name

    if payload.get("filename") != requested_filename:
        abort(403)

    return send_from_directory(
        BASE / "products",
        requested_filename,
        as_attachment=True
    )


@app.route("/admin")
def admin():
    conn = get_db()

    products = conn.execute(
        "SELECT * FROM products"
    ).fetchall()

    conn.close()

    return render_template(
        "admin.html",
        products=products
    )


init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv("PORT", "5000")
        )
    )
