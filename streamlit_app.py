"""MetroCal Web — versión Streamlit.

Reutiliza la misma base de datos, reglas y métodos de cálculo de app.py
(escalera, deriva, riesgos, verificación normativa), con interfaz en Streamlit.
Ejecutar localmente:  streamlit run streamlit_app.py
"""
import csv
import io
import math
import sqlite3
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import app as core

st.set_page_config(page_title='MetroCal · Gestión Metrológica', page_icon='📏', layout='wide')
core.init_db()

MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic']
STATUS_COLORS = {'Vigente': '#23aa88', 'Próximo': '#edae49', 'Vencido': '#db6a78', 'Sin calibración': '#a7b2c6'}
STATUS_ICON = {'Vigente': '🟢', 'Próximo': '🟡', 'Vencido': '🔴', 'Sin calibración': '⚪'}
PAGES = {
    'dashboard': '▦ Resumen general',
    'instruments': '▤ Instrumentos',
    'calibrations': '◷ Calibraciones',
    'intermediate': '◉ Verificaciones intermedias',
    'analysis': '⌁ Análisis de intervalos',
    'risk': '◇ Evaluación de riesgos',
    'compliance': '✓ Verificación normativa',
    'decisions': '☷ Decisiones y trazabilidad',
}
RISK_NAMES = {
    'usage': ('Intensidad de uso', '1 = ocasional · 2 = frecuente · 3 = intensivo'),
    'environment': ('Condiciones ambientales', '1 = controlado · 2 = variable · 3 = severo'),
    'impact': ('Impacto de medición incorrecta', '1 = bajo · 2 = importante · 3 = crítico'),
    'history': ('Historial de estabilidad', '1 = estable · 2 = variable · 3 = inestable'),
    'check_frequency': ('Escasez de verificaciones intermedias',
                        '1 = verificaciones frecuentes · 2 = periódicas · 3 = sin verificaciones'),
}

