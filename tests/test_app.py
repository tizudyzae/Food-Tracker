import json, re, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from food_tracker.app.core import connect, food_day, migrate, nutrient_totals_by_day, save_meal, settings, totals
from food_tracker.app.importer import run_import
from food_tracker.app.reminders import process_reminders
from food_tracker.app.web import create_app

@pytest.fixture
def app(tmp_path): return create_app({"TESTING":True,"DATABASE":str(tmp_path/"test.db")})
@pytest.fixture
def db(app):
    d=connect(app.config["DATABASE"]); yield d; d.close()
def payload(at="2026-08-11T00:30",mode="confirmed",override=None): return {"mode":mode,"eaten_at":at,"food_day":override,"items":[{"food_id":1,"multiplier":1}]}
def test_existing_database_gets_server_persistence_migration(tmp_path):
    path=tmp_path/"old.db"; d=sqlite3.connect(path)
    d.execute("CREATE TABLE foods(id INTEGER PRIMARY KEY, name TEXT NOT NULL, basis TEXT NOT NULL DEFAULT 'serving', amount REAL NOT NULL DEFAULT 1, unit TEXT NOT NULL DEFAULT 'serving', calories REAL, protein REAL, carbs REAL, sugars REAL, fat REAL, saturates REAL, fibre REAL, salt REAL, source TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)")
    d.execute("INSERT INTO foods VALUES(1,'My renamed banana','serving',1,'banana',120,2,28,NULL,.4,NULL,3.2,0,'Packet checked',0)"); d.commit(); d.close()
    migrate(path)
    with connect(path) as upgraded:
        assert "seed_key" in {row[1] for row in upgraded.execute("pragma table_info(foods)")}
        row=upgraded.execute("select * from foods where id=1").fetchone()
        assert row["name"]=="My renamed banana" and row["seed_key"]=="banana-medium"
        assert upgraded.execute("select count(*) from migrations where version=2").fetchone()[0]==1
def test_proposed_meal_not_saved(db):
    with pytest.raises(ValueError): save_meal(db,payload(mode="plan"))
    assert db.execute("select count(*) from meals").fetchone()[0]==0
def test_missing_time_rejected(db):
    with pytest.raises(ValueError): save_meal(db,payload(at=""))
def test_confirmed_and_rollover(db):
    mid=save_meal(db,payload()); assert mid and db.execute("select food_day from meals").fetchone()[0]=="2026-08-10"
def test_override(db):
    save_meal(db,payload(override="2026-08-11")); assert db.execute("select food_day from meals").fetchone()[0]=="2026-08-11"
def test_correction_replaces_and_totals_all(db):
    mid=save_meal(db,payload(at="2026-08-10T14:00")); save_meal(db,payload(at="2026-08-10T15:00"),mid); save_meal(db,payload(at="2026-08-10T16:00"))
    assert db.execute("select count(*) from meals").fetchone()[0]==2
    assert totals(db,"2026-08-10")["calories"]==210
def test_unknown_marks_incomplete(db):
    save_meal(db,{"mode":"confirmed","eaten_at":"2026-08-10T14:00","items":[{"food_id":2,"multiplier":1}]})
    assert totals(db,"2026-08-10")["incomplete"]["fibre"]
def test_logged_meals_follow_current_food_database_values(db):
    save_meal(db,payload(at="2026-08-10T14:00"))
    db.execute("update foods set calories=123, protein=4 where id=1"); db.commit()
    assert totals(db,"2026-08-10")["calories"]==123
    assert totals(db,"2026-08-10")["protein"]==4
    assert nutrient_totals_by_day(db,"calories","2026-08-10","2026-08-16")["2026-08-10"]["total"]==123
def test_import_idempotent(db):
    assert run_import(db,save_meal)["imported"]==2
    assert run_import(db,save_meal)["imported"]==0
def test_reminder_once(db):
    c=settings(db); c.update(reminders=True,meal_times=["14:15"],quiet_start="22:00",quiet_end="08:00")
    db.execute("update settings set json=? where id=1",(json.dumps(c),)); db.commit(); calls=[]; now=datetime(2026,8,10,14,15,tzinfo=ZoneInfo("Europe/London"))
    assert len(process_reminders(db,now,lambda *x:calls.append(x)))==1
    assert process_reminders(db,now,lambda *x:calls.append(x))==[] and len(calls)==1
def test_london_dst_food_dates(db):
    c=settings(db)
    for stamp in ("2026-03-29T00:30","2026-10-25T00:30"):
        local=datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("Europe/London")); assert food_day(local.isoformat(),c)==(local.date()-__import__('datetime').timedelta(days=1)).isoformat()

def test_dashboard_and_meal_form_render(app):
    client=app.test_client()
    dashboard=client.get("/?day=2026-08-11")
    assert dashboard.status_code==200
    assert b"Tuesday, 11 August" in dashboard.data
    assert b"Log your first meal" in dashboard.data
    meal=client.get("/meal")
    assert meal.status_code==200 and b"Save as eaten" in meal.data

