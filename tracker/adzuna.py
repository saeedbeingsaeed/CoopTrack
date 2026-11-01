# Adzuna job search API (the third-party web service).
# Docs: https://developer.adzuna.com/docs/search

import datetime
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache

from .domain.errors import JobSearchError
from .domain.postings import JobSource, Posting

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
# The free plan has very few calls, and changing the sort order shouldn't spend
# another one, so the same search is reused for 30 minutes.
CACHE_SECONDS = 30 * 60


class AdzunaJobSource(JobSource):
    def __init__(self, app_id, app_key, country="ca", timeout=10):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.timeout = timeout

    def search(self, keywords, location, limit):
        raw = f"{self.country}|{keywords.lower()}|{location.lower()}|{limit}"
        key = "adzuna:" + hashlib.sha256(raw.encode()).hexdigest()
        postings = cache.get(key)
        if postings is None:
            postings = self._fetch(keywords, location, limit)
            cache.set(key, postings, CACHE_SECONDS)
        return postings

    def _fetch(self, keywords, location, limit):
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": limit,
            "what": keywords,
            "content-type": "application/json",
        }
        if location:
            params["where"] = location
        url = SEARCH_URL.format(country=self.country) + "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            raise JobSearchError(f"Adzuna returned an error ({error.code}). Try again later.") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise JobSearchError("Couldn't reach Adzuna. Try again in a minute.") from error
        return [to_posting(item) for item in body.get("results", [])]


def to_posting(item):
    created = item.get("created")
    return Posting(
        id=f"adzuna-{item['id']}",
        title=strip_tags(item.get("title", "")),
        company=(item.get("company") or {}).get("display_name", "") or "Unknown company",
        location=(item.get("location") or {}).get("display_name", ""),
        salary_min=item.get("salary_min"),
        salary_max=item.get("salary_max"),
        created=datetime.datetime.fromisoformat(created) if created else None,
        url=item.get("redirect_url", ""),
        description=strip_tags(item.get("description", "")),
    )


def strip_tags(text):
    # Adzuna wraps matched words in <strong>.
    return text.replace("<strong>", "").replace("</strong>", "").strip()
