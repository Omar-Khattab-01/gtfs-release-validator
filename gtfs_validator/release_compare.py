"""Independent keyed, field-level comparison; never used to build a feed."""
from collections import Counter
from contextlib import closing
from decimal import Decimal,InvalidOperation
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile
from .release_matcher import read_table

KEYS={'agency.txt':['agency_id'],'routes.txt':['route_id'],'stops.txt':['stop_id'],'trips.txt':['trip_id'],
      'stop_times.txt':['trip_id','stop_sequence'],'shapes.txt':['shape_id','shape_pt_sequence'],
      'calendar.txt':['service_id'],'calendar_dates.txt':['service_id','date','exception_type'],'feed_info.txt':[]}
NUMERIC={'stop_lat','stop_lon','shape_pt_lat','shape_pt_lon','shape_dist_traveled','shape_pt_sequence','stop_sequence'}


def canonical(row):
    clean={}
    for key,value in row.items():
        if key in NUMERIC and value:
            try:value=format(Decimal(value).normalize(),'f')
            except InvalidOperation:pass
        clean[key]=value
    return clean


def compare_releases(candidate,reference):
    """Stream to private SQLite storage rather than retaining millions of dicts."""
    report={'candidate':str(candidate),'reference':str(reference),'tables':{},'equivalent':True,
            'comparison':'Keyed GTFS records; surrounding whitespace and numeric formatting normalized. ZIP byte order is not compared.'}
    with zipfile.ZipFile(candidate) as output,zipfile.ZipFile(reference) as baseline:
        for archive in (output,baseline):
            names=archive.namelist()
            if len(names)!=len(set(names)):raise ValueError('Duplicate archive member names')
            if sum(i.file_size for i in archive.infolist())>4*1024**3:raise ValueError('Comparison archive exceeds 4 GB uncompressed')
            if archive.testzip():raise ValueError('Comparison ZIP integrity failure')
        cn=set(output.namelist());rn=set(baseline.namelist())
        report['member_names_equal']=cn==rn
        report['candidate_only_members']=sorted(cn-rn);report['reference_only_members']=sorted(rn-cn)
        if cn!=rn:report['equivalent']=False
        with tempfile.TemporaryDirectory(prefix='gtfs-reference-compare-') as folder,closing(sqlite3.connect(str(Path(folder)/'compare.sqlite'))) as db:
            db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA synchronous=OFF')
            db.execute('CREATE TABLE expected (key TEXT PRIMARY KEY,data TEXT,seen INTEGER DEFAULT 0) WITHOUT ROWID')
            for name in sorted(cn & rn):
                if name not in KEYS:
                    same=output.read(name)==baseline.read(name);report['tables'][name]={'byte_equal':same}
                    report['equivalent'] &= same;continue
                db.execute('DELETE FROM expected');db.commit();stats=Counter();changes=Counter();examples=[]
                for number,row in enumerate(read_table(baseline,name)):
                    key=json.dumps([row.get(k,'') for k in KEYS[name]] if KEYS[name] else [number],separators=(',',':'))
                    try:db.execute('INSERT INTO expected(key,data) VALUES (?,?)',(key,json.dumps(canonical(row),sort_keys=True,separators=(',',':'))))
                    except sqlite3.IntegrityError:raise ValueError('Duplicate reference key in '+name+': '+key)
                    stats['reference_rows']+=1
                db.commit()
                for number,row in enumerate(read_table(output,name)):
                    key=json.dumps([row.get(k,'') for k in KEYS[name]] if KEYS[name] else [number],separators=(',',':'));stats['candidate_rows']+=1
                    found=db.execute('SELECT data,seen FROM expected WHERE key=?',(key,)).fetchone()
                    if found is None:
                        db.execute('INSERT INTO expected(key,data,seen) VALUES (?,NULL,1)',(key,))
                        stats['candidate_only_rows']+=1
                        if len(examples)<12:examples.append({'key':key,'kind':'candidate_only','candidate':row})
                        continue
                    if found[1]:raise ValueError('Duplicate candidate key in '+name+': '+key)
                    db.execute('UPDATE expected SET seen=1 WHERE key=?',(key,))
                    first=json.loads(found[0]);second=canonical(row);different={k:{'reference':first.get(k),'candidate':second.get(k)} for k in set(first)|set(second) if first.get(k)!=second.get(k)}
                    if different:
                        stats['changed_rows']+=1;changes.update(different.keys())
                        if len(examples)<12:examples.append({'key':key,'kind':'changed','fields':different})
                    else:stats['equal_rows']+=1
                stats['reference_only_rows']=db.execute('SELECT COUNT(*) FROM expected WHERE seen=0').fetchone()[0]
                for key,data in db.execute('SELECT key,data FROM expected WHERE seen=0 LIMIT 5'):
                    if len(examples)<16:examples.append({'key':key,'kind':'reference_only','reference':json.loads(data)})
                db.commit();report['tables'][name]={'counts':dict(stats),'field_changes':dict(changes),'examples':examples}
                if any(stats[k] for k in ('candidate_only_rows','reference_only_rows','changed_rows')):report['equivalent']=False
    return report
