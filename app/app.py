"""
Flask Application Server — runs on IBM Power (ppc64le)
Connects to PostgreSQL managed by Crunchy Postgres Operator running on Intel (x86_64) node.

Provides:
  - Browser UI  : GET /        — full HTML web interface for CRUD operations
  - REST API    : /items, /arch, /health, /ready
"""

import os
import re
import time
import platform
import html
import psycopg2
from contextlib import contextmanager
from flask import Flask, jsonify, request, redirect, url_for

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Database URL construction
# ---------------------------------------------------------------------------
# Primary: use the full URI from the Crunchy operator secret (key: uri)
# Fallback: build from individual PG_* env vars (key: user/password/host/port/dbname)
# ---------------------------------------------------------------------------

def _build_database_url():
    uri = os.environ.get("DATABASE_URL", "")
    if not uri:
        user     = os.environ.get("PG_USER",     "appuser")
        password = os.environ.get("PG_PASSWORD",  "changeme")
        host     = os.environ.get("PG_HOST",      "hetero-pgcluster-primary")
        port     = os.environ.get("PG_PORT",      "5432")
        dbname   = os.environ.get("PG_DBNAME",    "appdb")
        uri = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    # Normalise sslmode: strip any existing sslmode param, then append sslmode=require
    uri = re.sub(r'([?&])sslmode=[^&]*(&?)', _remove_sslmode_param, uri)
    sep = '&' if '?' in uri else '?'
    uri = uri.rstrip('?&') + sep + 'sslmode=require'
    return uri


def _remove_sslmode_param(m):
    """Regex replacement helper: remove sslmode=... and fix leftover separators."""
    prefix = m.group(1)   # '?' or '&'
    suffix = m.group(2)   # trailing '&' or ''
    if prefix == '?' and suffix == '&':
        return '?'
    if prefix == '?' and suffix == '':
        return ''
    if prefix == '&' and suffix == '&':
        return '&'
    return ''


DATABASE_URL = _build_database_url()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    """Context manager: open a DB connection with retry, always close it."""
    conn = _connect_with_retry()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _connect_with_retry(retries=5, delay=3):
    """Open a psycopg2 connection, retrying on OperationalError."""
    last_exc: Exception = psycopg2.OperationalError("Could not connect to database")
    for attempt in range(retries):
        try:
            return psycopg2.connect(DATABASE_URL)
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt < retries - 1:
                print(f"DB connection attempt {attempt + 1} failed: {exc}. Retrying in {delay}s...")
                time.sleep(delay)
    raise last_exc


