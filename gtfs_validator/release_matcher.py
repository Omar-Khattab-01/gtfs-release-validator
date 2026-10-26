"""Source-only, calendar-aware CAD/HASTUS matching for candidate production."""
from array import array
from collections import Counter, defaultdict
import csv
import difflib
import io
import zipfile

from .rail import _services


def seconds(value):
    if not value:return -1
    parts=value.split(':')
    if len(parts)!=3:raise ValueError('Invalid GTFS time: '+value)
    h,m,s=map(int,parts)
    if h<0 or not 0<=m<60 or not 0<=s<60:raise ValueError('Invalid GTFS time: '+value)
    return h*3600+m*60+s


def read_table(archive,name):
    with archive.open(name) as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig',newline='')):
            if None in row:raise ValueError('Extra CSV fields in '+name)
            yield {key.strip():(value or '').strip() for key,value in row.items()}


class Source:
    def __init__(self,path,label):
        self.path=path;self.label=label
        with zipfile.ZipFile(path) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)):raise ValueError(label+': duplicate ZIP member names')
            if any('/' in n or '\\' in n or n.startswith('.') for n in names):raise ValueError(label+': GTFS must have root-level members')
            if sum(i.file_size for i in archive.infolist())>4*1024**3:raise ValueError(label+': uncompressed input exceeds 4 GB')
            if archive.testzip():raise ValueError(label+': ZIP integrity failure')
            self.tables={name:list(read_table(archive,name)) for name in names if name in {
                'trips.txt','stops.txt','routes.txt','calendar.txt','calendar_dates.txt','agency.txt','feed_info.txt'}}
            self.headers={}
            for name in names:
                if not name.endswith('.txt') or name=='error_warning.txt':continue
                with archive.open(name) as raw:
                    fields=next(csv.reader(io.TextIOWrapper(raw,encoding='utf-8-sig',newline='')),[])
                fields=[f.strip() for f in fields]
                if not fields or any(not f for f in fields) or len(fields)!=len(set(fields)):
                    raise ValueError(label+': blank or duplicate CSV column in '+name)
                self.headers[name]=fields
            self.names=names
        for name in ('trips.txt','stops.txt','routes.txt'):
            if name not in self.tables:raise ValueError(label+': missing '+name)
        self.trips=self._unique('trips.txt','trip_id');self.stops=self._unique('stops.txt','stop_id');self.routes=self._unique('routes.txt','route_id')
        self.columns=self.tables
        self.dates,_=_services(self,None)

    def _unique(self,name,key):
        result={}
        for row in self.tables[name]:
            ident=row.get(key,'')
            if not ident or ident in result:raise ValueError(self.label+': blank or duplicate '+key)
            result[ident]=row
        return result

    def rows(self,name):return self.tables.get(name,[])

    def load_models(self,stop_map,trip_ids=None):
        self.models={tid:{'id':tid,'record':record,'route':self.routes[record['route_id']]['route_short_name'],
                          'dates':set(self.dates.get(record['service_id'],set())),'rows':array('i')}
                     for tid,record in self.trips.items() if trip_ids is None or tid in trip_ids}
        keys={};self.stop_keys=[]
        def key(sid):
            canonical=stop_map.get(sid,'unmapped:'+self.label+':'+sid)
            # Interning the canonical string keeps repeated calls inexpensive.
            if canonical not in keys:keys[canonical]=len(keys);self.stop_keys.append(canonical)
            return keys[canonical]
        local={sid:key(sid) for sid in self.stops}
        self.headsigns=[];heads={}
        with zipfile.ZipFile(self.path) as archive:
            for row in read_table(archive,'stop_times.txt'):
                model=self.models.get(row.get('trip_id'))
                if model is None:continue
                if row['stop_id'] not in local:raise ValueError(self.label+': unknown stop '+row['stop_id'])
                text=row.get('stop_headsign','')
                if text not in heads:heads[text]=len(heads);self.headsigns.append(text)
                sequence=int(row['stop_sequence'])
                if sequence>model.get('_last_sequence',-1):
                    model['_last_sequence']=sequence;model['_end_arrival']=row.get('arrival_time','')
                model['rows'].extend((sequence,local[row['stop_id']],seconds(row.get('departure_time','')),
                                      int(row.get('timepoint') or '0'),int(row.get('pickup_type') or '0'),
                                      int(row.get('drop_off_type') or '0'),heads[text]))
        for model in self.models.values():
            data=model['rows']
            if any(data[i]<=data[i-7] for i in range(7,len(data),7)):
                ordered=sorted((data[i:i+7] for i in range(0,len(data),7)),key=lambda row:row[0])
                if len({r[0] for r in ordered})!=len(ordered):raise ValueError(self.label+': duplicate stop_sequence')
                model['rows']=data=array('i',(v for row in ordered for v in row))
                model['position_by_sequence']={data[i]:i//7 for i in range(0,len(data),7)}
            model['seq']=tuple(self.stop_keys[data[i+1]] for i in range(0,len(data),7))
            model['start']=data[2] if data else -1;model['end']=seconds(model.pop('_end_arrival',''))
            model['anchors']={(self.stop_keys[data[i+1]],data[i+2]) for i in range(0,len(data),7) if data[i+3] and data[i+2]>=0}


def align(source,target,tolerance):
    """Map occurrences, not simply IDs; repeated loop calls remain distinct."""
    if source['seq']==target['seq']:return dict(enumerate(range(len(target['seq']))))
    a=source['seq'];b=target['seq'];ac=Counter(a);bc=Counter(b);mapping={}
    for block in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            i=block.a+offset;j=block.b+offset
            if ac[a[i]]==bc[b[j]]==1:mapping[j]=i
    # Only unique timed occurrences may identify repeated stops. Do not choose
    # the first visit to a stop when the last visit is the relevant terminal.
    for j,sid in enumerate(b):
        if j in mapping:continue
        t=target['rows'][j*7+2]
        choices=[i for i,s in enumerate(a) if s==sid and t>=0 and abs(source['rows'][i*7+2]-t)<=tolerance]
        if len(choices)==1 and sum(s==sid and abs(target['rows'][k*7+2]-source['rows'][choices[0]*7+2])<=tolerance for k,s in enumerate(b))==1:
            mapping[j]=choices[0]
    return mapping


def match_sources(cad,hastus,tolerance=60,minimum_coverage=.8,progress=None):
    byseq=defaultdict(list);bytime=defaultdict(list);anchors=defaultdict(set)
    for tid,m in hastus.models.items():
        byseq[(m['route'],m['seq'])].append(tid)
        bytime[(m['route'],m['start'])].append(tid)
        for stop,t in m['anchors']:anchors[(m['route'],stop,t)].add(tid)
    matches={};learn=defaultdict(lambda:defaultdict(set))
    for tid,target in cad.models.items():
        exact=[hid for hid in byseq[(target['route'],target['seq'])]
               if target['dates'] & hastus.models[hid]['dates'] and target['start']==hastus.models[hid]['start']]
        matches[tid]={'candidate_ids':exact,'method':'exact_pattern_and_departure' if exact else 'unmatched'}
        if len(exact)==1:
            record=target['record'];candidate=hastus.models[exact[0]];cb=record.get('block_id','');hb=candidate['record'].get('block_id','')
            if cb and hb:
                for day in target['dates'] & candidate['dates']:learn[(cb,day)][hb].add(exact[0])
    known={k:next(iter(v)) for k,v in learn.items() if len(v)==1 and len(next(iter(v.values())))>=2}
    for number,(tid,target) in enumerate(cad.models.items()):
        result=matches[tid]
        if not result['candidate_ids']:
            endpoint=[]
            for hid in bytime[(target['route'],target['start'])]:
                candidate=hastus.models[hid]
                if candidate['end']!=target['end'] or not target['dates'] & candidate['dates']:continue
                shared=sum(b.size for b in difflib.SequenceMatcher(a=target['seq'],b=candidate['seq'],autojunk=False).get_matching_blocks())
                if shared/max(1,len(target['seq']),len(candidate['seq']))>=.90:endpoint.append(hid)
            if endpoint:result.update(candidate_ids=endpoint,method='endpoint_times_and_similar_pattern')
        if not result['candidate_ids']:
            hits=Counter()
            for stop,t in target['anchors']:
                hits.update(set(hid for delta in range(-tolerance,tolerance+1) for hid in anchors.get((target['route'],stop,t+delta),())))
            ranked=[]
            for hid,count in hits.items():
                candidate=hastus.models[hid]
                if count<2 or not target['dates'] & candidate['dates']:continue
                shared=sum(b.size for b in difflib.SequenceMatcher(a=target['seq'],b=candidate['seq'],autojunk=False).get_matching_blocks())
                coverage=shared/max(1,len(target['seq']),len(candidate['seq']))
                if coverage>=minimum_coverage:ranked.append((hid,coverage,count))
            strong=[r for r in ranked if r[1]>=.90]
            selected=strong or ranked
            result.update(candidate_ids=[r[0] for r in selected],method='timing_anchors' if strong else 'review_pattern' if ranked else 'unmatched')
        ids=result['candidate_ids'];perday={d:[h for h in ids if d in hastus.models[h]['dates']] for d in target['dates']}
        if ids and any(len(v)>1 for v in perday.values()):
            filtered={d:[h for h in values if hastus.models[h]['record'].get('block_id')==known[(target['record'].get('block_id',''),d)]]
                      if (target['record'].get('block_id',''),d) in known else values for d,values in perday.items()}
            if filtered and all(len(v)==1 for v in filtered.values()):
                result['candidates_before_block']=ids;ids=sorted({h for v in filtered.values() for h in v});result['candidate_ids']=ids;result['block_resolved']=True
                perday=filtered
        result['uncovered_dates']=sorted(d for d,v in perday.items() if not v)
        result['ambiguous_dates']=sorted(d for d,v in perday.items() if len(v)>1)
        result['alignments']={hid:align(hastus.models[hid],target,tolerance) for hid in ids}
        if progress and number%10000==0:progress(f'Matched {number:,} / {len(cad.models):,} CAD trip records')
    return matches
