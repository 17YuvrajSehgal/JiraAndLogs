"""Second pass: characteristic patterns we'll mimic in the redesigned humanizer."""
from __future__ import annotations
import textwrap, re
import pymysql, pymysql.cursors

CONN = dict(host="127.0.0.1", user="root", password="root",
            database="tawos", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor)

def q(cur, sql, args=()):
    cur.execute(sql, args); return cur.fetchall()

def section(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")

def safe(s):
    return (s or "").replace("—","-").replace("–","-")

def main():
    with pymysql.connect(**CONN) as conn:
        with conn.cursor() as cur:
            # -- A. % of Bug-typed issues with pasted code blocks ----------
            section("A. WHAT % OF BUGS HAVE A PASTED CODE/LOG BLOCK?")
            rows = q(cur, """
                SELECT
                  COUNT(*) AS total_bugs,
                  SUM(CASE WHEN Description_Code IS NOT NULL
                            AND CHAR_LENGTH(Description_Code) > 30
                       THEN 1 ELSE 0 END) AS with_code,
                  SUM(CASE WHEN Description_Code IS NOT NULL
                            AND CHAR_LENGTH(Description_Code) > 200
                       THEN 1 ELSE 0 END) AS with_substantial_code
                FROM issue
                WHERE Type IN ('Bug','Defect')
            """)
            r = rows[0]
            tot = int(r['total_bugs'])
            wc = int(r['with_code']); ws = int(r['with_substantial_code'])
            print(f"  total bugs:            {tot:>10,}")
            print(f"  with any code block:   {wc:>10,}  ({100*wc/tot:.1f}%)")
            print(f"  with >200 char block:  {ws:>10,}  ({100*ws/tot:.1f}%)")

            # -- B. Median-length bug descriptions (short, real-world voice)
            section("B. WHAT A MEDIAN-LENGTH (200-500 char) BUG REPORT LOOKS LIKE")
            rows = q(cur, """
                SELECT i.Title, i.Description_Text, i.Priority,
                       p.Project_Key AS pk
                FROM issue i JOIN project p ON p.ID = i.Project_ID
                WHERE i.Type IN ('Bug','Defect')
                  AND i.Description_Text IS NOT NULL
                  AND CHAR_LENGTH(i.Description_Text) BETWEEN 200 AND 500
                  AND p.Project_Key IN ('SERVER','MESOS','FAB','MULE','TIMOB')
                ORDER BY RAND() LIMIT 5
            """)
            for r in rows:
                print(f"\n--- [{r['pk']}] [{r['Priority']}] {safe(r['Title'])[:80]} ---")
                print(textwrap.indent(safe(r['Description_Text'])[:600], "  "))

            # -- C. Resolution time distribution for "Fixed" bugs ----------
            section("C. RESOLUTION TIME (HOURS) FOR FIXED BUGS")
            rows = q(cur, """
                SELECT
                  COUNT(*) AS n,
                  MIN(Resolution_Time_Minutes)/60 AS min_h,
                  ROUND(AVG(Resolution_Time_Minutes)/60, 1) AS avg_h
                FROM issue
                WHERE Resolution='Fixed' AND Resolution_Time_Minutes > 0
                  AND Type IN ('Bug','Defect')
            """)
            print(f"  {rows[0]}")
            rows = q(cur, """
                SELECT
                  SUM(CASE WHEN Resolution_Time_Minutes < 60 THEN 1 ELSE 0 END) AS lt_1h,
                  SUM(CASE WHEN Resolution_Time_Minutes BETWEEN 60 AND 1440 THEN 1 ELSE 0 END) AS lt_1d,
                  SUM(CASE WHEN Resolution_Time_Minutes BETWEEN 1440 AND 10080 THEN 1 ELSE 0 END) AS lt_1wk,
                  SUM(CASE WHEN Resolution_Time_Minutes BETWEEN 10080 AND 43200 THEN 1 ELSE 0 END) AS lt_1mo,
                  SUM(CASE WHEN Resolution_Time_Minutes >= 43200 THEN 1 ELSE 0 END) AS gt_1mo
                FROM issue
                WHERE Resolution='Fixed' AND Resolution_Time_Minutes > 0
                  AND Type IN ('Bug','Defect')
            """)
            r = rows[0]
            print(f"  <1h:    {int(r['lt_1h']):>8,}")
            print(f"  1h-1d:  {int(r['lt_1d']):>8,}")
            print(f"  1d-1wk: {int(r['lt_1wk']):>8,}")
            print(f"  1wk-1m: {int(r['lt_1mo']):>8,}")
            print(f"  >1mo:   {int(r['gt_1mo']):>8,}")

            # -- D. Comment_Code samples — pasted logs INSIDE a comment ----
            section("D. COMMENT_CODE SAMPLES (log-paste mid-conversation)")
            rows = q(cur, """
                SELECT Issue_ID, Comment_Text, Comment_Code, Creation_Date
                FROM comment
                WHERE Comment_Code IS NOT NULL
                  AND CHAR_LENGTH(Comment_Code) BETWEEN 100 AND 1000
                ORDER BY RAND() LIMIT 4
            """)
            for r in rows:
                print(f"\n--- comment on issue {r['Issue_ID']} @ {r['Creation_Date']} ---")
                print(" [prose]")
                print(textwrap.indent(safe(r['Comment_Text'])[:300], "   "))
                print(" [pasted code/log]")
                print(textwrap.indent(safe(r['Comment_Code'])[:800], "   "))

            # -- E. Top stack-trace markers (what tokens we should generate)
            section("E. STACK-TRACE TOKEN FREQUENCY IN Description_Code (sample 10K bugs)")
            rows = q(cur, """
                SELECT Description_Code FROM issue
                WHERE Type IN ('Bug','Defect')
                  AND Description_Code IS NOT NULL
                  AND CHAR_LENGTH(Description_Code) > 100
                LIMIT 10000
            """)
            markers = ['Exception', 'Error', 'Caused by:', '\tat ', 'WARN ',
                       'ERROR', 'INFO ', 'DEBUG ', 'NullPointerException',
                       'Traceback', 'at line', 'java.', 'org.', 'com.',
                       'StackTrace', 'panic:', 'fatal ', 'segfault',
                       'OutOfMemory', 'Timeout', 'Refused', 'Reset by peer']
            counts = {m: 0 for m in markers}
            for r in rows:
                code = r['Description_Code'] or ""
                for m in markers:
                    if m in code:
                        counts[m] += 1
            for m, c in sorted(counts.items(), key=lambda kv: -kv[1]):
                if c > 0:
                    print(f"  {m:25s} {c:>6,} / 10,000  ({c/100:.1f}%)")

            # -- F. Title style — terseness ---------------------------------
            section("F. SAMPLE BUG TITLES (showing terse engineer style)")
            rows = q(cur, """
                SELECT Title, p.Project_Key AS pk FROM issue i
                JOIN project p ON p.ID = i.Project_ID
                WHERE i.Type IN ('Bug','Defect')
                  AND CHAR_LENGTH(i.Title) BETWEEN 25 AND 110
                  AND p.Project_Key IN ('SERVER','MESOS','FAB','MULE')
                ORDER BY RAND() LIMIT 12
            """)
            for r in rows:
                print(f"  [{r['pk']:7s}] {safe(r['Title'])}")

if __name__ == "__main__":
    main()