def init_db():
    """Initialize the database schema."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.close()
    print("Database initialized successfully.")


# Initialize DB on startup
with app.app_context():
    try:
        init_db()
    except Exception as exc:
        print(f"WARNING: Could not initialize DB at startup: {exc}")


# ---------------------------------------------------------------------------
# HTML template — full browser UI
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Heterogeneous HCP Demo</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f1117; color: #e0e0e0; min-height: 100vh; }}
    header {{ background: linear-gradient(135deg, #1a1f2e 0%, #0d1b2a 100%); border-bottom: 2px solid #ee0000; padding: 20px 40px; }}
    header h1 {{ font-size: 1.6rem; color: #fff; }}
    header h1 span {{ color: #ee0000; }}
    .arch-banner {{ display: flex; gap: 20px; padding: 16px 40px; background: #161b27; border-bottom: 1px solid #2a2f3e; flex-wrap: wrap; }}
    .arch-card {{ background: #1e2535; border-radius: 8px; padding: 12px 20px; border-left: 4px solid; flex: 1; min-width: 200px; }}
    .arch-card.power {{ border-color: #4caf50; }}
    .arch-card.intel {{ border-color: #2196f3; }}
    .arch-card h3 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: 6px; }}
    .arch-card .value {{ font-size: 1rem; font-weight: 600; }}
    .arch-card.power .value {{ color: #4caf50; }}
    .arch-card.intel .value {{ color: #2196f3; }}
    .arch-card .sub {{ font-size: 0.75rem; color: #666; margin-top: 4px; }}
    .container {{ max-width: 960px; margin: 30px auto; padding: 0 20px; }}
    .card {{ background: #1e2535; border-radius: 10px; padding: 24px; margin-bottom: 24px; border: 1px solid #2a2f3e; }}
    .card h2 {{ font-size: 1.1rem; color: #fff; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid #2a2f3e; }}
    .form-row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .form-group {{ flex: 1; min-width: 150px; }}
    label {{ display: block; font-size: 0.8rem; color: #888; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
    input[type=text], textarea {{ width: 100%; background: #0f1117; border: 1px solid #2a2f3e; border-radius: 6px; padding: 10px 14px; color: #e0e0e0; font-size: 0.9rem; outline: none; transition: border-color 0.2s; }}
    input[type=text]:focus, textarea:focus {{ border-color: #ee0000; }}
    textarea {{ resize: vertical; min-height: 70px; }}
    .btn {{ padding: 10px 22px; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem; font-weight: 600; transition: all 0.2s; }}
    .btn-primary {{ background: #ee0000; color: #fff; }}
    .btn-primary:hover {{ background: #cc0000; }}
    .btn-warning {{ background: transparent; color: #ff9800; border: 1px solid #ff9800; padding: 6px 14px; font-size: 0.8rem; }}
    .btn-warning:hover {{ background: #ff9800; color: #fff; }}
    .btn-danger {{ background: transparent; color: #f44336; border: 1px solid #f44336; padding: 6px 14px; font-size: 0.8rem; }}
    .btn-danger:hover {{ background: #f44336; color: #fff; }}
    .btn-refresh {{ background: #1e2535; color: #888; border: 1px solid #2a2f3e; }}
    .btn-refresh:hover {{ border-color: #888; color: #e0e0e0; }}
    .btn-save {{ background: #4caf50; color: #fff; padding: 6px 14px; font-size: 0.8rem; }}
    .btn-save:hover {{ background: #388e3c; }}
    .btn-cancel {{ background: transparent; color: #888; border: 1px solid #444; padding: 6px 14px; font-size: 0.8rem; }}
    .btn-cancel:hover {{ border-color: #888; color: #e0e0e0; }}
    .flash {{ padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 0.9rem; }}
    .flash.success {{ background: #1b3a1b; border: 1px solid #4caf50; color: #4caf50; }}
    .flash.error {{ background: #3a1b1b; border: 1px solid #f44336; color: #f44336; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; color: #666; padding: 8px 12px; border-bottom: 1px solid #2a2f3e; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #1a1f2e; font-size: 0.9rem; vertical-align: middle; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #252b3b; }}
    .badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }}
    .badge-power {{ background: #1b3a1b; color: #4caf50; }}
    .badge-intel {{ background: #1b2a3a; color: #2196f3; }}
    .empty {{ text-align: center; color: #555; padding: 30px; font-size: 0.9rem; }}
    .ts {{ color: #555; font-size: 0.8rem; }}
    .edit-row td {{ background: #1a2030 !important; }}
    .edit-row input[type=text] {{ padding: 6px 10px; font-size: 0.85rem; }}
    .action-btns {{ display: flex; gap: 6px; flex-wrap: nowrap; }}
    footer {{ text-align: center; padding: 20px; color: #444; font-size: 0.8rem; margin-top: 20px; }}
  </style>
</head>
<body>
  <header>
    <h1>IBM Power and <span>IBM Fusion HCI</span> Demo &nbsp;|&nbsp; IBM Power + Intel on OpenShift</h1>
  </header>

  <div class="arch-banner">
    <div class="arch-card power">
      <h3>App Server (This Pod)</h3>
      <div class="value">ppc64le &mdash; IBM Power</div>
      <div class="sub">{app_node}</div>
    </div>
    <div class="arch-card intel">
      <h3>Database (Crunchy PGO)</h3>
      <div class="value">x86_64 &mdash; Intel</div>
      <div class="sub">hetero-pgcluster-primary &nbsp;&bull;&nbsp; PostgreSQL 16</div>
    </div>
    <div class="arch-card" style="border-color:#9c27b0;">
      <h3>DB Status</h3>
      <div class="value" style="color:{db_color};">{db_status}</div>
      <div class="sub">{db_version}</div>
    </div>
  </div>

  <div class="container">
    {flash}

    <!-- Add Item Form -->
    <div class="card">
      <h2>&#43; Add new item to inventory</h2>
      <form method="POST" action="/ui/items">
        <div class="form-row">
          <div class="form-group">
            <label for="name">Item Name *</label>
            <input type="text" id="name" name="name" placeholder="e.g. hetero-demo-item" required maxlength="255">
          </div>
          <div class="form-group" style="flex:2;">
            <label for="description">Description</label>
            <input type="text" id="description" name="description" placeholder="Written from IBM Power node to Intel PostgreSQL via Crunchy PGO" maxlength="1000">
          </div>
        </div>
        <br>
        <button type="submit" class="btn btn-primary">&#128190; Save</button>
        &nbsp;
        <a href="/"><button type="button" class="btn btn-refresh">&#8635; Refresh</button></a>
      </form>
    </div>

    <!-- Items Table -->
    <div class="card">
      <h2>&#128203; Inventory items &nbsp;<span style="color:#555;font-size:0.85rem;font-weight:400;">({count} record{plural})</span></h2>
      {table}
    </div>

    <!-- Architecture Info -->
    <div class="card">
      <h2>&#127760; Cross-Architecture Info</h2>
      <table>
        <tr><th>Component</th><th>Architecture</th><th>Node</th><th>Role</th></tr>
        <tr>
          <td>Flask App Server</td>
          <td><span class="badge badge-power">ppc64le</span></td>
          <td style="font-size:0.8rem;">{app_node}</td>
          <td>Application Logic + Web UI</td>
        </tr>
        <tr>
          <td>PostgreSQL (Crunchy PGO)</td>
          <td><span class="badge badge-intel">x86_64</span></td>
          <td style="font-size:0.8rem;">hetero-pgcluster-primary</td>
          <td>Data Persistence</td>
        </tr>
      </table>
    </div>
  </div>

  <footer>
    Heterogeneous HCP Demo &mdash; IBM Power (ppc64le) + Intel (x86_64) on OpenShift Hosted Control Plane
  </footer>

  <script>
    function showEditRow(id, name, description) {{
      // Hide view row, show edit row
      document.getElementById('view-' + id).style.display = 'none';
      document.getElementById('edit-' + id).style.display = '';
      document.getElementById('edit-name-' + id).value = name;
      document.getElementById('edit-desc-' + id).value = description;
    }}
    function cancelEdit(id) {{
      document.getElementById('view-' + id).style.display = '';
      document.getElementById('edit-' + id).style.display = 'none';
    }}
  </script>
</body>
</html>"""


