"""Read-only reconnaissance of the COPIED database: schema + real ids for path substitution."""
import json
import sqlite3
import sys

DB = r"_audit\probe_data\machining_dfm\machining_dfm.sqlite3"


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = {}
    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' order by name")]
    out["tables"] = tables
    print("=== TABLES ===")
    for t in tables:
        cols = [c[1] for c in con.execute(f'pragma table_info("{t}")')]
        try:
            n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
        except Exception as exc:  # pragma: no cover
            n = f"ERR {exc}"
        print(f"{t:38s} n={n:<6} cols={cols}")
        out.setdefault("schema", {})[t] = cols

    print("\n=== SAMPLE DATA (ids) ===")
    queries = {
        "projects": "select id,name from projects limit 12",
        "project_processes": "select id,project_id,name from project_processes limit 12",
        "project_process_tools": "select id,process_id,tool_id from project_process_tools limit 12",
        "project_issues": "select id,project_id from project_issues limit 12",
        "project_selections": "select project_id,kind,slot from project_selections limit 20",
        "project_history": "select id,project_id from project_history limit 12",
        "assets": "select id from assets limit 12",
        "machines": "select id,name from machines limit 8",
        "tools": "select id,name from tools limit 8",
        "fixtures": "select * from fixtures limit 6",
        "gauges": "select * from gauges limit 6",
        "tool_groups": "select code from tool_groups limit 12",
        "tool_categories": "select code from tool_categories limit 12",
        "fixture_centers": "select * from fixture_centers limit 8",
        "gauge_categories": "select * from gauge_categories limit 8",
    }
    for label, q in queries.items():
        try:
            rows = [dict(r) for r in con.execute(q)]
        except Exception as exc:
            rows = f"ERR {exc}"
        out.setdefault("samples", {})[label] = rows
        print(f"-- {label}: {json.dumps(rows, ensure_ascii=False)[:900]}")
    con.close()
    with open(r"_audit\probe_ids.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("\nwrote _audit/probe_ids.json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
