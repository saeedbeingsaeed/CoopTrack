import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Posting:
    id: str
    title: str
    company: str
    location: str
    salary_min: float | None
    salary_max: float | None
    created: datetime.datetime | None
    url: str
    description: str = ""

    @property
    def pay(self):
        # Same free-text style as Application.pay, e.g. "$55,000–$65,000/yr".
        low, high = self.salary_min, self.salary_max
        if not (low or high):
            return ""
        if low and high and round(low) != round(high):
            return f"${low:,.0f}–${high:,.0f}/yr"
        return f"${(high or low):,.0f}/yr"


class JobSource:
    # The service only knows this interface, so Adzuna can be swapped out or faked in tests.
    is_sample = False

    def search(self, keywords, location, limit):
        raise NotImplementedError


class SampleJobSource(JobSource):
    # Used when there are no Adzuna keys (local dev, tests, or the free calls ran out).
    # The page says these are samples.
    is_sample = True

    def search(self, keywords, location, limit):
        now = datetime.datetime.now(datetime.UTC)
        rows = [
            ("s-1", "Software Developer Co-op (Winter 2027)", "Northwind Software", "Hamilton, ON", 52000, 60000, 1,
             "Build Python and Django services with a small team. Co-op students welcome."),
            ("s-2", "Junior Backend Developer", "Lakeshore Analytics", "Toronto, ON", 65000, 75000, 3,
             "Python APIs, PostgreSQL and AWS. One year of experience preferred."),
            ("s-3", "Data Engineering Intern", "Maple Ridge Bank", "Toronto, ON", None, None, 0,
             "SQL, Python and dashboards. 4 or 8 month internship."),
            ("s-4", "QA Automation Student", "Harbourview Health", "Burlington, ON", 45000, 45000, 6,
             "Automated testing with Playwright and pytest for a patient-facing web app."),
            ("s-5", "Full-Stack Developer", "Escarpment Labs", "Remote (Canada)", 80000, 95000, 10,
             "Vue.js front end, Spring Boot back end. Mentorship for new developers."),
            ("s-6", "IT Support Co-op", "Niagara Region", "Thorold, ON", 40000, 46000, 14,
             "Help desk, Microsoft 365 and Sentinel alerts for a municipal IT team."),
        ]  # fmt: skip
        postings = [
            Posting(pid, title, company, place, low, high, now - datetime.timedelta(days=days),
                    f"https://example.com/jobs/{pid}", text)
            for pid, title, company, place, low, high, days, text in rows
        ]  # fmt: skip
        return postings[:limit]
