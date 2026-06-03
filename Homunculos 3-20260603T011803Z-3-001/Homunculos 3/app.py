"""
app.py – Backend Flask para o Sistema Cacaonnattenie / Omunculos
================================================================
Módulos cobertos
  • Autenticação  (login, cadastro, recuperação de senha)
  • Estoque       – CRUD + stats via /api/items
  • Entregas      – CRUD via /api/entregas
  • Liberação     – CRUD via /api/liberacoes
  • Contratos     – CRUD via /api/contratos
  • Recebimentos  – CRUD via /api/recebimentos

Banco de dados: SQLite (arquivo cacaonnattenie.db criado automaticamente)
Dependências  : flask, werkzeug  (pip install flask)
"""

import sqlite3
import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash

# ──────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omunculos-choco-secret-2024")

DATABASE = "cacaonnattenie.db"


# ──────────────────────────────────────────────
# BANCO DE DADOS
# ──────────────────────────────────────────────
def get_db():
    """Retorna a conexão com o banco, criando se necessário."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Cria todas as tabelas caso não existam."""
    db = get_db()

    # ── Usuários ──────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            nome     TEXT    NOT NULL,
            email    TEXT    NOT NULL UNIQUE,
            senha    TEXT    NOT NULL,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Estoque ───────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS estoque (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nome       TEXT    NOT NULL,
            categoria  TEXT    NOT NULL DEFAULT 'Ingrediente',
            unidade    TEXT    NOT NULL DEFAULT 'kg',
            quantidade REAL    NOT NULL DEFAULT 0,
            minimo     REAL    NOT NULL DEFAULT 10,
            emoji      TEXT    NOT NULL DEFAULT '🍫',
            criado_em  DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Entregas ──────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS entregas (
            id             TEXT PRIMARY KEY,
            fornecedor     TEXT NOT NULL,
            item           TEXT NOT NULL,
            qtd            TEXT,
            previsao       TEXT,
            previsao_iso   TEXT,
            transportadora TEXT,
            rastreio       TEXT,
            status         TEXT NOT NULL DEFAULT 'aguardando',
            obs            TEXT,
            criado_em      DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS entrega_eventos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entrega_id TEXT NOT NULL REFERENCES entregas(id) ON DELETE CASCADE,
            status     TEXT NOT NULL,
            label      TEXT NOT NULL,
            descricao  TEXT,
            criado_em  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Liberação de Insumos ──────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS liberacoes (
            id          TEXT PRIMARY KEY,
            insumo      TEXT NOT NULL,
            qtd         TEXT NOT NULL,
            solicitante TEXT NOT NULL,
            setor       TEXT NOT NULL,
            previsao    TEXT,
            previsao_iso TEXT,
            progresso   INTEGER NOT NULL DEFAULT 0,
            status      TEXT    NOT NULL DEFAULT 'Pendente',
            obs         TEXT,
            criado_em   DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Contratos ─────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS contratos (
            id             TEXT PRIMARY KEY,
            fornecedor     TEXT NOT NULL,
            volume         TEXT NOT NULL,
            preco          TEXT NOT NULL,
            duracao        TEXT NOT NULL DEFAULT '1 ANO',
            assinatura     TEXT,
            assinatura_iso TEXT,
            status         TEXT NOT NULL DEFAULT 'analise',
            obs            TEXT,
            criado_em      DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Recebimentos ──────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS recebimentos (
            id         TEXT PRIMARY KEY,
            fornecedor TEXT NOT NULL,
            data_arr   TEXT,
            data_iso   TEXT,
            item       TEXT NOT NULL,
            esp        TEXT NOT NULL,
            rec        TEXT,
            status     TEXT NOT NULL DEFAULT 'pending',
            obs        TEXT,
            criado_em  DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def login_required(f):
    """Decorator – redireciona para login se não autenticado."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "usuario_id" not in session:
            flash("Faça login para continuar.", "info")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def api_login_required(f):
    """Decorator para rotas de API – retorna 401 JSON se não autenticado."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "usuario_id" not in session:
            return jsonify({"error": "Não autenticado"}), 401
        return f(*args, **kwargs)
    return decorated


def estoque_status(quantidade, minimo):
    if quantidade <= 0:
        return "sem_estoque"
    if quantidade <= minimo:
        return "estoque_baixo"
    return "em_estoque"


def calcular_stats_estoque(db):
    items = db.execute("SELECT quantidade, minimo FROM estoque").fetchall()
    stats = {"total": len(items), "em_estoque": 0, "estoque_baixo": 0, "sem_estoque": 0}
    for it in items:
        s = estoque_status(it["quantidade"], it["minimo"])
        stats[s] += 1
    return stats


def next_id(db, table, prefix, id_col="id", pad=3):
    """Gera o próximo ID sequencial no formato PREFIX001."""
    row = db.execute(f"SELECT {id_col} FROM {table} ORDER BY {id_col} DESC LIMIT 1").fetchone()
    if not row:
        return f"{prefix}{str(1).zfill(pad)}"
    last = row[0].replace(prefix, "")
    try:
        return f"{prefix}{str(int(last) + 1).zfill(pad)}"
    except ValueError:
        return f"{prefix}001"


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# ROTAS – AUTENTICAÇÃO
# ──────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    """Página principal: login / cadastro / recuperação de senha."""
    with app.app_context():
        init_db()

    logado = "usuario_id" in session
    nome_usuario = session.get("nome_usuario", "")

    if logado:
        return render_template("index.html", logado=True, nome_usuario=nome_usuario)

    if request.method == "GET":
        return render_template(
            "index.html", logado=False,
            email_preenchido="", mostrar_aba=None, abrir_modal_recuperacao=False
        )

    acao = request.form.get("acao")

    # ── LOGIN ──────────────────────────────────
    if acao == "login":
        email = request.form.get("email_login", "").strip().lower()
        senha = request.form.get("senha_login", "")

        db = get_db()
        usuario = db.execute(
            "SELECT * FROM usuarios WHERE email = ?", (email,)
        ).fetchone()

        if not usuario or not check_password_hash(usuario["senha"], senha):
            flash("E-mail ou senha incorretos.", "error")
            return render_template(
                "index.html", logado=False,
                email_preenchido=email, mostrar_aba=None, abrir_modal_recuperacao=False
            )

        session.permanent = True
        session["usuario_id"] = usuario["id"]
        session["nome_usuario"] = usuario["nome"]
        return redirect(url_for("index"))

    # ── CADASTRO ───────────────────────────────
    elif acao == "cadastro":
        nome = request.form.get("nome_cadastro", "").strip()
        email = request.form.get("email_cadastro", "").strip().lower()
        senha = request.form.get("senha_cadastro", "")
        confirmar = request.form.get("confirmar_senha_cadastro", "")

        erros = []
        if len(senha) < 8:
            erros.append("A senha deve ter pelo menos 8 caracteres.")
        if senha != confirmar:
            erros.append("As senhas não coincidem.")

        if erros:
            for e in erros:
                flash(e, "error")
            return render_template(
                "index.html", logado=False,
                email_preenchido=email, mostrar_aba="cadastro", abrir_modal_recuperacao=False
            )

        db = get_db()
        existente = db.execute(
            "SELECT id FROM usuarios WHERE email = ?", (email,)
        ).fetchone()

        if existente:
            flash("Este e-mail já está cadastrado. Faça o login.", "error")
            return render_template(
                "index.html", logado=False,
                email_preenchido=email, mostrar_aba=None, abrir_modal_recuperacao=False
            )

        senha_hash = generate_password_hash(senha)
        db.execute(
            "INSERT INTO usuarios (nome, email, senha) VALUES (?, ?, ?)",
            (nome, email, senha_hash)
        )
        db.commit()

        flash("Conta criada com sucesso! Faça o login.", "success")
        return render_template(
            "index.html", logado=False,
            email_preenchido=email, mostrar_aba=None, abrir_modal_recuperacao=False
        )

    # ── ESQUECI MINHA SENHA ────────────────────
    elif acao == "esqueci_senha":
        email = request.form.get("email_recuperacao", "").strip().lower()
        db = get_db()
        usuario = db.execute(
            "SELECT id FROM usuarios WHERE email = ?", (email,)
        ).fetchone()

        if usuario:
            flash(
                f"E-mail encontrado! Em produção, um link de redefinição seria enviado para {email}.",
                "success"
            )
        else:
            flash("Nenhuma conta encontrada com este e-mail.", "error")
            return render_template(
                "index.html", logado=False,
                email_preenchido="", mostrar_aba=None, abrir_modal_recuperacao=True
            )

        return render_template(
            "index.html", logado=False,
            email_preenchido="", mostrar_aba=None, abrir_modal_recuperacao=False
        )

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu da conta com sucesso.", "info")
    return redirect(url_for("index"))


# ──────────────────────────────────────────────
# ROTAS – PÁGINAS HTML (servir os templates)
# ──────────────────────────────────────────────
@app.route("/estoque")
@login_required
def estoque():
    return render_template("estoque.html")


@app.route("/entregas")
@login_required
def entregas():
    return render_template("acompanhar_entregas.html")


@app.route("/liberacao")
@login_required
def liberacao():
    return render_template("liberacao_insumos.html")


@app.route("/contratos")
@login_required
def contratos():
    return render_template("negociar_contrato.html")


@app.route("/recebimentos")
@login_required
def recebimentos():
    return render_template("receber_materiais.html")


# ══════════════════════════════════════════════
# API – ESTOQUE
# ══════════════════════════════════════════════
@app.route("/api/items", methods=["GET"])
@api_login_required
def api_items_list():
    db = get_db()
    q = request.args.get("q", "").strip()
    categoria = request.args.get("categoria", "").strip()

    query = "SELECT * FROM estoque WHERE 1=1"
    params = []

    if q:
        query += " AND (LOWER(nome) LIKE ? OR LOWER(categoria) LIKE ?)"
        params += [f"%{q.lower()}%", f"%{q.lower()}%"]
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)

    query += " ORDER BY id DESC"
    items_raw = db.execute(query, params).fetchall()

    items = []
    for it in items_raw:
        d = dict(it)
        d["status"] = estoque_status(d["quantidade"], d["minimo"])
        items.append(d)

    stats = calcular_stats_estoque(db)
    atualizado = datetime.now().strftime("%d/%m/%Y %H:%M")

    return jsonify({"items": items, "stats": stats, "updated_at": atualizado})


@app.route("/api/items", methods=["POST"])
@api_login_required
def api_items_create():
    db = get_db()
    data = request.get_json(force=True)

    nome = data.get("nome", "").strip()
    if not nome:
        return jsonify({"error": "Nome é obrigatório"}), 400

    db.execute(
        """INSERT INTO estoque (nome, categoria, unidade, quantidade, minimo, emoji)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            nome,
            data.get("categoria", "Ingrediente"),
            data.get("unidade", "kg"),
            float(data.get("quantidade", 0)),
            float(data.get("minimo", 10)),
            data.get("emoji", "🍫"),
        )
    )
    db.commit()

    stats = calcular_stats_estoque(db)
    return jsonify({"ok": True, "stats": stats}), 201


@app.route("/api/items/<int:item_id>", methods=["PUT"])
@api_login_required
def api_items_update(item_id):
    db = get_db()
    data = request.get_json(force=True)

    nome = data.get("nome", "").strip()
    if not nome:
        return jsonify({"error": "Nome é obrigatório"}), 400

    db.execute(
        """UPDATE estoque
           SET nome=?, categoria=?, unidade=?, quantidade=?, minimo=?, emoji=?,
               atualizado_em=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            nome,
            data.get("categoria", "Ingrediente"),
            data.get("unidade", "kg"),
            float(data.get("quantidade", 0)),
            float(data.get("minimo", 10)),
            data.get("emoji", "🍫"),
            item_id,
        )
    )
    db.commit()

    stats = calcular_stats_estoque(db)
    return jsonify({"ok": True, "stats": stats})


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
@api_login_required
def api_items_delete(item_id):
    db = get_db()
    db.execute("DELETE FROM estoque WHERE id=?", (item_id,))
    db.commit()
    stats = calcular_stats_estoque(db)
    return jsonify({"ok": True, "stats": stats})


# ══════════════════════════════════════════════
# API – ENTREGAS
# ══════════════════════════════════════════════
STATUS_ENTREGA_PCT = {
    "aguardando": 0, "transito": 55, "parcial": 70,
    "entregue": 100, "atraso": 40, "cancelado": 0,
}
STATUS_ENTREGA_LABEL = {
    "aguardando": "Aguardando Coleta", "transito": "Em Trânsito",
    "parcial": "Entrega Parcial", "entregue": "Entregue",
    "atraso": "Com Atraso", "cancelado": "Cancelado",
}


def _entrega_stats(db):
    rows = db.execute("SELECT status FROM entregas").fetchall()
    s = {"total": len(rows), "transito": 0, "entregue": 0, "atraso": 0, "aguardando": 0}
    for r in rows:
        key = r["status"]
        if key in s:
            s[key] += 1
    return s


def _entrega_to_dict(row, db):
    d = dict(row)
    d["pct"] = STATUS_ENTREGA_PCT.get(d["status"], 0)
    eventos = db.execute(
        "SELECT status, label, descricao AS desc, criado_em AS data FROM entrega_eventos "
        "WHERE entrega_id=? ORDER BY id ASC", (d["id"],)
    ).fetchall()
    d["eventos"] = rows_to_list(eventos)
    return d


@app.route("/api/entregas", methods=["GET"])
@api_login_required
def api_entregas_list():
    db = get_db()
    q = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "").strip()

    query = "SELECT * FROM entregas WHERE 1=1"
    params = []
    if q:
        query += " AND (LOWER(id) LIKE ? OR LOWER(fornecedor) LIKE ? OR LOWER(item) LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY criado_em DESC"

    rows = db.execute(query, params).fetchall()
    items = [_entrega_to_dict(r, db) for r in rows]
    return jsonify({"items": items, "stats": _entrega_stats(db)})


@app.route("/api/entregas", methods=["POST"])
@api_login_required
def api_entregas_create():
    db = get_db()
    data = request.get_json(force=True)

    fornecedor = data.get("fornecedor", "").strip()
    item = data.get("item", "").strip()
    if not fornecedor or not item:
        return jsonify({"error": "fornecedor e item são obrigatórios"}), 400

    eid = next_id(db, "entregas", "ENT")
    status = data.get("status", "aguardando")
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    db.execute(
        """INSERT INTO entregas
           (id, fornecedor, item, qtd, previsao, previsao_iso, transportadora, rastreio, status, obs)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            eid, fornecedor, item,
            data.get("qtd", ""),
            data.get("previsao", ""),
            data.get("previsaoISO", ""),
            data.get("transportadora", ""),
            data.get("rastreio", ""),
            status,
            data.get("obs", ""),
        )
    )
    db.execute(
        "INSERT INTO entrega_eventos (entrega_id, status, label, descricao, criado_em) VALUES (?,?,?,?,?)",
        (eid, status, STATUS_ENTREGA_LABEL.get(status, status),
         "Entrega registrada no sistema", agora)
    )
    db.commit()

    row = db.execute("SELECT * FROM entregas WHERE id=?", (eid,)).fetchone()
    return jsonify({"item": _entrega_to_dict(row, db), "stats": _entrega_stats(db)}), 201


@app.route("/api/entregas/<eid>", methods=["PUT"])
@api_login_required
def api_entregas_update(eid):
    db = get_db()
    data = request.get_json(force=True)

    db.execute(
        """UPDATE entregas SET fornecedor=?, item=?, qtd=?, previsao=?, previsao_iso=?,
           transportadora=?, rastreio=?, status=?, obs=?, atualizado_em=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            data.get("fornecedor", ""),
            data.get("item", ""),
            data.get("qtd", ""),
            data.get("previsao", ""),
            data.get("previsaoISO", ""),
            data.get("transportadora", ""),
            data.get("rastreio", ""),
            data.get("status", "aguardando"),
            data.get("obs", ""),
            eid,
        )
    )

    # Registra evento se status foi informado
    if "status" in data:
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        status = data["status"]
        db.execute(
            "INSERT INTO entrega_eventos (entrega_id, status, label, descricao, criado_em) VALUES (?,?,?,?,?)",
            (eid, status, STATUS_ENTREGA_LABEL.get(status, status),
             data.get("desc", "Dados atualizados"), agora)
        )

    db.commit()
    row = db.execute("SELECT * FROM entregas WHERE id=?", (eid,)).fetchone()
    return jsonify({"item": _entrega_to_dict(row, db), "stats": _entrega_stats(db)})


@app.route("/api/entregas/<eid>", methods=["DELETE"])
@api_login_required
def api_entregas_delete(eid):
    db = get_db()
    db.execute("DELETE FROM entregas WHERE id=?", (eid,))
    db.commit()
    return jsonify({"ok": True, "stats": _entrega_stats(db)})


@app.route("/api/entregas/<eid>/eventos", methods=["POST"])
@api_login_required
def api_entregas_add_evento(eid):
    """Adiciona um evento de rastreamento a uma entrega."""
    db = get_db()
    data = request.get_json(force=True)
    status = data.get("status", "")
    desc = data.get("desc", STATUS_ENTREGA_LABEL.get(status, status))
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    db.execute(
        "INSERT INTO entrega_eventos (entrega_id, status, label, descricao, criado_em) VALUES (?,?,?,?,?)",
        (eid, status, STATUS_ENTREGA_LABEL.get(status, status), desc, agora)
    )
    # Atualiza status da entrega
    db.execute(
        "UPDATE entregas SET status=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=?",
        (status, eid)
    )
    db.commit()

    row = db.execute("SELECT * FROM entregas WHERE id=?", (eid,)).fetchone()
    return jsonify({"item": _entrega_to_dict(row, db), "stats": _entrega_stats(db)})


# ══════════════════════════════════════════════
# API – LIBERAÇÃO DE INSUMOS
# ══════════════════════════════════════════════
PROGRESSO_POR_STATUS = {
    "Pendente": 10, "Aprovado": 40, "Separando": 65,
    "Liberado": 100, "Cancelado": 0,
}


def _lib_stats(db):
    rows = db.execute("SELECT status FROM liberacoes").fetchall()
    s = {"total": len(rows), "Pendente": 0, "Aprovado": 0,
         "Separando": 0, "Liberado": 0, "Cancelado": 0}
    for r in rows:
        k = r["status"]
        if k in s:
            s[k] += 1
    return s


@app.route("/api/liberacoes", methods=["GET"])
@api_login_required
def api_liberacoes_list():
    db = get_db()
    q = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "").strip()

    query = "SELECT * FROM liberacoes WHERE 1=1"
    params = []
    if q:
        query += " AND (LOWER(id) LIKE ? OR LOWER(insumo) LIKE ? OR LOWER(solicitante) LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY criado_em DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify({"items": rows_to_list(rows), "stats": _lib_stats(db)})


