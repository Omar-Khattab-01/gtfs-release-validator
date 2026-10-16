import csv
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from gtfs_validator.feed_index import get_index, clear_indexes
from gtfs_validator.hastus_diagnostics import parse_message, decode_log, export_trips
from gtfs_validator.inspection import inspect_feed
from gtfs_validator.web import Job, JOBS, ValidatorHandler, _run_job
from test_validator import FILES, write_feed


ITINERARY='Warning:  Trip pattern route:    13 Number:          97 has at least one missing itinerary. The generated files might be invalid.'


class HastusDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.feed=self.root/'source.zip'
        write_feed(self.feed,extra={'trips.txt':FILES['trips.txt'].replace('shape19','130097'),
                                    'error_warning.txt':ITINERARY+'\nWarning: Something new <script>\n'})

    def tearDown(self):
        clear_indexes();self.temp.cleanup()

    def test_missing_shape_log_correlation_and_exact_trip_csv(self):
        data=inspect_feed(str(self.feed),'hastus');diag=data['hastus_diagnostics']
        self.assertEqual(1,diag['counts']['missing_shapes'])
        self.assertEqual(1,diag['counts']['affected_trips'])
        group=diag['missing_shapes'][0]
        self.assertEqual('130097',group['shape_id']);self.assertEqual(2,group['stop_time_count'])
        self.assertEqual([1],group['log_lines']);self.assertEqual(0,group['trips_without_stop_times'])
        entry=diag['log']['messages'][0]
        self.assertEqual('97',entry['pattern_id']);self.assertEqual(['t1'],entry['trip_ids'])
        self.assertEqual('confirmed_defect',entry['assessment'])
        unknown=diag['log']['messages'][1]
        self.assertEqual('unknown',unknown['kind']);self.assertIn('<script>',unknown['raw'])
        exported=list(csv.DictReader(io.StringIO(export_trips(diag).decode('utf-8-sig'))))
        self.assertEqual('t1',exported[0]['trip_id']);self.assertEqual('2',exported[0]['stop_time_count'])
        self.assertEqual('97',exported[0]['oig_pattern_ids'])
        self.assertEqual(11,len(diag['rule_inventory']))
        self.assertTrue(any(f['rule_id']=='REL009' for f in data['validation']['findings']))
        self.assertTrue(all(f['severity']!='error' for f in data['validation']['findings'] if f['rule_id']=='OIG001'))

    def test_absent_empty_and_stale_log_do_not_hide_independent_defects(self):
        for log in ['',ITINERARY.replace('97','98')]:
            write_feed(self.feed,extra={'trips.txt':FILES['trips.txt'].replace('shape19','130097'),'error_warning.txt':log});clear_indexes()
            diag=inspect_feed(str(self.feed),'hastus')['hastus_diagnostics']
            self.assertEqual(1,diag['counts']['affected_trips'])
            self.assertEqual([],diag['missing_shapes'][0]['log_lines'])
            if log:self.assertEqual([],diag['log']['messages'][0]['trip_ids'])
        write_feed(self.feed);clear_indexes()
        self.assertEqual('not_supplied',inspect_feed(str(self.feed),'hastus')['hastus_diagnostics']['log']['status'])
        self.assertIsNone(inspect_feed(str(self.feed),'cad')['hastus_diagnostics'])
        self.assertIsNotNone(inspect_feed(str(self.feed),'rail')['hastus_diagnostics'])

    def test_source_warning_with_present_shape_is_not_confirmed_defect(self):
        write_feed(self.feed,extra={'trips.txt':FILES['trips.txt'].replace('shape19','130097'),
                                    'shapes.txt':FILES['shapes.txt'].replace('shape19','130097'),'error_warning.txt':ITINERARY})
        diag=inspect_feed(str(self.feed),'hastus')['hastus_diagnostics']
        self.assertEqual(0,diag['counts']['missing_shapes'])
        self.assertEqual('source_review',diag['log']['messages'][0]['assessment'])

    def test_station_warning_shows_valid_name_and_parent_without_false_error(self):
        stops=FILES['stops.txt'].replace('10017,ST-LAURENT D,45.422,-75.638,0,,0','10017,ST-LAURENT D,45.422,-75.638,0,parent,0')+'parent,ST-LAURENT,45.422,-75.638,1,,0\n'
        message='Warning: Station 3034 (10017) Platform D is marked with usage station but is missing an english station description.'
        write_feed(self.feed,extra={'stops.txt':stops,'error_warning.txt':message})
        data=inspect_feed(str(self.feed),'hastus');entry=data['hastus_diagnostics']['log']['messages'][0]
        self.assertEqual('source_review',entry['assessment'])
        self.assertEqual('ST-LAURENT',entry['evidence'][0]['parent_station']['stop_name'])
        self.assertEqual(['r19'],entry['route_ids']);self.assertEqual(['t1'],entry['trip_ids'])
        self.assertTrue(any(data['validation']['findings'][number]['rule_id']=='OIG001' for number in data['routes'][0]['finding_indices']))

    def test_all_eleven_message_conditions(self):
        cases={
            'scheduling_units':'Error: WKD is planned for dates in more than one scheduling unit (A, B).',
            'operating_exception':'Error: WKD has at least one day exception with no variations operating on the day: 20261015 for scheduling unit A.',
            'missing_itinerary':ITINERARY,
            'deleted_pattern':'Error: Booking: X Vehicle schedule: Y has at least one trip with an assigned trip pattern that does not exist anymore.',
            'stop_location':'Warning: Trip pattern route: 13 Number: 97 uses a stop location identifier: AA-2 different from the default stop location: AA-1',
            'destination_names':'Warning: Trips for route: 13 Direction: Town has no name for its last node/timpoint: AA',
            'station_code':'Warning: Stop 1234 (AA) is marked with usage station but does not have a 560 number starting with 30.',
            'stop_usage':'Warning: Station 3034 (AA) has a 560# starting with 30 but is marked with usage stop not station.',
            'station_description':'Warning: Station 3034 (AA) is marked with usage station but is missing an english station description.',
            'route_colours':'Error: Route 13 is missing its main and secondary colour values.',
            'route_directions':'Error: Route 13 is missing its Public Information direction names.'}
        for expected,raw in cases.items():
            with self.subTest(expected=expected):self.assertEqual(expected,parse_message(raw,1)['kind'])
        self.assertEqual('WKD',parse_message(cases['operating_exception'],1)['service_id'])

    def test_french_templates_and_encoding(self):
        raw='Avertissement: Parcours type ligne: R Numéro: 12345 a au moins un itinéraire manquant.'
        parsed=parse_message(raw,4)
        self.assertEqual('R12345',parsed['shape_id']);self.assertEqual('Warning',parsed['source_severity'])
        text,encoding,warning=decode_log(raw.encode('cp1252'))
        self.assertEqual(raw,text);self.assertIn('assumed',encoding);self.assertTrue(warning)
        self.assertEqual(raw,decode_log(raw.encode('utf-16'))[0])
        self.assertIn('replaced',decode_log(b'\x81invalid')[2])
        french={
            'scheduling_units':"Erreur: WKD est planifié pour des dates dans plus d'une unité horaire (A, B).",
            'operating_exception':"Erreur: WKD a au moins une variation journalière sans variations en service pour ce jour: demain",
            'deleted_pattern':"Erreur: Horaire a au moins un voyage ayant un parcours type assigné n'existant plus.",
            'stop_location':"Avertissement: Parcours type ligne: 13 Numéro: 97 utilise une localisation d'arrêt: A-2 différente de la localisation de défaut: A-1"}
        for expected,message in french.items():self.assertEqual(expected,parse_message(message,1)['kind'])

    def test_log_is_text_not_csv_and_saved_index_keeps_encoding(self):
        # A comma and quotes must remain literal message text, including line one.
        message='Warning: Unknown, "not CSV"\n'+ITINERARY
        write_feed(self.feed,extra={'error_warning.txt':message})
        with patch.dict(os.environ,{'GTFS_VALIDATOR_CACHE_DIR':str(self.root/'cache')}):
            first=get_index(str(self.feed),persist=True)
            self.assertEqual(['line_number','message'],first.columns['error_warning.txt'])
            self.assertEqual('Warning: Unknown, "not CSV"',first.rows('error_warning.txt')[0]['message'])
            del first;clear_indexes()
            restored=get_index(str(self.feed),persist=True)
            self.assertEqual('Reused saved index',restored.cache_status)
            self.assertEqual('UTF-8',next(f for f in restored.files if f['name']=='error_warning.txt')['text_log']['encoding'])
            self.assertEqual(2,len(restored.rows('error_warning.txt')))

    def test_missing_shape_without_stop_times_and_formula_safe_export(self):
        write_feed(self.feed,extra={'trips.txt':FILES['trips.txt'].replace('shape19','absent').replace('Parliament','=malicious'),
                                    'stop_times.txt':FILES['stop_times.txt'].splitlines()[0]+'\n'})
        diag=inspect_feed(str(self.feed),'hastus')['hastus_diagnostics']
        self.assertEqual(1,diag['missing_shapes'][0]['trips_without_stop_times'])
        self.assertIn("'=malicious",export_trips(diag).decode('utf-8-sig'))
        with self.assertRaises(ValueError):export_trips(diag,'invalid')

    def test_all_route_versions_and_service_links_are_retained(self):
        routes=FILES['routes.txt'].replace('r19,','13-373,')+FILES['routes.txt'].splitlines()[1].replace('r19,','13-374,')+'\n'
        first=FILES['trips.txt'].replace('r19,','13-373,').replace('shape19','130097')
        trips=first+first.splitlines()[1].replace('13-373,','13-374,').replace(',t1,',',t2,')+'\n'
        message=ITINERARY+'\nError: WKD is planned for dates in more than one scheduling unit (A, B).'
        write_feed(self.feed,extra={'routes.txt':routes,'trips.txt':trips,'error_warning.txt':message})
        data=inspect_feed(str(self.feed),'hastus')['hastus_diagnostics']
        self.assertEqual(2,len(data['missing_shapes']))
        for entry in data['log']['messages']:
            self.assertEqual(['13-373','13-374'],entry['route_ids'])
            self.assertEqual(['t1','t2'],entry['trip_ids'])
        self.assertEqual('source_review',data['log']['messages'][1]['assessment'])

    def test_http_csv_and_saved_audit_include_diagnostics(self):
        job=Job('hastus-diagnostics','',str(self.feed),save_indexes=True)
        with patch.dict(os.environ,{'GTFS_VALIDATOR_CACHE_DIR':str(self.root/'cache')}):
            _run_job(job)
            restored=Job('restored','',str(self.feed),save_indexes=True)
            with patch('gtfs_validator.web.add_inspections',side_effect=AssertionError('Did not reuse saved audit')):_run_job(restored)
            self.assertEqual('complete',restored.status,restored.error)
            self.assertEqual(1,restored.report['stats']['individual_feeds']['hastus']['hastus_diagnostics']['counts']['affected_trips'])
        JOBS[job.id]=job
        server=ThreadingHTTPServer(('127.0.0.1',0),ValidatorHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}/api/runs/{job.id}/hastus-trips.csv?source=hastus'
        try:
            with urllib.request.urlopen(url+'&group=0') as response:
                self.assertIn('attachment',response.headers['Content-Disposition'])
                records=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
            self.assertEqual(['t1'],[row['trip_id'] for row in records])
            with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(url+'&group=bad')
            self.assertEqual(400,caught.exception.code)
        finally:server.shutdown();server.server_close();thread.join();JOBS.pop(job.id,None)
