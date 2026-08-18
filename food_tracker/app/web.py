import io, json, os, re, sqlite3, threading, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from .core import NUTRIENTS, connect, food_day, meal_totals, migrate, nutrient_totals_by_day, refresh_logged_food, save_meal, settings, totals
from .importer import run_import


_SAFE_INGRESS_PATH = re.compile(r"^/[A-Za-z0-9/_-]*$")


class IngressPathMiddleware:
    """Teach Flask about the path Home Assistant places in front of the app."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        ingress_path = environ.get("HTTP_X_INGRESS_PATH", "").rstrip("/")
        if ingress_path and _SAFE_INGRESS_PATH.fullmatch(ingress_path):
            environ["SCRIPT_NAME"] = ingress_path
        return self.app(environ, start_response)

def create_app(test_config=None):
    app=Flask(__name__); app.secret_key="local-mounjaro-coach"
    app.wsgi_app=IngressPathMiddleware(app.wsgi_app)
    app.config.update(test_config or {})
    path=app.config.get("DATABASE") or os.path.join(os.getenv("DATA_DIR","/data"),"coach.db")
    migrate(path); app.config["DATABASE"]=path
    if not app.config.get("TESTING"):
        def reminder_loop():
            from .reminders import process_reminders
            while True:
                try:
                    with connect(path) as reminder_db: process_reminders(reminder_db)
                except Exception: app.logger.exception("Reminder check failed")
                time.sleep(30)
        threading.Thread(target=reminder_loop, daemon=True, name="reminders").start()
    def db(): return connect(path)
    @app.context_processor
    def common():
        with db() as d: return {"cfg":settings(d),"nutrients":NUTRIENTS}
    @app.get("/health")
    def health(): return jsonify(status="ok")
    @app.get("/")
    def dashboard():
        with db() as d:
            cfg=settings(d); today=food_day(datetime.now().isoformat(timespec="minutes"),cfg); day=request.args.get("day") or today
            try: selected=datetime.strptime(day,"%Y-%m-%d").date()
            except ValueError: return redirect(url_for("dashboard"))
            meals=d.execute("SELECT * FROM meals WHERE food_day=? AND status='confirmed' ORDER BY eaten_at",(day,)).fetchall(); review=d.execute("SELECT count(*) FROM meals WHERE status='review'").fetchone()[0]
            meal_summaries={m["id"]:meal_totals(d,m["id"]) for m in meals}
            return render_template("dashboard.html",day=day,day_label=selected.strftime("%A, %d %B"),today=today,previous=(selected-timedelta(days=1)).isoformat(),next_day=(selected+timedelta(days=1)).isoformat(),meals=meals,meal_totals=meal_summaries,total=totals(d,day),review=review)
    @app.get("/trends/<nutrient>")
    def trends(nutrient):
        if nutrient not in NUTRIENTS: abort(404)
        with db() as d:
            cfg=settings(d); today=datetime.now(ZoneInfo(cfg["timezone"])).date()
            try: start,end=selected_date_range(request.args,today)
            except ValueError as e:
                flash(str(e),"error"); return redirect(url_for("trends",nutrient=nutrient))
            grouped=nutrient_totals_by_day(d,nutrient,start.isoformat(),end.isoformat())
            series=nutrient_series(grouped,start,end); chart=nutrient_chart(series)
            span=end-start+timedelta(days=1); previous_start=start-span; previous_end=end-span; next_start=start+span; next_end=end+span
            total_value=sum(point["value"] for point in series); logged_days=sum(point["items"]>0 for point in series)
            summary={"total":total_value,"average":total_value/len(series),"logged_days":logged_days,"incomplete_days":sum(point["incomplete"] for point in series)}
            labels={"calories":"Calories","protein":"Protein","carbs":"Carbohydrates","sugars":"Sugars","fat":"Fat","saturates":"Saturates","fibre":"Fibre","salt":"Salt"}
            return render_template("trends.html",nutrient=nutrient,label=labels[nutrient],labels=labels,series=series,chart=chart,summary=summary,start=start.isoformat(),end=end.isoformat(),start_label=start.strftime("%d %B %Y"),end_label=end.strftime("%d %B %Y"),previous_start=previous_start.isoformat(),previous_end=previous_end.isoformat(),next_start=next_start.isoformat(),next_end=next_end.isoformat(),unit="kcal" if nutrient=="calories" else "g",guide=nutrient_guide(nutrient,cfg))
    @app.route("/meal",methods=["GET","POST"])
    @app.route("/meal/<int:mid>",methods=["GET","POST"])
    def meal(mid=None):
        with db() as d:
            existing=d.execute("SELECT * FROM meals WHERE id=?",(mid,)).fetchone() if mid else None
            if mid and not existing: abort(404)
            items=d.execute("SELECT * FROM meal_items WHERE meal_id=?",(mid,)).fetchall() if mid else []
            draft=None; preview=None; preview_summary=None
            if request.method=="POST":
                ids=request.form.getlist("food_id"); mult=request.form.getlist("multiplier")
                draft={"mode":request.form.get("mode"),"eaten_at":request.form.get("eaten_at"),"food_day":request.form.get("food_day") or None,"note":request.form.get("note", ""),"items":[{"food_id":x,"multiplier":m} for x,m in zip(ids,mult) if x]}
                items=draft["items"]
                try:
                    if draft["mode"]=="plan":
                        preview=calculate(d,draft["items"]); preview_summary=calculation_summary(preview)
                    else:
                        save_meal(d,draft,mid); flash("Meal saved as eaten.","ok"); return redirect(url_for("dashboard",day=draft.get("food_day") or ""))
                except (ValueError,sqlite3.Error) as e: flash(str(e),"error")
            foods=d.execute("SELECT * FROM foods WHERE archived=0 OR id IN (SELECT food_id FROM meal_items WHERE meal_id=?) ORDER BY archived,name",(mid or -1,)).fetchall()
            return render_template("meal.html",foods=foods,meal=existing,draft=draft,items=items,preview=preview,preview_summary=preview_summary,now=datetime.now().strftime("%Y-%m-%dT%H:%M"))
    @app.post("/meal/<int:mid>/delete")
    def delete_meal(mid):
        with db() as d: d.execute("DELETE FROM meals WHERE id=?",(mid,)); d.commit()
        return redirect(url_for("dashboard"))
    @app.post("/meal/<int:mid>/duplicate")
    def duplicate(mid):
        with db() as d:
            m=d.execute("SELECT * FROM meals WHERE id=?",(mid,)).fetchone(); its=d.execute("SELECT food_id,multiplier FROM meal_items WHERE meal_id=?",(mid,)).fetchall()
            new=save_meal(d,{"mode":"confirmed","eaten_at":m['eaten_at'],"food_day":m['food_day'],"note":"Copy: "+m['note'],"items":[dict(x) for x in its]})
        return redirect(url_for("meal",mid=new))
    @app.route("/foods",methods=["GET","POST"])
    def foods():
        with db() as d:
            if request.method=="POST":
                vals=[request.form.get(x) or None for x in NUTRIENTS]
                d.execute("INSERT INTO foods(name,basis,amount,unit,"+','.join(NUTRIENTS)+",source) VALUES("+','.join(['?']*13)+")",(request.form['name'],request.form['basis'],float(request.form['amount']),request.form['unit'],*[float(x) if x is not None else None for x in vals],request.form['source'])); d.commit(); flash("Food saved to the server.","ok"); return redirect(url_for('foods'))
            return render_template("foods.html",foods=d.execute("SELECT * FROM foods ORDER BY archived,name").fetchall())
    @app.post("/foods/<int:fid>/toggle")
    def toggle_food(fid):
        with db() as d: d.execute("UPDATE foods SET archived=1-archived WHERE id=?",(fid,)); d.commit()
        return redirect(url_for('foods'))
    @app.post("/foods/<int:fid>/edit")
    def edit_food(fid):
        with db() as d:
            if not d.execute("SELECT 1 FROM foods WHERE id=?",(fid,)).fetchone(): return ("Food not found",404)
            values=[]
            for n in NUTRIENTS:
                raw=request.form.get(n,"").strip(); values.append(None if raw=="" else float(raw))
            with d:
                d.execute("UPDATE foods SET name=?,basis=?,amount=?,unit=?,"+",".join(n+"=?" for n in NUTRIENTS)+",source=? WHERE id=?",(request.form["name"],request.form.get("basis","serving"),float(request.form["amount"]),request.form["unit"],*values,request.form["source"],fid))
                refresh_logged_food(d,fid)
        flash("Food updated on the server. Logged meals and trends were recalculated.","ok"); return redirect(url_for('foods'))
    @app.route("/weights",methods=["GET","POST"])
    def weights():
        with db() as d:
            if request.method=="POST": d.execute("INSERT INTO weights(measured_at,kg) VALUES(?,?)",(request.form['measured_at'],float(request.form['kg']))); d.commit(); return redirect(url_for('weights'))
            rows=d.execute("SELECT *, (SELECT count(*) FROM weights b WHERE b.kg=w.kg AND abs(julianday(b.measured_at)-julianday(w.measured_at))<1) > 1 duplicate FROM weights w ORDER BY measured_at").fetchall()
            chart=weight_chart(rows)
            summary={"latest":rows[-1]["kg"] if rows else None,"change":rows[-1]["kg"]-rows[0]["kg"] if len(rows)>1 else None,"readings":len(rows)}
            return render_template("weights.html",weights=rows,chart=chart,summary=summary)
    @app.post("/weights/<int:wid>/delete")
    def delete_weight(wid):
        with db() as d: d.execute("DELETE FROM weights WHERE id=?",(wid,)); d.commit()
        return redirect(url_for('weights'))
    @app.route("/settings",methods=["GET","POST"])
    def config_page():
        with db() as d:
            if request.method=="POST":
                c=settings(d)
                for k in c:
                    if k=="meal_times": c[k]=[x.strip() for x in request.form.get(k,"").split(",")]
                    elif isinstance(c[k],bool): c[k]=k in request.form
                    elif isinstance(c[k],(int,float)): c[k]=float(request.form.get(k,c[k]))
                    else: c[k]=request.form.get(k,c[k])
                d.execute("UPDATE settings SET json=? WHERE id=1",(json.dumps(c),)); d.commit(); flash("Settings saved.","ok")
            return render_template("settings.html")
    @app.post("/import-history")
    def import_history():
        with db() as d: flash("Import report: "+json.dumps(run_import(d,save_meal)),"ok")
        return redirect(url_for('review'))
    @app.get("/review")
    def review():
        with db() as d: return render_template("review.html",rows=d.execute("SELECT * FROM meals WHERE status='review'").fetchall(),runs=d.execute("SELECT * FROM import_runs ORDER BY id DESC").fetchall())
    @app.get("/export")
    def export():
        with db() as d:
            out={t:[dict(x) for x in d.execute("SELECT * FROM "+t)] for t in ("settings","foods","meals","meal_items","weights")}
        return Response(json.dumps(out,indent=2),mimetype="application/json",headers={"Content-Disposition":"attachment; filename=mounjaro-coach.json"})
    @app.post("/import")
    def import_data():
        data=json.load(request.files['file']); allowed=("settings","foods","meals","meal_items","weights")
        with db() as d:
            with d:
                for t in reversed(allowed): d.execute("DELETE FROM "+t)
                for t in allowed:
                    for row in data.get(t,[]):
                        keys=[k for k in row if k in {x[1] for x in d.execute('PRAGMA table_info('+t+')')}]
                        d.execute(f"INSERT INTO {t} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[row[k] for k in keys])
        flash("Import complete.","ok"); return redirect(url_for('config_page'))
    return app

def calculate(d, items):
    result=[]
    for i in items:
        f=d.execute("SELECT * FROM foods WHERE id=?",(i['food_id'],)).fetchone(); m=float(i['multiplier'])
        if not f or m<=0: raise ValueError("Food and positive serving/weight are required.")
        result.append((f,m,{n:(None if f[n] is None else f[n]*m) for n in NUTRIENTS}))
    return result


def calculation_summary(items):
    totals_out={n:sum(values[n] or 0 for _,_,values in items) for n in NUTRIENTS}
    totals_out["incomplete"]={n:any(values[n] is None for _,_,values in items) for n in NUTRIENTS}
    return totals_out


def selected_date_range(args, today):
    raw_start=args.get("start","").strip(); raw_end=args.get("end","").strip()
    try:
        if not raw_start and not raw_end:
            start=today-timedelta(days=today.weekday()); end=start+timedelta(days=6)
        elif raw_start and not raw_end:
            start=datetime.strptime(raw_start,"%Y-%m-%d").date(); end=start+timedelta(days=6)
        elif raw_end and not raw_start:
            end=datetime.strptime(raw_end,"%Y-%m-%d").date(); start=end-timedelta(days=6)
        else:
            start=datetime.strptime(raw_start,"%Y-%m-%d").date(); end=datetime.strptime(raw_end,"%Y-%m-%d").date()
    except ValueError: raise ValueError("Choose valid start and end dates.")
    if end<start: raise ValueError("The end date must be on or after the start date.")
    if (end-start).days>365: raise ValueError("Choose a date range of one year or less.")
    return start,end


def nutrient_series(grouped, start, end):
    series=[]; cursor=start
    while cursor<=end:
        saved=grouped.get(cursor.isoformat(),{})
        series.append({"date":cursor.isoformat(),"label":cursor.strftime("%a %d"),"value":float(saved.get("total",0)),"incomplete":bool(saved.get("incomplete",False)),"items":int(saved.get("items",0))})
        cursor+=timedelta(days=1)
    return series


def nutrient_chart(series, width=820, height=270, left=34, top=18, bottom=40):
    maximum=max((point["value"] for point in series),default=0) or 1
    usable_width=width-left*2; usable_height=height-top-bottom; slot=usable_width/len(series); label_every=max(1,(len(series)+8)//9)
    bars=[]
    for index,point in enumerate(series):
        bar_width=min(42,slot*.64); bar_height=point["value"]/maximum*usable_height
        bars.append({**point,"x":round(left+slot*index+(slot-bar_width)/2,2),"y":round(top+usable_height-bar_height,2),"width":round(bar_width,2),"height":round(bar_height,2),"show_label":index%label_every==0 or index==len(series)-1})
    return {"bars":bars,"maximum":maximum,"width":width,"height":height,"baseline":top+usable_height}


def nutrient_guide(nutrient, cfg):
    if nutrient=="calories": return f"Daily target {cfg['calorie_min']:.0f}–{cfg['calorie_max']:.0f} kcal"
    if nutrient=="protein": return f"Daily guidance {cfg['protein_min']:.0f}–{cfg['protein_max']:.0f} g"
    if nutrient=="fibre": return f"Daily target at least {cfg['fibre_low']:.0f} g"
    if nutrient=="salt": return f"Daily guide up to {cfg['salt_warn']:.1f} g"
    return "Based on food logged for each day"


def weight_chart(rows, width=760, height=230, pad=24):
    if not rows: return {"points":"","dots":[],"low":None,"high":None}
    values=[float(row["kg"]) for row in rows]
    low,high=min(values),max(values); span=high-low or 1
    usable_width=width-pad*2; usable_height=height-pad*2
    dots=[]
    for index,row in enumerate(rows):
        x=pad+(usable_width*index/(len(rows)-1) if len(rows)>1 else usable_width/2)
        y=pad+(high-float(row["kg"]))/span*usable_height
        dots.append({"x":round(x,2),"y":round(y,2),"kg":row["kg"],"date":row["measured_at"][:10]})
    return {"points":" ".join(f'{dot["x"]},{dot["y"]}' for dot in dots),"dots":dots,"low":low,"high":high}