@app.route("/api/liberacoes", methods=["POST"])
@api_login_required
def api_liberacoes_create():
    db = get_db()
    data = request.get_json(force=True)

    obrigatorios = ["insumo", "qtd", "solicitante", "setor"]
    for campo in obrigatorios:
        if not data.get(campo, "").strip():
            return jsonify({"error": f"'{campo}' é obrigatório"}), 400

    lid = next_id(db, "liberacoes", "INS")
    status = data.get("status", "Pendente")
    progresso = PROGRESSO_POR_STATUS.get(status, 0)

    db.execute(
        """INSERT INTO liberacoes
           (id, insumo, qtd, solicitante, setor, previsao, previsao_iso, progresso, status, obs)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            lid,
            data["insumo"].strip(),
            data["qtd"].strip(),
            data["solicitante"].strip(),
            data["setor"].strip(),
            data.get("data", ""),
            data.get("dataISO", ""),
            progresso,
            status,
            data.get("obs", ""),
        )
    )
    db.commit()

    row = db.execute("SELECT * FROM liberacoes WHERE id=?", (lid,)).fetchone()
    return jsonify({"item": row_to_dict(row), "stats": _lib_stats(db)}), 201


@app.route("/api/liberacoes/<lid>", methods=["PUT"])
@api_login_required
def api_liberacoes_update(lid):
    db = get_db()
    data = request.get_json(force=True)
    status = data.get("status", "Pendente")
    progresso = data.get("progresso", PROGRESSO_POR_STATUS.get(status, 0))

    db.execute(
        """UPDATE liberacoes
           SET insumo=?, qtd=?, solicitante=?, setor=?, previsao=?, previsao_iso=?,
               progresso=?, status=?, obs=?, atualizado_em=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            data.get("insumo", ""),
            data.get("qtd", ""),
            data.get("solicitante", ""),
            data.get("setor", ""),
            data.get("data", ""),
            data.get("dataISO", ""),
            int(progresso),
            status,
            data.get("obs", ""),
            lid,
        )
    )
    db.commit()

    row = db.execute("SELECT * FROM liberacoes WHERE id=?", (lid,)).fetchone()
    return jsonify({"item": row_to_dict(row), "stats": _lib_stats(db)})


