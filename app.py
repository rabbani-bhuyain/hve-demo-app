"""
Small Business Inventory & Sales (POS) System

A Flask + SQLite CRUD web application for managing product inventory and
recording sales for a small business.
"""

import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, g

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"  # needed for flash messages
DATABASE = os.environ.get("DATABASE", "inventory.db")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    """Open a new database connection if one doesn't already exist for this request."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row  # lets us access columns by name
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they don't exist yet. Safe to run every startup."""
    db = sqlite3.connect(DATABASE)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sku TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            quantity_in_stock INTEGER NOT NULL DEFAULT 0,
            reorder_level INTEGER NOT NULL DEFAULT 5,
            unit_price REAL NOT NULL,
            supplier TEXT
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity_sold INTEGER NOT NULL,
            unit_price_at_sale REAL NOT NULL,
            total_amount REAL NOT NULL,
            sale_date TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        """
    )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    db = get_db()

    total_products = db.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]

    stock_value_row = db.execute(
        "SELECT COALESCE(SUM(quantity_in_stock * unit_price), 0) AS v FROM products"
    ).fetchone()
    stock_value = stock_value_row["v"]

    low_stock = db.execute(
        """SELECT * FROM products
           WHERE quantity_in_stock <= reorder_level
           ORDER BY quantity_in_stock ASC"""
    ).fetchall()

    total_revenue_row = db.execute(
        "SELECT COALESCE(SUM(total_amount), 0) AS v FROM sales"
    ).fetchone()
    total_revenue = total_revenue_row["v"]

    recent_sales = db.execute(
        """SELECT sales.*, products.name AS product_name
           FROM sales
           JOIN products ON sales.product_id = products.id
           ORDER BY sales.sale_date DESC, sales.id DESC
           LIMIT 5"""
    ).fetchall()

    return render_template(
        "dashboard.html",
        total_products=total_products,
        stock_value=stock_value,
        low_stock=low_stock,
        total_revenue=total_revenue,
        recent_sales=recent_sales,
    )


# ---------------------------------------------------------------------------
# Products — CRUD
# ---------------------------------------------------------------------------

@app.route("/products")
def list_products():
    db = get_db()
    search = request.args.get("search", "").strip()

    if search:
        products = db.execute(
            """SELECT * FROM products
               WHERE name LIKE ? OR sku LIKE ? OR category LIKE ?
               ORDER BY name""",
            (f"%{search}%", f"%{search}%", f"%{search}%"),
        ).fetchall()
    else:
        products = db.execute("SELECT * FROM products ORDER BY name").fetchall()

    return render_template("products_list.html", products=products, search=search)


@app.route("/products/add", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        name = request.form["name"].strip()
        sku = request.form["sku"].strip()
        category = request.form["category"].strip()
        quantity_in_stock = request.form.get("quantity_in_stock", "0")
        reorder_level = request.form.get("reorder_level", "5")
        unit_price = request.form.get("unit_price", "0")
        supplier = request.form.get("supplier", "").strip()

        # Basic validation
        errors = []
        if not name:
            errors.append("Product name is required.")
        if not sku:
            errors.append("SKU is required.")
        try:
            quantity_in_stock = int(quantity_in_stock)
            if quantity_in_stock < 0:
                errors.append("Quantity in stock cannot be negative.")
        except ValueError:
            errors.append("Quantity in stock must be a whole number.")
        try:
            reorder_level = int(reorder_level)
        except ValueError:
            errors.append("Reorder level must be a whole number.")
        try:
            unit_price = float(unit_price)
            if unit_price < 0:
                errors.append("Unit price cannot be negative.")
        except ValueError:
            errors.append("Unit price must be a number.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("product_form.html", product=request.form, mode="add")

        db = get_db()
        try:
            db.execute(
                """INSERT INTO products (name, sku, category, quantity_in_stock, reorder_level, unit_price, supplier)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, sku, category, quantity_in_stock, reorder_level, unit_price, supplier),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash(f"A product with SKU '{sku}' already exists.", "error")
            return render_template("product_form.html", product=request.form, mode="add")

        flash(f"Product '{name}' added.", "success")
        return redirect(url_for("list_products"))

    return render_template("product_form.html", product=None, mode="add")


