import json, sqlite3
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

NUTRIENTS = ("calories", "protein", "carbs", "sugars", "fat", "saturates", "fibre", "salt")
DEFAULTS = {"calorie_min":2000,"calorie_max":2200,"protein_min":150,"protein_max":170,"rollover":"04:00","timezone":"Europe/London","meal_times":["14:15","19:45","00:00"],"reminders":False,"weigh_reminder":False,"weigh_day":"Monday","weigh_time":"09:00","budget_reminder":False,"notification_service":"notify.notify","quiet_start":"22:00","quiet_end":"08:00","salt_warn":6,"fibre_low":20,"meal_calorie_warn":900,"meal_fat_warn":35}

def connect(path):
    db=sqlite3.connect(path, timeout=10); db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON"); db.execute("PRAGMA journal_mode=WAL")
    return db

def migrate(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as d:
        d.executescript('''CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS foods(id INTEGER PRIMARY KEY, name TEXT NOT NULL, basis TEXT NOT NULL DEFAULT 'serving', amount REAL NOT NULL DEFAULT 1, unit TEXT NOT NULL DEFAULT 'serving', calories REAL, protein REAL, carbs REAL, sugars REAL, fat REAL, saturates REAL, fibre REAL, salt REAL, source TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS meals(id INTEGER PRIMARY KEY, eaten_at TEXT NOT NULL, food_day TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL CHECK(status IN ('confirmed','review')), import_key TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS meal_items(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE, food_id INTEGER REFERENCES foods(id), name TEXT NOT NULL, multiplier REAL NOT NULL, calories REAL, protein REAL, carbs REAL, sugars REAL, fat REAL, saturates REAL, fibre REAL, salt REAL);
        CREATE TABLE IF NOT EXISTS weights(id INTEGER PRIMARY KEY, measured_at TEXT NOT NULL, kg REAL NOT NULL CHECK(kg>0), source_key TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS notifications(window_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS import_runs(id INTEGER PRIMARY KEY, run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, report TEXT NOT NULL);''')
        d.execute("INSERT OR IGNORE INTO settings(id,json) VALUES(1,?)",(json.dumps(DEFAULTS),)); d.execute("INSERT OR IGNORE INTO migrations VALUES(1)")
        seed(d)

def seed(d):
    foods=[
    ("Banana, medium","serving",1,"banana",105,1.3,27,None,.3,None,3,0,"Project Rules.txt; standard estimate"),
    ("Co-op Lime & Chilli Chicken Protein Chunks","serving",60,"g",81,16,2.4,None,.9,None,None,None,"Project Rules.txt; verified"),
    ("Co-op Tikka Chicken Chunks","serving",80,"g",103,20,None,None,None,None,None,None,"Project Rules.txt; verified"),
    ("Co-op Flame Grilled Chicken Mini Fillets","serving",130,"g pack",154,36,None,None,None,None,None,None,"Project Rules.txt; verified"),
    ("Co-op Protein Jalapeño BBQ Popped Chips","serving",25,"g",102,6.7,13,None,2.6,None,1,.26,"Project Rules.txt; verified"),
    ("Itsu Thai Sweet Chilli Prawn Crackers","serving",19,"g",97,.5,12,None,5.2,None,None,None,"Project Rules.txt; protein listed as <0.5g"),
    ("Huel Black RTD Strawberry Banana","serving",500,"ml",400,35,None,None,None,None,7,None,"Project Rules.txt; partial label"),
    ("Huel Banana RTD","serving",500,"ml",400,20,None,None,None,None,None,None,"Project Rules.txt; verified"),
    ("UFIT Strawberry Protein Shake","serving",330,"ml",149,25,None,None,None,None,None,None,"Project Rules.txt; verified"),
    ("Optimum Nutrition High Protein Shake","serving",330,"ml",185,25,None,None,None,None,None,None,"Project Rules.txt; verified"),
    ("YFood Complete Drink","serving",500,"ml",400,35,None,None,None,None,None,None,"Project Rules.txt; verify flavour"),
    ("Chicken breast, raw","100g",100,"g",110,23,0,None,1.5,None,0,0,"Project Rules.txt; estimated range midpoint for fat"),
    ("Co-op stir-fry vegetables","serving",320,"g",86,4,None,None,.9,None,10,None,"Project Rules.txt; fat recorded as <1g"),
    ("Ben's Egg Fried Rice","serving",220,"g pouch",345,9,None,None,None,None,None,None,"Project Rules.txt; estimated"),
    ("Wagamama Firecracker Sauce","serving",120,"g pouch",106,2.4,None,None,None,None,None,4.28,"Project Rules.txt; verified"),
    ("Salt & Pepper Chicken Spring Rolls","serving",100,"g pack",307,8.2,27,None,18,None,3.6,.49,"Project Rules.txt; verified")]
    for x in foods: d.execute("INSERT INTO foods(name,basis,amount,unit,calories,protein,carbs,sugars,fat,saturates,fibre,salt,source) SELECT ?,?,?,?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM foods WHERE name=?)",x+(x[0],))
    weights=[("2026-07-29T23:14",126.4),("2026-07-12T08:52",124.2),("2026-07-12T08:51",124.2),("2026-02-24T11:14",108.6),("2025-12-17T12:33",101.8),("2025-11-30T15:44",101.9),("2025-11-25T13:00",103.4),("2025-11-18T10:48",104.6),("2025-11-10T12:40",105.6),("2025-11-03T11:30",106.7)]
    for dt,kg in weights: d.execute("INSERT OR IGNORE INTO weights(measured_at,kg,source_key) VALUES(?,?,?)",(dt,kg,"seed:"+dt))

def settings(d):
    return {**DEFAULTS, **json.loads(d.execute("SELECT json FROM settings WHERE id=1").fetchone()[0])}
def food_day(eaten_at, cfg, override=None):
    if override: return override
    dt=datetime.fromisoformat(eaten_at); h,m=map(int,cfg["rollover"].split(":"))
    return (dt.date()-timedelta(days=1) if dt.time()<time(h,m) else dt.date()).isoformat()
def save_meal(d, payload, meal_id=None):
    if payload.get("mode") != "confirmed": raise ValueError("Planning results are not saved. Choose Save as eaten.")
    if not payload.get("eaten_at"): raise ValueError("Eating date and time are required.")
    items=payload.get("items") or []
    if not items: raise ValueError("Add at least one food.")
    day=food_day(payload["eaten_at"],settings(d),payload.get("food_day"))
    with d:
        if meal_id:
            d.execute("UPDATE meals SET eaten_at=?,food_day=?,note=? WHERE id=?",(payload["eaten_at"],day,payload.get("note",""),meal_id)); d.execute("DELETE FROM meal_items WHERE meal_id=?",(meal_id,))
            mid=meal_id
        else: mid=d.execute("INSERT INTO meals(eaten_at,food_day,note,status) VALUES(?,?,?,'confirmed')",(payload["eaten_at"],day,payload.get("note","") )).lastrowid
        for i in items:
            f=d.execute("SELECT * FROM foods WHERE id=?",(int(i["food_id"]),)).fetchone(); mult=float(i.get("multiplier",1));
            if not f or mult<=0: raise ValueError("Food and positive serving/weight are required.")
            vals=[None if f[n] is None else f[n]*mult for n in NUTRIENTS]
            d.execute("INSERT INTO meal_items(meal_id,food_id,name,multiplier,"+','.join(NUTRIENTS)+") VALUES("+','.join(['?']*12)+")",(mid,f['id'],f['name'],mult,*vals))
    return mid
def totals(d, day):
    rows=d.execute("SELECT i.* FROM meal_items i JOIN meals m ON m.id=i.meal_id WHERE m.food_day=? AND m.status='confirmed'",(day,)).fetchall()
    return {n:sum(r[n] or 0 for r in rows) for n in NUTRIENTS}|{"incomplete":{n:any(r[n] is None for r in rows) for n in NUTRIENTS},"items":len(rows)}
