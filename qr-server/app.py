"""
Hub Automacao Pro - Admin Panel
Painel de gestao de clientes multi-instancia.
"""
import os
import re
import logging
from functools import wraps
from flask import Flask, request, redirect, url_for, render_template, \
    flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

import db
import evolution

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-me-in-production')
BOT_WEBHOOK_URL = os.getenv('BOT_INTERNAL_URL', 'http://hub-bot:3000') + '/webhook'
ADMIN_DEFAULT_PASSWORD = os.getenv('ADMIN_DEFAULT_PASSWORD', 'admin123')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('hub-admin')


def slugify(text):
    """Converte nome para slug de instancia."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text[:50]


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped


def ensure_default_admin():
    """Cria admin padrao se nenhum existe."""
    if db.count_admin_users() == 0:
        db.create_admin_user('admin', generate_password_hash(ADMIN_DEFAULT_PASSWORD))
        log.info('Admin padrao criado (usuario: admin)')


# --- Auth ---

@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.get_admin_user(request.form.get('username', ''))
        if user and check_password_hash(user['password_hash'], request.form.get('password', '')):
            session['admin'] = user['username']
            return redirect(url_for('dashboard'), code=303)
        flash('Usuario ou senha incorretos', 'error')
    return render_template('login.html')


@app.route('/admin/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('login'))


# --- Dashboard ---

@app.route('/admin/dashboard')
@login_required
def dashboard():
    empresas = db.list_empresas()
    for e in empresas:
        m = db.get_mensagens_hoje(str(e['id']))
        e['msgs_hoje'] = m['total'] if m else 0
    empresa_ids = [str(e['id']) for e in empresas]
    empresa_instances = [e.get('whatsapp_instance', '') for e in empresas]
    return render_template('dashboard.html',
                           empresas=empresas,
                           empresa_ids=empresa_ids,
                           empresa_instances=empresa_instances)


@app.route('/admin/api/status/<empresa_id>')
@login_required
def api_status(empresa_id):
    empresa = db.get_empresa(empresa_id)
    if not empresa or not empresa.get('whatsapp_instance'):
        return jsonify({'state': 'unknown'})
    state = evolution.get_connection_state(empresa['whatsapp_instance'])
    result = {'state': state}
    if state != 'open':
        qr = evolution.get_qr_code(empresa['whatsapp_instance'])
        result['qr_base64'] = qr.get('base64', '')
    return jsonify(result)


# --- Clientes CRUD ---

@app.route('/admin/clients/new')
@login_required
def client_new():
    return render_template('client_form.html', empresa=None)


@app.route('/admin/clients', methods=['POST'])
@login_required
def client_create():
    nome = request.form.get('nome', '').strip()
    if not nome:
        flash('Nome e obrigatorio', 'error')
        return redirect(url_for('client_new'))

    instance = request.form.get('whatsapp_instance', '').strip()
    if not instance:
        instance = slugify(nome)

    system_prompt = request.form.get('system_prompt', '').strip()
    model = request.form.get('model', 'claude-3-haiku-20240307')
    max_tokens = int(request.form.get('max_tokens', 150))

    empresa = db.create_empresa(
        nome=nome,
        whatsapp_instance=instance,
        system_prompt=system_prompt,
        model=model,
        max_tokens=max_tokens,
        greeting_message=request.form.get('greeting_message', '').strip() or None,
        persona_name=request.form.get('persona_name', '').strip() or None,
        business_hours_start=request.form.get('business_hours_start') or None,
        business_hours_end=request.form.get('business_hours_end') or None,
        outside_hours_message=request.form.get('outside_hours_message', '').strip() or None,
        typing_delay_ms=int(request.form.get('typing_delay_ms', 800)),
        max_history_messages=int(request.form.get('max_history_messages', 10))
    )

    if not empresa:
        flash('Erro ao criar cliente (instancia ja existe?)', 'error')
        return redirect(url_for('client_new'))

    # Criar instancia na Evolution API
    result = evolution.create_instance(instance)
    if 'error' in result:
        log.warning(f'Erro ao criar instancia Evolution: {result}')
        flash(f'Cliente criado no banco mas erro na Evolution: {result.get("error", "")}', 'error')
    else:
        # Configurar webhook
        if evolution.set_webhook(instance, BOT_WEBHOOK_URL):
            db.set_webhook_configured(str(empresa['id']), True)
            flash(f'Cliente "{nome}" criado com sucesso!', 'success')
        else:
            flash(f'Cliente criado mas webhook falhou. Configure manualmente.', 'error')

    return redirect(url_for('client_detail', empresa_id=empresa['id']))


@app.route('/admin/clients/<empresa_id>')
@login_required
def client_detail(empresa_id):
    empresa = db.get_empresa(empresa_id)
    if not empresa:
        flash('Cliente nao encontrado', 'error')
        return redirect(url_for('dashboard'))
    consumo = db.get_consumo_empresa(empresa_id) or {}
    return render_template('client_detail.html', empresa=empresa, consumo=consumo)


@app.route('/admin/clients/<empresa_id>/edit')
@login_required
def client_edit(empresa_id):
    empresa = db.get_empresa(empresa_id)
    if not empresa:
        flash('Cliente nao encontrado', 'error')
        return redirect(url_for('dashboard'))
    return render_template('client_form.html', empresa=empresa)


@app.route('/admin/clients/<empresa_id>', methods=['POST'])
@login_required
def client_update(empresa_id):
    empresa = db.get_empresa(empresa_id)
    if not empresa:
        flash('Cliente nao encontrado', 'error')
        return redirect(url_for('dashboard'))

    db.update_empresa(empresa_id,
        nome=request.form.get('nome', '').strip(),
        system_prompt=request.form.get('system_prompt', '').strip(),
        model=request.form.get('model', 'claude-3-haiku-20240307'),
        max_tokens=int(request.form.get('max_tokens', 150)),
        greeting_message=request.form.get('greeting_message', '').strip() or None,
        persona_name=request.form.get('persona_name', '').strip() or None,
        business_hours_start=request.form.get('business_hours_start') or None,
        business_hours_end=request.form.get('business_hours_end') or None,
        outside_hours_message=request.form.get('outside_hours_message', '').strip() or None,
        typing_delay_ms=int(request.form.get('typing_delay_ms', 800)),
        max_history_messages=int(request.form.get('max_history_messages', 10))
    )
    flash('Configuracoes salvas', 'success')
    return redirect(url_for('client_detail', empresa_id=empresa_id))


@app.route('/admin/clients/<empresa_id>/connect', methods=['POST'])
@login_required
def client_connect(empresa_id):
    empresa = db.get_empresa(empresa_id)
    if not empresa:
        flash('Cliente nao encontrado', 'error')
        return redirect(url_for('dashboard'))

    instance = empresa['whatsapp_instance']
    state = evolution.get_connection_state(instance)

    if state == 'error' or state == 'unknown':
        # Instancia nao existe, criar
        evolution.create_instance(instance)

    if not empresa.get('webhook_configured'):
        if evolution.set_webhook(instance, BOT_WEBHOOK_URL):
            db.set_webhook_configured(empresa_id, True)

    flash('Instancia reconectada. Escaneie o QR code.', 'success')
    return redirect(url_for('client_detail', empresa_id=empresa_id))


@app.route('/admin/clients/<empresa_id>/disconnect', methods=['POST'])
@login_required
def client_disconnect(empresa_id):
    empresa = db.get_empresa(empresa_id)
    if empresa and empresa.get('whatsapp_instance'):
        evolution.logout_instance(empresa['whatsapp_instance'])
        flash('WhatsApp desconectado', 'success')
    return redirect(url_for('client_detail', empresa_id=empresa_id))


@app.route('/admin/clients/<empresa_id>/delete', methods=['POST'])
@login_required
def client_delete(empresa_id):
    empresa = db.get_empresa(empresa_id)
    if empresa:
        if empresa.get('whatsapp_instance'):
            evolution.delete_instance(empresa['whatsapp_instance'])
        db.deactivate_empresa(empresa_id)
        flash(f'Cliente "{empresa["nome"]}" desativado', 'success')
    return redirect(url_for('dashboard'))


# --- Consumo ---

@app.route('/admin/consumption')
@login_required
def consumption():
    consumos = db.get_consumo_global()
    return render_template('consumption.html', consumos=consumos)


# --- Public QR (para o cliente) ---

@app.route('/qr/<token>')
def public_qr(token):
    empresa = db.get_empresa_by_token(token)
    if not empresa:
        return 'Link invalido', 404
    return render_template('client_qr.html', empresa=empresa, token=token)


@app.route('/api/qr/<token>')
def api_qr(token):
    empresa = db.get_empresa_by_token(token)
    if not empresa or not empresa.get('whatsapp_instance'):
        return jsonify({'error': 'not found'}), 404

    instance = empresa['whatsapp_instance']
    state = evolution.get_connection_state(instance)

    if state == 'open':
        return jsonify({'state': 'open'})

    qr = evolution.get_qr_code(instance)
    return jsonify({
        'state': state,
        'base64': qr.get('base64', '')
    })


# --- Startup ---

if __name__ == '__main__':
    db.init_pool()
    ensure_default_admin()
    log.info('Admin Panel iniciado na porta 9615')
    app.run(host='0.0.0.0', port=9615)
