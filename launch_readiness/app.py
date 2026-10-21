"""The web app. Run with: flask --app launch_readiness.app run"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

import click
from flask import Flask, abort, g, redirect, render_template, request, url_for

from . import db
from .dashboard import countdown, group_by_team, needs_attention, summarize
from .decision_form import parse_go_no_go_form, parse_scope_change_form
from .decisions import (
    changes_since,
    latest_go_no_go,
    latest_go_no_go_by_launch,
    list_decisions,
    record_go_no_go,
)
from .gate_form import parse_gate_form
from .launch_form import parse_launch_form
from .launch_status import assess_launch, current_gate_views
from .launches import (
    create_launch,
    get_configuration,
    get_gate,
    get_gate_additions,
    get_launch,
    get_removed_gates,
    get_scope_changes,
    list_launches,
    update_gate,
)
from .models import LABELS, Capability, GateStatus, Stage, Surface
from .readiness import assess
from .scope_change import (
    CapabilityAlreadyEnabled,
    CapabilityNotEnabled,
    disable_capability,
    enable_capability,
    preview_disable,
    preview_enable,
)
from .seed import seed_database

OUTDATED_DB_MESSAGE = (
    "This database was made by an older version of the app. "
    "To replace it with the sample data, run: flask --app launch_readiness.app seed"
)


def create_app(test_config: Optional[dict] = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config["DATABASE"] = os.path.join(app.instance_path, "launch_readiness.db")
    app.config["TODAY"] = None  # tests can fix "today" to a date
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

    def today() -> date:
        return app.config["TODAY"] or date.today()

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def check_schema():
        if request.endpoint != "static" and not db.schema_is_current(get_db()):
            return render_template("message.html", message=OUTDATED_DB_MESSAGE), 503

    @app.template_filter("label")
    def label(value: str) -> str:
        return LABELS.get(value, value)

    @app.context_processor
    def choices():
        return {
            "stages": list(Stage),
            "surfaces": list(Surface),
            "capabilities": list(Capability),
            "statuses": list(GateStatus),
        }

    # --- Launches -------------------------------------------------------------

    @app.get("/")
    def index():
        conn = get_db()
        return render_template(
            "index.html", launches=list_launches(conn), latest=latest_go_no_go_by_launch(conn)
        )

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

    def _launch_or_404(launch_id: int):
        launch = get_launch(get_db(), launch_id)
        if launch is None:
            abort(404)
        return launch

    def _countdown(launch) -> str:
        return countdown(date.fromisoformat(launch["target_date"]), today())

    @app.get("/launches/<int:launch_id>")
    def launch_page(launch_id: int):
        conn = get_db()
        launch = _launch_or_404(launch_id)
        config = get_configuration(conn, launch_id)
        gates, required = current_gate_views(conn, launch_id, today(), config=config)
        return render_template(
            "launch.html",
            launch=launch,
            config=config,
            countdown=_countdown(launch),
            readiness=assess(gates, required),
            summary=summarize(gates),
            attention=needs_attention(gates),
            teams=group_by_team(gates),
            removed=get_removed_gates(conn, launch_id),
            additions=get_gate_additions(conn, launch_id),
            latest=latest_go_no_go(conn, launch_id),
        )

    # --- Go/no-go view and scope changes --------------------------------------

    def _render_go_no_go(launch_id: int, form=None, errors=None, status=200):
        conn = get_db()
        launch = _launch_or_404(launch_id)
        config = get_configuration(conn, launch_id)
        gates, required = current_gate_views(conn, launch_id, today(), config=config)
        previews = [
            preview_disable(conn, launch_id, cap, today())
            for cap in Capability
            if cap in config.capabilities
        ]
        additions = [
            preview_enable(conn, launch_id, cap, today())
            for cap in Capability
            if cap not in config.capabilities
        ]
        return render_template(
            "go_no_go.html",
            launch=launch,
            countdown=_countdown(launch),
            readiness=assess(gates, required),
            previews=previews,
            additions=additions,
            scope_changes=get_scope_changes(conn, launch_id),
            latest=latest_go_no_go(conn, launch_id),
            today=today(),
            form=form or {},
            errors=errors or {},
        ), status

    @app.get("/launches/<int:launch_id>/go-no-go")
    def go_no_go(launch_id: int):
        return _render_go_no_go(launch_id)

    # --- Decision log -----------------------------------------------------------

    @app.post("/launches/<int:launch_id>/decisions")
    def record_decision(launch_id: int):
        conn = get_db()
        _launch_or_404(launch_id)
        ready = assess_launch(conn, launch_id, today()).ready
        decision, errors = parse_go_no_go_form(request.form, today(), ready)
        if errors:
            form = {k: request.form.get(k, "") for k in
                    ("kind", "decided_by", "decided_on", "rationale", "follow_up",
                     "acknowledge_blockers")}
            return _render_go_no_go(launch_id, form, errors, 400)
        record_go_no_go(conn, launch_id, decision, today())
        return redirect(url_for("decision_log", launch_id=launch_id))

    @app.get("/launches/<int:launch_id>/decisions")
    def decision_log(launch_id: int):
        conn = get_db()
        launch = _launch_or_404(launch_id)
        current = assess_launch(conn, launch_id, today())
        latest = latest_go_no_go(conn, launch_id)
        return render_template(
            "decision_log.html",
            launch=launch,
            decisions=list_decisions(conn, launch_id=launch_id),
            latest=latest,
            since=changes_since(conn, latest, current) if latest else None,
            current=current,
        )

    @app.get("/decisions")
    def all_decisions():
        conn = get_db()
        launch_filter = request.args.get("launch", type=int)
        kind_filter = request.args.get("kind") or None
        if kind_filter not in (None, "go", "no_go", "scope_change"):
            kind_filter = None
        return render_template(
            "all_decisions.html",
            decisions=list_decisions(conn, launch_id=launch_filter, kind=kind_filter),
            launches=list_launches(conn),
            launch_filter=launch_filter,
            kind_filter=kind_filter,
        )

    def _preview_or_404(launch_id: int, capability: str):
        try:
            cap = Capability(capability)
            return preview_disable(get_db(), launch_id, cap, today())
        except (ValueError, CapabilityNotEnabled):
            abort(404)

    @app.get("/launches/<int:launch_id>/disable/<capability>")
    def disable_page(launch_id: int, capability: str):
        launch = _launch_or_404(launch_id)
        preview = _preview_or_404(launch_id, capability)
        return render_template(
            "disable_capability.html", launch=launch, preview=preview, form={}, errors={}
        )

    @app.post("/launches/<int:launch_id>/disable/<capability>")
    def disable(launch_id: int, capability: str):
        launch = _launch_or_404(launch_id)
        preview = _preview_or_404(launch_id, capability)
        decision, errors = parse_scope_change_form(request.form)
        if errors:
            form = {k: request.form.get(k, "") for k in ("decided_by", "rationale", "follow_up")}
            return render_template(
                "disable_capability.html", launch=launch, preview=preview, form=form, errors=errors
            ), 400
        disable_capability(get_db(), launch_id, preview.capability, decision, today())
        return redirect(url_for("go_no_go", launch_id=launch_id))

    # --- Delta review: turning a capability on --------------------------------

    def _enable_preview_or_404(launch_id: int, capability: str):
        try:
            cap = Capability(capability)
            return preview_enable(get_db(), launch_id, cap, today())
        except (ValueError, CapabilityNotEnabled, CapabilityAlreadyEnabled):
            abort(404)

    @app.get("/launches/<int:launch_id>/enable/<capability>")
    def enable_page(launch_id: int, capability: str):
        launch = _launch_or_404(launch_id)
        preview = _enable_preview_or_404(launch_id, capability)
        return render_template(
            "enable_capability.html", launch=launch, preview=preview, form={}, errors={}
        )

    @app.post("/launches/<int:launch_id>/enable/<capability>")
    def enable(launch_id: int, capability: str):
        launch = _launch_or_404(launch_id)
        preview = _enable_preview_or_404(launch_id, capability)
        decision, errors = parse_scope_change_form(request.form, follow_up_required=False)
        if errors:
            form = {k: request.form.get(k, "") for k in ("decided_by", "rationale", "follow_up")}
            return render_template(
                "enable_capability.html", launch=launch, preview=preview, form=form, errors=errors
            ), 400
        enable_capability(get_db(), launch_id, preview.capability, decision, today())
        return redirect(url_for("launch_page", launch_id=launch_id))

    # --- Gate editing ---------------------------------------------------------

    def _gate_or_404(launch_id: int, gate_id: int):
        launch = _launch_or_404(launch_id)
        gate = get_gate(get_db(), launch_id, gate_id)
        if gate is None:
            abort(404)
        return launch, gate

    @app.get("/launches/<int:launch_id>/gates/<int:gate_id>/edit")
    def edit_gate(launch_id: int, gate_id: int):
        launch, gate = _gate_or_404(launch_id, gate_id)
        form = {key: gate[key] or "" for key in
                ("status", "owner", "due_date", "notes", "waiver_rationale", "waived_by")}
        return render_template("edit_gate.html", launch=launch, gate=gate, form=form, errors={})

    @app.post("/launches/<int:launch_id>/gates/<int:gate_id>/edit")
    def save_gate(launch_id: int, gate_id: int):
        launch, gate = _gate_or_404(launch_id, gate_id)
        update, errors = parse_gate_form(request.form)
        if errors:
            form = {key: request.form.get(key, "") for key in
                    ("status", "owner", "due_date", "notes", "waiver_rationale", "waived_by")}
            return render_template(
                "edit_gate.html", launch=launch, gate=gate, form=form, errors=errors
            ), 400
        update_gate(get_db(), gate_id, update)
        return redirect(url_for("launch_page", launch_id=launch_id))

    # --- Command line ---------------------------------------------------------

    @app.cli.command("seed")
    @click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
    def seed_command(yes: bool):
        """Replace all data with the sample launches."""
        if not yes:
            click.confirm(
                "This deletes all launches and loads the sample data. Continue?", abort=True
            )
        conn = db.get_connection(app.config["DATABASE"])
        try:
            ids = seed_database(conn)
            for launch in list_launches(conn):
                click.echo(f"  {launch['name']}  ->  /launches/{launch['id']}")
            click.echo(f"Loaded {len(ids)} sample launches.")
        finally:
            conn.close()

    return app
