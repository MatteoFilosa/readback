import os
import threading
import time

import duckdb

from . import data


class Store:
    def __init__(self, path: str):
        if not os.path.exists(path):
            data.build(path, int(os.environ.get("COHORT_ROWS", "200000")))
        self.con = duckdb.connect(path, read_only=True)
        self._lock = threading.Lock()
        self.total = self._one("SELECT count(*) FROM patients")
        self.meta = dict(self.con.execute("SELECT key, value FROM meta").fetchall())

    def _cursor(self):
        with self._lock:
            return self.con.cursor()

    def _one(self, sql, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def run(self, where: str, params: list, sample: int = 12) -> dict:
        cur = self._cursor()
        cohort = f"SELECT * FROM patients WHERE {where}"
        t0 = time.perf_counter()
        count = cur.execute(f"SELECT count(*) FROM ({cohort})", params).fetchone()[0]
        sex = cur.execute(f"SELECT sex, count(*) FROM ({cohort}) GROUP BY 1 ORDER BY 1",
                          params).fetchall()
        ages = cur.execute(
            f"SELECT least(age // 10, 9) * 10 AS b, count(*) FROM ({cohort}) GROUP BY 1 "
            f"ORDER BY 1", params).fetchall()
        top = cur.execute(
            f"SELECT c, count(*) n FROM (SELECT unnest(conditions) c FROM ({cohort})) "
            f"GROUP BY c ORDER BY n DESC, c LIMIT 8", params).fetchall()
        regions = cur.execute(
            f"SELECT region, count(*) n FROM ({cohort}) GROUP BY 1 ORDER BY n DESC, 1 LIMIT 6",
            params).fetchall()
        cols = ["id", "age", "sex", "region", "admission_date", "length_of_stay", "triage",
                "systolic_bp", "temperature", "bmi", "smoking", "conditions"]
        rows = cur.execute(f"SELECT {', '.join(cols)} FROM ({cohort}) ORDER BY id LIMIT ?",
                           params + [sample]).fetchall()
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "count": count, "total": self.total, "ms": ms,
            "sex": dict(sex),
            "age_bins": [{"from": b, "n": n} for b, n in ages],
            "top_conditions": [{"key": c, "n": n} for c, n in top],
            "top_regions": [{"key": r, "n": n} for r, n in regions],
            "sample": [{k: (str(v) if k == "admission_date" else v) for k, v in zip(cols, r)}
                       for r in rows],
        }
