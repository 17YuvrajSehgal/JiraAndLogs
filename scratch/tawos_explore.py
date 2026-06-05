"""One-shot TAWOS exploration. Produces a compact report that helps us
understand what real Jira issues look like (especially their inclusion of
stack traces / log lines / pager-speak comments) so we can redesign the
synthetic humanizer to mimic real distributions.

Read-only. Does not modify TAWOS or our project data.
"""
from __future__ import annotations

import json
import re
import textwrap
import pymysql
import pymysql.cursors

CONN = dict(host="127.0.0.1", user="root", password="root",
            database="tawos", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor)

def q(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()

def section(title):
    bar = "=" * 72
    # ASCII only (Windows console code page chokes on em-dash)
    print(f"\n{bar}\n{title}\n{bar}")

def safe(s):
    if s is None:
        return ""
    return s.encode("ascii", "replace").decode("ascii")

def main():
    with pymysql.connect(**CONN) as conn:
        with conn.cursor() as cur:
            # -- 1. Row counts ---------------------------------------------
            section("1. ROW COUNTS")
            for t in ("issue", "comment", "project", "change_log",
                      "issue_link", "user", "component", "sprint"):
                n = q(cur, f"SELECT COUNT(*) AS c FROM `{t}`")[0]["c"]
                print(f"  {t:18s} {n:>10,}")

            # -- 2. Schemas -------------------------------------------------
            section("2. SCHEMAS — issue, comment")
            for t in ("issue", "comment"):
                print(f"\n-- {t} --")
                rows = q(cur, f"DESCRIBE `{t}`")
                for r in rows:
                    print(f"  {r['Field']:30s} {r['Type']}")

            # -- 3. Projects (top by ticket count) --------------------------
            section("3. TOP 15 PROJECTS BY TICKET COUNT")
            rows = q(cur, """
                SELECT p.Name, p.Project_Key AS proj_key, COUNT(i.ID) AS n
                FROM project p JOIN issue i ON i.Project_ID = p.ID
                GROUP BY p.ID ORDER BY n DESC LIMIT 15
            """)
            for r in rows:
                pk = r['proj_key'] or "?"
                nm = (r['Name'] or "")[:35]
                print(f"  {pk:8s} {nm:35s} {r['n']:>8,}")

            # -- 4. Description length distribution -------------------------
            section("4. DESCRIPTION LENGTH DISTRIBUTION (chars)")
            rows = q(cur, """
                SELECT
                  COUNT(*) AS n,
                  ROUND(AVG(CHAR_LENGTH(Description))) AS mean,
                  MIN(CHAR_LENGTH(Description)) AS minlen,
                  MAX(CHAR_LENGTH(Description)) AS maxlen
                FROM issue WHERE Description IS NOT NULL AND Description <> ''
            """)
            print(f"  {rows[0]}")
            rows = q(cur, """
                SELECT FLOOR(CHAR_LENGTH(Description) / 500) * 500 AS bucket,
                       COUNT(*) AS n
                FROM issue
                WHERE Description IS NOT NULL AND CHAR_LENGTH(Description) > 0
                GROUP BY bucket
                ORDER BY bucket LIMIT 12
            """)
            for r in rows:
                print(f"  [{int(r['bucket']):>5d}, {int(r['bucket'])+500:>5d})  {r['n']:>8,}")

            # -- 5. Comments per issue distribution -------------------------
            section("5. COMMENTS PER ISSUE (subset of issues with >=1 comment)")
            rows = q(cur, """
                SELECT
                  AVG(c) AS avg, MAX(c) AS max,
                  SUM(CASE WHEN c=1 THEN 1 ELSE 0 END) AS n_1,
                  SUM(CASE WHEN c BETWEEN 2 AND 5 THEN 1 ELSE 0 END) AS n_2_5,
                  SUM(CASE WHEN c BETWEEN 6 AND 15 THEN 1 ELSE 0 END) AS n_6_15,
                  SUM(CASE WHEN c > 15 THEN 1 ELSE 0 END) AS n_15_plus
                FROM (
                  SELECT Issue_ID, COUNT(*) AS c FROM comment GROUP BY Issue_ID
                ) t
            """)
            print(f"  {rows[0]}")

            # -- 6. Sample tickets WITH non-empty Description_Code (where
            #       stack traces / log lines actually live in TAWOS)
            section("6. SAMPLE TICKETS WITH PASTED LOG / STACK CONTENT (Description_Code)")
            rows = q(cur, """
                SELECT i.ID, i.Title, i.Description_Text, i.Description_Code,
                       p.Project_Key AS proj_key
                FROM issue i JOIN project p ON p.ID = i.Project_ID
                WHERE i.Description_Code IS NOT NULL
                  AND CHAR_LENGTH(i.Description_Code) BETWEEN 80 AND 1500
                  AND i.Type IN ('Bug','Defect')
                ORDER BY RAND() LIMIT 5
            """)
            for r in rows:
                print(f"\n--- {r['proj_key']}-{r['ID']}: {safe((r['Title'] or ''))[:80]} ---")
                print("  [Description_Text]")
                print(textwrap.indent(safe((r['Description_Text'] or ''))[:600], "    "))
                print("  [Description_Code]")
                print(textwrap.indent(safe((r['Description_Code'] or ''))[:1000], "    "))

            # -- 7. Sample 5 comment threads on rich tickets -----------------
            section("7. SAMPLE COMMENT THREADS (engineer voice)")
            rows = q(cur, """
                SELECT Issue_ID, COUNT(*) c
                FROM comment
                GROUP BY Issue_ID
                HAVING c BETWEEN 4 AND 10
                ORDER BY RAND() LIMIT 3
            """)
            for r in rows:
                iid = r["Issue_ID"]
                head = q(cur, "SELECT Title FROM issue WHERE ID=%s", (iid,))
                title = head[0]["Title"] if head else "(none)"
                print(f"\n--- issue {iid}: {title[:80]} ---")
                comments = q(cur, """
                    SELECT Comment_Text, Comment, Creation_Date AS Created_Date
                    FROM comment
                    WHERE Issue_ID=%s ORDER BY Creation_Date LIMIT 8
                """, (iid,))
                for c in comments:
                    body = safe(c.get('Body') or c.get('Comment_Text') or c.get('Comment') or "")
                    body = body[:400].replace("\r\n", "\n").strip()
                    print(f"  [{c['Created_Date']}]")
                    print(textwrap.indent(body, "    "))

            # -- 8. Resolution sample ---------------------------------------
            section("8. RESOLUTION / STATUS DISTRIBUTION")
            rows = q(cur, """
                SELECT Resolution, COUNT(*) AS n FROM issue
                WHERE Resolution IS NOT NULL
                GROUP BY Resolution ORDER BY n DESC LIMIT 10
            """)
            for r in rows:
                print(f"  {r['Resolution']:20s} {r['n']:>8,}")

if __name__ == "__main__":
    main()
