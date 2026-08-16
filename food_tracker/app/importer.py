import json

# Conservative transcription: only explicit "eating/having" statements with a time and
# nutrition recoverable from the rules. Other source messages remain review records.
RELIABLE=[("chat-2026-08-10-1939","2026-08-10T19:39",[(10,1),(2,1),(7,1)]),
          ("chat-2026-08-10-0000","2026-08-11T00:00",[(12,3),(14,1),(13,1),(15,1),(16,1)])]
UNCERTAIN=["Source images are unavailable offline for several explicitly eaten meals; exact products cannot be verified.","Some older daily totals conflict with later salt corrections.","Proposed 3 August meal and untimed Saturday drinks were not imported."]
def run_import(d, save_meal):
    imported=skipped=0
    for key,dt,items in RELIABLE:
        if d.execute("SELECT 1 FROM meals WHERE import_key=?",(key,)).fetchone(): skipped+=1; continue
        mid=save_meal(d,{"mode":"confirmed","eaten_at":dt,"items":[{"food_id":x,"multiplier":m} for x,m in items]})
        d.execute("UPDATE meals SET import_key=? WHERE id=?",(key,mid)); imported+=1
    for i,msg in enumerate(UNCERTAIN): d.execute("INSERT OR IGNORE INTO meals(eaten_at,food_day,note,status,import_key) VALUES('2026-08-01T00:00','2026-07-31',?,'review',?)",(msg,"review:"+str(i)))
    report={"imported":imported,"skipped":skipped,"corrected":0,"uncertain":len(UNCERTAIN)}
    d.execute("INSERT INTO import_runs(report) VALUES(?)",(json.dumps(report),)); d.commit(); return report
