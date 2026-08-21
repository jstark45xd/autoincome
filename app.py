import os
import sqlite3
from pathlib import Path
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    send_from_directory,
    abort,
    flash,
)

BASE = Path(__file__).parent
DB = BASE / "autoincome.db"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "development-secret")


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

    existing = conn.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]

    if existing == 0:
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
        "SELECT * FROM products WHERE active=1 ORDER BY id DESC"
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
        (slug,),
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
        (slug,),
    ).fetchone()

    conn.close()

    if not product:
        abort(404)

    # Temporary checkout.
    # Stripe will replace this before accepting real payments.

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


@app.route("/admin", methods=["GET", "POST"])
def admin():

    admin_password = os.getenv(
        "ADMIN_PASSWORD",
        "change-me"
    )

    if request.method == "POST":

        if request.form.get("password") != admin_password:
            flash("Incorrect password.")
            return redirect(url_for("admin"))

        conn = get_db()

        conn.execute(
            """
            INSERT INTO products
            (name, slug, description, price_cents, filename)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                request.form["name"],
                request.form["slug"],
                request.form["description"],
                int(float(request.form["price"]) * 100),
                request.form["filename"],
            ),
        )

        conn.commit()
        conn.close()

        flash("Product added.")

        return redirect(url_for("admin"))

    conn = get_db()

    products = conn.execute(
        "SELECT * FROM products ORDER BY id DESC"
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
        port=int(os.getenv("PORT", 5000))
    )
