#!/usr/bin/env python3
"""Radar Tren Harian, Tahap 2.
Pakai:  python ambil_tren.py                       (data nyata, butuh API key)
        python ambil_tren.py --demo --tanggal 2026-10-26   (simulasi tanpa API)
Hasil: data/data.json (dibaca dashboard) dan data/riwayat.json (untuk hitung kecepatan naik)."""
import os, re, json, argparse, urllib.request, urllib.parse
from datetime import date, datetime
from pathlib import Path

DATA = Path("data"); DATA.mkdir(exist_ok=True)
BOBOT = (0.5, 0.3, 0.2)  # kecepatan naik, jumlah sumber, volume

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "radar-tren/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def kunci(t):
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()

# ---- Pengambil data. Tiap fungsi mengembalikan [(kategori, judul, nilai, sumber)] ----
def tmdb():
    d = get(f"https://api.themoviedb.org/3/trending/movie/day?api_key={os.environ['TMDB_KEY']}")
    return [("film", m["title"], m.get("popularity", 0), "TMDB") for m in d["results"][:20]]

def lastfm():
    d = get("https://ws.audioscrobbler.com/2.0/?method=geo.gettoptracks&country=indonesia"
            f"&limit=20&format=json&api_key={os.environ['LASTFM_KEY']}")
    return [("musik", t["name"], int(t["listeners"]), "Last.fm") for t in d["tracks"]["track"]]

def youtube():
    d = get("https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&chart=mostPopular"
            f"&regionCode=ID&videoCategoryId=10&maxResults=20&key={os.environ['YT_KEY']}")
    return [("musik", v["snippet"]["title"], int(v["statistics"].get("viewCount", 0)), "YouTube")
            for v in d["items"]]

def yt_viral():
    """Komedi, hiburan, dan chart umum YouTube Indonesia. Video yang ada di chart kategori DAN chart umum dihitung lintas sumber."""
    k = os.environ["YT_KEY"]; rows = []
    base = ("https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&chart=mostPopular"
            f"&regionCode=ID&maxResults=25&key={k}")
    for cat, label in (("23", "YouTube Komedi"), ("24", "YouTube Hiburan"), ("", "YouTube Populer")):
        try:
            d = get(base + (f"&videoCategoryId={cat}" if cat else ""))
        except Exception as e:
            print(f"[lewati] {label}: {e!r}"); continue
        for v in d.get("items", []):
            if not cat and v["snippet"].get("categoryId") == "10":
                continue  # video musik sudah punya kategori sendiri
            rows.append(("viral", v["snippet"]["title"], int(v["statistics"].get("viewCount", 0)), label))
    return rows

def gdelt():
    """Artikel berita Indonesia 24 jam terakhir, dikelompokkan per topik. Sumber = nama media."""
    q = urllib.parse.quote("(politik OR DPR OR presiden OR pemerintah) sourcecountry:ID")
    arts = get("https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&maxrecords=100"
               f"&format=json&timespan=24h&query={q}").get("articles", [])
    klaster = []  # [(kata_judul, judul, [domain])]
    for a in arts:
        kata = set(kunci(a["title"]).split())
        for k in klaster:
            if len(kata & k[0]) / max(len(kata | k[0]), 1) >= 0.4:
                k[2].append(a["domain"]); break
        else:
            klaster.append((kata, a["title"], [a["domain"]]))
    return [("politik", j, 1, dom) for _, j, doms in klaster if len(doms) > 1 for dom in set(doms)]

# ---- Data simulasi (tanpa API). Pola 7 hari, hari ini di ujung kanan ----
DEMO = [
 ("musik", "Lagu contoh A", [40,42,45,50,70,110,180], ["Last.fm","YouTube","Spotify"]),
 ("musik", "Remix contoh D", [5,6,5,8,30,80,150], ["YouTube"]),
 ("musik", "Penyanyi contoh E", [90,88,92,95,91,94,97], ["Last.fm","YouTube"]),
 ("film", "Film contoh F", [50,55,70,95,120,170,230], ["TMDB","YouTube","Reddit"]),
 ("film", "Rumor sekuel contoh I", [10,12,11,14,20,45,90], ["Reddit"]),
 ("viral", "Video komedi contoh P", [30,28,35,40,90,160,240], ["YouTube Komedi","YouTube Populer"]),
 ("viral", "Sketsa contoh Q", [12,10,15,14,18,60,130], ["YouTube Hiburan"]),
 ("politik", "Rancangan kebijakan contoh K", [30,35,40,60,100,160,210], [f"media{i}.id" for i in range(9)]),
 ("politik", "Isu contoh M beredar", [4,5,4,6,9,40,120], ["media1.id"]),
]
def demo():
    hari_ini = [(k, j, v[6], s) for k, j, v, ss in DEMO for s in ss]
    riwayat = [{kunci(j): {x: v[i] for x in ss} for k, j, v, ss in DEMO} for i in range(6)]
    return hari_ini, riwayat

