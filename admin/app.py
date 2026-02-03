"""Hub Automacao Pro - Admin Panel with RBAC.

Roles:
- super_admin: sees all tenants, manages everything
- admin: sees only their own tenant
- viewer: read-only access to their tenant
"""

import os
import re
import logging
from functools import wraps
from flask import Flask, request, redirect, url_for, render_template, \
    flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin import db as admin_db
from app.channels import whatsapp

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-me-in-production')


@app.context_processor
def inject_globals():
    return {
        'is_super_admin': session.get('role') == 'super_admin' if session.get('admin') else False,
    }
BOT_WEBHOOK_URL = os.getenv('BOT_INTERNAL_URL', 'http://hub-bot:3000') + '/webhook'
ADMIN_DEFAULT_PASSWORD = os.getenv('ADMIN_DEFAULT_PASSWORD', 'admin123')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('hub-admin')


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text[:50]


# --- Auth decorators ---

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped


def super_admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('login'))
        if session.get('role') != 'super_admin':
            flash('Acesso restrito a super admin', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapped


def _get_user_tenant_id():
    """Get the tenant_id for the current user. None for super_admin."""
    return session.get('tenant_id')


def _can_access_tenant(tenant_id):
    """Check if current user can access a specific tenant."""
    if session.get('role') == 'super_admin':
        return True
    return str(session.get('tenant_id')) == str(tenant_id)


def ensure_default_admin():
    if admin_db.count_admin_users() == 0:
        admin_db.create_admin_user('admin', generate_password_hash(ADMIN_DEFAULT_PASSWORD))
        log.info('Default admin created (username: admin)')


# --- Auth Routes ---

@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = admin_db.get_admin_user(request.form.get('username', ''))
        if user and check_password_hash(user['password_hash'], request.form.get('password', '')):
            session['admin'] = user['username']
            session['role'] = user.get('role', 'admin')
            session['tenant_id'] = str(user['tenant_id']) if user.get('tenant_id') else None
            return redirect(url_for('dashboard'), code=303)
        flash('Usuario ou senha incorretos', 'error')
    return render_template('login.html')


@app.route('/admin/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- Dashboard ---

@app.route('/admin/dashboard')
@login_required
def dashboard():
    user_tenant = _get_user_tenant_id()
    tenants = admin_db.list_tenants(tenant_id=user_tenant)

    for t in tenants:
        accounts = admin_db.list_whatsapp_accounts(str(t['id']))
        t['accounts'] = accounts
        m = admin_db.get_messages_today(str(t['id']))
        t['msgs_today'] = m['total'] if m else 0

    return render_template('dashboard.html',
                           tenants=tenants,
                           is_super_admin=session.get('role') == 'super_admin')


# --- Clients Management ---

@app.route('/admin/clients')
@login_required
def clients():
    user_tenant = _get_user_tenant_id()
    is_super = session.get('role') == 'super_admin'

    if is_super:
        tenants = admin_db.get_tenants_with_stats()
    else:
        tenants = admin_db.list_tenants(tenant_id=user_tenant)
        # Add basic stats for scoped admin
        for t in tenants:
            accounts = admin_db.list_whatsapp_accounts(str(t['id']))
            t['instance_count'] = len(accounts)
            m = admin_db.get_messages_today(str(t['id']))
            t['msgs_today'] = m['total'] if m else 0
            t['cost_30d'] = 0
            t['ai_cost'] = 0
            t['tts_cost'] = 0
            t['stt_cost'] = 0
            t['total_conversations'] = 0

    return render_template('clients.html',
                           tenants=tenants,
                           is_super_admin=is_super)


# --- Tenant Management ---

@app.route('/admin/tenants/new')
@login_required
def tenant_new():
    return render_template('tenant_form.html', tenant=None)


def _build_persona_from_form():
    """Extract persona + voice config from form fields."""
    persona = {}
    if request.form.get('persona_name'):
        persona['name'] = request.form['persona_name'].strip()
    if request.form.get('persona_role'):
        persona['role'] = request.form['persona_role'].strip()
    if request.form.get('persona_tone'):
        persona['tone'] = request.form['persona_tone'].strip()
    if request.form.get('persona_gender'):
        persona['gender'] = request.form['persona_gender']
    if request.form.get('persona_age_range'):
        persona['age_range'] = request.form['persona_age_range']

    # Voice config (nested inside persona)
    voice = {}
    voice['enabled'] = request.form.get('voice_enabled') == 'true'
    voice['tts_voice'] = request.form.get('voice_tts_voice', 'echo')
    voice['speed'] = float(request.form.get('voice_speed', 1.0))
    voice['default_language'] = request.form.get('voice_language', 'pt')
    persona['voice'] = voice

    return persona


def _get_tools_from_form():
    """Extract enabled tools from form checkboxes."""
    tools = request.form.getlist('tools')
    return tools if tools else ['web_search']


@app.route('/admin/tenants', methods=['POST'])
@login_required
def tenant_create():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Nome e obrigatorio', 'error')
        return redirect(url_for('tenant_new'))

    slug = request.form.get('slug', '').strip() or slugify(name)

    # API key override
    api_key = request.form.get('anthropic_api_key', '').strip() or None

    tenant = admin_db.create_tenant(name, slug, api_key=api_key)
    if not tenant:
        flash('Erro ao criar cliente (slug ja existe?)', 'error')
        return redirect(url_for('tenant_new'))

    # Create agent config with full persona + voice + tools
    persona = _build_persona_from_form()
    tools = _get_tools_from_form()

    admin_db.upsert_agent_config(
        tenant_id=str(tenant['id']),
        system_prompt=request.form.get('system_prompt', ''),
        model=request.form.get('model', 'claude-sonnet-4-20250514'),
        max_tokens=int(request.form.get('max_tokens', 150)),
        max_history_messages=int(request.form.get('max_history_messages', 10)),
        persona=persona,
        tools_enabled=tools,
    )

    flash(f'Cliente "{name}" criado com sucesso!', 'success')
    return redirect(url_for('tenant_detail', tenant_id=tenant['id']), code=303)


@app.route('/admin/tenants/<tenant_id>')
@login_required
def tenant_detail(tenant_id):
    if not _can_access_tenant(tenant_id):
        flash('Acesso negado', 'error')
        return redirect(url_for('dashboard'))

    tenant = admin_db.get_tenant(tenant_id)
    if not tenant:
        flash('Tenant nao encontrado', 'error')
        return redirect(url_for('dashboard'))

    accounts = admin_db.list_whatsapp_accounts(tenant_id)
    agent_config = admin_db.get_agent_config(tenant_id)
    consumption = admin_db.get_consumption(tenant_id)
    consumption_by_op = admin_db.get_consumption_by_operation(tenant_id)

    return render_template('tenant_detail.html',
                           tenant=tenant,
                           accounts=accounts,
                           agent_config=agent_config,
                           consumption=consumption,
                           consumption_by_op=consumption_by_op)


@app.route('/admin/tenants/<tenant_id>/edit')
@login_required
def tenant_edit(tenant_id):
    if not _can_access_tenant(tenant_id):
        flash('Acesso negado', 'error')
        return redirect(url_for('dashboard'))

    tenant = admin_db.get_tenant(tenant_id)
    agent_config = admin_db.get_agent_config(tenant_id)
    return render_template('tenant_form.html', tenant=tenant, agent_config=agent_config)


@app.route('/admin/tenants/<tenant_id>', methods=['POST'])
@login_required
def tenant_update(tenant_id):
    if not _can_access_tenant(tenant_id):
        flash('Acesso negado', 'error')
        return redirect(url_for('dashboard'))

    # Update tenant fields
    update_fields = {'name': request.form.get('name', '').strip()}
    if request.form.get('status'):
        update_fields['status'] = request.form['status']

    # API key override
    api_key = request.form.get('anthropic_api_key', '').strip()
    if api_key:
        update_fields['anthropic_api_key'] = api_key

    admin_db.update_tenant(tenant_id, **update_fields)

    # Update agent config with full persona + voice + tools
    persona = _build_persona_from_form()
    tools = _get_tools_from_form()

    admin_db.upsert_agent_config(
        tenant_id=tenant_id,
        system_prompt=request.form.get('system_prompt', ''),
        model=request.form.get('model', 'claude-sonnet-4-20250514'),
        max_tokens=int(request.form.get('max_tokens', 150)),
        max_history_messages=int(request.form.get('max_history_messages', 10)),
        persona=persona,
        tools_enabled=tools,
    )

    flash('Configuracoes salvas!', 'success')
    return redirect(url_for('tenant_detail', tenant_id=tenant_id), code=303)


# --- WhatsApp Account Management ---

@app.route('/admin/tenants/<tenant_id>/accounts/new', methods=['POST'])
@login_required
def account_create(tenant_id):
    if not _can_access_tenant(tenant_id):
        flash('Acesso negado', 'error')
        return redirect(url_for('dashboard'))

    instance_name = request.form.get('instance_name', '').strip()
    if not instance_name:
        flash('Nome da instancia e obrigatorio', 'error')
        return redirect(url_for('tenant_detail', tenant_id=tenant_id))

    account = admin_db.create_whatsapp_account(tenant_id, instance_name)
    if not account:
        flash('Erro ao criar instancia (ja existe?)', 'error')
        return redirect(url_for('tenant_detail', tenant_id=tenant_id))

    # Create instance on Evolution API
    result = whatsapp.create_instance(instance_name)
    if 'error' not in result:
        if whatsapp.set_webhook(instance_name, BOT_WEBHOOK_URL):
            admin_db.set_webhook_configured(str(account['id']), True)
            flash(f'Instancia "{instance_name}" criada!', 'success')
        else:
            flash('Instancia criada mas webhook falhou', 'error')
    else:
        flash(f'Erro na Evolution: {result.get("error", "")}', 'error')

    return redirect(url_for('tenant_detail', tenant_id=tenant_id))


@app.route('/admin/api/status/<account_id>')
@login_required
def api_status(account_id):
    account = admin_db.get_whatsapp_account(account_id)
    if not account:
        return jsonify({'state': 'unknown'})

    if not _can_access_tenant(account.get('tenant_id')):
        return jsonify({'error': 'forbidden'}), 403

    state = whatsapp.get_connection_state(account['instance_name'])
    result = {'state': state}
    if state != 'open':
        qr = whatsapp.get_qr_code(account['instance_name'])
        result['qr_base64'] = qr.get('base64', '')
    return jsonify(result)


@app.route('/admin/accounts/<account_id>/connect', methods=['POST'])
@login_required
def account_connect(account_id):
    account = admin_db.get_whatsapp_account(account_id)
    if not account or not _can_access_tenant(account.get('tenant_id')):
        flash('Acesso negado', 'error')
        return redirect(url_for('dashboard'))

    instance = account['instance_name']
    state = whatsapp.get_connection_state(instance)

    if state in ('error', 'unknown'):
        whatsapp.create_instance(instance)

    if not account.get('webhook_configured'):
        if whatsapp.set_webhook(instance, BOT_WEBHOOK_URL):
            admin_db.set_webhook_configured(account_id, True)

    flash('Instancia reconectada. Escaneie o QR code.', 'success')
    return redirect(url_for('tenant_detail', tenant_id=account['tenant_id']))


@app.route('/admin/accounts/<account_id>/disconnect', methods=['POST'])
@login_required
def account_disconnect(account_id):
    account = admin_db.get_whatsapp_account(account_id)
    if account and _can_access_tenant(account.get('tenant_id')):
        whatsapp.logout_instance(account['instance_name'])
        flash('WhatsApp desconectado', 'success')
    return redirect(url_for('tenant_detail', tenant_id=account['tenant_id']))


@app.route('/admin/accounts/<account_id>/delete', methods=['POST'])
@login_required
def account_delete(account_id):
    account = admin_db.get_whatsapp_account(account_id)
    if account and _can_access_tenant(account.get('tenant_id')):
        whatsapp.delete_instance(account['instance_name'])
        admin_db.deactivate_whatsapp_account(account_id)
        flash('Instancia desativada', 'success')
    return redirect(url_for('tenant_detail', tenant_id=account['tenant_id']))


# --- API Costs Dashboard ---

@app.route('/admin/api-costs')
@login_required
def api_costs():
    user_tenant = _get_user_tenant_id()
    is_super = session.get('role') == 'super_admin'

    today = admin_db.get_costs_today(tenant_id=user_tenant)
    month = admin_db.get_costs_month(tenant_id=user_tenant)
    by_operation = admin_db.get_costs_by_operation(tenant_id=user_tenant, days=30)
    daily = admin_db.get_daily_costs(tenant_id=user_tenant, days=30)
    projection = admin_db.get_projected_monthly_cost(tenant_id=user_tenant)

    # Calculate projection
    projected_cost = 0
    if projection and projection.get('days_active') and projection.get('days_in_month'):
        daily_avg = float(projection['month_so_far']) / max(float(projection['current_day']), 1)
        projected_cost = daily_avg * float(projection['days_in_month'])

    # Per-tenant breakdown (super_admin only)
    by_tenant = admin_db.get_costs_by_tenant(days=30) if is_super else []

    # Voice costs by provider (ElevenLabs vs OpenAI)
    voice_by_provider = admin_db.get_voice_costs_by_provider(tenant_id=user_tenant, days=30)
    voice_by_tenant = admin_db.get_voice_costs_by_tenant(days=30) if is_super else []
    daily_voice = admin_db.get_daily_voice_costs(tenant_id=user_tenant, days=30)

    # Aggregate voice daily data for chart
    voice_chart_days = {}
    for row in daily_voice:
        day_str = str(row['day'])
        if day_str not in voice_chart_days:
            voice_chart_days[day_str] = {'day': day_str, 'elevenlabs': 0, 'openai': 0, 'total': 0}
        provider = row['provider']
        cost = float(row['total_cost'])
        voice_chart_days[day_str][provider] = voice_chart_days[day_str].get(provider, 0) + cost
        voice_chart_days[day_str]['total'] += cost
    voice_chart_data = sorted(voice_chart_days.values(), key=lambda x: x['day'])

    # Aggregate daily data for chart
    chart_days = {}
    for row in daily:
        day_str = str(row['day'])
        if day_str not in chart_days:
            chart_days[day_str] = {'day': day_str, 'chat': 0, 'tts': 0, 'transcription': 0, 'total': 0}
        op = row['operation']
        cost = float(row['total_cost'])
        chart_days[day_str][op] = chart_days[day_str].get(op, 0) + cost
        chart_days[day_str]['total'] += cost
    chart_data = sorted(chart_days.values(), key=lambda x: x['day'])

    return render_template('api_costs.html',
                           today=today,
                           month=month,
                           by_operation=by_operation,
                           chart_data=chart_data,
                           projected_cost=round(projected_cost, 4),
                           by_tenant=by_tenant,
                           voice_by_provider=voice_by_provider,
                           voice_by_tenant=voice_by_tenant,
                           voice_chart_data=voice_chart_data,
                           is_super_admin=is_super)


# --- Consumption (legacy) ---

@app.route('/admin/consumption')
@login_required
def consumption():
    return redirect(url_for('api_costs'))


# --- Public QR (for clients) ---

@app.route('/qr/<token>')
def public_qr(token):
    # Look up account by client_token
    account = admin_db._query(
        "SELECT * FROM whatsapp_accounts WHERE client_token = %s",
        (token,),
        fetch='one',
    )
    if not account:
        return 'Link invalido', 404
    return render_template('client_qr.html', account=account, token=token)


@app.route('/api/qr/<token>')
def api_qr(token):
    account = admin_db._query(
        "SELECT * FROM whatsapp_accounts WHERE client_token = %s",
        (token,),
        fetch='one',
    )
    if not account:
        return jsonify({'error': 'not found'}), 404

    instance = account['instance_name']
    state = whatsapp.get_connection_state(instance)
    if state == 'open':
        return jsonify({'state': 'open'})
    qr = whatsapp.get_qr_code(instance)
    return jsonify({'state': state, 'base64': qr.get('base64', '')})


# --- Startup ---

def _init_app():
    """Initialize DB pools and default admin. Called on import (for gunicorn) and __main__."""
    admin_db.init_pool(
        host=os.getenv('DB_HOST', 'postgres'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_NAME', 'hub_database'),
        user=os.getenv('DB_USER', 'hub_user'),
        password=os.getenv('DB_PASSWORD', ''),
        database_url=os.getenv('DATABASE_URL', ''),
    )
    ensure_default_admin()


# Initialize on module load (gunicorn imports admin.app:app)
_init_app()


if __name__ == '__main__':
    port = int(os.getenv('PORT', '9615'))
    log.info(f'Admin Panel started on port {port}')
    app.run(host='0.0.0.0', port=port)
