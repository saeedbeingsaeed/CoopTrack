# Strategy pattern.
#
# Each RankingStrategy is a different way to order job search results. The
# service picks one at runtime from the "Sort by" menu (or --rank on the CLI)
# and just calls rank(). To add a new order, write a class and add it to RANKINGS.

import datetime
import re

from .errors import CoopTrackError

OLDEST = datetime.datetime.min.replace(tzinfo=datetime.UTC)


class RankingStrategy:
    key = ""
    label = ""

    def rank(self, postings, keywords):
        raise NotImplementedError


class BestMatch(RankingStrategy):
    # Count how often the search words appear; a hit in the title counts 3x.
    key, label = "match", "Best match"

    def rank(self, postings, keywords):
        words = [w for w in re.findall(r"\w+", keywords.lower()) if len(w) > 1]

        def score(p):
            title, body = p.title.lower(), p.description.lower()
            return sum(3 * title.count(w) + body.count(w) for w in words)

        return sorted(postings, key=score, reverse=True)


class Newest(RankingStrategy):
    key, label = "newest", "Newest first"

    def rank(self, postings, keywords):
        return sorted(postings, key=lambda p: p.created or OLDEST, reverse=True)


class HighestPay(RankingStrategy):
    # Postings without a salary go to the bottom.
    key, label = "pay", "Highest pay"

    def rank(self, postings, keywords):
        return sorted(postings, key=lambda p: p.salary_max or p.salary_min or -1, reverse=True)


class StudentRolesFirst(RankingStrategy):
    # Co-op/intern/student titles first, newest first within each group.
    key, label = "student", "Co-op and internships first"
    PATTERN = re.compile(r"\b(co-?op|intern(ship)?s?|student|summer|placement|new grad)\b", re.IGNORECASE)

    def rank(self, postings, keywords):
        newest = Newest().rank(postings, keywords)
        return sorted(newest, key=lambda p: not self.PATTERN.search(p.title))


RANKINGS = {s.key: s for s in (BestMatch(), Newest(), HighestPay(), StudentRolesFirst())}
DEFAULT_RANKING = BestMatch.key


def get_ranking(key):
    if key not in RANKINGS:
        raise CoopTrackError(f"Unknown sort “{key}”. Use one of: {', '.join(RANKINGS)}.")
    return RANKINGS[key]
