import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "adr.db")

def main():
    if not os.path.exists(DB_PATH):
        print("Database not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT answer_clear, source_clear, citation_useful, increased_trust, would_use FROM feedback").fetchall()
    conn.close()

    if not rows:
        print("Feedback Summary: 0 responses recorded so far.")
        return

    n = len(rows)
    # Calculate overall average across all dimensions for all rows
    total_score = sum(sum(row) for row in rows)
    overall_avg = total_score / (n * 5)
    
    # Calculate percentage of users who would use it (rating >= 4)
    would_use_count = sum(1 for row in rows if row[4] >= 4)
    would_use_pct = (would_use_count / n) * 100

    print(f"Feedback Summary ({n} responses):")
    print(f"  Overall Average Score: {overall_avg:.2f}/5.0")
    print(f"  {would_use_pct:.0f}% of users rated 'Likelihood to Use' >= 4")

if __name__ == "__main__":
    main()
