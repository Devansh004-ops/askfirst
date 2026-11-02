CREATE TABLE members (
    member_id   INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    branch      TEXT NOT NULL CHECK (branch IN ('Central', 'Riverside', 'Hillcrest')),
    joined_on   TEXT NOT NULL
);

CREATE TABLE books (
    book_id         INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    author          TEXT NOT NULL,
    genre           TEXT NOT NULL,
    published_year  INTEGER NOT NULL
);

CREATE TABLE loans (
    loan_id      INTEGER PRIMARY KEY,
    member_id    INTEGER NOT NULL REFERENCES members(member_id),
    book_id      INTEGER NOT NULL REFERENCES books(book_id),
    loaned_on    TEXT NOT NULL,
    due_on       TEXT NOT NULL,
    returned_on  TEXT
);

CREATE TABLE reviews (
    review_id    INTEGER PRIMARY KEY,
    member_id    INTEGER NOT NULL REFERENCES members(member_id),
    book_id      INTEGER NOT NULL REFERENCES books(book_id),
    rating       INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    reviewed_on  TEXT NOT NULL,
    UNIQUE (member_id, book_id)
);

-- Internal bookkeeping; hidden from model-written SQL (leading underscore).
CREATE TABLE _askfirst_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