def test_nutrition_preview_keeps_complete_meal_draft(app):
    client=app.test_client()
    response=client.post("/meal",data={"mode":"plan","eaten_at":"2026-08-18T14:15","food_day":"2026-08-18","note":"Preview lunch","food_id":["1","2"],"multiplier":["2","1"]})
    assert response.status_code==200
    assert b"Your selections are still in the form below" in response.data
    assert b'value="2026-08-18T14:15"' in response.data
    assert b'value="2026-08-18"' in response.data
    assert b'value="Preview lunch"' in response.data
    assert b'value="1" selected' in response.data and b'value="2" selected' in response.data
    with connect(app.config["DATABASE"]) as d: assert d.execute("select count(*) from meals").fetchone()[0]==0

def test_food_additions_and_edits_persist_and_refresh_logged_rows(app):
    client=app.test_client()
    with connect(app.config["DATABASE"]) as d: save_meal(d,payload(at="2026-08-18T14:00"))
    edit={"name":"Banana corrected","basis":"serving","amount":"1","unit":"banana","calories":"120","protein":"2","carbs":"28","sugars":"","fat":"0.4","saturates":"","fibre":"3.2","salt":"0","source":"Packet checked"}
    response=client.post("/foods/1/edit",data=edit)
    assert response.status_code==302
    with connect(app.config["DATABASE"]) as d:
        food=d.execute("select * from foods where id=1").fetchone(); item=d.execute("select * from meal_items where food_id=1").fetchone()
        assert food["name"]=="Banana corrected" and food["calories"]==120
        assert food["seed_key"]=="banana-medium"
        assert item["name"]=="Banana corrected" and item["calories"]==120
        assert totals(d,"2026-08-18")["calories"]==120
    create_app({"TESTING":True,"DATABASE":app.config["DATABASE"]})
    with connect(app.config["DATABASE"]) as d:
        assert d.execute("select count(*) from foods where seed_key='banana-medium'").fetchone()[0]==1
        assert d.execute("select name from foods where seed_key='banana-medium'").fetchone()[0]=="Banana corrected"
    add={"name":"Server saved test food","basis":"serving","amount":"50","unit":"g","calories":"99","protein":"10","carbs":"5","sugars":"1","fat":"2","saturates":"0.5","fibre":"3","salt":"0.2","source":"Test label"}
    response=client.post("/foods",data=add)
    assert response.status_code==302
    with connect(app.config["DATABASE"]) as d: assert d.execute("select calories from foods where name=?",("Server saved test food",)).fetchone()[0]==99
    create_app({"TESTING":True,"DATABASE":app.config["DATABASE"]})
    with connect(app.config["DATABASE"]) as d: assert d.execute("select count(*) from foods where name=?",("Server saved test food",)).fetchone()[0]==1

def test_dated_nutrition_trends_render_and_are_linked(app):
    client=app.test_client()
    with connect(app.config["DATABASE"]) as d: save_meal(d,payload(at="2026-08-18T14:00"))
    trend=client.get("/trends/calories?start=2026-08-17&end=2026-08-23")
    assert trend.status_code==200
    assert b"Daily calories" in trend.data and b"2026-08-18" in trend.data and b"105.0 kcal" in trend.data
    dashboard=client.get("/?day=2026-08-18")
    assert b'href="/trends/protein"' in dashboard.data
    assert client.get("/trends/not-real").status_code==404

def test_invalid_dashboard_date_redirects(app):
    response=app.test_client().get("/?day=not-a-date")
    assert response.status_code==302 and response.headers["Location"].endswith("/")

def test_home_assistant_ingress_prefixes_links_assets_and_redirects(app):
    client=app.test_client(); headers={"X-Ingress-Path":"/api/hassio_ingress/test-token/"}
    dashboard=client.get("/",headers=headers)
    assert dashboard.status_code==200
    assert b'href="/api/hassio_ingress/test-token/static/style.css"' in dashboard.data
    assert b'href="/api/hassio_ingress/test-token/meal"' in dashboard.data
    response=client.get("/?day=not-a-date",headers=headers)
    assert response.status_code==302
    assert response.headers["Location"].endswith("/api/hassio_ingress/test-token/")

def test_every_internal_page_url_stays_inside_ingress(app):
    client=app.test_client(); prefix=b"/api/hassio_ingress/test-token"; headers={"X-Ingress-Path":prefix.decode()}
    for path in ("/","/meal","/foods","/weights","/settings","/review","/trends/protein"):
        response=client.get(path,headers=headers)
        assert response.status_code==200
        internal=[url for url in re.findall(rb'(?:href|action)="([^"]+)"',response.data) if url.startswith(b"/")]
        assert internal and all(url.startswith(prefix) for url in internal)

def test_invalid_ingress_header_is_ignored(app):
    response=app.test_client().get("/",headers={"X-Ingress-Path":"https://bad.invalid/path"})
    assert response.status_code==200
    assert b'href="/static/style.css"' in response.data

def test_health_and_main_pages_render(app):
    client=app.test_client()
    assert client.get("/health").get_json()=={"status":"ok"}
    for path in ("/foods","/weights","/settings","/review","/trends/protein"):
        response=client.get(path)
        assert response.status_code==200
        assert b"Mounjaro Coach" in response.data
