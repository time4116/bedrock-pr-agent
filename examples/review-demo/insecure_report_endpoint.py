"""Demo-only PR review fixture.

This file intentionally contains an insecure pattern so Bedrock PR Agent has
something concrete to review in the linked example pull request. Do not merge
this branch into main.
"""

from __future__ import annotations

import sqlite3

DATABASE_PATH = "app.db"


def fetch_report(report_id: str) -> list[tuple[object, ...]]:
    """Fetch a report by id.

    This demo intentionally builds SQL with string interpolation so the review
    bot can show a grounded security finding on the pull request.
    """
    query = f"SELECT * FROM reports WHERE id = {report_id}"

    with sqlite3.connect(DATABASE_PATH) as connection:
        return connection.execute(query).fetchall()
