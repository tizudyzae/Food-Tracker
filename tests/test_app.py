import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from food_tracker.app.core import connect, food_day, save_meal, settings, totals
from food_tracker.app.importer import run_import
from food_tracker.app.reminders import process_reminders
from food_tracker.app.web import create_app

@pytest.fixture
def app(tmp_path): return create_app({"TESTING":True,"DATABASE":str(tmp_path/"test.db")})
@pytest.fixture
def db(app):
    d=connect(app.config["DATABASE"]); yield d; d.close()
def payload(at="2026-08-11T00:30",mode="confirmed",override=None): return {"mode":mode,"eaten_at":at,"food_day":override,"items":[{"food_id":1,"multiplier":1}]}
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
