import copy,importlib.util,json,sys,unittest
from datetime import datetime
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from audit_simple_daily import audit

class DailyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('techprobe',ROOT/'adapters/supermind_tech1_daily_probe.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        dates=pd.bdate_range('2018-09-03','2019-06-28');n=len(dates)
        c=[10+i*.01 for i in range(n)]
        frame=pd.DataFrame(dict(close=c,high=[v+.02 for v in c],low=[v-.02 for v in c],
                                factor=[1.]*n,volume=[10_000_000.]*(n-2)+[20_000_000.,20_000_000.],
                                turnover=[100_000_000.]*n,is_st=[0.]*n,is_paused=[0.]*n),index=dates)
        module.get_price=lambda symbols,*args,**kw:{s:frame.copy() for s in symbols}
        module.get_all_securities=lambda *args:pd.DataFrame(index=['600001.SH'])
        module.get_datetime=lambda:datetime(2026,9,4)
        module.log=type('Log',(),{'info':lambda *args:None})()
        cls.frame=frame;cls.packets={};module.emit_packet=lambda k,v:cls.packets.update({k:v})
        module.before_trading(None)
    def test_platform_filter_and_independent_reconstruction_agree(self):
        report=audit(self.packets)
        self.assertEqual(report['status'],'PASS_TECH1_QUARTER_SCREEN')
        self.assertEqual(sum(len(d['candidates']) for d in report['days']),2)
        self.assertEqual(len(report['minute_requests']),1)
    def test_omitted_security_and_changed_indicator_fail(self):
        p=copy.deepcopy(self.packets);p['tech1_2019-06-28']['candidates']=[]
        with self.assertRaisesRegex(ValueError,'分区'):audit(p)
        p=copy.deepcopy(self.packets);p['tech1_2019-06-28']['candidates'][0]['ma20']+=1
        with self.assertRaisesRegex(ValueError,'重算'):audit(p)
    def test_future_window_and_missing_quarter_fail(self):
        p=copy.deepcopy(self.packets);p['tech1_2019-06-28']['candidates'][0]['audit_window']['dates'][-1]='2019-07-01'
        with self.assertRaisesRegex(ValueError,'未来'):audit(p)
        p=copy.deepcopy(self.packets);del p['tech1_2019-04-01']
        with self.assertRaisesRegex(ValueError,'不完整'):audit(p)
    def test_source_errors_never_become_pass(self):
        p=copy.deepcopy(self.packets);d=p['tech1_2019-06-28'];d['candidates']=[];d['errors']=[['600001.SH','INVALID_DATA']]
        self.assertEqual(audit(p)['status'],'BLOCKED_DAILY_SOURCE_ERRORS')
    def test_market_closed_cannot_hide_candidates_on_market_open_day(self):
        p=copy.deepcopy(self.packets);d=p['tech1_2019-06-28']
        d['candidates']=[];d['excluded']={'MARKET_CLOSED':['600001.SH']}
        with self.assertRaisesRegex(ValueError,'大盘关闭'):audit(p)
    def test_array_exporter_preserves_original_rule_outputs(self):
        spec=importlib.util.spec_from_file_location('fastprobe',ROOT/'adapters/supermind_tech1_history_probe.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.WARMUP='20180901';module.START='2019-03-29';module.END='20190628'
        module.get_price=lambda symbols,*args,**kw:{s:self.frame.copy() for s in symbols}
        module.get_all_securities=lambda *args:pd.DataFrame(index=['600001.SH'])
        module.get_datetime=lambda:datetime(2026,9,4)
        module.log=type('Log',(),{'info':lambda *args:None})()
        packets={};module.emit_packet=lambda k,v:packets.update({k:v})
        module.before_trading(None)
        self.assertEqual(audit(packets),audit(self.packets))
    def test_real_equal_means_do_not_create_breakout_signal(self):
        fixture=json.loads((ROOT/'reports/simple_research/2018/precision_boundary_fixture.json').read_text(encoding='utf8'))
        w=fixture['audit_window'];frame=pd.DataFrame(w['data'],index=pd.to_datetime(w['dates']))
        prefix=pd.DataFrame({k:[float(frame[k].iloc[0])]*120 for k in frame},index=pd.bdate_range(end=frame.index[0]-pd.Timedelta(days=1),periods=120))
        frame=pd.concat([prefix,frame])
        spec=importlib.util.spec_from_file_location('precisionprobe',ROOT/'adapters/supermind_tech1_history_probe.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.START='2018-03-16';module.get_price=lambda symbols,*args,**kw:{s:frame.copy() for s in symbols}
        module.get_all_securities=lambda *args:pd.DataFrame(index=['002367.SZ'])
        module.get_datetime=lambda:datetime(2026,9,4);module.log=type('Log',(),{'info':lambda *args:None})()
        packets={};module.emit_packet=lambda k,v:packets.update({k:v});module.before_trading(None)
        self.assertEqual(packets['tech1_2018-03-16']['candidates'],[])
        self.assertEqual(packets['tech1_2018-03-16']['excluded'],{'NO_TECH_SIGNAL':['002367.SZ']})
    def test_transport_risk_filter_preserves_minute_requests(self):
        spec=importlib.util.spec_from_file_location('riskprobe',ROOT/'adapters/supermind_tech1_history_probe.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        m.START='2019-03-29';frame=self.frame.copy();frame['high']=frame['close']+2;frame['low']=frame['close']-2
        m.get_price=lambda symbols,*args,**kw:{s:frame.copy() for s in symbols}
        m.get_all_securities=lambda *args:pd.DataFrame(index=['600001.SH']);m.get_datetime=lambda:datetime(2026,9,4)
        m.log=type('Log',(),{'info':lambda *args:None})();packets={};m.emit_packet=lambda k,v:packets.update({k:v})
        m.before_trading(None);before=audit(packets)
        self.assertTrue(sum(len(d['candidates']) for d in before['days']))
        m.ONLY_EXECUTABLE=True;packets.clear();m.before_trading(None);after=audit(packets)
        self.assertEqual(before['minute_requests'],after['minute_requests'])
        self.assertFalse(sum(len(d['candidates']) for d in after['days']))

if __name__=='__main__':unittest.main()