def get_db_info():
    """Get DB connection status and version string."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            cur.close()
        short_ver = version.split(',')[0] if version else "Unknown"
        return True, short_ver
    except Exception as exc:
        return False, str(exc)[:80]


def get_items():
    """Fetch all items from DB, ordered newest first."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, description, created_at FROM items ORDER BY id DESC;")
            rows = cur.fetchall()
            cur.close()
        return rows, None
    except Exception as exc:
        return [], str(exc)


def _esc(value):
    """HTML-escape a value for safe rendering."""
    return html.escape(str(value)) if value is not None else ""


def build_table(rows):
    """Build HTML table from rows with inline edit support."""
    if not rows:
        return '<div class="empty">No items yet. Add your first item above!</div>'

    html_parts = ["""<table>
      <tr>
        <th style="width:50px">#</th>
        <th>Name</th>
        <th>Description</th>
        <th style="width:160px">Created At</th>
        <th style="width:160px">Actions</th>
      </tr>"""]

    for row in rows:
        rid, rname, rdesc, rts = row[0], row[1], row[2] or "", row[3]
        ename  = _esc(rname)
        edesc  = _esc(rdesc)
        ets    = _esc(str(rts)[:19])
        # JS-safe single-quoted strings for onclick
        js_name = rname.replace("'", "\\'").replace('"', '"')
        js_desc = rdesc.replace("'", "\\'").replace('"', '"')

        # View row
        html_parts.append(f"""
      <tr id="view-{rid}">
        <td style="color:#555;">{rid}</td>
        <td><strong>{ename}</strong></td>
        <td style="color:#aaa;">{edesc}</td>
        <td class="ts">{ets}</td>
        <td>
          <div class="action-btns">
            <button type="button" class="btn btn-warning"
              onclick="showEditRow({rid}, '{js_name}', '{js_desc}')">&#9998; Edit</button>
            <form method="POST" action="/ui/items/{rid}/delete" style="display:inline;">
              <button type="submit" class="btn btn-danger"
                onclick="return confirm('Delete item {rid}?')">&#128465;</button>
            </form>
          </div>
        </td>
      </tr>""")

        # Edit row (hidden by default)
        html_parts.append(f"""
      <tr id="edit-{rid}" class="edit-row" style="display:none;">
        <td style="color:#555;">{rid}</td>
        <td colspan="2">
          <form method="POST" action="/ui/items/{rid}/edit" id="edit-form-{rid}">
            <div class="form-row">
              <div class="form-group">
                <input type="text" id="edit-name-{rid}" name="name"
                  value="{ename}" required maxlength="255" placeholder="Item name">
              </div>
              <div class="form-group" style="flex:2;">
                <input type="text" id="edit-desc-{rid}" name="description"
                  value="{edesc}" maxlength="1000" placeholder="Description">
              </div>
            </div>
          </form>
        </td>
        <td class="ts">{ets}</td>
        <td>
          <div class="action-btns">
            <button type="submit" form="edit-form-{rid}" class="btn btn-save">&#10003; Save</button>
            <button type="button" class="btn btn-cancel" onclick="cancelEdit({rid})">&#10005;</button>
          </div>
        </td>
      </tr>""")

    html_parts.append("</table>")
    return "".join(html_parts)


