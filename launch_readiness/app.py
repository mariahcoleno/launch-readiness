"""The web app. Run with: flask --app launch_readiness.app run"""

from __future__ import annotations

import os
from typing import Optional

from flask import Flask, abort, g, redirect, render_template, request, url_for

from . import db
from .launch_form import parse_launch_form
from .launches import create_launch, get_configuration, get_gates, get_launch, list_launches
from .models import LABELS, Capability, Stage, Surface
from .rules_engine import required_gates


def create_app(test_config: Optional[dict] = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config["DATABASE"] = os.path.join(app.instance_path, "launch_readiness.db")
    if test_config:
        app.config.update(test_config)

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    conn = db.get_connection(app.config["DATABASE"])
    db.init_db(conn)  # safe to run on every start
    conn.close()

    def get_db():
        if "db" not in g:
            g.db = db.get_connection(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.template_filter("label")
    def label(value: str) -> str:
        return LABELS.get(value, value)

    @app.context_processor
    def choices():
        return {"stages": list(Stage), "surfaces": list(Surface), "capabilities": list(Capability)}

    @app.get("/")
    def index():
        return render_template("index.html", launches=list_launches(get_db()))

    @app.get("/launches/new")
    def new_launch():
        return render_template("new_launch.html", form={}, errors={})

    @app.post("/launches")
    def create():
        data, errors = parse_launch_form(request.form)
        if errors:
            form = {
                "name": request.form.get("name", ""),
                "model_version": request.form.get("model_version", ""),
                "target_date": request.form.get("target_date", ""),
                "stage": request.form.get("stage", ""),
                "surfaces": request.form.getlist("surfaces"),
                "capabilities": request.form.getlist("capabilities"),
            }
            return render_template("new_launch.html", form=form, errors=errors), 400
        launch_id = create_launch(get_db(), data)
        return redirect(url_for("launch_page", launch_id=launch_id))

    @app.get("/launches/<int:launch_id>")
    def launch_page(launch_id: int):
        conn = get_db()
        launch = get_launch(conn, launch_id)
        if launch is None:
            abort(404)
        config = get_configuration(conn, launch_id)
        reasons = {gate.id: gate.reasons for gate in required_gates(config)}
        return render_template(
            "launch.html",
            launch=launch,
            config=config,
            gates=get_gates(conn, launch_id),
            reasons=reasons,
        )

    return app
