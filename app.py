"""A small, local-first internship and job application tracker."""

from __future__ import annotations

import csv
import hmac
import io
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, flash, g, make_response, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("APPLICATION_TRACKER_DB", BASE_DIR / "applications.db"))
STATUSES = ("Interested", "Applied", "Interviewing", "Offer", "Rejected", "Withdrawn")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_db()) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('Interested','Applied','Interviewing','Offer','Rejected','Withdrawn')),
                location TEXT NOT NULL DEFAULT '',
                applied_on TEXT NOT NULL,
                posting_url TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.commit()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect_db()
    return g.db


@app.teardown_appcontext
def close_db(_error: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.context_processor
def inject_form_helpers() -> dict[str, object]:
    def csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return str(session["csrf_token"])

    return {"csrf_token": csrf_token, "statuses": STATUSES}


@app.before_request
def validate_post_token() -> None:
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(submitted, str(expected)):
            abort(400, description="The form expired. Reload the page and try again.")


def application_from_form() -> dict[str, str]:
    company = request.form.get("company", "").strip()[:100]
    role = request.form.get("role", "").strip()[:100]
    status = request.form.get("status", "Applied")
    location = request.form.get("location", "").strip()[:100]
    applied_on = request.form.get("applied_on", "").strip()
    posting_url = request.form.get("posting_url", "").strip()[:500]
    notes = request.form.get("notes", "").strip()[:2000]

    if not company or not role:
        raise ValueError("Company and role are required.")
    if status not in STATUSES:
        raise ValueError("Choose a valid application status.")
    try:
        date.fromisoformat(applied_on)
    except ValueError as exc:
        raise ValueError("Enter a valid application date.") from exc
    if posting_url:
        parsed = urlparse(posting_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Links must start with http:// or https://.")

    return {
        "company": company,
        "role": role,
        "status": status,
        "location": location,
        "applied_on": applied_on,
        "posting_url": posting_url,
        "notes": notes,
    }


@app.get("/")
def index():
    db = get_db()
    status_filter = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip()[:100]
    clauses: list[str] = []
    values: list[str] = []
    if status_filter in STATUSES:
        clauses.append("status = ?")
        values.append(status_filter)
    if search:
        clauses.append("(company LIKE ? OR role LIKE ? OR location LIKE ?)")
        needle = f"%{search}%"
        values.extend((needle, needle, needle))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    applications = db.execute(
        f"SELECT * FROM applications {where} ORDER BY applied_on DESC, id DESC", values
    ).fetchall()
    grouped = {row["status"]: row["total"] for row in db.execute(
        "SELECT status, COUNT(*) AS total FROM applications GROUP BY status"
    )}
    counts = {
        "total": sum(grouped.values()),
        "active": sum(grouped.get(item, 0) for item in ("Interested", "Applied", "Interviewing")),
        "interviews": grouped.get("Interviewing", 0),
        "offers": grouped.get("Offer", 0),
    }
    return render_template(
        "index.html", applications=applications, counts=counts,
        status_filter=status_filter, search=search,
    )


@app.route("/applications/new", methods=["GET", "POST"])
def new_application():
    values = {"status": "Applied", "applied_on": date.today().isoformat()}
    if request.method == "POST":
        try:
            values = application_from_form()
            db = get_db()
            db.execute(
                """INSERT INTO applications (company, role, status, location, applied_on, posting_url, notes)
                   VALUES (:company, :role, :status, :location, :applied_on, :posting_url, :notes)""",
                values,
            )
            db.commit()
            flash("Application saved.", "success")
            return redirect(url_for("index"))
        except ValueError as error:
            flash(str(error), "error")
    return render_template("form.html", application=values, page_title="Add an application")


@app.route("/applications/<int:application_id>/edit", methods=["GET", "POST"])
def edit_application(application_id: int):
    db = get_db()
    application = db.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    if application is None:
        abort(404)
    values = dict(application)
    if request.method == "POST":
        try:
            values = application_from_form()
            db.execute(
                """UPDATE applications SET company=:company, role=:role, status=:status,
                   location=:location, applied_on=:applied_on, posting_url=:posting_url,
                   notes=:notes WHERE id=:id""",
                {**values, "id": application_id},
            )
            db.commit()
            flash("Application updated.", "success")
            return redirect(url_for("index"))
        except ValueError as error:
            flash(str(error), "error")
    return render_template("form.html", application=values, page_title="Edit application")


@app.post("/applications/<int:application_id>/delete")
def delete_application(application_id: int):
    db = get_db()
    db.execute("DELETE FROM applications WHERE id = ?", (application_id,))
    db.commit()
    flash("Application removed.", "success")
    return redirect(url_for("index"))


@app.get("/export.csv")
def export_csv():
    rows = get_db().execute(
        "SELECT company, role, status, location, applied_on, posting_url, notes FROM applications ORDER BY applied_on DESC"
    ).fetchall()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("Company", "Role", "Status", "Location", "Applied on", "Posting URL", "Notes"))
    writer.writerows(tuple(row) for row in rows)
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=applications.csv"
    return response


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
