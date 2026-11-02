"""Deterministic demo data for the library domain.

    generate("library.db", seed=7, today="2026-01-15")

Same arguments => identical database. "Today" is stored in the database
(`_askfirst_meta.as_of`) and used as the reference date for relative phrases, so
the data never goes stale the way data generated relative to the wall clock does.

A few facts are *planted* so that every reading of an ambiguous question has a
different, unique winner. Without that, "most popular book" by loans, by borrowers
and by rating might all name the same book and an evaluation could not tell the
readings apart:

    book 3   (workhorse) most loans overall, but from very few borrowers
    book 12  (crowd-pleaser) most distinct borrowers
    book 25  (favourite) the only book averaging 5.0 stars with 3+ reviews
    member 5   most loans overall (repeats the same three books)
    member 8   most distinct books
    member 11  most loans in the last 30 days (and 7 days)
    member 27  most loans in the last 90 days (a burst 40-85 days ago)
    members 38-40 have never borrowed anything
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

FIRST = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Zara", "Ethan", "Isla", "Kabir", "Nora",
         "Omar", "Lena", "Arjun", "Mia", "Yusuf", "Chloe", "Rohan", "Elena", "Jonas", "Priya"]
LAST = ["Sharma", "Okafor", "Lindqvist", "Moreau", "Tanaka", "Haddad", "Novak", "Ferreira",
        "Banerjee", "Kowalski", "Mbeki", "Castillo", "Fischer", "Nakamura", "Rossi", "Verma",
        "Andersen", "Petrov", "Dubois", "Iyer"]
ADJ = ["Silent", "Hidden", "Last", "Golden", "Broken", "Distant", "Burning", "Quiet",
       "Forgotten", "Crimson", "Endless", "Winter"]
NOUN = ["Garden", "Harbour", "Archive", "Orchard", "Signal", "Letter", "Lantern", "Compass",
        "Bridge", "Almanac", "Mirror", "Voyage"]
GENRES = ["Mystery", "Fantasy", "Science Fiction", "History", "Biography", "Romance", "Thriller", "Poetry"]
BRANCHES = ["Central", "Riverside", "Hillcrest"]

WORKHORSE, CROWD_PLEASER, FAVOURITE = 3, 12, 25
HEAVY_BORROWER, WIDE_READER, RECENT_BORROWER, QUARTER_BORROWER = 5, 8, 11, 27
NEVER_BORROWED = (38, 39, 40)
N_MEMBERS, N_BOOKS = 40, 60


def _iso(d: date) -> str:
    return d.isoformat()


def generate(db_path: str | Path, *, seed: int = 7, today: str = "2026-01-15") -> dict:
    rng = random.Random(seed)
    today_d = date.fromisoformat(today)
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

    path = Path(db_path)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(schema)

    # ---- members & books ----------------------------------------------------
    names = rng.sample([f"{f} {l}" for f in FIRST for l in LAST], N_MEMBERS)
    members = [(i, names[i - 1], rng.choice(BRANCHES), _iso(today_d - timedelta(days=rng.randint(60, 1100))))
               for i in range(1, N_MEMBERS + 1)]
    titles = rng.sample([f"The {a} {n}" for a in ADJ for n in NOUN], N_BOOKS)
    authors = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(35)]
    books = [(i, titles[i - 1], rng.choice(authors), rng.choice(GENRES), rng.randint(1990, 2024))
             for i in range(1, N_BOOKS + 1)]

    # ---- loans ---------------------------------------------------------------
    loans = []  # (member_id, book_id, loaned_on: date, returned_on: date | None)

    def add_loan(member, book, loaned, *, open_ok=False):
        returned = loaned + timedelta(days=rng.randint(2, 12))
        if returned > today_d or (open_ok and rng.random() < 0.5):
            returned = None
        loans.append((member, book, loaned, returned))

    borrowers = [m for m in range(1, N_MEMBERS + 1) if m not in NEVER_BORROWED]
    for _ in range(350):                                   # background traffic
        age = rng.randint(1, 365)
        recent = age <= 30
        loaned = today_d - timedelta(days=age)
        member, book = rng.choice(borrowers), rng.randint(1, N_BOOKS)
        returned = loaned + timedelta(days=rng.randint(2, 28))
        if returned > today_d or rng.random() < (0.5 if recent else 0.03):
            returned = None                                # still out (overdue if older than 14 days)
        loans.append((member, book, loaned, returned))

    for book, count in ((WORKHORSE, 40), (7, 15), (9, 15)):  # one reader, three books, many times
        for _ in range(count):
            add_loan(HEAVY_BORROWER, book, today_d - timedelta(days=rng.randint(120, 364)))
    crowd = rng.sample([m for m in borrowers if m != HEAVY_BORROWER], 30)
    for member in crowd:                                   # 30 different people, one book each
        add_loan(member, CROWD_PLEASER, today_d - timedelta(days=rng.randint(10, 300)))
    for book in rng.sample([b for b in range(1, N_BOOKS + 1)], 45):  # one reader, 45 different books
        add_loan(WIDE_READER, book, today_d - timedelta(days=rng.randint(100, 360)))
    for _ in range(25):                                    # a burst of recent activity
        add_loan(RECENT_BORROWER, rng.randint(1, N_BOOKS), today_d - timedelta(days=rng.randint(1, 60)),
                 open_ok=True)

    for _ in range(30):                                    # active a while ago, quiet this month
        add_loan(QUARTER_BORROWER, rng.randint(1, N_BOOKS), today_d - timedelta(days=rng.randint(40, 85)))

    # ---- reviews (ratings 1-4 everywhere except the planted favourite) --------
    reviews, taken = [], set()
    for member, book, loaned, _ in rng.sample(loans, 190):
        if book == FAVOURITE or (member, book) in taken:
            continue
        taken.add((member, book))
        reviewed = min(today_d, loaned + timedelta(days=rng.randint(3, 20)))
        reviews.append((member, book, rng.randint(1, 4), reviewed))
    for member in range(20, 28):                           # eight five-star reviews of one book
        add_loan(member, FAVOURITE, today_d - timedelta(days=rng.randint(30, 200)))
        reviews.append((member, FAVOURITE, 5, today_d - timedelta(days=rng.randint(5, 25))))

    # ---- write ---------------------------------------------------------------
    loans.sort(key=lambda row: (row[2], row[0], row[1]))
    conn.executemany("INSERT INTO members VALUES (?,?,?,?)", members)
    conn.executemany("INSERT INTO books VALUES (?,?,?,?,?)", books)
    conn.executemany(
        "INSERT INTO loans VALUES (?,?,?,?,?,?)",
        [(i, m, b, _iso(l), _iso(l + timedelta(days=14)), _iso(r) if r else None)
         for i, (m, b, l, r) in enumerate(loans, 1)])
    conn.executemany(
        "INSERT INTO reviews VALUES (?,?,?,?,?)",
        [(i, m, b, rating, _iso(d)) for i, (m, b, rating, d) in enumerate(reviews, 1)])
    conn.execute("INSERT INTO _askfirst_meta VALUES ('as_of', ?)", (today,))
    conn.commit()
    conn.close()
    return {"members": len(members), "books": len(books), "loans": len(loans), "reviews": len(reviews)}
