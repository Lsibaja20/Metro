"""MetroCal Web 1.5 — prototipo académico local sin dependencias externas."""
import csv
import math
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import threading
import webbrowser
from datetime import date, datetime, timedelta
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).resolve().parent
DB = BASE / 'metrocal.sqlite3'
STATIC = BASE / 'static'
SESSIONS = {}
LOCK = threading.RLock()
PORT = int(os.environ.get('METROCAL_PORT', '8765'))


@contextmanager
def db():
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
    return salt + ':' + digest


def check_password(password, stored):
    try:
        salt, digest = stored.split(':', 1)
        return hmac.compare_digest(hash_password(password, salt).split(':')[1], digest)
    except (ValueError, TypeError):
        return False


def init_db():
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS instruments(
          id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), code TEXT NOT NULL,
          name TEXT NOT NULL, kind TEXT NOT NULL, area TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL,
          emp REAL NOT NULL CHECK(emp>0), interval_months INTEGER NOT NULL CHECK(interval_months>0),
          last_calibration TEXT, risk TEXT NOT NULL DEFAULT 'Media', manufacturer TEXT NOT NULL DEFAULT '',
          serial TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
          UNIQUE(company_id,code));
        CREATE TABLE IF NOT EXISTS calibrations(
          id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL REFERENCES instruments(id),
          performed_on TEXT NOT NULL, reference_value REAL, indicated_value REAL,
          error REAL NOT NULL, uncertainty REAL NOT NULL DEFAULT 0,
          technician TEXT NOT NULL DEFAULT '', remarks TEXT NOT NULL DEFAULT '', adjusted INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS risk_assessments(
          instrument_id INTEGER PRIMARY KEY REFERENCES instruments(id), usage INTEGER NOT NULL,
          environment INTEGER NOT NULL, impact INTEGER NOT NULL, history INTEGER NOT NULL,
          check_frequency INTEGER NOT NULL, mitigation TEXT NOT NULL, assessed_by TEXT NOT NULL,
          reviewed_on TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS compliance_evidence(
          instrument_id INTEGER PRIMARY KEY REFERENCES instruments(id), traceability INTEGER NOT NULL DEFAULT 0,
          identified INTEGER NOT NULL DEFAULT 0, protected INTEGER NOT NULL DEFAULT 0,
          certificate TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          reviewed_by TEXT NOT NULL DEFAULT '', reviewed_on TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS intermediate_checks(
          id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL REFERENCES instruments(id),
          checked_on TEXT NOT NULL, reference_value REAL NOT NULL, indicated_value REAL NOT NULL,
          uncertainty REAL NOT NULL DEFAULT 0, performed_by TEXT NOT NULL,
          pattern_code TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS decisions(
          id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL REFERENCES instruments(id),
          method TEXT NOT NULL, previous_interval INTEGER NOT NULL, suggested_interval INTEGER NOT NULL,
          note TEXT NOT NULL, approved_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')
        # Migración compatible con bases anteriores de MetroCal.
        cols={r[1] for r in con.execute('PRAGMA table_info(calibrations)')}
        for col in ('certificate_number','laboratory','reference_pattern'):
            if col not in cols:
                con.execute(f"ALTER TABLE calibrations ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if con.execute('SELECT COUNT(*) FROM companies').fetchone()[0] == 0:
            con.execute('INSERT INTO companies(name) VALUES(?)', ('Precisión Industrial del Valle S.A. (DEMO)',))
            con.execute('INSERT INTO users(company_id,username,password_hash,name) VALUES(?,?,?,?)',
                        (1, 'admin', hash_password('MetroCal2026!'), 'Administrador de metrología'))
            sample = [
                ('BAL-001','Balanza de laboratorio','Balanza','Control de calidad','g',0.25,12,'Alta'),
                ('BAL-002','Balanza de plataforma','Balanza','Envasado','g',1.0,12,'Alta'),
                ('TER-001','Termómetro digital 01','Termómetro','Producción','°C',0.50,12,'Alta'),
                ('TER-002','Termómetro digital 02','Termómetro','Laboratorio','°C',0.40,12,'Media'),
                ('MAN-001','Manómetro línea A','Manómetro','Sala de máquinas','bar',0.20,12,'Alta'),
                ('MAN-002','Manómetro línea B','Manómetro','Producción','bar',0.25,12,'Media'),
                ('VER-001','Calibrador digital','Calibrador','Control de calidad','mm',0.02,12,'Media'),
                ('MIC-001','Micrómetro externo','Micrómetro','Laboratorio','mm',0.01,12,'Alta'),
                ('TER-003','Termómetro de cámara','Termómetro','Almacenamiento','°C',0.60,12,'Media'),
                ('BAL-003','Balanza de recepción','Balanza','Recepción','g',2.0,12,'Baja'),
                ('MAN-003','Manómetro servicio','Manómetro','Mantenimiento','bar',0.40,12,'Baja'),
                ('VER-002','Calibrador auxiliar','Calibrador','Mantenimiento','mm',0.03,12,'Media'),
            ]
            today = date.today()
            for i, entry in enumerate(sample):
                code,name,kind,area,unit,emp,interval,risk=entry
                ago = [8,13,10,6,16,3,11,7,14,1,9,5][i]
                yr = today.year - (ago // 12)
                mo = today.month - ago%12
                if mo<=0: yr-=1;mo+=12
                day=min(today.day,28)
                last=f'{yr:04d}-{mo:02d}-{day:02d}'
                cur=con.execute('INSERT INTO instruments(company_id,code,name,kind,area,unit,emp,interval_months,last_calibration,risk) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (1,code,name,kind,area,unit,emp,interval,last,risk))
                inst_id=cur.lastrowid
                for k in range(3):
                    base=date.fromisoformat(last)
                    cal_year=base.year-(2-k)
                    caldate=base.replace(year=cal_year).isoformat()
                    err=round(emp*(0.16 + 0.19*k + (i%4)*0.045),5)
                    con.execute('INSERT INTO calibrations(instrument_id,performed_on,error,uncertainty,technician) VALUES(?,?,?,?,?)',
                                (inst_id,caldate,err,round(emp*0.09,5),'Laboratorio externo (simulado)'))


def rows(sql, args=()):
    with db() as con: return [dict(r) for r in con.execute(sql, args)]


def single(sql,args=()):
    with db() as con:
        r=con.execute(sql,args).fetchone()
        return dict(r) if r else None


def add_months(iso, n):
    d=date.fromisoformat(iso)
    y=d.year+(d.month-1+n)//12
    m=(d.month-1+n)%12+1
    import calendar
    return date(y,m,min(d.day,calendar.monthrange(y,m)[1])).isoformat()


def enriched(inst):
    latest=single('SELECT performed_on,error,uncertainty FROM calibrations WHERE instrument_id=? ORDER BY performed_on DESC,id DESC LIMIT 1',(inst['id'],))
    if latest: inst['last_calibration']=latest['performed_on']
    nextdate=add_months(inst['last_calibration'],inst['interval_months']) if inst['last_calibration'] else None
    remaining=(date.fromisoformat(nextdate)-date.today()).days if nextdate else None
    inst.update(next_calibration=nextdate,days_left=remaining,status=('Sin calibración' if remaining is None else 'Vencido' if remaining<0 else 'Próximo' if remaining<=30 else 'Vigente'),latest_error=latest['error'] if latest else None,latest_uncertainty=latest['uncertainty'] if latest else None)
    return inst


def instruments(company_id):
    return [enriched(r) for r in rows('SELECT * FROM instruments WHERE company_id=? AND active=1 ORDER BY code',(company_id,))]


def get_risk(inst_id):
    row=single('SELECT * FROM risk_assessments WHERE instrument_id=?',(inst_id,))
    if row is None:return None
    score=sum(int(row[k]) for k in ('usage','environment','impact','history','check_frequency'))
    row['score']=score
    row['level']='Alto' if score>=12 else 'Medio' if score>=8 else 'Bajo'
    return row


def compliance_result(inst):
    record=single('SELECT * FROM compliance_evidence WHERE instrument_id=?',(inst['id'],))
    record=record or {}
    history=single('SELECT COUNT(*) AS n FROM calibrations WHERE instrument_id=?',(inst['id'],))['n']
    checks=[
      ('Identificación del equipo', bool(inst['code']) and bool(record.get('identified'))),
      ('Calibración en fecha especificada', inst['status'] in ('Vigente','Próximo')),
      ('Resultados de calibración registrados', history>0),
      ('Evidencia de trazabilidad documental', bool(record.get('traceability')) and bool(record.get('certificate','').strip())),
      ('Protección y condiciones de conservación verificadas', bool(record.get('protected'))),
    ]
    return {'instrument_id':inst['id'],'code':inst['code'],'name':inst['name'],
      'checks':[{'label':k,'ok':v} for k,v in checks], 'passed':sum(v for _,v in checks),
      'total':len(checks),'complete':all(v for _,v in checks), 'evidence':record,
      'note':'Lista de verificación de apoyo basada en ISO 9001:2015 7.1.5.2; no es certificación ni auditoría completa.'}



def calculate(inst, history, method):
    current=inst['interval_months']; emp=inst['emp']
    if not history: return {'ok':False,'message':'Primero registre una calibración.'}
    last=history[-1]; e=abs(last['error']); u=last['uncertainty']
    if e+u>emp:
        return {'ok':False,'message':'El error absoluto más la incertidumbre exceden el EMP. Revisar conformidad, evaluar el instrumento y posible impacto en mediciones anteriores antes de modificar el intervalo.','critical':True}
    risk=get_risk(inst['id'])
    last_check=single('SELECT * FROM intermediate_checks WHERE instrument_id=? ORDER BY checked_on DESC,id DESC LIMIT 1',(inst['id'],))
    check_alert=(last_check is not None and abs(last_check['indicated_value']-last_check['reference_value'])+last_check['uncertainty']>emp)
    if method=='escalera':
        percent=e/emp*100
        if percent>80: suggested=max(1,round(current*.5));label='Reducir'
        elif percent<80: suggested=min(36,max(current,round(current*1.5)));label='Considerar ampliar'
        else: suggested=current;label='Mantener y revisar'
        if suggested>current and check_alert:
            return {'ok':False,'message':'Ampliación bloqueada: la última verificación intermedia requiere atención.'}
        if suggested>current and (risk is None or risk['level']=='Alto'):
            return {'ok':False,'message':'Ampliación bloqueada: registre evaluación de riesgos y verifique que no sea de nivel alto.', 'critical':False}
        return {'ok':True,'method':'Escalera','suggested':suggested,'current':current,'percentage':round(percent,2),'message':f'{label}: el error corresponde al {percent:.1f}% del EMP. Regla didáctica ±50%; no es aprobación automática.','explanation':'La incertidumbre y los riesgos requieren evaluación técnica adicional.'}
    if method=='deriva':
        if len(history)<2:return {'ok':False,'message':'El método de deriva necesita al menos dos calibraciones registradas.'}
        a,b=history[-2:]
        if a['adjusted'] or b['adjusted']:
            return {'ok':False,'message':'Se registró un ajuste en una de las últimas calibraciones. No se debe estimar deriva con estos datos sin un análisis técnico del efecto del ajuste.'}
        days=(date.fromisoformat(b['performed_on'])-date.fromisoformat(a['performed_on'])).days
        if days<=0:return {'ok':False,'message':'Las últimas calibraciones deben tener fechas distintas y consecutivas.'}
        slope=(b['error']-a['error'])/(days/365.2425)
        if abs(slope)<1e-12:return {'ok':False,'message':'No hay deriva apreciable con estos dos registros. No se justifica extender el intervalo por extrapolación.'}
        # Conservador: margen disponible con incertidumbre y error actual.
        available=emp-abs(b['error'])-b['uncertainty']
        if available<=0:return {'ok':False,'message':'No existe margen disponible frente al EMP. Solicitar evaluación técnica.'}
        years=available/abs(slope)
        suggested=max(1,min(36,int(years*12)))
        if suggested>current and check_alert:
            return {'ok':False,'message':'Ampliación bloqueada: la última verificación intermedia requiere atención.'}
        if suggested>current and (risk is None or risk['level']=='Alto'):
            return {'ok':False,'message':'Ampliación bloqueada: se requiere evaluación de riesgos vigente con nivel no alto.'}

        return {'ok':True,'method':'Deriva','suggested':suggested,'current':current,'slope':round(slope,8),'margin':round(available,8),'message':f'Deriva observada: {slope:.5g} {inst["unit"]}/año. Margen (EMP − |error| − U): {available:.5g} {inst["unit"]}. Propuesta conservadora: {suggested} meses (máximo configurado: 36).','explanation':'Estimación lineal basada en dos calibraciones. Requiere más datos, evaluación del riesgo y aprobación técnica. No equivale a una carta de control estadística completa.'}
    if method=='uso':
        return {'ok':False,'message':'Tiempo en uso requiere un historial confiable de horas acumuladas. No se calcula sin ese dato.'}
    return {'ok':False,'message':'Método no reconocido.'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        if not self.path.startswith('/api/'): super().log_message(format,*args)

    def session(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:return None
        sid=cookie.get('metrocal_sid')
        if not sid:return None
        with LOCK:return SESSIONS.get(sid.value)

    def send_json(self,obj,status=200,cookie=None):
        b=json.dumps(obj,ensure_ascii=False,default=str).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(b)

    def send_file(self,path,ctype):
        if not path.is_file():return self.send_json({'error':'No encontrado'},404)
        data=path.read_bytes();self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)

    def data(self):
        size=int(self.headers.get('Content-Length','0'))
        if size>100000:return None
        try:return json.loads(self.rfile.read(size))
        except (ValueError,UnicodeDecodeError):return None

    def required(self):
        user=self.session()
        if not user:self.send_json({'error':'Inicia sesión para continuar.'},401)
        return user

    def own_instrument(self,user,inst_id):
        return single('SELECT * FROM instruments WHERE id=? AND company_id=? AND active=1',(inst_id,user['company_id']))

    def do_GET(self):
        route=urlparse(self.path).path
        if route=='/':return self.send_file(STATIC/'index.html','text/html; charset=utf-8')
        if route=='/static/style.css':return self.send_file(STATIC/'style.css','text/css; charset=utf-8')
        if route=='/static/app.js':return self.send_file(STATIC/'app.js','application/javascript; charset=utf-8')
        if route=='/api/me':return self.send_json({'user':self.session()})
        if not route.startswith('/api/'):return self.send_json({'error':'No encontrado'},404)
        user=self.required()
        if not user:return
        company=user['company_id']
        if route=='/api/instruments':return self.send_json({'items':instruments(company)})
        if route=='/api/dashboard':
            items=instruments(company); counts={s:sum(i['status']==s for i in items) for s in ['Vigente','Próximo','Vencido','Sin calibración']}
            return self.send_json({'total':len(items),'counts':counts,'instruments':items,'company':user['company_name']})
        if route=='/api/calibrations':
            params=parse_qs(urlparse(self.path).query)
            if params.get('instrument_id'):
                try:ident=int(params['instrument_id'][0])
                except ValueError:return self.send_json({'error':'ID inválido'},400)
                if not self.own_instrument(user,ident):return self.send_json({'error':'Instrumento no encontrado'},404)
                items=rows('SELECT * FROM calibrations WHERE instrument_id=? ORDER BY performed_on,id',(ident,))
            else:
                items=rows('SELECT c.*,i.code,i.name,i.unit,i.emp FROM calibrations c JOIN instruments i ON i.id=c.instrument_id WHERE i.company_id=? AND i.active=1 ORDER BY c.performed_on DESC,c.id DESC LIMIT 200',(company,))
            return self.send_json({'items':items})
        if route=='/api/decisions':
            return self.send_json({'items':rows('SELECT d.*,i.code,i.name FROM decisions d JOIN instruments i ON i.id=d.instrument_id WHERE i.company_id=? ORDER BY d.created_at DESC,d.id DESC',(company,))})
        if route=='/api/risk':
            result=[{'instrument_id':i['id'],'code':i['code'],'name':i['name'],'risk':get_risk(i['id'])} for i in instruments(company)]
            return self.send_json({'items':result})
        if route=='/api/compliance':
            return self.send_json({'items':[compliance_result(i) for i in instruments(company)]})
        if route=='/api/intermediate':
            results=rows('''SELECT c.*,i.code,i.name,i.unit,i.emp FROM intermediate_checks c
             JOIN instruments i ON i.id=c.instrument_id WHERE i.company_id=? AND i.active=1
             ORDER BY c.checked_on DESC,c.id DESC''',(company,))
            for c in results:
                c['error']=round(c['indicated_value']-c['reference_value'],10)
                c['attention']=abs(c['error'])+c['uncertainty']>c['emp']
            return self.send_json({'items':results})
        if route=='/api/export':
            output=io.StringIO();writer=csv.writer(output);writer.writerow(['Código','Instrumento','Tipo','Área','Unidad','EMP','Intervalo meses','Última calibración','Próxima calibración','Estado','Riesgo'])
            for x in instruments(company):writer.writerow([x.get(k,'') for k in ('code','name','kind','area','unit','emp','interval_months','last_calibration','next_calibration','status','risk')])
            content='\ufeff'+output.getvalue();b=content.encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="MetroCal_inventario.csv"');self.send_header('Content-Length',str(len(b)));self.end_headers();return self.wfile.write(b)
        return self.send_json({'error':'No encontrado'},404)

    def do_POST(self):
        route=urlparse(self.path).path
        payload=self.data()
        if not isinstance(payload,dict):return self.send_json({'error':'Datos JSON no válidos'},400)
        if route=='/api/login':
            username=str(payload.get('username','')).strip(); password=str(payload.get('password',''))
            u=single('SELECT u.*,c.name AS company_name FROM users u JOIN companies c ON c.id=u.company_id WHERE u.username=?',(username,))
            if not u or not check_password(password,u['password_hash']):return self.send_json({'error':'Usuario o contraseña incorrectos.'},401)
            sid=secrets.token_urlsafe(32)
            public={'id':u['id'],'company_id':u['company_id'],'username':u['username'],'name':u['name'],'company_name':u['company_name']}
            with LOCK:SESSIONS[sid]=public
            return self.send_json({'user':public},cookie=f'metrocal_sid={sid}; HttpOnly; SameSite=Strict; Path=/')
        if route=='/api/logout':
            ck=SimpleCookie();ck.load(self.headers.get('Cookie',''))
            if ck.get('metrocal_sid'):
                with LOCK:SESSIONS.pop(ck['metrocal_sid'].value,None)
            return self.send_json({'ok':True},cookie='metrocal_sid=; HttpOnly; Max-Age=0; SameSite=Strict; Path=/')
        user=self.required()
        if not user:return
        if route in ('/api/instruments','/api/instruments/update'):
            try:
                code=str(payload.get('code','')).strip().upper();name=str(payload.get('name','')).strip()
                kind=str(payload.get('kind','')).strip();area=str(payload.get('area','')).strip();unit=str(payload.get('unit','')).strip()
                emp=float(payload['emp']);months=int(payload['interval_months']);risk=str(payload.get('risk','Media'))
                last=payload.get('last_calibration') or None
                if last:date.fromisoformat(last)
                if not code or not name or not unit or not kind or emp<=0 or months<1 or months>120 or risk not in ('Alta','Media','Baja'):raise ValueError()
                if route.endswith('update'):
                    ident=int(payload['id'])
                    if not self.own_instrument(user,ident):return self.send_json({'error':'Instrumento no encontrado'},404)
                    with db() as con:con.execute('UPDATE instruments SET code=?,name=?,kind=?,area=?,unit=?,emp=?,interval_months=?,last_calibration=?,risk=? WHERE id=?',(code,name,kind,area,unit,emp,months,last,risk,ident))
                else:
                    with db() as con:con.execute('INSERT INTO instruments(company_id,code,name,kind,area,unit,emp,interval_months,last_calibration,risk) VALUES(?,?,?,?,?,?,?,?,?,?)',(user['company_id'],code,name,kind,area,unit,emp,months,last,risk))
                return self.send_json({'ok':True})
            except sqlite3.IntegrityError:return self.send_json({'error':'Código duplicado para esta empresa.'},409)
            except (ValueError,KeyError,TypeError):return self.send_json({'error':'Revisa campos obligatorios, EMP positivo y meses de intervalo.'},400)
        if route=='/api/instruments/delete':
            try:ident=int(payload['id'])
            except (ValueError,KeyError,TypeError):return self.send_json({'error':'ID inválido'},400)
            if not self.own_instrument(user,ident):return self.send_json({'error':'Instrumento no encontrado'},404)
            with db() as con:con.execute('UPDATE instruments SET active=0 WHERE id=?',(ident,))
            return self.send_json({'ok':True})
        if route=='/api/intermediate':
            try:
                ident=int(payload['instrument_id'])
                inst=self.own_instrument(user,ident)
                if not inst:return self.send_json({'error':'Instrumento no encontrado.'},404)
                checked_on=str(payload['checked_on']);date.fromisoformat(checked_on)
                ref=float(payload['reference_value']);ind=float(payload['indicated_value'])
                unc=float(payload.get('uncertainty',0))
                person=str(payload.get('performed_by','')).strip()[:150]
                pattern=str(payload.get('pattern_code','')).strip()[:150]
                notes=str(payload.get('notes','')).strip()[:1000]
                if not person or unc<0 or not all(math.isfinite(x) and abs(x)<1e12 for x in (ref,ind,unc)):raise ValueError()
                with db() as con:
                    con.execute('''INSERT INTO intermediate_checks
                       (instrument_id,checked_on,reference_value,indicated_value,uncertainty,performed_by,pattern_code,notes)
                       VALUES(?,?,?,?,?,?,?,?)''',(ident,checked_on,ref,ind,unc,person,pattern,notes))
                error=ind-ref
                return self.send_json({'ok':True,'error':error,'attention':abs(error)+unc>inst['emp']})
            except (ValueError,KeyError,TypeError):return self.send_json({'error':'Revisa los datos de la comprobación y el responsable.'},400)
        if route=='/api/calibrations':
            try:
                ident=int(payload['instrument_id']);inst=self.own_instrument(user,ident)
                if not inst:return self.send_json({'error':'Instrumento no encontrado'},404)
                performed=str(payload['performed_on']);date.fromisoformat(performed)
                error=float(payload['error']);uncertainty=float(payload.get('uncertainty',0))
                if uncertainty<0 or not all(map(lambda x:abs(x)<1e12,(error,uncertainty))):raise ValueError()
                technician=str(payload.get('technician',''))[:150];remarks=str(payload.get('remarks',''))[:1000]
                adjusted=int(bool(payload.get('adjusted',False)))
                cert=str(payload.get('certificate_number','')).strip()[:150]
                lab=str(payload.get('laboratory','')).strip()[:200]
                pat=str(payload.get('reference_pattern','')).strip()[:200]
                with db() as con:con.execute('''INSERT INTO calibrations
                   (instrument_id,performed_on,error,uncertainty,technician,remarks,adjusted,certificate_number,laboratory,reference_pattern)
                   VALUES(?,?,?,?,?,?,?,?,?,?)''',(ident,performed,error,uncertainty,technician,remarks,adjusted,cert,lab,pat))
                return self.send_json({'ok':True,'conformity':'Revisar' if abs(error)+uncertainty>inst['emp'] else 'Dentro del criterio simplificado'})
            except (ValueError,KeyError,TypeError):return self.send_json({'error':'Revisa fecha, error e incertidumbre.'},400)
        if route=='/api/risk':
            try:
                ident=int(payload['instrument_id'])
                if not self.own_instrument(user,ident):return self.send_json({'error':'Instrumento no encontrado.'},404)
                values=[int(payload[k]) for k in ('usage','environment','impact','history','check_frequency')]
                if any(v not in (1,2,3) for v in values):raise ValueError()
                assessed_by=str(payload.get('assessed_by','')).strip()[:120]
                mitigation=str(payload.get('mitigation','')).strip()[:700]
                if not assessed_by or not mitigation:raise ValueError()
                with db() as con:con.execute("""INSERT INTO risk_assessments(instrument_id,usage,environment,impact,history,check_frequency,mitigation,assessed_by,reviewed_on)
                  VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET usage=excluded.usage,environment=excluded.environment,
                  impact=excluded.impact,history=excluded.history,check_frequency=excluded.check_frequency,
                  mitigation=excluded.mitigation,assessed_by=excluded.assessed_by,reviewed_on=excluded.reviewed_on""",
                  (ident,*values,mitigation,assessed_by,date.today().isoformat()))
                return self.send_json({'ok':True,'risk':get_risk(ident)})
            except (KeyError,ValueError,TypeError):return self.send_json({'error':'Complete los cinco factores (1–3), responsable y medidas.'},400)
        if route=='/api/compliance':
            try:
                ident=int(payload['instrument_id'])
                inst=self.own_instrument(user,ident)
                if not inst:return self.send_json({'error':'Instrumento no encontrado.'},404)
                by=str(payload.get('reviewed_by','')).strip()[:120]
                certificate=str(payload.get('certificate','')).strip()[:250]
                notes=str(payload.get('notes','')).strip()[:700]
                if not by:raise ValueError()
                checks=[int(bool(payload.get(k))) for k in ('traceability','identified','protected')]
                with db() as con:con.execute("""INSERT INTO compliance_evidence(instrument_id,traceability,identified,protected,certificate,notes,reviewed_by,reviewed_on)
                  VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET
                  traceability=excluded.traceability,identified=excluded.identified,protected=excluded.protected,
                  certificate=excluded.certificate,notes=excluded.notes,reviewed_by=excluded.reviewed_by,reviewed_on=excluded.reviewed_on""",
                  (ident,*checks,certificate,notes,by,date.today().isoformat()))
                return self.send_json({'ok':True,'item':compliance_result(enriched(inst))})
            except (KeyError,ValueError,TypeError):return self.send_json({'error':'Ingrese responsable y evidencia verificable.'},400)
        if route=='/api/calculate':
            try:ident=int(payload['instrument_id']);method=str(payload['method'])
            except (ValueError,KeyError,TypeError):return self.send_json({'error':'Selecciona instrumento y método.'},400)
            inst=self.own_instrument(user,ident)
            if not inst:return self.send_json({'error':'Instrumento no encontrado'},404)
            hist=rows('SELECT * FROM calibrations WHERE instrument_id=? ORDER BY performed_on,id',(ident,))
            return self.send_json(calculate(inst,hist,method))
        if route=='/api/decisions':
            try:
                ident=int(payload['instrument_id']);inst=self.own_instrument(user,ident)
                if not inst:return self.send_json({'error':'Instrumento no encontrado'},404)
                method=str(payload['method']);suggested=int(payload['suggested_interval'])
                approver=str(payload.get('approved_by','')).strip();note=str(payload.get('note','')).strip()
                if not approver or not note or suggested<1 or suggested>120:raise ValueError()
                hist=rows('SELECT * FROM calibrations WHERE instrument_id=? ORDER BY performed_on,id',(ident,))
                proposal=calculate(inst,hist,method)
                if not proposal.get('ok') or proposal['suggested']!=suggested:return self.send_json({'error':'La recomendación cambió. Vuelve a calcular antes de aprobar.'},409)
                with db() as con:
                    con.execute('INSERT INTO decisions(instrument_id,method,previous_interval,suggested_interval,note,approved_by) VALUES(?,?,?,?,?,?)',(ident,method,inst['interval_months'],suggested,note,approver))
                    con.execute('UPDATE instruments SET interval_months=? WHERE id=?',(suggested,ident))
                return self.send_json({'ok':True})
            except (ValueError,KeyError,TypeError):return self.send_json({'error':'Completa responsable, justificación e intervalo.'},400)
        return self.send_json({'error':'No encontrado'},404)


def main():
    init_db()
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    url=f'http://127.0.0.1:{PORT}'
    print('\n'+'='*58+f'\n MetroCal Web - {url}\n Usuario demo: admin  |  Contraseña: MetroCal2026!\n Ctrl+C para cerrar\n'+'='*58+'\n',flush=True)
    threading.Timer(1.0,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