@app.route("/api/liberacoes/<lid>", methods=["DELETE"])
@api_login_required
def api_liberacoes_delete(lid):
    db = get_db()
    db.execute("DELETE FROM liberacoes WHERE id=?", (lid,))
    db.commit()
    return jsonify({"ok": True, "stats": _lib_stats(db)})


# ══════════════════════════════════════════════
# API – CONTRATOS
# ══════════════════════════════════════════════
def _contrato_stats(db):
    rows = db.execute("SELECT status, volume, preco FROM contratos").fetchall()
    ativos = sum(1 for r in rows if r["status"] in ("assinado", "aprovado"))
    analise = sum(1 for r in rows if r["status"] == "analise")
    volumes = [float(r["volume"]) for r in rows if r["volume"]]
    precos = [float(r["preco"]) for r in rows if r["preco"]]
    total_vol = round(sum(volumes), 1)
    avg_preco = (f"R$ {sum(precos)/len(precos):.2f}") if precos else "—"
    return {"ativos": ativos, "analise": analise, "volume": total_vol, "preco": avg_preco}


@app.route("/api/contratos", methods=["GET"])
@api_login_required
def api_contratos_list():
    db = get_db()
    status = request.args.get("status", "").strip()

    query = "SELECT * FROM contratos"
    params = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY criado_em DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify({"items": rows_to_list(rows), "stats": _contrato_stats(db)})


