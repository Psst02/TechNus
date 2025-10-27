from datetime import date, datetime, timedelta
from helpers import get_db

def delete_old_articles():
    """Delete articles fetched more than 5 days ago"""

    db = get_db()

    # Compute cutoff date
    cutoff_date = date.today() - timedelta(days=5)

    # Delete all older entries
    db.execute("DELETE FROM articles WHERE DATE(fetched_at) < ?", (cutoff_date,))
    db.commit()

    print(f"[{datetime.now()}] Old articles deleted (fetched before {cutoff_date}).")


if __name__ == "__main__":
    delete_old_articles()