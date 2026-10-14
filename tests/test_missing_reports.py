import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from gtfs_validator.feed_index import clear_indexes
from gtfs_validator.merge import validate_exports
from gtfs_validator.missing_reports import missing_report, variation_evidence, export_excel, printable_report, _xlsx
from test_validator import FILES, write_feed


class MissingReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();directory=Path(self.temp.name)
        self.cad=directory/'cad.zip';self.hastus=directory/'hastus.zip'
        trips=FILES['trips.txt']+FILES['trips.txt'].splitlines()[1].replace(',t1,',',t2,')+'\n'
        times=FILES['stop_times.txt']+'\n'.join(line.replace('t1,','t2,').replace('25:','26:') for line in FILES['stop_times.txt'].splitlines()[1:])+'\n'
        write_feed(self.cad,extra={'trips.txt':trips,'stop_times.txt':times})
        write_feed(self.hastus,extra={'routes.txt':FILES['routes.txt'].replace('r19,OCT,19,','r20,OCT,20,'),'trips.txt':FILES['trips.txt'].replace('r19,','r20,')})
        self.paths={'cad':str(self.cad),'hastus':str(self.hastus)}
        self.report=validate_exports(self.cad,self.hastus).to_dict()

    def tearDown(self):
        clear_indexes();self.temp.cleanup()

    def test_source_direction_and_search(self):
        first=missing_report(self.report,'hastus');second=missing_report(self.report,'cad')
        self.assertEqual(['19'],[route['route_short_name'] for route in first['routes']])
        self.assertEqual(['20'],[route['route_short_name'] for route in second['routes']])
        self.assertEqual(2,first['trip_count']);self.assertEqual(1,first['variation_count'])
        self.assertEqual(0,missing_report(self.report,'hastus','20')['route_count'])
        self.assertEqual(1,missing_report(self.report,'hastus','shape19')['route_count'])
        with self.assertRaises(ValueError):missing_report(self.report,'final')

    def test_full_variation_trips_and_membership(self):
        variation=missing_report(self.report,'hastus')['routes'][0]['variations'][0]['variation']
        evidence=variation_evidence(self.report,self.paths,'hastus','19',variation['variation_id'],'t2')
        self.assertEqual({'t1','t2'},{row['trip_id'] for row in evidence['trips']})
        self.assertEqual('t2',evidence['detail']['trip']['trip_id'])
        self.assertEqual(2,len(evidence['stop_times']));self.assertEqual(2,len(evidence['detail']['stops']))
        self.assertEqual(2,len(evidence['detail']['shape']))
        self.assertEqual('19',evidence['route']['route_short_name'])
        self.assertIn('calendar.txt',evidence['services'])
        with self.assertRaises(ValueError):variation_evidence(self.report,self.paths,'hastus','19',variation['variation_id'],'wrong-trip')
        with self.assertRaises(ValueError):variation_evidence(self.report,self.paths,'cad','19',variation['variation_id'])

    def test_xlsx_complete_source_rows_and_valid_package(self):
        payload=export_excel(self.report,self.paths,'hastus')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():ET.fromstring(archive.read(name))
            workbook=archive.read('xl/workbook.xml').decode()
            for name in ['Report','Variations','Trips','Stop times','Stops','Shapes','Services']:self.assertIn(name,workbook)
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            trips=ET.fromstring(archive.read('xl/worksheets/sheet4.xml'))
            times=ET.fromstring(archive.read('xl/worksheets/sheet5.xml'))
            self.assertEqual(3,len(trips.findall('s:sheetData/s:row',ns)))
            self.assertEqual(5,len(times.findall('s:sheetData/s:row',ns)))
            self.assertIn('t2',archive.read('xl/worksheets/sheet4.xml').decode())
            self.assertIn('26:15:00',archive.read('xl/worksheets/sheet5.xml').decode())
            self.assertIn('ST-LAURENT D',archive.read('xl/worksheets/sheet6.xml').decode())

    def test_excel_injection_control_characters_and_leading_zero_ids(self):
        with zipfile.ZipFile(io.BytesIO(_xlsx([('Test',[['ID','Name'],['001','=<script>\x00']])]))) as archive:
            xml=archive.read('xl/worksheets/sheet1.xml').decode()
            ET.fromstring(xml)
            self.assertIn('>001<',xml);self.assertIn('=&lt;script&gt;',xml)
            self.assertNotIn('<f>',xml)

    def test_filtered_empty_exports_and_pdf_print_view(self):
        with zipfile.ZipFile(io.BytesIO(export_excel(self.report,self.paths,'hastus','not found'))) as archive:
            self.assertIsNone(archive.testzip())
        html=printable_report(self.report,self.paths,'hastus').decode()
        self.assertIn('Route 19',html);self.assertNotIn('Route 20',html)
        self.assertIn('ST-LAURENT D',html);self.assertIn('Representative stop sequence',html)
        self.assertIn('Microsoft Print to PDF',html)
        self.assertIn('not proof',html)
        escaped=printable_report(self.report,self.paths,'hastus','<script>alert(1)</script>').decode()
        self.assertNotIn('<script>alert(1)</script>',escaped)
        self.assertIn('&lt;script&gt;',escaped)
