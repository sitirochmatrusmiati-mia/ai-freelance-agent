"""
Scout Agent - RemoteOK
=======================
Mengambil listing pekerjaan dari API publik resmi RemoteOK (remoteok.com/api)
dan menormalisasinya jadi "task object" yang siap dilempar ke evaluator agent.

Catatan penting (wajib dibaca):
- RemoteOK API bersifat publik & gratis, TIDAK butuh API key.
- ToS RemoteOK mewajibkan setiap penggunaan data ini mencantumkan link balik
  ke sumber aslinya (field `url` di tiap task sudah otomatis mengarah ke sana).
- RemoteOK butuh header User-Agent yang wajar, kalau tidak sering kena 403.
- Endpoint ini adalah snapshot ~100-400 listing terbaru, tidak ada pagination
  ke listing lama.

Cara pakai cepat:
    python scout_remoteok.py --tag python
    python scout_remoteok.py                 # ambil semua tag
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REMOTEOK_API_URL = "https://remoteok.com/api"
TASK_POOL_FILE = Path(__file__).parent / "task_pool.json"

# RemoteOK akan menolak request tanpa User-Agent yang wajar
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ScoutAgent/0.1; "
        "personal-freelance-automation-project)"
    ),
    "Accept": "application/json",
}


def is_remote_job(job: dict) -> bool:
    """Cek apakah job ini beneran remote, bukan lowongan on-site.

    Pengamatan dari data asli: job remote sungguhan punya field `location`
    kosong atau berisi kata "remote". Job on-site (hotel, toko, pabrik, dst)
    selalu punya nama kota/negara di field ini, mis. "San Juan, " atau
    "Ipojuca, ". Ini jauh lebih akurat daripada menebak dari kata kunci judul.
    """
    location = (job.get("location") or "").strip().lower()
    return location == "" or "remote" in location


def fetch_remoteok_jobs(tag: str | None = None, remote_only: bool = True) -> list[dict]:
    """Ambil daftar job mentah dari RemoteOK API.

    RemoteOK tidak menyediakan query param filter di endpoint resmi,
    jadi kita ambil semua lalu filter tag & lokasi secara lokal.
    """
    req = urllib.request.Request(REMOTEOK_API_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[scout] HTTP error {e.code} saat fetch RemoteOK: {e.reason}", file=sys.stderr)
        return []
    except urllib.error.URLError as e:
        print(f"[scout] Gagal konek ke RemoteOK: {e.reason}", file=sys.stderr)
        return []

    # Elemen pertama biasanya metadata legal, bukan job asli -> skip
    jobs = [item for item in raw if isinstance(item, dict) and item.get("id")]

    total_before = len(jobs)

    if remote_only:
        jobs = [j for j in jobs if is_remote_job(j)]
        print(f"[scout] Filter lokasi: {total_before} -> {len(jobs)} job remote asli.")

    if tag:
        tag_lower = tag.lower()
        jobs = [j for j in jobs if tag_lower in [t.lower() for t in j.get("tags", [])]]

    return jobs


def normalize_task(job: dict) -> dict:
    """Ubah job mentah RemoteOK jadi task object standar antar-agent.

    Skema ini yang nanti dipakai evaluator agent, orchestrator, dst -
    supaya semua scout agent (dari sumber manapun) punya bentuk output sama.
    """
    return {
        "task_id": f"remoteok-{job.get('id')}",
        "source": "remoteok",
        "source_url": job.get("url"),  # wajib ada untuk attribution ToS
        "title": job.get("position") or job.get("title"),
        "company": job.get("company"),
        "tags": job.get("tags", []),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "location": job.get("location") or "remote",
        "description_snippet": (job.get("description") or "")[:280],
        "posted_at": job.get("date"),
        "fetched_at": int(time.time()),
        "status": "new",  # new -> evaluated -> in_auction -> assigned -> done
    }


def save_task_pool(tasks: list[dict]) -> None:
    """Simpan ke file JSON lokal sebagai pengganti DB sementara.

    Nanti tinggal ganti fungsi ini supaya nulis ke Postgres/SQLite
    tanpa mengubah bagian fetch & normalize di atas.
    """
    existing = []
    if TASK_POOL_FILE.exists():
        existing = json.loads(TASK_POOL_FILE.read_text())

    existing_ids = {t["task_id"] for t in existing}
    new_tasks = [t for t in tasks if t["task_id"] not in existing_ids]

    combined = existing + new_tasks
    TASK_POOL_FILE.write_text(json.dumps(combined, indent=2, ensure_ascii=False))

    print(f"[scout] {len(new_tasks)} task baru ditambahkan, total {len(combined)} di task pool.")


def main():
    parser = argparse.ArgumentParser(description="Scout agent untuk RemoteOK")
    parser.add_argument("--tag", help="Filter berdasarkan tag, mis. 'python'", default=None)
    parser.add_argument(
        "--include-onsite",
        action="store_true",
        help="Matikan filter remote-only, ambil semua job termasuk yang on-site",
    )
    args = parser.parse_args()

    print(f"[scout] Mengambil listing dari RemoteOK (tag={args.tag or 'semua'})...")
    raw_jobs = fetch_remoteok_jobs(tag=args.tag, remote_only=not args.include_onsite)
    print(f"[scout] Ditemukan {len(raw_jobs)} listing mentah.")

    tasks = [normalize_task(j) for j in raw_jobs]
    save_task_pool(tasks)


if __name__ == "__main__":
    main()
