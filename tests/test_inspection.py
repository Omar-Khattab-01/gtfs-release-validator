import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from gtfs_validator import viewer
from gtfs_validator.feed_index import clear_indexes
from gtfs_validator.inspection import inspect_feed
from gtfs_validator.source_final import compare_source_final
from gtfs_validator.web import Job,_run_job,ValidatorHandler,JOBS
from test_validator import FILES,write_feed


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)
        self.feed=self.directory/'feed.zip';write_feed(self.feed)
    def tearDown(self):
        clear_indexes();self.temp.cleanup()

    def test_each_role_can_be_supplied_alone(self):
        for source,field in [('hastus','hastus_path'),('cad','clevercad_path'),('rail','rail_path'),('final','final_path')]:
            with self.subTest(source=source):
                job=Job(source,'','',**({} if source in {'cad','hastus'} else {field:str(self.feed)}))
                if source in {'cad','hastus'}:setattr(job,field,str(self.feed))
                _run_job(job)
                self.assertEqual('complete',job.status,job.error)
                self.assertIn(source,job.report['stats']['individual_feeds'])
                self.assertEqual(1,job.report['stats']['individual_feeds'][source]['inventory']['trips'])
                self.assertEqual('not_available',job.report['stats']['workflow']['bus_comparison'])

    def test_bus_rail_inspection_does_not_require_cad(self):
        job=Job('bus-rail','',str(self.feed),rail_path=str(self.feed));_run_job(job)
        self.assertEqual('complete',job.status,job.error)
        self.assertEqual({'hastus','rail'},set(job.report['stats']['individual_feeds']))
        self.assertNotIn('trip_reconciliation',job.report['stats'])
        self.assertTrue(any(item['rule_id']=='INS015' for item in job.report['stats']['individual_feeds']['hastus']['validation']['findings']))

    def test_progressive_input_combinations_keep_each_inspector(self):
        rail=self.directory/'rail.zip'
        write_feed(rail,extra={'routes.txt':FILES['routes.txt'].replace('r19,OCT,19,','rail1,OCT,1,').replace(',3,DA291C',',0,DA291C'),
                              'trips.txt':FILES['trips.txt'].replace('r19,','rail1,')})
        fields={'cad':'clevercad_path','hastus':'hastus_path','rail':'rail_path','final':'final_path'}
        for sources in [('cad','hastus'),('cad','rail'),('cad','final'),('hastus','rail','final'),('cad','hastus','rail','final')]:
            with self.subTest(sources=sources):
                job=Job('combination','','')
                for source in sources:setattr(job,fields[source],str(rail if source=='rail' else self.feed))
                _run_job(job)
                self.assertEqual('complete',job.status,job.error)
                self.assertEqual(set(sources),set(job.report['stats']['individual_feeds']))
                self.assertEqual('complete' if 'cad' in sources and 'hastus' in sources else 'not_available',job.report['stats']['workflow']['bus_comparison'])

    def test_incomplete_rail_in_bus_is_flagged_and_still_browsable(self):
        write_feed(self.feed,extra={'routes.txt':FILES['routes.txt'].replace(',3,DA291C',',0,DA291C'),
                                    'stop_times.txt':FILES['stop_times.txt'].splitlines()[0]+'\n',
                                    'trips.txt':FILES['trips.txt'].replace('shape19','not-a-shape')})
        data=inspect_feed(str(self.feed),'hastus')
        rules={row['rule_id'] for row in data['validation']['findings']}
        self.assertTrue({'INS008','INS010','REL009'} <= rules)
        self.assertEqual(1,data['inventory']['rail_routes'])
        self.assertEqual('needs_review',data['routes'][0]['status'])
        detail=viewer.route_detail(str(self.feed),'r19')
        self.assertEqual(1,len(detail['variations']));self.assertEqual(0,detail['variations'][0]['stop_count'])

    def test_optional_release_files_are_not_source_errors(self):
        # Generate a fresh test archive; supplied archives are never changed.
        selected={name:value for name,value in FILES.items() if name not in {'feed_info.txt','shapes.txt'}}
        selected['trips.txt']=selected['trips.txt'].replace('shape19','')
        write_feed(self.feed)
        path=self.directory/'minimal-source.zip'
        with zipfile.ZipFile(path,'w') as archive:
            for name,value in selected.items():
                info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=(0o100644)<<16
                archive.writestr(info,value)
        data=inspect_feed(str(path),'hastus')
        missing=[item for item in data['validation']['findings'] if item['rule_id']=='PKG014']
        self.assertTrue(missing);self.assertTrue(all(item['severity']=='info' for item in missing))
        self.assertTrue(any(item['rule_id']=='INS012' and item['category']=='Agency review' for item in data['validation']['findings']))

    def test_all_files_inventory_unknown_table_and_row_counts(self):
        write_feed(self.feed,extra={'custom.txt':'id,value\n001,hello\n002,world\n'})
        data=inspect_feed(str(self.feed),'hastus')
        custom=next(item for item in data['files'] if item['name']=='custom.txt')
        self.assertEqual(2,custom['rows']);self.assertEqual(['id','value'],custom['columns'])
        self.assertIn('no table-specific rules',custom['check_coverage'])

    def test_invalid_sequences_remain_inspectable(self):
        write_feed(self.feed,extra={'stop_times.txt':FILES['stop_times.txt'].replace('10017,1','10017,bad'),
                                   'shapes.txt':FILES['shapes.txt'].replace('-75.639,1','-75.639,bad')})
        self.assertEqual(1,len(viewer.route_detail(str(self.feed),'r19')['variations']))
        self.assertEqual(2,len(viewer.trip_detail(str(self.feed),'t1')['shape']))

    def test_missing_required_values_and_stations(self):
        write_feed(self.feed,extra={'stops.txt':FILES['stops.txt'].replace('ST-LAURENT D,45.422',' ,').replace('PARLIAMENT A,45.423,-75.700,0,,0','PARLIAMENT A,45.423,-75.700,2,,0'),
                                    'trips.txt':FILES['trips.txt'].replace('WKD,t1',',t1')})
        rules={row['rule_id'] for row in inspect_feed(str(self.feed),'rail')['validation']['findings']}
        self.assertTrue({'INS001','INS002','INS003','REL012'}<=rules)

    def test_empty_optional_calendar_exceptions_and_boarding_area_parent(self):
        stops=FILES['stops.txt']+'BA,Boarding area,,,4,10017,0\n'
        write_feed(self.feed,extra={'calendar_dates.txt':FILES['calendar_dates.txt'].splitlines()[0]+'\n','stops.txt':stops})
        data=inspect_feed(str(self.feed),'hastus')
        self.assertFalse(any(row['rule_id']=='REL011' for row in data['validation']['findings']))
        self.assertTrue(all(row['severity']=='info' for row in data['validation']['findings'] if row['rule_id']=='CSV007'))

    def test_single_source_final_match_changed_and_missing(self):
        final=self.directory/'final.zip';write_feed(final)
        self.assertEqual({'matching':1},compare_source_final(str(self.feed),str(final))['counts'])
        write_feed(final,extra={'stop_times.txt':FILES['stop_times.txt'].replace('25:15:00','25:16:00')})
        clear_indexes()
        self.assertEqual({'changed':1},compare_source_final(str(self.feed),str(final))['counts'])
        write_feed(final,extra={'routes.txt':FILES['routes.txt'].replace('OCT,19,','OCT,20,')});clear_indexes()
        self.assertEqual({'missing':1},compare_source_final(str(self.feed),str(final))['counts'])

    def test_single_hastus_plus_final_pipeline_and_technical_isolation(self):
        final=self.directory/'final.zip';write_feed(final)
        job=Job('hastus-final','',str(self.feed),str(final));_run_job(job)
        self.assertEqual('complete',job.status,job.error)
        self.assertEqual({'matching':1},job.report['stats']['source_final']['hastus']['counts'])
        self.assertFalse(any(item.get('context',{}).get('inspection_source') for item in job.final_validation['technical']['findings']))

    def test_single_source_final_attributes_and_coverage(self):
        final=self.directory/'final.zip'
        write_feed(final,extra={'routes.txt':FILES['routes.txt'].replace(',3,DA291C',',0,DA291C'),
                               'stops.txt':FILES['stops.txt'].replace('ST-LAURENT D','Changed platform')})
        result=compare_source_final(str(self.feed),str(final))
        self.assertEqual('needs_review',result['routes'][0]['status'])
        self.assertIn('route_type',result['routes'][0]['route_attribute_changes'][0]['fields'])
        self.assertEqual(1,result['routes'][0]['stop_difference_count'])
        self.assertEqual({'changed':1},result['counts'])
        write_feed(final,extra={'feed_info.txt':FILES['feed_info.txt'].replace('20261001,20261031','20270101,20270131'),
                               'calendar.txt':FILES['calendar.txt'].replace('20261001,20261031','20270101,20270131')})
        clear_indexes()
        self.assertEqual({'outside_final_window':1},compare_source_final(str(self.feed),str(final))['counts'])

    def test_one_bad_file_does_not_hide_other_individual_feeds(self):
        bad=self.directory/'bad.zip';bad.write_bytes(b'not a ZIP')
        job=Job('mixed','',str(bad),rail_path=str(self.feed));_run_job(job)
        self.assertEqual('complete',job.status,job.error)
        self.assertEqual('unavailable',job.report['stats']['individual_feeds']['hastus']['status'])
        self.assertEqual('complete',job.report['stats']['individual_feeds']['rail']['status'])
        self.assertEqual('not_compared',job.report['stats']['rail']['status'])

    def test_saved_single_source_restores_inspection(self):
        with patch.dict(os.environ,{'GTFS_VALIDATOR_CACHE_DIR':str(self.directory/'cache')}):
            first=Job('first','',str(self.feed),save_indexes=True);_run_job(first)
            second=Job('second','',str(self.feed),save_indexes=True)
            with patch('gtfs_validator.web.add_inspections',side_effect=AssertionError('Re-inspected saved run')):_run_job(second)
            self.assertEqual('complete',second.status,second.error)
            self.assertIn('Reused saved audit',second.audit_cache_status)
            self.assertEqual(first.report,second.report)

    def test_http_accepts_single_source_and_returns_exact_record(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),ValidatorHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        request=urllib.request.Request(base+'/api/runs',data=json.dumps({'hastus_path':str(self.feed)}).encode(),headers={'Content-Type':'application/json','X-GTFS-Validator':'1'})
        try:
            with urllib.request.urlopen(request) as response:identifier=json.load(response)['id']
            # Row inspection is available from the indexed feed even before checks finish.
            with urllib.request.urlopen(base+f'/api/runs/{identifier}/inspection-row?source=hastus&file=trips.txt&row=2') as response:record=json.load(response)
            self.assertEqual('t1',record['record']['trip_id'])
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+f'/api/runs/{identifier}/inspection-row?source=cad&file=trips.txt&row=2')
            self.assertEqual(400,error.exception.code)
            # Wait for this test-owned worker before removing its files.
            import time
            for _ in range(100):
                if JOBS[identifier].status in {'complete','failed'}:break
                time.sleep(.02)
            self.assertEqual('complete',JOBS[identifier].status,JOBS[identifier].error)
        finally:server.shutdown();server.server_close();thread.join()
