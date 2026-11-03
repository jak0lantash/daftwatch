"""daft.ie property search results.

daft.ie is a Next.js site: every search page embeds its results as JSON in
<script id="__NEXT_DATA__">, so no browser is needed, only a client that looks like Chrome
(adwatch.http). It rate-limits quickly, so pages are fetched on demand, 20+ seconds apart.
"""
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from adwatch import http
from adwatch.sites import Page, Site

PAGE_SIZE = 20


def page_url(url, offset):
    u = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k not in ("from", "pageSize")]
    if not any(k == "sort" for k, _ in params):
        params.append(("sort", "publishDateDesc"))  # newest first, so new ads land on page 1
    params += [("pageSize", str(PAGE_SIZE)), ("from", str(offset))]
    return urlunparse(u._replace(query=urlencode(params)))


def _int(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d[\d,]*", str(v))
    return int(m.group().replace(",", "")) if m else None


def _price(text):
    """'€450,000' / 'AMV: €450,000' / 'From €395,000' -> 450000; 'Price on Application' -> None."""
    if not text:
        return None
    m = re.search(r"€\s*([\d,]+(?:\.\d+)?)\s*([mk])?", str(text), re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    mult = {"m": 1_000_000, "k": 1000}.get((m.group(2) or "").lower(), 1)
    return int(n * mult) or None


def _area(fa):
    if isinstance(fa, dict):
        v = fa.get("value")
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        unit = (fa.get("unit") or "").upper()
        if unit.startswith("FT") or "SQ_FT" in unit or unit == "SQFT":
            v *= 0.092903
        if unit.startswith("ACRE"):
            return None
        return round(v, 1)
    return None


def _town(title):
    """'12 Main St, Ballincollig, Co. Cork' -> ('Ballincollig', 'Cork')."""
    parts = [p.strip() for p in (title or "").split(",") if p.strip()]
    if parts and re.fullmatch(r"[A-Z]\d[\dW]\s?[A-Z0-9]{4}", parts[-1].upper()):  # Eircode
        parts.pop()
    county = None
    county_re = r"^(co\.\s*|co\s+|county\s+)"
    if parts and re.match(county_re, parts[-1], re.I):
        county = re.sub(county_re, "", parts.pop(), flags=re.I).strip()
    elif parts and re.search(r"\s+co\.?\s*cork$", parts[-1], re.I):  # "Ballincollig Co.Cork"
        county = "Cork"
        parts[-1] = re.sub(r"\s+co\.?\s*cork$", "", parts[-1], flags=re.I)
    elif parts and parts[-1].lower() in ("cork", "cork city"):
        county = "Cork"
        parts.pop()
    town = parts[-1] if parts else None
    if town and re.match(r"^cork\s*\d*$", town, re.I):  # "Cork 12" style -> keep previous part too
        town = parts[-2] + ", " + town if len(parts) > 1 else town
    return town, county


def _image(media):
    media = media or {}
    for img in media.get("images") or []:
        for k in ("size720x480", "size600x600", "size680x392", "size400x300", "size360x240", "size300x200"):
            if img.get(k):
                return img[k]
        for k, v in img.items():
            if isinstance(v, str) and v.startswith("http"):
                return v
    return None


def _published(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def _ad(l, parent=None):
    parent = parent or {}
    title = l.get("title") or parent.get("title")
    town, county = _town(title)
    seller = l.get("seller") or parent.get("seller") or {}
    pt = (l.get("point") or parent.get("point") or {}).get("coordinates") or [None, None]
    path = l.get("seoFriendlyPath") or parent.get("seoFriendlyPath") or ""
    ber = (l.get("ber") or {}).get("rating") or (parent.get("ber") or {}).get("rating")
    beds = _int(l.get("numBedrooms"))
    price_text = l.get("price") or (parent.get("price") if not parent.get("prs") else None)
    sale = [t for t in (l.get("saleType") or parent.get("saleType") or []) if str(t).lower() != "for sale"]
    sale = ", ".join(str(t) for t in sale) if isinstance(sale, list) else sale
    return {
        "id": str(l["id"]),
        "url": ("https://www.daft.ie" + path) if path.startswith("/") else (path or None),
        "title": title,
        "town": town,
        "county": county,
        "price": _price(price_text),
        "price_text": price_text,
        "beds": beds,
        "baths": _int(l.get("numBathrooms")),
        "ptype": l.get("propertyType") or parent.get("propertyType"),
        "ber": (str(ber).upper().replace("_", " ") if ber else None),
        "floor_m2": _area(l.get("floorArea") or l.get("floorAreaFormatted")),
        "seller": seller.get("branch") or seller.get("name"),
        "seller_type": seller.get("sellerType"),
        "image": _image(l.get("media")) or _image(parent.get("media")),
        "lat": pt[1] if len(pt) > 1 else None,
        "lng": pt[0] if pt else None,
        "published": _published(l.get("publishDate") or parent.get("publishDate")),
        "sale_type": (str(sale).strip() or None) if sale else None,
    }


def parse_listings(data):
    """Next.js page data -> (ads, total_count). New developments are split into their units."""
    pp = data.get("props", {}).get("pageProps", {})
    ads = []
    for item in pp.get("listings") or []:
        l = item.get("listing") or item
        if not l.get("id"):
            continue
        units = (l.get("prs") or {}).get("subUnits") or []
        if units:
            for u in units:
                if u.get("id"):
                    ads.append(_ad(u, parent=l))
        else:
            ads.append(_ad(l))
    paging = pp.get("paging") or {}
    total = paging.get("totalResults", paging.get("total"))
    return ads, total


class Daft(Site):
    id = "daft"
    label = "daft.ie"
    hosts = ["daft.ie"]
    mode = "on_demand"
    page_size = PAGE_SIZE
    min_gap = 20.0
    url_hint = "https://www.daft.ie/property-for-sale/ballincollig-cork/houses?numBeds_from=4&radius=10000"
    clearable = ("sale_type",)   # "Sale agreed" can go back to for sale

    def check_url(self, url):
        if "/for-sale/" in url and "/property-for-sale/" not in url and "/new-homes" not in url:
            return "That's a single ad. Paste the address of a search results page instead."
        m = re.search(r"[?&]radius=(\d+)", url)
        if m and int(m.group(1)) > 20000:  # daft.ie returns no results at all for these
            return "daft.ie's widest radius is 20 km (radius=20000); a wider one finds nothing."
        return None

    def fetch_page(self, search, page_no):
        url = page_url(search["url"], page_no * PAGE_SIZE)
        status, _, html = http.get(self.id, url)
        if status != 200:
            raise RuntimeError(f"daft.ie answered HTTP {status}")
        data = http.next_data(html, "daft.ie")
        ads, total = parse_listings(data)
        pp = data.get("props", {}).get("pageProps", {})
        raw = pp.get("listings") or []
        return Page(ads, total=int(total) if total is not None else None, raw_count=len(raw),
                    debug={"url_fetched": url, "paging": pp.get("paging"), "raw": raw[:3]})

    def derive(self, ad):
        t = (ad.get("ptype") or "").lower()
        ad["kind"] = "apartment" if any(w in t for w in ("apartment", "duplex", "studio", "flat")) else "house"
        try:
            area = float(ad.get("floor_m2") or 0)
        except (TypeError, ValueError):
            area = 0
        ad["ppm2"] = round(ad["price"] / area) if ad.get("price") and area > 20 else None

    def demo_ads(self):
        towns = [("Ballincollig", 51.888, -8.593), ("Ovens", 51.880, -8.660), ("Blarney", 51.933, -8.567),
                 ("Douglas", 51.877, -8.436), ("Macroom", 51.904, -8.957), ("Bishopstown", 51.882, -8.520)]
        types = ["Detached", "Semi-D", "Terrace", "Apartment", "Bungalow"]
        bers = ["A2", "A3", "B1", "B2", "B3", "C1", "C2", "D1", "E1"]
        out = []
        for i in range(24):
            town, lat, lng = towns[i % len(towns)]
            ptype = types[i % len(types)]
            beds = 2 + i % 4
            area = 60 + beds * 25 + (i * 7) % 30
            out.append({"id": f"demo-{i}", "url": f"https://www.daft.ie/for-sale/demo/{i}",
                        "title": f"{i + 1} Demo Road, {town}, Co. Cork", "town": town, "county": "Cork",
                        "price": 280000 + beds * 60000 + (i * 13) % 9 * 10000, "beds": beds, "baths": 1 + beds // 2,
                        "ptype": ptype, "ber": bers[i % len(bers)], "floor_m2": area, "seller": "Demo Estates",
                        "lat": lat + (i % 5) / 500, "lng": lng - (i % 3) / 500})
        return out
