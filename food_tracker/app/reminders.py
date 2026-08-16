import json, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from .core import settings

def process_reminders(d, now=None, sender=None):
    cfg=settings(d)
    if not cfg["reminders"]: return []
    now=now or datetime.now(ZoneInfo(cfg["timezone"])); hhmm=now.strftime("%H:%M")
    if _quiet(hhmm,cfg["quiet_start"],cfg["quiet_end"]): return []
    due=[]
    for index,at in enumerate(cfg["meal_times"]):
        if hhmm==at:
            message="Your usual meal window is here. Log only after eating."
            if cfg["budget_reminder"] and index==len(cfg["meal_times"])-1:
                from .core import food_day, totals
                consumed=totals(d,food_day(now.isoformat(),cfg))["calories"]
                message+=f" Remaining: {max(0,cfg['calorie_min']-consumed):.0f} kcal before {cfg['calorie_min']:.0f}, {max(0,cfg['calorie_max']-consumed):.0f} before {cfg['calorie_max']:.0f}."
            due.append((f"meal:{now.date()}:{index}:{at}","Meal window",message))
    if cfg["weigh_reminder"] and now.strftime("%A")==cfg.get("weigh_day","Monday") and hhmm==cfg.get("weigh_time","09:00"):
        due.append((f"weight:{now.date()}","Weekly weigh-in","For a comparable trend: morning, after toilet, before food or drink."))
    sent=[]
    for key,title,message in due:
        if d.execute("SELECT 1 FROM notifications WHERE window_key=?",(key,)).fetchone(): continue
        (sender or ha_notify)(cfg["notification_service"],title,message)
        d.execute("INSERT INTO notifications VALUES(?,?)",(key,now.isoformat())); sent.append(key)
    d.commit(); return sent

def _quiet(now,start,end): return (start<=now<end) if start<end else (now>=start or now<end)
def ha_notify(service,title,message):
    token=__import__('os').environ.get("SUPERVISOR_TOKEN")
    if not token: raise RuntimeError("Supervisor token unavailable")
    domain,name=service.split(".",1); req=urllib.request.Request(f"http://supervisor/core/api/services/{domain}/{name}",data=json.dumps({"title":title,"message":message}).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    urllib.request.urlopen(req,timeout=10).read()
