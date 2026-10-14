import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gtfs_validator.web import Job,_run_job
from gtfs_validator.rail import audit_rail,trip_evidence
from gtfs_validator.models import ValidationReport
from gtfs_validator.merge import validate_exports
from gtfs_validator.feed_index import clear_indexes
from gtfs_validator.audit_cache import identity
from test_validator import FILES,write_feed


def rail_files(final=False):
    files=dict(FILES)
    files['routes.txt']=files['routes.txt'].replace('r19,OCT,19,','rail-final,OCT,1,' if final else 'rail-source,OCT,1,').replace(',3,DA291C',',0,DA291C')
    files['trips.txt']=files['trips.txt'].replace('r19,WKD,t1,','rail-final,WKD,train,' if final else 'rail-source,WKD,train-WKD,')
    files['stop_times.txt']=files['stop_times.txt'].replace('t1,','train,' if final else 'train-WKD,')
    for name in ('stops.txt','stop_times.txt'):
        for a,b in [('10014','RA'),('10017','RB'),('20000','RC')]:files[name]=files[name].replace(a,b)
    return files


class RailTests(unittest.TestCase):
    def tearDown(self):clear_indexes()

    def test_rail_only_inspects_all_variations_without_comparing_bus_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'rail.zip';write_feed(path,extra=rail_files())
            job=Job('rail','','',rail_path=str(path));_run_job(job)
            self.assertEqual('complete',job.status,job.error)
            data=job.report['stats']['rail']
            self.assertEqual('not_compared',data['status'])
            self.assertEqual(1,data['trip_count'])
            self.assertEqual('not_compared',data['routes'][0]['variations'][0]['trips'][0]['status'])
            self.assertNotIn('trip_reconciliation',job.report['stats'])
            self.assertFalse(any(item['rule_id']=='RAIL002' for item in job.report['findings']))

    def test_rail_matches_final_with_route_version_and_service_suffix_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            rail,final=Path(directory)/'rail.zip',Path(directory)/'final.zip'
            write_feed(rail,extra=rail_files());write_feed(final,extra=rail_files(True))
            report=ValidationReport('test');data=audit_rail(str(rail),str(final),'','',report)
            trip=data['routes'][0]['variations'][0]['trips'][0]
            self.assertEqual('matching',trip['status'])
            self.assertEqual(['train'],trip['final_trip_ids'])
            evidence=trip_evidence(str(rail),str(final),trip['trip_id'],'train')
            self.assertEqual(2,len(evidence['alignment']))
            self.assertTrue(all(row['status']=='match' for row in evidence['alignment']))
            self.assertIn('rail',evidence['service'])

    def test_trip_stop_schedule_attributes_and_geometry_differences_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            rail,final=Path(directory)/'rail.zip',Path(directory)/'final.zip'
            write_feed(rail,extra=rail_files())
            files=rail_files(True)
            files['stop_times.txt']=files['stop_times.txt'].replace('RB,1','RA,1')
            files['trips.txt']=files['trips.txt'].replace(',1,1\n',',0,1\n')
            files['shapes.txt']=files['shapes.txt'].replace('45.423','45.424')
            write_feed(final,extra=files)
            data=audit_rail(str(rail),str(final),'','',ValidationReport('test'))
            trip=data['routes'][0]['variations'][0]['trips'][0]
            self.assertEqual('issues',trip['status'])
            self.assertIn('Ordered stop sequence differs.',trip['issues'])
            self.assertIn('Shape geometry differs.',trip['issues'])
            self.assertTrue(any('wheelchair_accessible' in item for item in trip['issues']))
            files=rail_files(True);files['stop_times.txt']=files['stop_times.txt'].replace('25:15:00','25:16:00')
            write_feed(final,extra=files)
            data=audit_rail(str(rail),str(final),'','',ValidationReport('test'))
            self.assertIn('Stop times or boarding rules differ.',data['routes'][0]['variations'][0]['trips'][0]['issues'])

    def test_missing_trips_and_routes_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            rail,final=Path(directory)/'rail.zip',Path(directory)/'final.zip'
            write_feed(rail,extra=rail_files());write_feed(final) # final only contains bus route 19
            report=ValidationReport('test');data=audit_rail(str(rail),str(final),'','',report)
            self.assertEqual('missing',data['routes'][0]['variations'][0]['status'])
            self.assertEqual(1,data['routes'][0]['counts']['missing'])
            self.assertTrue(any(item.rule_id=='RAIL004' for item in report.findings))

    def test_nonoverlapping_calendar_does_not_create_false_missing_or_extra_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            rail,final=Path(directory)/'rail.zip',Path(directory)/'final.zip'
            files=rail_files();files['calendar.txt']=files['calendar.txt'].replace('20261001,20261031','20261101,20261130')
            write_feed(rail,extra=files);write_feed(final,extra=rail_files(True))
            report=ValidationReport('test');data=audit_rail(str(rail),str(final),'','',report)
            self.assertEqual('outside_final_window',data['routes'][0]['status'])
            self.assertEqual([],data['routes'][0]['extra_final_trips'])
            self.assertFalse(any(item.rule_id in {'RAIL002','RAIL003','RAIL004'} for item in report.findings))

    def test_missing_service_dates_are_reported_even_when_trip_ids_match(self):
        with tempfile.TemporaryDirectory() as directory:
            rail,final=Path(directory)/'rail.zip',Path(directory)/'final.zip'
            write_feed(rail,extra=rail_files());files=rail_files(True)
            files['calendar.txt']=files['calendar.txt'].replace('1,1,1,1,1,0,0','1,1,1,1,0,0,0')
            write_feed(final,extra=files)
            data=audit_rail(str(rail),str(final),'','',ValidationReport('test'))
            trip=data['routes'][0]['variations'][0]['trips'][0]
            self.assertTrue(trip['missing_dates'])
            self.assertIn('Operating dates missing from final GTFS.',trip['issues'])

    def test_renamed_final_trip_and_shape_can_be_traced_by_exact_timetable(self):
        with tempfile.TemporaryDirectory() as directory:
            rail,final=Path(directory)/'rail.zip',Path(directory)/'final.zip'
            write_feed(rail,extra=rail_files());files=rail_files(True)
            for name in ('trips.txt','stop_times.txt'):files[name]=files[name].replace('train','renamed')
            for name in ('trips.txt','shapes.txt'):files[name]=files[name].replace('shape19','renamed-shape')
            write_feed(final,extra=files)
            data=audit_rail(str(rail),str(final),'','',ValidationReport('test'))
            trip=data['routes'][0]['variations'][0]['trips'][0]
            self.assertEqual('matching',trip['status'])
            self.assertEqual('exact stop schedule and operating dates',trip['matching_method'])

    def test_rail_accidentally_in_bus_source_is_flagged_and_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            rail,cad,bus,final=[Path(directory)/name for name in ('rail.zip','cad.zip','bus.zip','final.zip')]
            write_feed(rail,extra=rail_files());write_feed(cad,extra=rail_files());write_feed(bus);write_feed(final,extra=rail_files(True))
            report=validate_exports(cad,bus,final,rail)
            self.assertTrue(any(item.rule_id=='RAIL020' for item in report.findings))
            self.assertFalse(any(item.context.get('route_short_name')=='1' for item in report.findings if item.rule_id in {'TRP102','TRP103'}))
            self.assertFalse(any(item.rule_id in {'MRG101','MRG102','MRG103','MRG104'} for item in report.findings))

    def test_rail_input_is_part_of_saved_audit_identity(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GTFS_VALIDATOR_CACHE_DIR':directory}):
            rail=Path(directory)/'rail.zip';write_feed(rail,extra=rail_files())
            job=Job('rail','','',rail_path=str(rail),save_indexes=True)
            first=identity(job);_run_job(job)
            self.assertEqual('complete',job.status)
            files=rail_files();files['stops.txt']=files['stops.txt'].replace('ST-LAURENT D','CHANGED')
            write_feed(rail,extra=files)
            self.assertNotEqual(first,identity(job))