# ---- Penggabungan dan skor ----
def gabung(rows):
    maks = {}
    for k, j, n, s in rows:
        maks[(k, s)] = max(maks.get((k, s), 0), n) or 1
    item = {}
    for k, j, n, s in rows:
        kk = kunci(j)
        cocok = next((x for x, e in item.items() if e["kat"] == k and min(len(x), len(kk)) >= 4
                      and (x in kk or kk in x)), kk)
        e = item.setdefault(cocok, {"judul": j, "kat": k, "nilai": 0.0, "sumber": set(), "mentah": {}})
        e["nilai"] += n / maks[(k, s)]  # tiap sumber dinormalkan dulu agar satuannya setara
        e["sumber"].add(s)
        e["mentah"][s] = e["mentah"].get(s, 0) + n  # angka asli per sumber, untuk riwayat
    return item

def hitung(item, riwayat):
    maks = {}
    for e in item.values():
        maks[e["kat"]] = max(maks.get(e["kat"], 0), e["nilai"])
    hasil = []
    for kk, e in item.items():
        # kecepatan naik: rata-rata rasio (hari ini / rata-rata hari lalu) per sumber, dari angka asli
        rasio = []
        for src, n in e["mentah"].items():
            lalu = [h[kk][src] for h in riwayat if src in h.get(kk, {})]
            if len(lalu) >= 3 and sum(lalu): rasio.append(n / (sum(lalu) / len(lalu)) - 1)
        vel = sum(rasio) / len(rasio) if rasio else None
        cap = {"politik": 10, "viral": 3}.get(e["kat"], 5)
        ns, nl = min(len(e["sumber"]) / cap, 1), e["nilai"] / maks[e["kat"]]
        if vel is None:   # riwayat belum cukup: bobot kecepatan dibagi ke dua ukuran lain
            w = (0, BOBOT[1] / (BOBOT[1] + BOBOT[2]), BOBOT[2] / (BOBOT[1] + BOBOT[2])); nv = 0
        else:
            w, nv = BOBOT, min(max(vel, 0) / 3, 1)
        n = len(e["sumber"])
        hasil.append({"judul": e["judul"], "kategori": e["kat"],
                      "skor": round((nv * w[0] + ns * w[1] + nl * w[2]) * 100),
                      "kecepatan": None if vel is None else round(vel, 2),
                      "k_kecepatan": round(nv, 3), "k_sumber": round(ns, 3), "k_volume": round(nl, 3),
                      "ada_riwayat": vel is not None,
                      "jumlah_sumber": n, "sumber": sorted(e["sumber"])[:8],
                      "status": "lintas sumber" if n >= 3 else "dua sumber" if n == 2 else "belum terverifikasi"})
    return sorted(hasil, key=lambda x: -x["skor"])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tanggal", default=date.today().isoformat())
    p.add_argument("--demo", action="store_true")
    a = p.parse_args()
    rf = DATA / "riwayat.json"
    riwayat_all = json.loads(rf.read_text()) if rf.exists() else {}
    if a.demo:
        rows, riwayat = demo()
    else:
        rows = []
        for f in (tmdb, lastfm, youtube, yt_viral, gdelt):
            try:
                r = f(); rows += r; print(f"[ok] {f.__name__}: {len(r)} baris")
            except Exception as e:
                print(f"[lewati] {f.__name__}: {e!r}")
        tgl = sorted(t for t in riwayat_all if t < a.tanggal)[-6:]
        riwayat = [riwayat_all[t] for t in tgl]
    item = gabung(rows)
    hasil = hitung(item, riwayat)
    (DATA / "data.json").write_text(json.dumps(
        {"tanggal": a.tanggal, "simulasi": a.demo, "item": hasil}, ensure_ascii=False, indent=1))
    if not a.demo:
        riwayat_all[a.tanggal] = {k: e["mentah"] for k, e in item.items()}
        for t in sorted(riwayat_all)[:-14]: riwayat_all.pop(t)
        rf.write_text(json.dumps(riwayat_all))
    print(f"{a.tanggal}: {len(hasil)} topik -> data/data.json")

if __name__ == "__main__":
    main()