# ---------------------------------------------------------------------------
# Browser UI routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Main browser UI — shows items and add form."""
    flash_msg  = _esc(request.args.get("msg", ""))
    flash_type = request.args.get("type", "success")
    if flash_type not in ("success", "error"):
        flash_type = "success"
    flash_html = f'<div class="flash {flash_type}">{flash_msg}</div>' if flash_msg else ""

    db_ok, db_version = get_db_info()
    db_status = "Connected ✓" if db_ok else "Disconnected ✗"
    db_color  = "#4caf50" if db_ok else "#f44336"

    rows, err = get_items()
    if err:
        flash_html = f'<div class="flash error">DB Error: {_esc(err)}</div>'

    table  = build_table(rows)
    count  = len(rows)
    plural = "s" if count != 1 else ""
    app_node = _esc(os.environ.get("NODE_NAME", "unknown"))

    page = HTML_TEMPLATE.format(
        app_node=app_node,
        db_status=db_status,
        db_color=db_color,
        db_version=_esc(db_version[:80]) if db_ok else "",
        flash=flash_html,
        table=table,
        count=count,
        plural=plural,
    )
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/ui/items", methods=["POST"])
def ui_create_item():
    """Handle form submission — create item in PostgreSQL."""
    name        = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not name:
        return redirect(url_for("index", msg="Item name is required.", type="error"))
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO items (name, description) VALUES (%s, %s) RETURNING id;",
                (name, description),
            )
            item_id = cur.fetchone()[0]
            cur.close()
        return redirect(url_for("index",
                                msg=f"Item '{name}' saved to PostgreSQL (id={item_id}) ✓",
                                type="success"))
    except Exception as exc:
        return redirect(url_for("index", msg=f"Error: {exc}", type="error"))


@app.route("/ui/items/<int:item_id>/edit", methods=["POST"])
def ui_edit_item(item_id):
    """Handle inline edit form — update item in PostgreSQL."""
    name        = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not name:
        return redirect(url_for("index", msg="Item name cannot be empty.", type="error"))
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE items SET name=%s, description=%s WHERE id=%s RETURNING id;",
                (name, description, item_id),
            )
            updated = cur.fetchone()
            cur.close()
        if updated:
            return redirect(url_for("index",
                                    msg=f"Item {item_id} updated ✓",
                                    type="success"))
        return redirect(url_for("index",
                                msg=f"Item {item_id} not found.",
                                type="error"))
    except Exception as exc:
        return redirect(url_for("index", msg=f"Error: {exc}", type="error"))