@app.route("/products/edit/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()

    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("list_products"))

    if request.method == "POST":
        name = request.form["name"].strip()
        category = request.form["category"].strip()
        quantity_in_stock = request.form.get("quantity_in_stock", "0")
        reorder_level = request.form.get("reorder_level", "5")
        unit_price = request.form.get("unit_price", "0")
        supplier = request.form.get("supplier", "").strip()

        errors = []
        if not name:
            errors.append("Product name is required.")
        try:
            quantity_in_stock = int(quantity_in_stock)
        except ValueError:
            errors.append("Quantity in stock must be a whole number.")
        try:
            reorder_level = int(reorder_level)
        except ValueError:
            errors.append("Reorder level must be a whole number.")
        try:
            unit_price = float(unit_price)
        except ValueError:
            errors.append("Unit price must be a number.")

        if errors:
            for e in errors:
                flash(e, "error")
            merged = dict(product)
            merged.update(request.form)
            return render_template("product_form.html", product=merged, mode="edit", product_id=product_id)

        db.execute(
            """UPDATE products
               SET name = ?, category = ?, quantity_in_stock = ?, reorder_level = ?, unit_price = ?, supplier = ?
               WHERE id = ?""",
            (name, category, quantity_in_stock, reorder_level, unit_price, supplier, product_id),
        )
        db.commit()
        flash(f"Product '{name}' updated.", "success")
        return redirect(url_for("list_products"))

    return render_template("product_form.html", product=product, mode="edit", product_id=product_id)


@app.route("/products/delete/<int:product_id>", methods=["POST"])
def delete_product(product_id):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("list_products"))

    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    flash(f"Product '{product['name']}' deleted.", "success")
    return redirect(url_for("list_products"))


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

@app.route("/sales")
def list_sales():
    db = get_db()
    sales = db.execute(
        """SELECT sales.*, products.name AS product_name, products.sku AS sku
           FROM sales
           JOIN products ON sales.product_id = products.id
           ORDER BY sales.sale_date DESC, sales.id DESC"""
    ).fetchall()
    return render_template("sales_list.html", sales=sales)


@app.route("/sales/record", methods=["GET", "POST"])
def record_sale():
    db = get_db()
    products = db.execute("SELECT * FROM products ORDER BY name").fetchall()

    if request.method == "POST":
        product_id = request.form.get("product_id")
        quantity_sold = request.form.get("quantity_sold", "0")

        errors = []
        product = None
        if not product_id:
            errors.append("Please select a product.")
        else:
            product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product is None:
                errors.append("Selected product not found.")

        try:
            quantity_sold = int(quantity_sold)
            if quantity_sold <= 0:
                errors.append("Quantity sold must be a positive number.")
        except ValueError:
            errors.append("Quantity sold must be a whole number.")

        if not errors and product is not None and quantity_sold > product["quantity_in_stock"]:
            errors.append(
                f"Not enough stock. Only {product['quantity_in_stock']} unit(s) of "
                f"'{product['name']}' available."
            )

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("record_sale.html", products=products)

        total_amount = round(quantity_sold * product["unit_price"], 2)
        sale_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db.execute(
            """INSERT INTO sales (product_id, quantity_sold, unit_price_at_sale, total_amount, sale_date)
               VALUES (?, ?, ?, ?, ?)""",
            (product["id"], quantity_sold, product["unit_price"], total_amount, sale_date),
        )
        db.execute(
            "UPDATE products SET quantity_in_stock = quantity_in_stock - ? WHERE id = ?",
            (quantity_sold, product["id"]),
        )
        db.commit()

        flash(
            f"Sale recorded: {quantity_sold} x '{product['name']}' for ${total_amount:.2f}.",
            "success",
        )
        return redirect(url_for("list_sales"))

    return render_template("record_sale.html", products=products)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@app.route("/reports")
def reports():
    db = get_db()

    top_products = db.execute(
        """SELECT products.name, SUM(sales.quantity_sold) AS total_sold,
                  SUM(sales.total_amount) AS total_revenue
           FROM sales
           JOIN products ON sales.product_id = products.id
           GROUP BY products.id
           ORDER BY total_revenue DESC
           LIMIT 10"""
    ).fetchall()

    revenue_by_category = db.execute(
        """SELECT products.category, SUM(sales.total_amount) AS total_revenue
           FROM sales
           JOIN products ON sales.product_id = products.id
           GROUP BY products.category
           ORDER BY total_revenue DESC"""
    ).fetchall()

    return render_template(
        "reports.html", top_products=top_products, revenue_by_category=revenue_by_category
    )


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_RUN_PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "true").lower() in {"1", "true", "yes"},
    )
