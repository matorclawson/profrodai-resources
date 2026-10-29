"""Peer review for the class project: who reviews whom, and how the scores combine.

Run `python3 peer_review.py assign students.txt` (one student id per line) to print the review pairs.
Run `python3 peer_review.py combine scores.csv` (columns: author, reviewer, total; reviewer `instructor`
for the instructor's score) to print each project's final percentage.
"""
import csv
import statistics
import sys

REVIEWS_EACH = 3
PEER_WEIGHT, INSTRUCTOR_WEIGHT = 0.7, 0.3
RUBRIC_TOTAL = 20
SPREAD_LIMIT = 6  # if the peers' totals differ by more than this, the instructor re-runs the disputed lines


def assign(students):
    """Each student reviews the next k students in the sorted list: nobody reviews their own project,
    everyone reviews k projects, and every project gets k reviews. k is 3 for 7 or more students,
    otherwise (n - 1) // 2 so that two students never review each other; under 3 students there is
    no peer review and the instructor reviews every project."""
    ids = sorted(set(students))
    if len(ids) != len(students):
        raise ValueError("duplicate student id")
    k = min(REVIEWS_EACH, (len(ids) - 1) // 2)
    if k < 1:
        raise ValueError("fewer than 3 students: the instructor reviews every project")
    return [(reviewer, ids[(i + step) % len(ids)]) for i, reviewer in enumerate(ids) for step in range(1, k + 1)]


def combine(rows):
    """rows: (author, reviewer, total out of 20). Returns {author: {...}} with the final percentage.
    Peer score is the median of the peers' totals, so one outlier cannot move it. With fewer than 2 peer
    reviews the project is marked `needs_instructor`."""
    peers, instructor = {}, {}
    for author, reviewer, total in rows:
        if not 0 <= total <= RUBRIC_TOTAL:
            raise ValueError("score out of range")
        (instructor if reviewer == "instructor" else peers).setdefault(author, []).append(total)
    result = {}
    for author in sorted(set(peers) | set(instructor)):
        mine, boss = peers.get(author, []), instructor.get(author)
        entry = {"peer_reviews": len(mine), "needs_instructor": boss is None}
        entry["dispute"] = len(mine) >= 2 and max(mine) - min(mine) > SPREAD_LIMIT
        if boss is not None:
            peer = statistics.median(mine) if len(mine) >= 2 else boss[0]
            entry["final_percent"] = round(100 * (PEER_WEIGHT * peer + INSTRUCTOR_WEIGHT * boss[0]) / RUBRIC_TOTAL, 1)
        result[author] = entry
    return result


if __name__ == "__main__":
    command, path = sys.argv[1], sys.argv[2]
    if command == "assign":
        for reviewer, author in assign([line.strip() for line in open(path) if line.strip()]):
            print(reviewer, "reviews", author)
    elif command == "combine":
        with open(path, newline="") as handle:
            rows = [(r["author"], r["reviewer"], float(r["total"])) for r in csv.DictReader(handle)]
        for author, entry in combine(rows).items():
            print(author, entry)
