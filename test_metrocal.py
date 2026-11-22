"""Pruebas automáticas (stdlib). Ejecutar: py -m unittest -v"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import app

class TestMetroCal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patcher=patch.object(app, 'DB', Path(self.tmp.name)/'test.sqlite3')
        self.patcher.start()
        app.init_db()
    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()
    def test_seed(self):
        self.assertEqual(len(app.instruments(1)),12)
    def test_date_end_of_month(self):
        self.assertEqual(app.add_months('2026-01-31',1),'2026-02-28')
    def test_risk_levels(self):
        with app.db() as con:
            con.execute('INSERT INTO risk_assessments(instrument_id,usage,environment,impact,history,check_frequency,mitigation,assessed_by,reviewed_on) VALUES(1,1,1,1,1,1,?,?,?)',('Controles','Prueba',date.today().isoformat()))
        self.assertEqual(app.get_risk(1)['level'],'Bajo')
    def test_missing_risk_blocks_extension(self):
        inst=app.instruments(1)[0]
        with app.db() as con:
            con.execute('INSERT INTO calibrations(instrument_id,performed_on,error,uncertainty) VALUES(?,?,?,?)',(inst['id'],'2026-11-20',0.01,0.001))
        history=app.rows('SELECT * FROM calibrations WHERE instrument_id=? ORDER BY performed_on,id',(inst['id'],))
        result=app.calculate(inst,history,'escalera')
        self.assertFalse(result['ok'])
        self.assertIn('bloqueada',result['message'])
    def test_low_risk_allows_extension(self):
        inst=app.instruments(1)[0]
        with app.db() as con:
            con.execute('INSERT INTO risk_assessments(instrument_id,usage,environment,impact,history,check_frequency,mitigation,assessed_by,reviewed_on) VALUES(1,1,1,1,1,1,?,?,?)',('Control','Prueba',date.today().isoformat()))
        result=app.calculate(inst,app.rows('SELECT * FROM calibrations WHERE instrument_id=? ORDER BY performed_on,id',(inst['id'],)),'escalera')
        self.assertTrue(result['ok'])
    def test_compliance_incomplete_without_evidence(self):
        inst=app.instruments(1)[0]
        self.assertFalse(app.compliance_result(inst)['complete'])
    def test_intermediate_alert_prevents_extension(self):
        with app.db() as con:
            con.execute('INSERT INTO risk_assessments(instrument_id,usage,environment,impact,history,check_frequency,mitigation,assessed_by,reviewed_on) VALUES(1,1,1,1,1,1,?,?,?)',('Controles','Prueba',date.today().isoformat()))
            con.execute('INSERT INTO intermediate_checks(instrument_id,checked_on,reference_value,indicated_value,uncertainty,performed_by) VALUES(?,?,?,?,?,?)',(1,date.today().isoformat(),0,0.3,0.01,'Técnico'))
        inst=app.instruments(1)[0]
        hist=app.rows('SELECT * FROM calibrations WHERE instrument_id=? ORDER BY performed_on,id',(1,))
        result=app.calculate(inst,hist,'escalera')
        self.assertFalse(result['ok'])
        self.assertIn('verificación intermedia',result['message'])
    def test_traceability_columns_exist(self):
        with app.db() as con:
            cols={r[1] for r in con.execute('PRAGMA table_info(calibrations)')}
        self.assertTrue({'certificate_number','laboratory','reference_pattern'} <= cols)

if __name__=='__main__':unittest.main()