@app.route("/api/contratos", methods=["POST"])
@api_login_required
def api_contratos_create():
    db = get_db()
    data = request.get_json(force=True)

    for campo in ["fornecedor", "volume", "preco"]:
        if not str(data.get(campo, "")).strip():
            return jsonify({"error": f"'{campo}' é obrigatório"}), 400

    cid = next_id(db, "contratos", "CTR", pad=5)
    db.execute(
        """INSERT INTO contratos
           (id, fornecedor, volume, preco, duracao, assinatura, assinatura_iso, status, obs)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            cid,
            data["fornecedor"].strip(),
            str(data["volume"]).strip(),
            str(data["preco"]).strip(),
            data.get("duracao", "1 ANO"),
            data.get("assinatura", ""),
            data.get("assinaturaISO", ""),
            data.get("status", "analise"),
            data.get("obs", ""),
        )
    )
    db.commit()

    row = db.execute("SELECT * FROM contratos WHERE id=?", (cid,)).fetchone()
    return jsonify({"item": row_to_dict(row), "stats": _contrato_stats(db)}), 201


@app.route("/api/contratos/<cid>", methods=["PUT"])
@api_login_required
def api_contratos_update(cid):
    db = get_db()
    data = request.get_json(force=True)

    db.execute(
        """UPDATE contratos
           SET fornecedor=?, volume=?, preco=?, duracao=?, assinatura=?, assinatura_iso=?,
               status=?, obs=?, atualizado_em=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            data.get("fornecedor", ""),
            str(data.get("volume", "")),
            str(data.get("preco", "")),
            data.get("duracao", "1 ANO"),
            data.get("assinatura", ""),
            data.get("assinaturaISO", ""),
            data.get("status", "analise"),
            data.get("obs", ""),
            cid,
        )
    )
    db.commit()

    row = db.execute("SELECT * FROM contratos WHERE id=?", (cid,)).fetchone()
    return jsonify({"item": row_to_dict(row), "stats": _contrato_stats(db)})


