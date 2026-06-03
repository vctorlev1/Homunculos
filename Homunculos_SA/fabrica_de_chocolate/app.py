import re
from flask import Flask, render_template, request, flash, session, redirect, url_for, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'chocontastica_super_secreta' # Chave de segurança para a sessão

# ==========================================
# 1. BANCO DE DADOS SIMULADO
# ==========================================
USUARIOS_CADASTRADOS = {
    'teste@gmail.com': {
        'senha_hash': generate_password_hash('Chocolate123!'),
        'nome': 'Willy Wonka'
    }
}

items_estoque = [
    {"id": 1, "nome": "Cacau em Pó", "categoria": "Ingrediente", "unidade": "kg", "quantidade": 150.0, "minimo": 50.0, "emoji": "🍫"},
    {"id": 2, "nome": "Açúcar", "categoria": "Ingrediente", "unidade": "kg", "quantidade": 30.0, "minimo": 40.0, "emoji": "🍬"},
    {"id": 3, "nome": "Caixa para Bombom", "categoria": "Embalagem", "unidade": "un", "quantidade": 200.0, "minimo": 50.0, "emoji": "📦"},
]
next_id = 4

# ==========================================
# 2. ROTAS DE LOGIN E AUTENTICAÇÃO
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        acao = request.form.get('acao')
        
        if acao == 'login':
            email = request.form.get('email', '').strip().lower()
            senha = request.form.get('senha', '')
            
            if email in USUARIOS_CADASTRADOS and check_password_hash(USUARIOS_CADASTRADOS[email]['senha_hash'], senha):
                session['usuario_logado'] = email
                # Redireciona para o estoque como tela principal após o login
                return redirect(url_for('estoque'))
            else:
                flash('E-mail ou senha incorretos.', 'error')
                return render_template('login.html', logado=False, email_preenchido=email)
                
    return render_template('login.html', logado=False)

@app.route('/logout')
def logout():
    session.pop('usuario_logado', None)
    return redirect(url_for('login'))

# ==========================================
# 3. ROTAS DAS TELAS (PROTEGIDAS POR LOGIN)
# ==========================================
# Verificador de segurança: se não tiver logado, manda pro login
def verificar_login():
    if 'usuario_logado' not in session:
        return True
    return False

@app.route('/estoque')
def estoque():
    if verificar_login(): return redirect(url_for('login'))
    return render_template('estoque.html')

@app.route('/acompanhar_entregas')
def acompanhar_entregas():
    if verificar_login(): return redirect(url_for('login'))
    return render_template('acompanhar_entregas.html')

@app.route('/liberacao_insumos')
def liberacao_insumos():
    if verificar_login(): return redirect(url_for('login'))
    return render_template('liberacao_insumos.html')

@app.route('/negociar_contrato')
def negociar_contrato():
    if verificar_login(): return redirect(url_for('login'))
    return render_template('negociar_contrato.html')

@app.route('/receber_materiais')
def receber_materiais():
    if verificar_login(): return redirect(url_for('login'))
    return render_template('receber_materiais.html')

# ==========================================
# 4. API DO ESTOQUE (Backend para o JavaScript)
# ==========================================
def get_status(item):
    if item["quantidade"] == 0: return "Esgotado"
    if item["quantidade"] <= item["minimo"]: return "Baixo"
    return "Normal"

def get_stats():
    total = len(items_estoque)
    baixo = sum(1 for i in items_estoque if 0 < i["quantidade"] <= i["minimo"])
    esgotado = sum(1 for i in items_estoque if i["quantidade"] == 0)
    return {"total": total, "baixo": baixo, "esgotado": esgotado}

@app.route("/api/items", methods=["GET"])
def api_get_items():
    res = [{**i, "status": get_status(i)} for i in items_estoque]
    return jsonify({"items": res, "stats": get_stats()})

@app.route("/api/items", methods=["POST"])
def api_create_item():
    global next_id
    data = request.json
    new_item = {
        "id": next_id,
        "nome": data["nome"],
        "categoria": data["categoria"],
        "unidade": data["unidade"],
        "quantidade": float(data["quantidade"]),
        "minimo": float(data.get("minimo", 10)),
        "emoji": data.get("emoji", "📦"),
    }
    items_estoque.append(new_item)
    next_id += 1
    return jsonify({"item": {**new_item, "status": get_status(new_item)}, "stats": get_stats()})

if __name__ == '__main__':
    app.run(debug=True)