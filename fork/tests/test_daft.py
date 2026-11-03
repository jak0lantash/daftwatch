import json
import sqlite3

from adwatch import db, fetcher, server, sites
from adwatch.sites import Page


def listing(i, **kw):
    l = {"id": i, "title": f"{i} The Meadows, Classes Lake, Ballincollig, Co. Cork, P31P406",
         "saleType": ["For Sale"], "price": "€775,000", "numBedrooms": "4 Bed", "numBathrooms": "4 Bath",
         "propertyType": "Detached", "ber": {"rating": "B1"}, "floorArea": {"unit": "METRES_SQUARED", "value": "176"},
         "seller": {"name": "Joe", "branch": "Behan Irwin & Gosling", "sellerType": "BRANDED_AGENT"},
         "point": {"type": "Point", "coordinates": [-8.624967, 51.885051]}, "publishDate": 1793114456609,
         "seoFriendlyPath": f"/for-sale/x/{i}", "media": {"images": [{"size720x480": "https://media.daft.ie/x.jpg"}]}}
    l.update(kw)
    return {"listing": l}


def page_html(listings, total):
    data = {"props": {"pageProps": {"paging": {"totalResults": total}, "listings": listings}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def daft():
    return sites.get("daft")


def test_parse_listing_and_development_units():
    sites.load()
    from fork_sites_daft import parse_listings
    dev = listing(9, title="The Oaks, Ovens, Co. Cork", price="From €350,000",
                  prs={"subUnits": [{"id": 91, "price": "€350,000", "numBedrooms": "2 Bed", "propertyType": "Apartment",
                                     "seoFriendlyPath": "/new/91"}]})
    data = json.loads(page_html([listing(1), dev], 2).split(">", 1)[1].rsplit("<", 1)[0])
    ads, total = parse_listings(data)
    a, unit = ads
    assert total == 2
    assert (a["town"], a["county"], a["price"], a["beds"], a["ber"], a["floor_m2"]) == ("Ballincollig", "Cork", 775000, 4, "B1", 176.0)
    assert a["sale_type"] is None and a["seller"] == "Behan Irwin & Gosling" and a["published"].startswith("2026")
    assert unit["id"] == "91" and unit["price"] == 350000 and unit["town"] == "Ovens"
    assert unit["image"] == "https://media.daft.ie/x.jpg", "units without photos use the development's"


def test_town_parsing():
    sites.load()
    from fork_sites_daft import _town
    assert _town("1 X, Ballincollig, Co.Cork") == ("Ballincollig", "Cork")
    assert _town("8 The Manor, Model Farm Road, Co. Cork, T12YX8R") == ("Model Farm Road", "Cork")
    assert _town("2 Y, Cobh") == ("Cobh", None)


def test_page_url_and_url_checks():
    sites.load()
    from fork_sites_daft import page_url
    u = page_url("https://www.daft.ie/property-for-sale/cork/houses?numBeds_from=4&from=40", 20)
    assert "sort=publishDateDesc" in u and "from=20" in u and "from=40" not in u and "numBeds_from=4" in u
    assert sites.url_problem("https://www.daft.ie/property-for-sale/cork?radius=30000")
    assert sites.url_problem("https://www.daft.ie/for-sale/some-house/123")
    assert sites.url_problem("https://www.daft.ie/property-for-sale/cork?radius=20000") is None
    assert sites.url_problem("https://www.carzone.ie/used-cars")


def test_paging_and_cards(monkeypatch):
    pages = {0: [listing(i) for i in range(1, 21)], 20: [listing(i) for i in range(21, 26)]}
    seen = []

    def fake_get(key, url, **kw):
        off = int(url.split("from=")[-1])
        seen.append(off)
        return 200, url, page_html(pages[off], 25)
    monkeypatch.setattr("adwatch.http.get", fake_get)
    c = server.app.test_client()
    c.get("/api/ads?list=market")
    w = fetcher.worker("daft")
    sid = w.queue[0][1]
    w._first(sid); w.queue.clear()
    ads = c.get(f"/api/ads?list=market&search_id={sid}").json
    assert seen == [0] and len(ads["ads"]) == 20 and ads["more"]
    a = ads["ads"][0]
    assert a["kind"] == "house" and a["ppm2"] == round(775000 / 176) and a["km"] < 5
    w._next(sid)
    assert seen == [0, 20] and db.get_search(sid)["exhausted"]


def test_west_filter_on_default_search(monkeypatch):
    east = listing(2, point={"coordinates": [-8.43, 51.87]}, title="1 Rd, Douglas, Cork")
    monkeypatch.setattr("adwatch.http.get", lambda k, url, **kw: (200, url, page_html([listing(1), east], 2)))
    c = server.app.test_client()
    c.get("/api/ads?list=market")
    w = fetcher.worker("daft")
    house = next(s for s in db.list_searches() if s["filters"].get("side") == "west")
    w._first(house["id"])
    ids = [a["id"] for a in c.get(f"/api/ads?list=market&search_id={house['id']}").json["ads"]]
    assert ids == ["1"], "Douglas is east of Ballincollig"


OLD_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE searches(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, min_beds INTEGER, max_beds INTEGER, min_price INTEGER, max_price INTEGER,
  max_km REAL, west_only INTEGER NOT NULL DEFAULT 0, types TEXT, last_run TEXT, last_count INTEGER, last_error TEXT,
  next_from INTEGER NOT NULL DEFAULT 0, total INTEGER, refreshed_at TEXT);
CREATE TABLE ads(id TEXT PRIMARY KEY, url TEXT, title TEXT, town TEXT, county TEXT, price INTEGER, price_text TEXT,
  beds INTEGER, baths INTEGER, ptype TEXT, ber TEXT, floor_m2 REAL, seller TEXT, seller_type TEXT, image TEXT,
  lat REAL, lng REAL, published TEXT, sale_type TEXT, first_seen TEXT, last_seen TEXT, price_history TEXT DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'new', status_at TEXT);
CREATE TABLE ad_search(ad_id TEXT, search_id INTEGER, PRIMARY KEY(ad_id, search_id));
CREATE TABLE exclusions(id INTEGER PRIMARY KEY AUTOINCREMENT, field TEXT NOT NULL, value TEXT NOT NULL, UNIQUE(field, value));
CREATE TABLE runs(id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT, found INTEGER, new_ads INTEGER, error TEXT);
"""


def test_upgrade_from_daftwatch_before_adwatch(tmp_path, monkeypatch):
    path = tmp_path / "daftwatch.db"
    monkeypatch.setenv("DB_PATH", str(path))
    c = sqlite3.connect(path)
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO meta VALUES ('seeded', 'x'), ('radius20', 'x')")
    c.execute("INSERT INTO searches(name, url, min_beds, max_price, max_km, west_only, next_from, total, refreshed_at) "
              "VALUES ('4+ bed house', 'https://www.daft.ie/property-for-sale/ballincollig-cork/houses?radius=20000',"
              " 4, 1000000, 15, 1, 40, 356, '2026-11-01T10:00:00Z')")
    c.execute("INSERT INTO searches(name, url, min_beds, max_price, max_km, west_only, next_from, total) "
              "VALUES ('Apartments', 'https://www.daft.ie/property-for-sale/ballincollig-cork/apartments?radius=10000',"
              " 2, 400000, 10, 0, 0, 0)")
    c.execute("INSERT INTO ads(id, url, title, town, county, price, beds, ptype, ber, floor_m2, lat, lng, sale_type,"
              " first_seen, last_seen, price_history, status, status_at) VALUES ('6680363', 'https://www.daft.ie/x',"
              " '10 The Meadows, Ballincollig, Co. Cork', 'Ballincollig', 'Cork', 775000, 4, 'Detached', 'B1', 176,"
              " 51.885, -8.625, NULL, '2026-10-28T07:41:59Z', '2026-10-28T07:41:59Z', '[[\"2026-10-28T07:41:59Z\", 775000]]',"
              " 'liked', '2026-10-29T08:00:00Z')")
    c.execute("INSERT INTO ad_search VALUES ('6680363', 1)")
    c.execute("INSERT INTO exclusions(field, value) VALUES ('town', 'Douglas'), ('ber', 'E1'), ('beds', '5')")
    c.commit(); c.close()
    s1, s2 = db.list_searches()
    assert s1["filters"] == {"beds": {"min": 4}, "price": {"max": 1000000}, "distance": {"max": 15}, "side": "west"}
    assert (s1["site"], s1["next_page"], s1["total"], s1["refreshed_at"]) == ("daft", 2, 356, "2026-11-01T10:00:00Z")
    assert s2["filters"] == {"beds": {"min": 2}, "price": {"max": 400000}, "distance": {"max": 10}}
    assert s2["exhausted"]
    ad = db.get_ad("6680363")
    assert ad["site"] == "daft" and ad["beds"] == 4 and ad["ber"] == "B1" and ad["status"] == "liked"
    assert ad["kind"] == "house" and ad["ppm2"] == 4403
    saved = db.ads_for_list("liked")
    assert [a["id"] for a in saved] == ["6680363"] and saved[0]["searches"] == ["4+ bed house"]
    assert {(e["field"], e["value"]) for e in db.list_exclusions()} == {("town", "Douglas"), ("ber", "E1"), ("beds", "5")}
    assert len(db.list_searches()) == 2, "default searches aren't added to an upgraded database"
