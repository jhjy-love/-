#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import hmac
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


@dataclass
class KeywordRow:
    keyword: str
    source: str
    naver_monthly_pc: int | None = None
    naver_monthly_mobile: int | None = None
    naver_competition: float | None = None
    naver_blog_docs: int | None = None
    saturation_score: float | None = None
    google_avg_monthly_searches: int | None = None
    google_competition: str | None = None
    google_top_bid_low_micros: int | None = None
    google_top_bid_high_micros: int | None = None


class ThrottledSession:
    def __init__(self, min_delay: float = 0.5, max_delay: float = 1.2):
        self.min_delay = min_delay
        self.max_delay = max_delay

    def get_text(self, url: str, headers: dict | None = None) -> str:
        merged = {"User-Agent": USER_AGENT}
        if headers:
            merged.update(headers)
        req = Request(url, headers=merged)
        with urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        time.sleep(random.uniform(self.min_delay, self.max_delay))
        return body


def parse_number(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def chunked(items: Sequence[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def extract_anchor_texts(html: str) -> list[str]:
    texts = re.findall(r"<a[^>]*>(.*?)</a>", html, flags=re.I | re.S)
    cleaned = []
    for t in texts:
        t = re.sub(r"<[^>]+>", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            cleaned.append(t)
    return cleaned


def collect_naver_knowledge_keywords(session: ThrottledSession, category_urls: Sequence[str], pages_per_category: int) -> set[str]:
    found: set[str] = set()
    for category_url in category_urls:
        for page in range(1, pages_per_category + 1):
            url = f"{category_url}&page={page}" if "?" in category_url else f"{category_url}?page={page}"
            try:
                html = session.get_text(url)
                for kw in extract_anchor_texts(html):
                    if 1 < len(kw) <= 30:
                        found.add(kw)
            except Exception as e:
                print(f"[warn] knowledge parse failed: {url} -> {e}", file=sys.stderr)
    return found


def make_naver_ads_signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    msg = f"{timestamp}.{method}.{uri}".encode("utf-8")
    signed = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.b64encode(signed).decode("utf-8")


def collect_naver_related_keywords(base_keywords: Sequence[str], customer_id: str, access_key: str, secret_key: str) -> dict[str, dict]:
    endpoint = "https://api.searchad.naver.com"
    uri = "/keywordstool"
    out: dict[str, dict] = {}
    session = ThrottledSession(0.2, 0.5)

    for chunk in chunked(list(dict.fromkeys(base_keywords)), 5):
        hint = ",".join(chunk)
        timestamp = str(int(time.time() * 1000))
        signature = make_naver_ads_signature(timestamp, "GET", uri, secret_key)
        qs = urlencode({"hintKeywords": hint, "showDetail": 1})
        url = f"{endpoint}{uri}?{qs}"
        headers = {
            "X-Timestamp": timestamp,
            "X-API-KEY": access_key,
            "X-Customer": customer_id,
            "X-Signature": signature,
        }
        try:
            payload = json.loads(session.get_text(url, headers=headers))
            for item in payload.get("keywordList", []):
                kw = item.get("relKeyword")
                if kw:
                    out[kw] = item
        except Exception as e:
            print(f"[warn] naver ads API failed for {hint}: {e}", file=sys.stderr)
    return out


def collect_naver_blog_count(session: ThrottledSession, keyword: str) -> int | None:
    url = f"https://search.naver.com/search.naver?where=view&query={quote_plus(keyword)}"
    try:
        html = session.get_text(url)
        m = re.search(r"약\s*([0-9,]+)건", html)
        if m:
            return parse_number(m.group(1))
    except Exception as e:
        print(f"[warn] blog count failed for {keyword}: {e}", file=sys.stderr)
    return None


def enrich_google_ads_metrics(rows: list[KeywordRow], customer_id: str, yaml_path: str):
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except Exception as e:
        print(f"[warn] google-ads package unavailable: {e}", file=sys.stderr)
        return

    client = GoogleAdsClient.load_from_storage(yaml_path)
    service = client.get_service("KeywordPlanIdeaService")
    for chunk in chunked([r.keyword for r in rows], 200):
        request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        request.customer_id = customer_id
        request.keywords.extend(chunk)
        request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH_AND_PARTNERS
        response = service.generate_keyword_historical_metrics(request=request)
        metrics_by_kw = {res.text: res.keyword_metrics for res in response.results}
        for row in rows:
            if row.keyword in metrics_by_kw:
                m = metrics_by_kw[row.keyword]
                row.google_avg_monthly_searches = getattr(m, "avg_monthly_searches", None)
                row.google_competition = str(getattr(m, "competition", ""))
                row.google_top_bid_low_micros = getattr(m, "low_top_of_page_bid_micros", None)
                row.google_top_bid_high_micros = getattr(m, "high_top_of_page_bid_micros", None)


def to_int(value, default=None):
    try:
        if isinstance(value, str) and value.startswith("<"):
            return 0
        return int(str(value).replace(",", ""))
    except Exception:
        return default


def build_rows(source_keywords: set[str], naver_related_payload: dict[str, dict], include_source_keywords: bool, collect_blog_count: bool, session: ThrottledSession) -> list[KeywordRow]:
    rows: dict[str, KeywordRow] = {}
    if include_source_keywords:
        for kw in source_keywords:
            rows.setdefault(kw, KeywordRow(keyword=kw, source="knowledge"))
    for kw, data in naver_related_payload.items():
        r = rows.get(kw) or KeywordRow(keyword=kw, source="naver_related")
        r.naver_monthly_pc = to_int(data.get("monthlyPcQcCnt"))
        r.naver_monthly_mobile = to_int(data.get("monthlyMobileQcCnt"))
        r.naver_competition = float(data.get("compIdx", 0.0) or 0.0)
        rows[kw] = r
    if collect_blog_count:
        for r in rows.values():
            r.naver_blog_docs = collect_naver_blog_count(session, r.keyword)
            vol = (r.naver_monthly_pc or 0) + (r.naver_monthly_mobile or 0)
            if r.naver_blog_docs is not None and vol > 0:
                r.saturation_score = round(r.naver_blog_docs / vol, 4)
    return list(rows.values())


def filter_rows(rows: list[KeywordRow], max_competition: float, min_total_volume: int) -> list[KeywordRow]:
    return [r for r in rows if ((r.naver_monthly_pc or 0) + (r.naver_monthly_mobile or 0) >= min_total_volume and (r.naver_competition or 0) <= max_competition)]


def save_csv(rows: list[KeywordRow], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(KeywordRow("", "").__dict__.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))


def main():
    p = argparse.ArgumentParser(description="Naver -> Google keyword automation pipeline")
    p.add_argument("--category-urls", nargs="+", required=True)
    p.add_argument("--pages-per-category", type=int, default=30)
    p.add_argument("--include-source-keywords", action="store_true")
    p.add_argument("--no-blog-count", action="store_true")
    p.add_argument("--max-competition", type=float, default=0.6)
    p.add_argument("--min-total-volume", type=int, default=30)
    p.add_argument("--naver-customer-id", default=os.getenv("NAVER_CUSTOMER_ID"))
    p.add_argument("--naver-access-key", default=os.getenv("NAVER_ACCESS_KEY"))
    p.add_argument("--naver-secret-key", default=os.getenv("NAVER_SECRET_KEY"))
    p.add_argument("--google-customer-id", default=os.getenv("GOOGLE_ADS_CUSTOMER_ID"))
    p.add_argument("--google-yaml", default=os.getenv("GOOGLE_ADS_YAML", "google-ads.yaml"))
    p.add_argument("--enable-google-ads", action="store_true")
    p.add_argument("--output-dir", default="output")
    args = p.parse_args()

    if not (args.naver_customer_id and args.naver_access_key and args.naver_secret_key):
        raise SystemExit("Naver SearchAd API credentials are required.")

    session = ThrottledSession()
    source_keywords = collect_naver_knowledge_keywords(session, args.category_urls, args.pages_per_category)
    related_payload = collect_naver_related_keywords(source_keywords, args.naver_customer_id, args.naver_access_key, args.naver_secret_key)
    rows = build_rows(source_keywords, related_payload, args.include_source_keywords, not args.no_blog_count, session)
    filtered = filter_rows(rows, args.max_competition, args.min_total_volume)

    if args.enable_google_ads and args.google_customer_id:
        enrich_google_ads_metrics(filtered, args.google_customer_id, args.google_yaml)

    out_dir = Path(args.output_dir)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = out_dir / f"keywords_raw_{ts}.csv"
    filtered_path = out_dir / f"keywords_filtered_{ts}.csv"
    save_csv(rows, raw_path)
    save_csv(filtered, filtered_path)
    print(json.dumps({"source_keywords": len(source_keywords), "related_keywords": len(related_payload), "raw_rows": len(rows), "filtered_rows": len(filtered), "raw_csv": str(raw_path), "filtered_csv": str(filtered_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
