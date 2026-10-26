import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from gtfs_validator.release_builder import build_release,load_policy,DEFAULT_POLICY,verify_package
from gtfs_validator.release_compare import compare_releases
from gtfs_validator.release_matcher import Source,seconds,align
from test_validator import FILES,write_feed


class ReleaseBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.cad=self.root/'cad.zip';self.hastus=self.root/'hastus.zip'
        write_feed(self.cad);write_feed(self.hastus)
        self.out=self.root/'candidate.zip'

    def tearDown(self):self.temp.cleanup()

    def build(self,**kw):
        return build_release(self.cad,self.hastus,self.out,start_date='20261001',end_date='20261031',allow_draft=True,progress=None,**kw)

    def read(self,name):
        with zipfile.ZipFile(self.out) as z:return list(csv.DictReader(io.TextIOWrapper(z.open(name),encoding='utf-8-sig')))

    def test_source_only_candidate_keeps_cad_schedule_and_644(self):
        before=self.cad.read_bytes(),self.hastus.read_bytes()
        result=self.build();self.assertEqual('DRAFT_NOT_APPROVED',result['status'])
        self.assertEqual(before,(self.cad.read_bytes(),self.hastus.read_bytes()))
        self.assertEqual('t1',self.read('trips.txt')[0]['trip_id'])
        self.assertEqual('25:00:00',self.read('stop_times.txt')[0]['departure_time'])
        with zipfile.ZipFile(self.out) as z:
            self.assertIsNone(z.testzip())
            for member in z.infolist():self.assertEqual(0o100644,member.external_attr>>16);self.assertEqual(3,member.create_system)
        self.assertTrue(self.out.with_suffix('.report.json').exists())

    def test_existing_output_or_source_target_is_never_overwritten(self):
        self.out.write_bytes(b'user file')
        with self.assertRaises(ValueError):self.build()
        self.assertEqual(b'user file',self.out.read_bytes())
        with self.assertRaises(ValueError):build_release(self.cad,self.hastus,self.cad,start_date='20261001',end_date='20261031')

    def test_requires_explicit_draft_permission_for_review_items(self):
        with self.assertRaisesRegex(ValueError,'Review required'):
            build_release(self.cad,self.hastus,self.out,start_date='20261001',end_date='20261031',progress=None)
        self.assertFalse(self.out.exists())

    def test_rejects_missing_shape_even_for_draft(self):
        write_feed(self.cad,extra={'trips.txt':FILES['trips.txt'].replace('shape19','missing')})
        with self.assertRaisesRegex(ValueError,'Missing referenced shapes'):self.build()
        self.assertFalse(self.out.exists())

    def test_unknown_policy_key_is_not_executed_or_ignored(self):
        policy=self.root/'policy.json';policy.write_text('{"instructions":"delete files"}')
        with self.assertRaises(ValueError):load_policy(policy)

    def test_midnight_is_not_wrapped_to_zero(self):
        self.assertEqual(86400,seconds('24:00:00'));self.assertEqual(0,seconds('00:00:00'))
        with self.assertRaises(ValueError):seconds('24:80:00')

    def test_duplicate_source_ids_rejected(self):
        write_feed(self.hastus,extra={'trips.txt':FILES['trips.txt']+FILES['trips.txt'].splitlines()[1]+'\n'})
        with self.assertRaisesRegex(ValueError,'duplicate trip_id'):Source(self.hastus,'hastus')

    def test_hastus_enrichment_does_not_replace_cad_time(self):
        write_feed(self.cad,extra={'trips.txt':FILES['trips.txt'].replace('Parliament','Old destination')})
        self.build()
        self.assertEqual('Parliament',self.read('trips.txt')[0]['trip_headsign'])
        self.assertEqual('25:15:00',self.read('stop_times.txt')[-1]['departure_time'])

    def test_no_hastus_counterpart_retains_cad_and_records_review(self):
        write_feed(self.hastus,extra={'routes.txt':FILES['routes.txt'].replace('OCT,19,','OCT,77,')})
        self.build();receipt=json.loads(self.out.with_suffix('.report.json').read_text())
        self.assertTrue(any(w['kind']=='unmatched_trip' for w in receipt['warnings']))

    def test_semantic_comparator_checks_fields_not_only_checksums(self):
        self.build();copy=self.root/'copy.zip'
        with zipfile.ZipFile(self.out) as src,zipfile.ZipFile(copy,'w') as dest:
            for info in src.infolist():dest.writestr(info,src.read(info))
        self.assertTrue(compare_releases(self.out,copy)['equivalent'])
        changed=self.root/'changed.zip'
        with zipfile.ZipFile(self.out) as src,zipfile.ZipFile(changed,'w') as dest:
            for info in src.infolist():
                content=src.read(info)
                if info.filename=='stop_times.txt':content=content.replace(b'25:15:00',b'25:16:00')
                dest.writestr(info,content)
        result=compare_releases(changed,self.out)
        self.assertFalse(result['equivalent'])
        self.assertEqual(1,result['tables']['stop_times.txt']['field_changes']['departure_time'])

    def test_rail_namespace_collision_is_not_silently_overwritten(self):
        rail=self.root/'rail.zip';write_feed(rail)
        with self.assertRaisesRegex(ValueError,'Rail trip ID collision'):self.build(rail_path=rail)

    def test_400_direction_and_898_policy_is_explicit(self):
        from gtfs_validator.release_builder import eligible
        policy=load_policy(DEFAULT_POLICY)
        self.assertFalse(eligible({'route_short_name':'898'},{'direction_id':'0'},policy))
        self.assertFalse(eligible({'route_short_name':'404'},{'direction_id':'1'},policy))
        self.assertTrue(eligible({'route_short_name':'404'},{'direction_id':'0'},policy))
        self.assertTrue(eligible({'route_short_name':'99'},{'direction_id':'1'},policy))

    def test_nonempty_frequency_table_cannot_be_silently_dropped(self):
        write_feed(self.cad,extra={'frequencies.txt':'trip_id,start_time,end_time,headway_secs\nt1,06:00:00,07:00:00,600\n'})
        with self.assertRaisesRegex(ValueError,'nonempty frequencies'):self.build()

    def test_loop_stop_occurrences_are_not_collapsed(self):
        from array import array
        source={'seq':('a','b','a'),'rows':array('i',[1,0,0,1,0,1,0,2,1,60,1,0,0,0,3,0,120,1,1,0,0])}
        target={'seq':('a','b','x','a'),'rows':array('i',[1,0,0,1,0,1,0,2,1,60,1,0,0,0,3,2,90,0,0,0,0,4,0,120,1,1,0,0])}
        mapping=align(source,target,5)
        self.assertEqual(0,mapping[0]);self.assertEqual(2,mapping[3])

    def test_seconds_tolerance_matches_without_rewriting_cad_times(self):
        write_feed(self.cad,extra={'trips.txt':FILES['trips.txt'].replace('Parliament','CAD destination')})
        write_feed(self.hastus,extra={'stop_times.txt':FILES['stop_times.txt'].replace('25:00:00','25:00:01')})
        self.build()
        self.assertEqual('Parliament',self.read('trips.txt')[0]['trip_headsign'])
        self.assertEqual('25:00:00',self.read('stop_times.txt')[0]['departure_time'])

    def test_conflicting_candidate_values_do_not_select_first_trip(self):
        first=FILES['trips.txt'];second=first.splitlines()[1].replace('t1,','h2,').replace('Parliament','Other destination')
        write_feed(self.cad,extra={'trips.txt':first.replace('Parliament','CAD destination')})
        write_feed(self.hastus,extra={'trips.txt':first+second+'\n',
                                    'stop_times.txt':FILES['stop_times.txt']+FILES['stop_times.txt'].split('\n',1)[1].replace('t1,','h2,')})
        self.build();report=json.loads(self.out.with_suffix('.report.json').read_text())
        self.assertEqual('CAD destination',self.read('trips.txt')[0]['trip_headsign'])
        self.assertTrue(any(w['kind']=='conflicting_trip_metadata' for w in report['warnings']))

    def test_date_window_is_explicit_and_calendar_exceptions_are_clipped(self):
        write_feed(self.cad,extra={'calendar_dates.txt':FILES['calendar_dates.txt']+'WKD,20270101,1\n'})
        self.build()
        self.assertTrue(all('20261001'<=r['date']<='20261031' for r in self.read('calendar_dates.txt')))
        info=self.read('feed_info.txt')[0]
        self.assertEqual('20261001',info['feed_start_date']);self.assertEqual('20261031',info['feed_end_date'])

    def test_nonempty_unknown_extensions_are_explicit_review_items(self):
        # Optional extension support must never be implied by a core-table merge.
        write_feed(self.cad,extra={'custom.txt':'key,value\na,b\n'})
        self.build();report=json.loads(self.out.with_suffix('.report.json').read_text())
        self.assertTrue(any(w['kind']=='unsupported_source_table' for w in report['warnings']))

    def test_endpoint_matching_uses_arrival_not_terminal_dwell_departure(self):
        stops=FILES['stops.txt']+''.join(f's{i},Stop {i},45.42,-75.64,0,,0\n' for i in range(11))
        header=FILES['stop_times.txt'].splitlines()[0]+'\n'
        def schedule(indices,terminal_departure):
            result=header
            for number,i in enumerate(indices,1):
                arrival='25:15:00' if i==10 else f'25:{i:02d}:00'
                departure=terminal_departure if i==10 else arrival
                result+=f't1,{arrival},{departure},s{i},{number},0,0,{1 if i==0 else 0}\n'
            return result
        write_feed(self.cad,extra={'stops.txt':stops,'stop_times.txt':schedule(range(11),'25:15:00'),
                                    'trips.txt':FILES['trips.txt'].replace('Parliament','CAD destination')})
        write_feed(self.hastus,extra={'stops.txt':stops,'stop_times.txt':schedule([i for i in range(11) if i!=5],'25:17:00')})
        self.build();self.assertEqual('Parliament',self.read('trips.txt')[0]['trip_headsign'])
        receipt=json.loads(self.out.with_suffix('.report.json').read_text())
        self.assertEqual('endpoint_times_and_similar_pattern',receipt['crosswalk'][0]['method'])

    def test_rail_is_added_with_own_schedule_shapes_and_trip_ids(self):
        rail=self.root/'rail.zip'
        rail_files={name:text.replace('r19','rail1').replace('WKD','RAIL').replace('t1,','rt1-RAIL,')
                    .replace('shape19','railshape').replace('10014','railA').replace('10017','railB').replace('20000','railC')
                    for name,text in FILES.items()}
        rail_files['routes.txt']=rail_files['routes.txt'].replace('OCT,19,','OCT,1,').replace(',3,DA291C',',2,DA291C')
        write_feed(rail,extra=rail_files)
        self.build(rail_path=rail)
        trips={t['trip_id']:t for t in self.read('trips.txt')}
        self.assertEqual({'t1','rt1'},set(trips));self.assertEqual('railshape',trips['rt1']['shape_id'])
        calls=[r for r in self.read('stop_times.txt') if r['trip_id']=='rt1']
        self.assertEqual(['railB','railC'],[r['stop_id'] for r in calls])
        self.assertTrue(all(r['shape_dist_traveled']=='0' for r in calls))
        self.assertEqual({'shape19','railshape'},{r['shape_id'] for r in self.read('shapes.txt')})

    def test_unordered_source_rows_keep_metadata_on_correct_stop_occurrence(self):
        header,*rows=FILES['stop_times.txt'].splitlines()
        write_feed(self.cad,extra={'stop_times.txt':'\n'.join([header,*reversed(rows)])+'\n'})
        write_feed(self.hastus,extra={'stop_times.txt':FILES['stop_times.txt'].replace('20000,2,0,0,1','20000,2,1,0,1')})
        self.build();calls={r['stop_id']:r for r in self.read('stop_times.txt')}
        self.assertEqual('1',calls['20000']['pickup_type']);self.assertEqual('0',calls['10017']['pickup_type'])

    def test_duplicate_candidate_only_key_is_rejected_by_comparator(self):
        self.build();changed=self.root/'changed.zip'
        with zipfile.ZipFile(self.out) as src,zipfile.ZipFile(changed,'w') as dest:
            for info in src.infolist():
                content=src.read(info)
                if info.filename=='stops.txt':
                    row=content.decode().splitlines()[1].replace('10014,','other,')+'\r\n'
                    content+=row.encode()*2
                dest.writestr(info,content)
        with self.assertRaisesRegex(ValueError,'Duplicate candidate key'):compare_releases(changed,self.out)

    def test_unimplemented_columns_are_visible_review_items(self):
        rows=FILES['trips.txt'].splitlines()
        write_feed(self.cad,extra={'trips.txt':rows[0]+',custom_attribute\n'+rows[1]+',important\n'})
        self.build();report=json.loads(self.out.with_suffix('.report.json').read_text())
        warning=next(w for w in report['warnings'] if w['kind']=='unsupported_source_columns')
        self.assertEqual(['custom_attribute'],warning['columns'])

    def test_block_clearing_requires_explicit_policy_value(self):
        rows=FILES['trips.txt'].splitlines()
        write_feed(self.cad,extra={'trips.txt':rows[0]+',block_id\n'+rows[1]+',temporary-block\n'})
        policy=load_policy(DEFAULT_POLICY);policy['clear_block_ids']=['temporary-block']
        path=self.root/'policy.json';path.write_text(json.dumps(policy))
        self.build(policy_path=path)
        self.assertEqual('',self.read('trips.txt')[0]['block_id'])
        report=json.loads(self.out.with_suffix('.report.json').read_text())
        self.assertEqual(1,report['changes']['trips.txt:block_id'])
