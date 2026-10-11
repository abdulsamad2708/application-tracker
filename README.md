# ApplyTrack

A local-first application tracker for keeping a job or internship search organized. Add roles, record status changes and interview notes, filter the list, and export the data to CSV.

## Features

- Track company, role, location, status, application date, posting link, and notes.
- Filter by status and search across company, role, and location.
- View totals for active applications, interviews, and offers.
- Edit or remove entries and export the full log as CSV.
- Store records in SQLite on the current computer; no account or hosted service is required.
- Validate form inputs and protect update forms with a session token.

## Run locally

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The database is created as `applications.db` next to `app.py` and is excluded from Git.

## Built with

Python, Flask, SQLite, Jinja templates, HTML, and CSS.

This is a single-user learning project intended to run locally. It does not include user accounts or cloud sync; avoid exposing the development server to a public network.