st.markdown("""
<style>
.block-container{padding-top:3.5rem}
.mc-note{background:#f3f2fe;border-left:4px solid #655bdc;padding:12px 16px;border-radius:8px;margin:12px 0;font-size:.92rem}
.mc-note.warning{background:#fff7e6;border-color:#edae49}
.mc-note.danger{background:#fdecee;border-color:#db6a78}
.mc-big{font-size:2.1rem;font-weight:800;color:#4e47ae;line-height:1.1}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- utilidades
def fmt_date(d):
    if not d:
        return 'Sin registro'
    x = date.fromisoformat(str(d)[:10])
    return f'{x.day:02d} {MESES[x.month - 1]} {x.year}'


def num(x):
    if x is None:
        return '—'
    return f'{float(x):,.5f}'.rstrip('0').rstrip('.').replace(',', ' ')


def note(text, kind=''):
    st.markdown(f'<div class="mc-note {kind}">{text}</div>', unsafe_allow_html=True)


def user():
    return st.session_state.get('user')


def items():
    return core.instruments(user()['company_id'])


def own_instrument(inst_id):
    return core.single('SELECT * FROM instruments WHERE id=? AND company_id=? AND active=1',
                       (inst_id, user()['company_id']))


def history(inst_id):
    return core.rows('SELECT * FROM calibrations WHERE instrument_id=? ORDER BY performed_on,id', (inst_id,))


def flash(text, error=False):
    st.session_state['flash'] = (text, error)


def show_flash():
    msg = st.session_state.pop('flash', None)
    if msg:
        (st.error if msg[1] else st.success)(msg[0])


def label_inst(i):
    return f"{i['code']} — {i['name']}"


def export_csv(company_id):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Código', 'Instrumento', 'Tipo', 'Área', 'Unidad', 'EMP', 'Intervalo meses',
                     'Última calibración', 'Próxima calibración', 'Estado', 'Riesgo'])
    for x in core.instruments(company_id):
        writer.writerow([x.get(k, '') for k in ('code', 'name', 'kind', 'area', 'unit', 'emp', 'interval_months',
                                                 'last_calibration', 'next_calibration', 'status', 'risk')])
    return ('﻿' + output.getvalue()).encode('utf-8')


def csv_button(key):
    st.download_button('↓ Exportar inventario (CSV)', export_csv(user()['company_id']),
                       file_name='MetroCal_inventario.csv', mime='text/csv', key=key)


def go(page):
    st.session_state['page'] = page


# ------------------------------------------- escrituras (mismas validaciones)
def save_instrument(data, ident=None):
    try:
        code = str(data.get('code', '')).strip().upper()
        name = str(data.get('name', '')).strip()
        kind = str(data.get('kind', '')).strip()
        area = str(data.get('area', '')).strip()
        unit = str(data.get('unit', '')).strip()
        emp = float(data['emp'])
        months = int(data['interval_months'])
        risk = str(data.get('risk', 'Media'))
        last = data.get('last_calibration') or None
        if last:
            date.fromisoformat(last)
        if (not code or not name or not unit or not kind or emp <= 0 or months < 1 or months > 120
                or risk not in ('Alta', 'Media', 'Baja')):
            raise ValueError()
        with core.db() as con:
            if ident:
                if not own_instrument(ident):
                    return False, 'Instrumento no encontrado'
                con.execute('UPDATE instruments SET code=?,name=?,kind=?,area=?,unit=?,emp=?,interval_months=?,'
                            'last_calibration=?,risk=? WHERE id=?',
                            (code, name, kind, area, unit, emp, months, last, risk, ident))
            else:
                con.execute('INSERT INTO instruments(company_id,code,name,kind,area,unit,emp,interval_months,'
                            'last_calibration,risk) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (user()['company_id'], code, name, kind, area, unit, emp, months, last, risk))
        return True, 'Instrumento guardado correctamente'
    except sqlite3.IntegrityError:
        return False, 'Código duplicado para esta empresa.'
    except (ValueError, KeyError, TypeError):
        return False, 'Revisa campos obligatorios, EMP positivo y meses de intervalo.'


def deactivate_instrument(ident):
    if not own_instrument(ident):
        return False, 'Instrumento no encontrado'
    with core.db() as con:
        con.execute('UPDATE instruments SET active=0 WHERE id=?', (ident,))
    return True, 'Instrumento desactivado'


def save_calibration(d):
    try:
        ident = int(d['instrument_id'])
        inst = own_instrument(ident)
        if not inst:
            return False, 'Instrumento no encontrado'
        performed = str(d['performed_on'])
        date.fromisoformat(performed)
        error = float(d['error'])
        unc = float(d.get('uncertainty', 0))
        if unc < 0 or not all(abs(x) < 1e12 for x in (error, unc)):
            raise ValueError()
        with core.db() as con:
            con.execute('''INSERT INTO calibrations
               (instrument_id,performed_on,error,uncertainty,technician,remarks,adjusted,certificate_number,
                laboratory,reference_pattern) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (ident, performed, error, unc, str(d.get('technician', ''))[:150],
                         str(d.get('remarks', ''))[:1000], int(bool(d.get('adjusted'))),
                         str(d.get('certificate_number', '')).strip()[:150],
                         str(d.get('laboratory', '')).strip()[:200],
                         str(d.get('reference_pattern', '')).strip()[:200]))
        conformity = 'Revisar' if abs(error) + unc > inst['emp'] else 'Dentro del criterio simplificado'
        return True, f'Calibración registrada · {conformity}'
    except (ValueError, KeyError, TypeError):
        return False, 'Revisa fecha, error e incertidumbre.'


def save_intermediate(d):
    try:
        ident = int(d['instrument_id'])
        inst = own_instrument(ident)
        if not inst:
            return False, 'Instrumento no encontrado.'
        checked_on = str(d['checked_on'])
        date.fromisoformat(checked_on)
        ref = float(d['reference_value'])
        ind = float(d['indicated_value'])
        unc = float(d.get('uncertainty', 0))
        person = str(d.get('performed_by', '')).strip()[:150]
        pattern = str(d.get('pattern_code', '')).strip()[:150]
        notes = str(d.get('notes', '')).strip()[:1000]
        if not person or unc < 0 or not all(math.isfinite(x) and abs(x) < 1e12 for x in (ref, ind, unc)):
            raise ValueError()
        with core.db() as con:
            con.execute('''INSERT INTO intermediate_checks
               (instrument_id,checked_on,reference_value,indicated_value,uncertainty,performed_by,pattern_code,notes)
               VALUES(?,?,?,?,?,?,?,?)''', (ident, checked_on, ref, ind, unc, person, pattern, notes))
        attention = abs(ind - ref) + unc > inst['emp']
        return True, 'Verificación registrada: revisar desviación.' if attention else 'Verificación registrada'
    except (ValueError, KeyError, TypeError):
        return False, 'Revisa los datos de la comprobación y el responsable.'


def save_risk(d):
    try:
        ident = int(d['instrument_id'])
        if not own_instrument(ident):
            return False, 'Instrumento no encontrado.'
        values = [int(d[k]) for k in RISK_NAMES]
        if any(v not in (1, 2, 3) for v in values):
            raise ValueError()
        assessed_by = str(d.get('assessed_by', '')).strip()[:120]
        mitigation = str(d.get('mitigation', '')).strip()[:700]
        if not assessed_by or not mitigation:
            raise ValueError()
        with core.db() as con:
            con.execute("""INSERT INTO risk_assessments(instrument_id,usage,environment,impact,history,check_frequency,
              mitigation,assessed_by,reviewed_on) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET
              usage=excluded.usage,environment=excluded.environment,impact=excluded.impact,history=excluded.history,
              check_frequency=excluded.check_frequency,mitigation=excluded.mitigation,assessed_by=excluded.assessed_by,
              reviewed_on=excluded.reviewed_on""", (ident, *values, mitigation, assessed_by, date.today().isoformat()))
        return True, 'Evaluación de riesgos guardada'
    except (KeyError, ValueError, TypeError):
        return False, 'Complete los cinco factores (1–3), responsable y medidas.'


def save_compliance(d):
    try:
        ident = int(d['instrument_id'])
        if not own_instrument(ident):
            return False, 'Instrumento no encontrado.'
        by = str(d.get('reviewed_by', '')).strip()[:120]
        certificate = str(d.get('certificate', '')).strip()[:250]
        notes = str(d.get('notes', '')).strip()[:700]
        if not by:
            raise ValueError()
        checks = [int(bool(d.get(k))) for k in ('traceability', 'identified', 'protected')]
        with core.db() as con:
            con.execute("""INSERT INTO compliance_evidence(instrument_id,traceability,identified,protected,certificate,
              notes,reviewed_by,reviewed_on) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET
              traceability=excluded.traceability,identified=excluded.identified,protected=excluded.protected,
              certificate=excluded.certificate,notes=excluded.notes,reviewed_by=excluded.reviewed_by,
              reviewed_on=excluded.reviewed_on""", (ident, *checks, certificate, notes, by, date.today().isoformat()))
        return True, 'Evidencia actualizada'
    except (KeyError, ValueError, TypeError):
        return False, 'Ingrese responsable y evidencia verificable.'


def save_decision(ident, method, suggested, approver, note_text):
    try:
        inst = own_instrument(ident)
        if not inst:
            return False, 'Instrumento no encontrado'
        approver = approver.strip()
        note_text = note_text.strip()
        if not approver or not note_text or suggested < 1 or suggested > 120:
            raise ValueError()
        proposal = core.calculate(inst, history(ident), method)
        if not proposal.get('ok') or proposal['suggested'] != suggested:
            return False, 'La recomendación cambió. Vuelve a calcular antes de aprobar.'
        with core.db() as con:
            con.execute('INSERT INTO decisions(instrument_id,method,previous_interval,suggested_interval,note,'
                        'approved_by) VALUES(?,?,?,?,?,?)',
                        (ident, method, inst['interval_months'], suggested, note_text, approver))
            con.execute('UPDATE instruments SET interval_months=? WHERE id=?', (suggested, ident))
        return True, 'Decisión registrada con trazabilidad'
    except (ValueError, KeyError, TypeError):
        return False, 'Completa responsable, justificación e intervalo.'


# ----------------------------------------------------------- componentes UI
def instruments_df(lst):
    return pd.DataFrame([{
        'Código': i['code'], 'Instrumento': i['name'], 'Tipo': i['kind'], 'Ubicación': i['area'],
        'EMP': f"± {num(i['emp'])} {i['unit']}", 'Intervalo': f"{i['interval_months']} meses",
        'Próxima calibración': fmt_date(i['next_calibration']),
        'Estado': f"{STATUS_ICON[i['status']]} {i['status']}",
    } for i in lst])


def table(df, empty='Sin registros.'):
    if df.empty:
        st.info(empty)
    else:
        st.dataframe(df, hide_index=True, width='stretch')


def status_ring(counts):
    df = pd.DataFrame([{'Estado': k, 'Cantidad': counts.get(k, 0)} for k in STATUS_COLORS])
    chart = alt.Chart(df).mark_arc(innerRadius=65).encode(
        theta='Cantidad:Q',
        color=alt.Color('Estado:N', scale=alt.Scale(domain=list(STATUS_COLORS), range=list(STATUS_COLORS.values())),
                        legend=alt.Legend(orient='right')),
        tooltip=['Estado', 'Cantidad'])
    st.altair_chart(chart.properties(height=240), width='stretch')


def error_chart(hist, emp, unit):
    if not hist:
        st.info('Sin datos históricos para graficar.')
        return
    df = pd.DataFrame([{'Fecha': h['performed_on'], 'Error': h['error']} for h in hist])
    lim = pd.DataFrame({'y': [-emp, 0, emp], 'tipo': ['−EMP', '0', '+EMP']})
    line = alt.Chart(df).mark_line(point=alt.OverlayMarkDef(size=80, filled=True), color='#655bdc', strokeWidth=3)\
        .encode(x=alt.X('Fecha:O', title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y('Error:Q', title=f'Error ({unit})'),
                tooltip=['Fecha', 'Error'])
    rules = alt.Chart(lim).mark_rule(strokeDash=[5, 5]).encode(
        y='y:Q', color=alt.Color('tipo:N', scale=alt.Scale(domain=['−EMP', '0', '+EMP'],
                                                           range=['#db6a78', '#c5ccda', '#db6a78']),
                                 legend=None))
    st.altair_chart((rules + line).properties(height=260), width='stretch')


# --------------------------------------------------------------------- login
def login_page():
    left, right = st.columns([1.2, 1], gap='large')
    with left:
        st.caption('PLATAFORMA DE GESTIÓN METROLÓGICA')
        st.title('MetroCal.')
        st.header('Control metrológico *con evidencia.*')
        st.write('Centraliza instrumentos, analiza tendencias y toma decisiones confiables sobre tus intervalos '
                 'de calibración.')
        st.write('◈ Control de equipos  ·  ↗ Análisis de deriva  ·  ◷ Alertas inteligentes')
        st.caption('MetroCal · Proyecto académico UCR · 2026')
    with right:
        with st.form('login'):
            st.subheader('Iniciar sesión')
            st.caption('Ingresa a tu espacio de gestión metrológica.')
            username = st.text_input('Usuario', value='admin')
            password = st.text_input('Contraseña', value='MetroCal2026!', type='password')
            if st.form_submit_button('Entrar a la plataforma →', type='primary', width='stretch'):
                u = core.single('SELECT u.*,c.name AS company_name FROM users u JOIN companies c '
                                'ON c.id=u.company_id WHERE u.username=?', (username.strip(),))
                if not u or not core.check_password(password, u['password_hash']):
                    st.error('Usuario o contraseña incorrectos.')
                else:
                    st.session_state['user'] = {k: u[k] for k in ('id', 'company_id', 'username', 'name',
                                                                  'company_name')}
                    st.session_state['page'] = 'dashboard'
                    st.rerun()
        note('✦ <b>Acceso de demostración</b><br>Usuario: <b>admin</b> · Clave: <b>MetroCal2026!</b><br>'
             '<small>Los datos y la empresa son ficticios.</small>')


# --------------------------------------------------------------------- páginas
def page_dashboard():
    lst = items()
    counts = {s: sum(i['status'] == s for i in lst) for s in STATUS_COLORS}
    st.title('Buenos días, equipo 👋')
    st.markdown(f"Aquí tienes el estado de los instrumentos de **{user()['company_name']}**.")
    a, b = st.columns([1, 1])
    with a:
        csv_button('csv_dash')
    with b:
        st.button('＋ Nuevo instrumento', type='primary', on_click=go, args=('instruments',))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Instrumentos activos', len(lst), help='Registrados en el sistema')
    c2.metric('Calibración vigente', counts['Vigente'], help='En período de calibración')
    c3.metric('Próximos a vencer', counts['Próximo'], help='En 30 días o menos')
    c4.metric('Requieren atención', counts['Vencido'] + counts['Sin calibración'],
              help='Vencidos o sin calibración')
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader('Estado de calibración')
        st.caption('Distribución de instrumentos')
        status_ring(counts)
    with right, st.container(border=True):
        st.subheader('Atención prioritaria')
        near = sorted([i for i in lst if i['status'] != 'Vigente'],
                      key=lambda i: i['days_left'] if i['days_left'] is not None else -999)[:6]
        if not near:
            st.success('¡Todo en orden! No hay instrumentos próximos a vencer.')
        for i in near:
            d = i['days_left']
            days = 'Sin fecha' if d is None else f'{abs(d)} d venc.' if d < 0 else f'{d} d'
            st.markdown(f"{STATUS_ICON[i['status']]} **{i['name']}** — {i['code']} · "
                        f"{fmt_date(i['next_calibration'])} · `{days}`")
    with st.container(border=True):
        st.subheader('Inventario de instrumentos')
        table(instruments_df(lst[:6]), 'Todavía no hay instrumentos registrados.')
    note('✦ <b>Nota metrológica:</b> los intervalos son revisables, no garantías automáticas de conformidad. '
         'Las decisiones deben considerar el EMP, incertidumbre, uso, historial y riesgos. '
         'Los registros de este entorno son simulados.')


def instrument_form(key, i=None):
    i = i or {}
    kinds = ['Balanza', 'Termómetro', 'Manómetro', 'Calibrador', 'Micrómetro', 'Otro']
    with st.form(key, clear_on_submit=not i):
        c1, c2 = st.columns(2)
        code = c1.text_input('Código *', value=i.get('code', ''), max_chars=30, placeholder='BAL-004')
        name = c2.text_input('Nombre del instrumento *', value=i.get('name', ''), placeholder='Balanza digital')
        kind = c1.selectbox('Tipo de instrumento *', kinds,
                            index=kinds.index(i['kind']) if i.get('kind') in kinds else 0)
        area = c2.text_input('Área o ubicación', value=i.get('area', ''), placeholder='Producción')
        unit = c1.text_input('Unidad de medición *', value=i.get('unit', ''), placeholder='g, °C, mm…')
        emp = c2.number_input('EMP (valor positivo) *', min_value=0.0, value=float(i.get('emp') or 0.0),
                              format='%.6f')
        months = c1.number_input('Intervalo actual (meses) *', min_value=1, max_value=120,
                                 value=int(i.get('interval_months') or 12))
        last = c2.date_input('Última calibración', format='DD/MM/YYYY',
                             value=date.fromisoformat(i['last_calibration']) if i.get('last_calibration') else None)
        risk = c1.selectbox('Criticidad / riesgo', ['Alta', 'Media', 'Baja'],
                            index=['Alta', 'Media', 'Baja'].index(i.get('risk', 'Media')))
        if st.form_submit_button('Guardar instrumento', type='primary'):
            ok, msg = save_instrument({'code': code, 'name': name, 'kind': kind, 'area': area, 'unit': unit,
                                       'emp': emp, 'interval_months': months, 'risk': risk,
                                       'last_calibration': last.isoformat() if last else None}, i.get('id'))
            flash(msg, not ok)
            st.rerun()


def page_instruments():
    lst = items()
    st.title('Inventario metrológico')
    st.write('Registra, administra y consulta los instrumentos de medición de la empresa.')
    csv_button('csv_inst')
    with st.container(border=True):
        q = st.text_input('⌕ Buscar por código, equipo o área…', key='filter').lower()
        shown = [i for i in lst if any(q in (i[k] or '').lower() for k in ('code', 'name', 'area', 'kind'))]
        st.markdown(f'**{len(shown)} instrumentos** · Registro general de equipos activos')
        table(instruments_df(shown), 'Todavía no hay instrumentos registrados.')
    with st.expander('＋ Agregar instrumento'):
        instrument_form('new_inst')
    if lst:
        with st.expander('✎ Editar o desactivar instrumento'):
            sel = st.selectbox('Instrumento', lst, format_func=label_inst, key='edit_sel')
            instrument_form(f"edit_inst_{sel['id']}", sel)
            st.divider()
            confirm = st.checkbox('Confirmo que quiero desactivar este instrumento (su historial quedará guardado).',
                                  key=f"conf_{sel['id']}")
            if st.button('Desactivar equipo', disabled=not confirm):
                ok, msg = deactivate_instrument(sel['id'])
                flash(msg, not ok)
                st.rerun()


def calibration_form(lst):
    with st.form('cal_form', clear_on_submit=True):
        inst = st.selectbox('Instrumento', lst, format_func=lambda i: f"{i['code']} · {i['name']}")
        c1, c2 = st.columns(2)
        performed = c1.date_input('Fecha de calibración *', value=date.today(), format='DD/MM/YYYY')
        error = c2.number_input('Error de indicación *', value=None, format='%.6f', placeholder='0.012')
        unc = c1.number_input('Incertidumbre expandida U', min_value=0.0, value=0.0, format='%.6f')
        tech = c2.text_input('Realizado por', placeholder='Técnico o laboratorio')
        cert = c1.text_input('Número de certificado', placeholder='CAL-2026-001')
        lab = c2.text_input('Laboratorio de calibración', placeholder='Laboratorio acreditado / externo')
        pat = c1.text_input('Patrón o referencia utilizado', placeholder='Código de patrón')
        remarks = st.text_area('Observaciones', placeholder='Certificado, condiciones, observaciones...')
        adjusted = st.checkbox('El instrumento fue ajustado durante este proceso')
        if st.form_submit_button('Guardar calibración', type='primary'):
            if error is None:
                flash('Revisa fecha, error e incertidumbre.', True)
            else:
                ok, msg = save_calibration({'instrument_id': inst['id'], 'performed_on': performed.isoformat(),
                                            'error': error, 'uncertainty': unc, 'technician': tech,
                                            'remarks': remarks, 'adjusted': adjusted, 'certificate_number': cert,
                                            'laboratory': lab, 'reference_pattern': pat})
                flash(msg, not ok)
            st.rerun()


def page_calibrations():
    lst = items()
    st.title('Historial de calibraciones')
    st.write('Registro de errores e incertidumbres para evaluar tendencias y trazabilidad.')
    if lst:
        with st.expander('＋ Registrar calibración'):
            calibration_form(lst)
    res = core.rows('SELECT c.*,i.code,i.name,i.unit,i.emp FROM calibrations c JOIN instruments i '
                    'ON i.id=c.instrument_id WHERE i.company_id=? AND i.active=1 '
                    'ORDER BY c.performed_on DESC,c.id DESC LIMIT 200', (user()['company_id'],))
    with st.container(border=True):
        st.subheader('Últimos registros')
        st.caption(f'{len(res)} calibraciones disponibles')
        table(pd.DataFrame([{
            'Fecha': fmt_date(c['performed_on']), 'Código': c['code'], 'Instrumento': c['name'],
            'Error': f"{num(c['error'])} {c['unit']}", 'Incertidumbre (U)': f"{num(c['uncertainty'])} {c['unit']}",
            'Resultado indicativo': '🔴 Revisar' if abs(c['error']) + c['uncertainty'] > c['emp']
            else '🟢 Dentro del criterio',
            'Responsable': c['technician'] or '—'} for c in res]))
    note('El criterio ilustrativo |error| + U ≤ EMP se utiliza como filtro conservador de revisión, no como '
         'declaración formal de conformidad. Una decisión de conformidad requiere regla de decisión acordada y '
         'datos metrológicos completos.', 'warning')


def page_intermediate():
    lst = items()
    res = core.rows('''SELECT c.*,i.code,i.name,i.unit,i.emp FROM intermediate_checks c
         JOIN instruments i ON i.id=c.instrument_id WHERE i.company_id=? AND i.active=1
         ORDER BY c.checked_on DESC,c.id DESC''', (user()['company_id'],))
    for c in res:
        c['error'] = round(c['indicated_value'] - c['reference_value'], 10)
        c['attention'] = abs(c['error']) + c['uncertainty'] > c['emp']
    st.title('Verificaciones intermedias')
    st.write('Registra comprobaciones entre calibraciones y detecta resultados que requieren revisión.')
    if lst:
        with st.expander('＋ Nueva verificación'):
            with st.form('inter_form', clear_on_submit=True):
                inst = st.selectbox('Instrumento', lst, format_func=label_inst)
                c1, c2 = st.columns(2)
                checked = c1.date_input('Fecha', value=date.today(), format='DD/MM/YYYY')
                ref = c2.number_input('Valor de referencia', value=None, format='%.6f')
                ind = c1.number_input('Indicación del instrumento', value=None, format='%.6f')
                unc = c2.number_input('Incertidumbre expandida U', min_value=0.0, value=0.0, format='%.6f')
                pat = c1.text_input('Patrón utilizado', placeholder='Identificación')
                person = c2.text_input('Responsable')
                notes = st.text_area('Observaciones')
                if st.form_submit_button('Registrar verificación', type='primary'):
                    if ref is None or ind is None:
                        flash('Revisa los datos de la comprobación y el responsable.', True)
                    else:
                        ok, msg = save_intermediate({'instrument_id': inst['id'], 'checked_on': checked.isoformat(),
                                                     'reference_value': ref, 'indicated_value': ind,
                                                     'uncertainty': unc, 'pattern_code': pat,
                                                     'performed_by': person, 'notes': notes})
                        flash(msg, not ok)
                    st.rerun()
    c1, c2, c3 = st.columns(3)
    c1.metric('Verificaciones', len(res), help='Registros en el sistema')
    c2.metric('Con alerta', sum(x['attention'] for x in res), help='Requieren evaluación técnica')
    c3.metric('Sin alerta', sum(not x['attention'] for x in res), help='Según criterio ilustrativo')
    with st.container(border=True):
        st.subheader('Historial de verificaciones')
        table(pd.DataFrame([{
            'Fecha': fmt_date(x['checked_on']), 'Código': x['code'],
            'Referencia': f"{num(x['reference_value'])} {x['unit']}",
            'Indicación': f"{num(x['indicated_value'])} {x['unit']}", 'Error': f"{num(x['error'])} {x['unit']}",
            'Incertidumbre': num(x['uncertainty']),
            'Resultado': '🔴 Revisar' if x['attention'] else '🟢 Sin alerta', 'Responsable': x['performed_by'],
        } for x in res]), 'Aún no hay verificaciones. Registra una para comenzar.')
    note('<b>Alcance:</b> la alerta emplea |error| + U &gt; EMP como criterio conservador de seguimiento. '
         'No demuestra conformidad formal ni sustituye una regla de decisión definida.', 'warning')


def show_result(r):
    if r['ok']:
        with st.container(border=True):
            st.caption('INTERVALO SUGERIDO')
            st.markdown(f"<div class='mc-big'>{r['suggested']} <small style='font-size:1rem'>meses</small></div>",
                        unsafe_allow_html=True)
            st.write(r['message'])
            st.caption(r['explanation'])
    else:
        note(r['message'], 'danger' if r.get('critical') else 'warning')


def page_analysis():
    lst = items()
    st.title('Análisis de intervalos')
    if not lst:
        st.write('Registra un instrumento para comenzar.')
        st.button('Agregar instrumento', on_click=go, args=('instruments',))
        return
    st.write('Evalúa el comportamiento de los instrumentos a partir de sus calibraciones históricas.')
    ids = [i['id'] for i in lst]
    if st.session_state.get('an_sel') not in ids:
        st.session_state['an_sel'] = ids[0]
    sel_id = st.selectbox('Seleccionar instrumento', ids, key='an_sel',
                          format_func=lambda x: label_inst(next(i for i in lst if i['id'] == x)))
    inst = next(i for i in lst if i['id'] == sel_id)
    hist = history(inst['id'])
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader('Calculadora de intervalos')
        method = st.selectbox('Método de evaluación', ['escalera', 'deriva'], key='an_method')
        st.markdown(f"Intervalo vigente: **{inst['interval_months']} meses**  \n"
                    f"EMP del instrumento: **± {num(inst['emp'])} {inst['unit']}**  \n"
                    f"Último error: **{'—' if inst['latest_error'] is None else num(inst['latest_error']) + ' ' + inst['unit']}**")
        if st.button('⌁ Calcular intervalo recomendado', type='primary', width='stretch'):
            st.session_state['calc'] = {'inst': inst['id'], 'method': method,
                                        'result': core.calculate(inst, hist, method)}
            st.session_state.pop('compare', None)
        if st.button('Comparar ambos métodos', width='stretch'):
            st.session_state['compare'] = {'inst': inst['id'],
                                           'a': core.calculate(inst, hist, 'escalera'),
                                           'b': core.calculate(inst, hist, 'deriva')}
            st.session_state.pop('calc', None)
        cmp = st.session_state.get('compare')
        if cmp and cmp['inst'] == inst['id']:
            cell = lambda r: f"**{r['suggested']} meses** — {r['message']}" if r['ok'] else f"_{r['message']}_"
            with st.container(border=True):
                st.markdown('**Comparación de métodos**')
                st.markdown(f"**Escalera:** {cell(cmp['a'])}")
                st.markdown(f"**Deriva:** {cell(cmp['b'])}")
                st.caption('Estimaciones orientativas. La elección y aprobación del intervalo corresponde al '
                           'responsable metrológico.')
        calc = st.session_state.get('calc')
        if calc and calc['inst'] == inst['id']:
            r = calc['result']
            show_result(r)
            if r['ok']:
                with st.expander('Registrar decisión y aprobar →', expanded=False):
                    note(f"<b>Revisión técnica obligatoria</b><br>La recomendación de {r['suggested']} meses es "
                         'orientativa. Al aprobarla se actualiza el intervalo registrado y queda guardada la '
                         'trazabilidad.', 'warning')
                    with st.form('decision_form'):
                        st.text_input('Intervalo actual', value=f"{r['current']} meses", disabled=True)
                        st.text_input('Intervalo propuesto', value=f"{r['suggested']} meses", disabled=True)
                        approver = st.text_input('Responsable de aprobar *', placeholder='Nombre y cargo')
                        why = st.text_area('Justificación técnica y riesgos revisados *',
                                           placeholder='Evidencia, condiciones de uso, incertidumbre, impacto, '
                                                       'revisión de datos históricos...')
                        if st.form_submit_button('Aprobar y registrar', type='primary'):
                            ok, msg = save_decision(inst['id'], calc['method'], r['suggested'], approver, why)
                            flash(msg, not ok)
                            if ok:
                                st.session_state.pop('calc', None)
                                st.session_state['page'] = 'decisions'
                            st.rerun()
    with right, st.container(border=True):
        st.subheader('Evolución del error')
        st.caption(f"EMP: ±{num(inst['emp'])} {inst['unit']}")
        error_chart(hist, inst['emp'], inst['unit'])
        note('Gráfico de errores frente a EMP. No constituye por sí solo una carta de control estadística completa.')
    with st.container(border=True):
        st.subheader('Historial de medición')
        st.caption(f'{len(hist)} calibraciones')
        table(pd.DataFrame([{
            'Fecha': fmt_date(c['performed_on']), 'Error': f"{num(c['error'])} {inst['unit']}",
            'Incertidumbre': f"{num(c['uncertainty'])} {inst['unit']}", 'Ajuste realizado': 'Sí' if c['adjusted'] else 'No',
            'Responsable': c['technician'] or '—',
            'Certificado / patrón': f"{c.get('certificate_number') or '—'} / {c.get('reference_pattern') or '—'}",
        } for c in hist]))


def page_risk():
    lst = items()
    data = [{'inst': i, 'risk': core.get_risk(i['id'])} for i in lst]
    assessed = [x for x in data if x['risk']]
    st.title('Evaluación de riesgos')
    st.write('Matriz multicriterio de apoyo: asigna 1, 2 o 3 puntos por factor. '
             'No sustituye una evaluación profesional.')
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Equipos evaluados', f'{len(assessed)}/{len(data)}', help='Evaluaciones registradas')
    c2.metric('Riesgo alto', sum(x['risk']['level'] == 'Alto' for x in assessed), help='Requieren revisión prioritaria')
    c3.metric('Sin evaluación', len(data) - len(assessed), help='Pendiente de documentar')
    c4.metric('Criterios', 5, help='Escala de 5 a 15 puntos')
    with st.container(border=True):
        st.subheader('Matriz de riesgos por instrumento')
        table(pd.DataFrame([{
            'Código': x['inst']['code'], 'Instrumento': x['inst']['name'],
            'Puntaje': f"{x['risk']['score']}/15" if x['risk'] else '—',
            'Nivel': x['risk']['level'] if x['risk'] else 'Sin evaluar',
            'Responsable': x['risk']['assessed_by'] if x['risk'] else '—'} for x in data]))
    if lst:
        with st.expander('◇ Evaluar o revisar un instrumento'):
            inst = st.selectbox('Instrumento', lst, format_func=label_inst, key='risk_sel')
            cur = core.get_risk(inst['id']) or {}
            with st.form(f"risk_form_{inst['id']}"):
                vals = {}
                cols = st.columns(2)
                for n, (key, (lab, desc)) in enumerate(RISK_NAMES.items()):
                    vals[key] = cols[n % 2].selectbox(lab, [1, 2, 3], index=int(cur.get(key, 2)) - 1, help=desc)
                mitigation = st.text_area('Medidas de control o mitigación', value=cur.get('mitigation', ''))
                by = st.text_input('Responsable de evaluación', value=cur.get('assessed_by', ''))
                if st.form_submit_button('Guardar evaluación', type='primary'):
                    ok, msg = save_risk({'instrument_id': inst['id'], **vals, 'mitigation': mitigation,
                                         'assessed_by': by})
                    flash(msg, not ok)
                    st.rerun()
    note('<b>Regla propuesta para el prototipo:</b> 5–7 riesgo bajo, 8–11 medio, 12–15 alto. Se impide ampliar el '
         'intervalo sin una evaluación o con riesgo alto. Es un criterio académico configurable y debe ser validado '
         'con la empresa.', 'warning')


def page_compliance():
    lst = items()
    res = [core.compliance_result(i) for i in lst]
    complete = sum(r['complete'] for r in res)
    st.title('Verificación normativa')
    st.write('Lista de apoyo basada en ISO 9001:2015, apartado 7.1.5.2. Evidencias documentales y seguimiento.')
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Instrumentos', len(res), help='En inventario activo')
    c2.metric('Con lista completa', complete, help='Todos los criterios marcados')
    c3.metric('Pendientes', len(res) - complete, help='Falta evidencia o vigencia')
    c4.metric('Porcentaje', f'{round(complete / len(res) * 100)}%' if res else '—', help='Completitud de listas')
    with st.container(border=True):
        st.subheader('Lista de verificación de trazabilidad y control')
        rows_ = []
        for r in res:
            row = {'Código': r['code'], 'Instrumento': r['name'], 'Completitud': f"{r['passed']}/{r['total']}",
                   'Resultado': '🟢 Lista completa' if r['complete'] else '🟡 Pendiente'}
            for k in r['checks']:
                row[k['label']] = '✓' if k['ok'] else '✗'
            rows_.append(row)
        table(pd.DataFrame(rows_))
    if lst:
        with st.expander('✓ Verificar evidencia de un instrumento'):
            inst = st.selectbox('Instrumento', lst, format_func=label_inst, key='comp_sel')
            r = core.compliance_result(inst)
            x = r['evidence'] or {}
            note(f"Estado actual: {r['passed']} de {r['total']} criterios. La vigencia y existencia del historial se "
                 'calculan automáticamente.')
            with st.form(f"comp_form_{inst['id']}"):
                identified = st.checkbox('Instrumento identificado y etiquetado', value=bool(x.get('identified')))
                trace = st.checkbox('Trazabilidad respaldada en certificado o referencia',
                                    value=bool(x.get('traceability')))
                protected = st.checkbox('Protección y conservación verificadas', value=bool(x.get('protected')))
                cert = st.text_input('Número de certificado o referencia documental', value=x.get('certificate', ''),
                                     placeholder='Ejemplo: CAL-2026-001')
                notes = st.text_area('Observaciones y evidencia adicional', value=x.get('notes', ''))
                by = st.text_input('Verificado por', value=x.get('reviewed_by', ''))
                if st.form_submit_button('Guardar verificación', type='primary'):
                    ok, msg = save_compliance({'instrument_id': inst['id'], 'identified': identified,
                                               'traceability': trace, 'protected': protected, 'certificate': cert,
                                               'notes': notes, 'reviewed_by': by})
                    flash(msg, not ok)
                    st.rerun()
    note('<b>Alcance:</b> esta lista verifica cinco evidencias seleccionadas; no es una auditoría ISO 9001, no '
         'demuestra acreditación y no establece una declaración formal de conformidad de resultados metrológicos.',
         'warning')


def page_decisions():
    ds = core.rows('SELECT d.*,i.code,i.name FROM decisions d JOIN instruments i ON i.id=d.instrument_id '
                   'WHERE i.company_id=? ORDER BY d.created_at DESC,d.id DESC', (user()['company_id'],))
    st.title('Decisiones y trazabilidad')
    st.write('Historial auditable de las recomendaciones revisadas y aprobadas.')
    with st.container(border=True):
        st.subheader('Registro de decisiones')
        st.caption(f'{len(ds)} decisiones documentadas')
        table(pd.DataFrame([{
            'Fecha': d['created_at'][:16], 'Instrumento': d['code'], 'Método': d['method'],
            'Antes': f"{d['previous_interval']} meses", 'Después': f"{d['suggested_interval']} meses",
            'Aprobado por': d['approved_by'], 'Justificación': d['note']} for d in ds]),
            'Aún no hay decisiones aprobadas. Utiliza el módulo Análisis de intervalos.')
    note('Cada cambio de intervalo requiere un responsable y una justificación escrita. Los registros reflejan '
         'decisiones de usuarios de la aplicación, no certificaciones de un laboratorio acreditado.')


# ---------------------------------------------------------------- navegación
def main():
    if not user():
        login_page()
        return
    page = st.session_state.setdefault('page', 'dashboard')
    with st.sidebar:
        st.markdown('## MetroCal.')
        st.caption('ESPACIO DE TRABAJO')
        for key, label in PAGES.items():
            st.button(label, key=f'nav_{key}', on_click=go, args=(key,), width='stretch',
                      type='primary' if key == page else 'secondary')
        st.divider()
        st.caption('✦ PROYECTO ACADÉMICO — Un sistema más inteligente para medir mejor.')
        st.markdown(f"**{user()['name']}**  \nGestión metrológica")
        if st.button('⇥ Cerrar sesión', width='stretch'):
            st.session_state.clear()
            st.rerun()
    st.caption(f"Empresa / **{PAGES[page].split(' ', 1)[1]}**  ·  🟢 Entorno de demostración")
    show_flash()
    {'dashboard': page_dashboard, 'instruments': page_instruments, 'calibrations': page_calibrations,
     'intermediate': page_intermediate, 'analysis': page_analysis, 'risk': page_risk,
     'compliance': page_compliance, 'decisions': page_decisions}[page]()
    st.divider()
    st.caption('MetroCal · Plataforma de aseguramiento metrológico · Datos de demostración, no certificados')


main()
