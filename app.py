import os
import sqlite3
from pathlib import Path

import stripe
from flask import Flask, render_template, request, redirect, send_from_directory, abort

BASE = Path(__file__).parent
DB = BASE / "autoincome.db"

app = Flask(__name__, template_folder="templates")

app.secret_key = os.getenv(
    "SECRET_KEY",
    "autoincome-development-secret"
)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


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

                            # Stripe Managed Payments requires
                            # an eligible product tax code.
                            #
                            # Use this only if the product is
                            # accurately classified as a downloadable
                            # digital book/content product.
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

    return render_template(
        "success.html",
        p=product
    )


@app.route("/download/<filename>")
def download(filename):
    safe_filename = Path(filename).name

    return send_from_directory(
        BASE / "products",
        safe_filename,
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