@app.route("/api/contratos/<cid>", methods=["DELETE"])
@api_login_required
def api_contratos_delete(cid):
    db = get_db()
    db.execute("DELETE FROM contratos WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True, "stats": _contrato_stats(db)})


# ══════════════════════════════════════════════
# API – RECEBIMENTOS
# ══════════════════════════════════════════════
def _receb_stats(db):
    rows = db.execute("SELECT status FROM recebimentos").fetchall()
    total = len(rows)
    insp = sum(1 for r in rows if r["status"] == "pending")
    div = sum(1 for r in rows if r["status"] == "diverge")
    return {"total": total, "inspecoes": insp, "divergencias": div}


@app.route("/api/recebimentos", methods=["GET"])
@api_login_required
def api_recebimentos_list():
    db = get_db()
    q = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "").strip()

    query = "SELECT * FROM recebimentos WHERE 1=1"
    params = []
    if q:
        query += " AND (LOWER(id) LIKE ? OR LOWER(fornecedor) LIKE ? OR LOWER(item) LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY criado_em DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify({"items": rows_to_list(rows), "stats": _receb_stats(db)})


@app.route("/api/recebimentos", methods=["POST"])
@api_login_required
def api_recebimentos_create():
    db = get_db()
    data = request.get_json(force=True)

    for campo in ["fornecedor", "item", "esp"]:
        if not str(data.get(campo, "")).strip():
            return jsonify({"error": f"'{campo}' é obrigatório"}), 400

    rid = next_id(db, "recebimentos", "REC")
    db.execute(
        """INSERT INTO recebimentos
           (id, fornecedor, data_arr, data_iso, item, esp, rec, status, obs)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            rid,
            data["fornecedor"].strip(),
            data.get("data", ""),
            data.get("dataISO", ""),
            data["item"].strip(),
            data["esp"].strip(),
            data.get("rec", ""),
            data.get("status", "pending"),
            data.get("obs", ""),
        )
    )
    db.commit()

    row = db.execute("SELECT * FROM recebimentos WHERE id=?", (rid,)).fetchone()
    return jsonify({"item": row_to_dict(row), "stats": _receb_stats(db)}), 201


@app.route("/api/recebimentos/<rid>", methods=["PUT"])
@api_login_required
def api_recebimentos_update(rid):
    db = get_db()
    data = request.get_json(force=True)

    db.execute(
        """UPDATE recebimentos
           SET fornecedor=?, data_arr=?, data_iso=?, item=?, esp=?, rec=?, status=?, obs=?,
               atualizado_em=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            data.get("fornecedor", ""),
            data.get("data", ""),
            data.get("dataISO", ""),
            data.get("item", ""),
            data.get("esp", ""),
            data.get("rec", ""),
            data.get("status", "pending"),
            data.get("obs", ""),
            rid,
        )
    )
    db.commit()

    row = db.execute("SELECT * FROM recebimentos WHERE id=?", (rid,)).fetchone()
    return jsonify({"item": row_to_dict(row), "stats": _receb_stats(db)})


@app.route("/api/recebimentos/<rid>", methods=["DELETE"])
@api_login_required
def api_recebimentos_delete(rid):
    db = get_db()
    db.execute("DELETE FROM recebimentos WHERE id=?", (rid,))
    db.commit()
    return jsonify({"ok": True, "stats": _receb_stats(db)})


# ──────────────────────────────────────────────
# UTILITÁRIO – limpar banco (dev only)
# ──────────────────────────────────────────────
@app.route("/api/dev/reset", methods=["POST"])
def dev_reset():
    """Remove e recria o banco. Usar apenas em desenvolvimento."""
    if app.debug:
        if os.path.exists(DATABASE):
            os.remove(DATABASE)
        with app.app_context():
            init_db()
        return jsonify({"ok": True, "message": "Banco resetado."})
    return jsonify({"error": "Disponível apenas em modo debug"}), 403


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)