@app.route("/ui/items/<int:item_id>/delete", methods=["POST"])
def ui_delete_item(item_id):
    """Handle delete button — remove item from PostgreSQL."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM items WHERE id = %s RETURNING name;", (item_id,))
            deleted = cur.fetchone()
            cur.close()
        if deleted:
            return redirect(url_for("index",
                                    msg=f"Item '{deleted[0]}' deleted ✓",
                                    type="success"))
        return redirect(url_for("index",
                                msg=f"Item {item_id} not found.",
                                type="error"))
    except Exception as exc:
        return redirect(url_for("index", msg=f"Error: {exc}", type="error"))


# ---------------------------------------------------------------------------
# REST API routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/ready")
def ready():
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1;")
            cur.close()
        return jsonify({"status": "ready", "db": "connected"}), 200
    except Exception as exc:
        return jsonify({"status": "not ready", "db": str(exc)}), 503


@app.route("/arch")
def arch_info():
    db_ok, pg_version = get_db_info()
    return jsonify({
        "heterogeneous_demo": {
            "app_server": {
                "role": "Application Server + Web UI",
                "architecture": platform.machine(),
                "platform": platform.platform(),
                "node": os.environ.get("NODE_NAME", "unknown"),
                "pod": os.environ.get("POD_NAME", "unknown"),
                "arch_label": "ppc64le (IBM Power)",
            },
            "database": {
                "role": "Database Server (Crunchy PGO)",
                "architecture": "x86_64 (Intel)",
                "host": "hetero-pgcluster-primary.hetero-demo.svc.cluster.local",
                "port": 5432,
                "connected": db_ok,
                "postgres_version": pg_version,
            },
        }
    })


@app.route("/items", methods=["GET"])
def get_items_api():
    rows, err = get_items()
    if err:
        return jsonify({"error": err}), 500
    items = [
        {"id": r[0], "name": r[1], "description": r[2], "created_at": str(r[3])}
        for r in rows
    ]
    return jsonify({"items": items, "count": len(items)}), 200


@app.route("/items/<int:item_id>", methods=["GET"])
def get_item_api(item_id):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, description, created_at FROM items WHERE id = %s;",
                (item_id,),
            )
            row = cur.fetchone()
            cur.close()
        if row:
            return jsonify({
                "item": {
                    "id": row[0], "name": row[1],
                    "description": row[2], "created_at": str(row[3]),
                }
            }), 200
        return jsonify({"error": f"Item {item_id} not found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/items", methods=["POST"])
def create_item_api():
    data = request.get_json(silent=True)
    if not data or "name" not in data:
        return jsonify({"error": "Field 'name' is required"}), 400
    name        = str(data["name"]).strip()
    description = str(data.get("description", "")).strip()
    if not name:
        return jsonify({"error": "Field 'name' must not be blank"}), 400
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO items (name, description) VALUES (%s, %s)"
                " RETURNING id, name, description, created_at;",
                (name, description),
            )
            row = cur.fetchone()
            cur.close()
        return jsonify({
            "item": {
                "id": row[0], "name": row[1],
                "description": row[2], "created_at": str(row[3]),
            },
            "message": "Item created successfully",
        }), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/items/<int:item_id>", methods=["PUT"])
def update_item_api(item_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name        = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    if not name:
        return jsonify({"error": "Field 'name' must not be blank"}), 400
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE items SET name=%s, description=%s WHERE id=%s"
                " RETURNING id, name, description, created_at;",
                (name, description, item_id),
            )
            row = cur.fetchone()
            cur.close()
        if row:
            return jsonify({
                "item": {
                    "id": row[0], "name": row[1],
                    "description": row[2], "created_at": str(row[3]),
                },
                "message": "Item updated successfully",
            }), 200
        return jsonify({"error": f"Item {item_id} not found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/items/<int:item_id>", methods=["DELETE"])
def delete_item_api(item_id):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM items WHERE id = %s RETURNING id;", (item_id,))
            deleted = cur.fetchone()
            cur.close()
        if deleted:
            return jsonify({"message": f"Item {item_id} deleted"}), 200
        return jsonify({"error": f"Item {item_id} not found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)