import io, json, os, sqlite3, threading, time
from datetime import datetime
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for
from .core import NUTRIENTS, connect, migrate, save_meal, settings, totals
from .importer import run_import

def create_app(test_config=None):
    app=Flask(__name__); app.secret_key="local-mounjaro-coach"
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
    def common(): return {"cfg":settings(db()),"nutrients":NUTRIENTS}
    @app.get("/")
    def dashboard():
        with db() as d:
            cfg=settings(d); day=request.args.get("day") or __import__('app.core',fromlist=['food_day']).food_day(datetime.now().isoformat(timespec="minutes"),cfg)
            meals=d.execute("SELECT * FROM meals WHERE food_day=? AND status='confirmed' ORDER BY eaten_at",(day,)).fetchall(); review=d.execute("SELECT count(*) FROM meals WHERE status='review'").fetchone()[0]
            return render_template("dashboard.html",day=day,meals=meals,total=totals(d,day),review=review)
    @app.route("/meal",methods=["GET","POST"])
    @app.route("/meal/<int:mid>",methods=["GET","POST"])
    def meal(mid=None):
        with db() as d:
            if request.method=="POST":
                try:
                    ids=request.form.getlist("food_id"); mult=request.form.getlist("multiplier")
                    payload={"mode":request.form.get("mode"),"eaten_at":request.form.get("eaten_at"),"food_day":request.form.get("food_day") or None,"note":request.form.get("note", ""),"items":[{"food_id":x,"multiplier":m} for x,m in zip(ids,mult) if x]}
                    if payload["mode"]=="plan": return render_template("plan.html",items=calculate(d,payload["items"]))
                    save_meal(d,payload,mid); flash("Meal saved as eaten.","ok"); return redirect(url_for("dashboard",day=payload.get("food_day") or ""))
                except (ValueError,sqlite3.Error) as e: flash(str(e),"error")
            foods=d.execute("SELECT * FROM foods WHERE archived=0 ORDER BY name").fetchall(); existing=None; items=[]
            if mid: existing=d.execute("SELECT * FROM meals WHERE id=?",(mid,)).fetchone(); items=d.execute("SELECT * FROM meal_items WHERE meal_id=?",(mid,)).fetchall()
            return render_template("meal.html",foods=foods,meal=existing,items=items)
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
                d.execute("INSERT INTO foods(name,basis,amount,unit,"+','.join(NUTRIENTS)+",source) VALUES("+','.join(['?']*13)+")",(request.form['name'],request.form['basis'],float(request.form['amount']),request.form['unit'],*[float(x) if x is not None else None for x in vals],request.form['source'])); d.commit(); return redirect(url_for('foods'))
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
            d.execute("UPDATE foods SET name=?,amount=?,unit=?,"+",".join(n+"=?" for n in NUTRIENTS)+",source=? WHERE id=?",(request.form["name"],float(request.form["amount"]),request.form["unit"],*values,request.form["source"],fid)); d.commit()
        flash("Food updated. Existing logged meals retain their original nutrition.","ok"); return redirect(url_for('foods'))
    @app.route("/weights",methods=["GET","POST"])
    def weights():
        with db() as d:
            if request.method=="POST": d.execute("INSERT INTO weights(measured_at,kg) VALUES(?,?)",(request.form['measured_at'],float(request.form['kg']))); d.commit(); return redirect(url_for('weights'))
            rows=d.execute("SELECT *, (SELECT count(*) FROM weights b WHERE b.kg=w.kg AND abs(julianday(b.measured_at)-julianday(w.measured_at))<1) > 1 duplicate FROM weights w ORDER BY measured_at").fetchall(); return render_template("weights.html",weights=rows)
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
        f=d.execute("SELECT * FROM foods WHERE id=?",(i['food_id'],)).fetchone(); m=float(i['multiplier']); result.append((f,m,{n:(None if f[n] is None else f[n]*m) for n in NUTRIENTS}))
    return result
