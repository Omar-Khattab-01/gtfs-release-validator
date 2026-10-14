"""Read-only source-only pattern reports and dependency-free Excel exports."""
from html import escape
import io
import json
import itertools
import re
import stat
import zipfile
from xml.sax.saxutils import escape as xml_escape

from .feed_index import get_index
from .viewer import trip_detail

DISCLAIMER = 'No sufficiently similar counterpart was paired. This is a review finding, not proof that service is absent.'


def missing_report(report, missing, search=''):
    if missing not in {'cad','hastus'}:
        raise ValueError('Missing source must be cad or hastus')
    present = 'hastus' if missing == 'cad' else 'clevercad'
    absent = 'clevercad' if missing == 'cad' else 'hastus'
    routes = []
    for route in report.get('stats',{}).get('trip_reconciliation',{}).get('route_health',[]):
        catalog = {item['variation_id']:item for item in route.get(present+'_variations',[])}
        variations = []
        for pair in route.get('variation_pairs',[]):
            if pair.get('status')!='not_comparable' or pair.get(absent+'_variation_id') or not pair.get(present+'_variation_id'):
                continue
            item = catalog.get(pair[present+'_variation_id'])
            if item:
                entry = {'pair':pair,'variation':item}
                searchable=[route.get('route_short_name'),item.get('variation_id'),item.get('headsigns'),item.get('shape_ids'),item.get('direction_ids'),item.get('first_time'),item.get('last_time'),item.get('trip_ids'),pair.get('reason')]
                if search.casefold() in json.dumps(searchable,ensure_ascii=False).casefold():
                    variations.append(entry)
        if variations:
            routes.append({'route_short_name':route['route_short_name'],'status':route['status'],
                           'direction_alignment':route.get('direction_alignment'),'variations':variations,
                           'clevercad_variation_count':route.get('clevercad_variation_count',0),
                           'hastus_variation_count':route.get('hastus_variation_count',0)})
    routes.sort(key=lambda item: [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)',str(item['route_short_name']))])
    return {'missing':missing,'present':'hastus' if missing=='cad' else 'cad','title':'Missing in '+('CAD' if missing=='cad' else 'HASTUS'),
            'disclaimer':DISCLAIMER,'routes':routes,'route_count':len(routes),
            'variation_count':sum(len(route['variations']) for route in routes),
            'trip_count':sum(item['variation']['trip_count'] for route in routes for item in route['variations']),
            'search':search,'completed_at':report.get('completed_at'),'inputs':report.get('stats',{}).get('inputs',{})}


def variation_evidence(report, paths, missing, route_name, variation_id, trip_id=''):
    data = missing_report(report,missing)
    entry = next((entry for route in data['routes'] if str(route['route_short_name'])==route_name
                  for entry in route['variations'] if entry['variation']['variation_id']==variation_id),None)
    if entry is None:raise ValueError('Source-only variation not found in this report')
    variation=entry['variation'];ids=variation.get('trip_ids') or [variation['example_trip_id']]
    selected=trip_id or variation['example_trip_id']
    if selected not in ids:raise ValueError('Trip does not belong to this variation')
    path=paths[data['present']];index=get_index(path)
    detail=trip_detail(path,selected)
    route=[row for row in index.small_tables.get('routes.txt',[]) if row.get('route_id')==detail['trip'].get('route_id')]
    services={name:[row for row in index.rows(name) if row.get('service_id')==detail['trip'].get('service_id')]
              for name in ('calendar.txt','calendar_dates.txt') if name in index.columns}
    return {'summary':entry,'source':data['present'],'route':route[0] if route else {},'detail':detail,
            'trips':index.lookup_many('trips.txt',ids,entity=True),
            'stop_times':sorted(index.lookup('stop_times.txt',selected),key=lambda row:int(row.get('stop_sequence') or 0)),
            'services':services,'disclaimer':DISCLAIMER}


def _records_table(records):
    fields=list(dict.fromkeys(field for row in records for field in row))
    return [fields]+[[json.dumps(row.get(field,''),ensure_ascii=False) if isinstance(row.get(field), (dict,list)) else row.get(field,'') for field in fields] for row in records]


def export_excel(report, paths, missing, search=''):
    data=missing_report(report,missing,search);index=get_index(paths[data['present']]) if data['routes'] else None
    variants=[];trips=[];time_groups=[];route_rows=[];stop_ids=set();shape_ids=set();service_ids=set()
    for route in data['routes']:
        for entry in route['variations']:
            item=entry['variation'];prefix={'route_number':route['route_short_name'],'variation':item['variation_id']}
            variants.append({**prefix,'missing_source':data['title'],'reason':entry['pair'].get('reason',''),**{key:value for key,value in item.items() if key!='trip_ids'}})
            ids=item.get('trip_ids') or [item['example_trip_id']]
            rows=index.lookup_many('trips.txt',ids,entity=True)
            trips.extend({**prefix,**row} for row in rows)
            route_ids={row.get('route_id') for row in rows}
            route_rows.extend(row for row in index.small_tables.get('routes.txt',[]) if row.get('route_id') in route_ids)
            service_ids.update(row.get('service_id','') for row in rows)
            shape_ids.update(row.get('shape_id','') for row in rows)
            time_groups.append((prefix,ids))
            # All trips in this variation share the ordered stop pattern.
            stop_ids.update(row.get('stop_id','') for row in index.lookup('stop_times.txt',item['example_trip_id']))
    # Preserve platform and parent-station attributes, not just names.
    stop_ids |= {index.stops.get(stop,{}).get('parent_station','') for stop in list(stop_ids)} - {''}
    stops=[index.stops[stop] for stop in sorted(stop_ids) if stop in index.stops]
    def time_records():
        for prefix,ids in time_groups:
            for start in range(0,len(ids),200):
                for row in index.lookup_many('stop_times.txt',ids[start:start+200]):yield {**prefix,**row}
    def streamed_table(fields,records):
        return itertools.chain([fields],([row.get(field,'') for field in fields] for row in records))
    times=streamed_table(['route_number','variation',*(index.columns.get('stop_times.txt',[]) if index else [])],time_records())
    shapes=streamed_table(index.columns.get('shapes.txt',[]) if index else [],(row for shape in sorted(shape_ids-{''}) for row in index.lookup('shapes.txt',shape))) if index and 'shapes.txt' in index.columns else [[]]
    services=[{'source_file':name,**row} for name in ('calendar.txt','calendar_dates.txt') if index and name in index.columns
              for row in index.rows(name) if row.get('service_id') in service_ids]
    metadata=[['Report',data['title']],['Meaning',DISCLAIMER],['Audit completed',data['completed_at'] or ''],['Search filter',search],
              ['Affected routes',data['route_count']],['Unpaired variations',data['variation_count']],['Source trips',data['trip_count']]]
    metadata.extend([[label,json.dumps(value,ensure_ascii=False)] for label,value in data['inputs'].items()])
    sheets=[('Report',metadata),('Variations',_records_table(variants)),('Routes',_records_table(list({row.get('route_id'):row for row in route_rows}.values()))),
            ('Trips',_records_table(trips)),('Stop times',times),('Stops',_records_table(stops)),('Shapes',shapes),('Services',_records_table(services))]
    return _xlsx(sheets)


def _xlsx(sheets):
    """OOXML inline-string cells: feed values can never execute as formulas."""
    namespace='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def column(number):
        value=''
        while number:number,rem=divmod(number-1,26);value=chr(65+rem)+value
        return value
    def clean(value):
        # XML 1.0 excludes control characters; Excel cells allow at most 32,767 characters.
        value=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))
        if len(value)>32767:raise ValueError('A report cell exceeds Excel’s 32,767 character limit; narrow the report search')
        return xml_escape(value)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        def write(name,content):
            info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,content.encode('utf-8'))
        write('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))+'</Types>')
        write('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        write('xl/workbook.xml',f'<workbook xmlns="{namespace}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{escape(name,quote=True)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        write('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        write('xl/styles.xml',f'<styleSheet xmlns="{namespace}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf xfId="0"/><xf fontId="1" applyFont="1" xfId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i,(_,rows) in enumerate(sheets,1):
            iterator=iter(rows);header=next(iterator,[]);width=max(1,len(header))
            info=zipfile.ZipInfo(f'xl/worksheets/sheet{i}.xml');info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
            # Stream worksheet XML rather than retaining millions of XML cells in memory.
            with archive.open(info,'w') as stream:
                stream.write(f'<worksheet xmlns="{namespace}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="{width}" width="28" customWidth="1"/></cols><sheetData>'.encode())
                count=0
                for r,row in enumerate(itertools.chain([header],iterator),1):
                    if r>1048576:raise ValueError('Report exceeds Excel’s row limit; narrow the report search')
                    body=f'<row r="{r}">'+''.join(f'<c r="{column(c)}{r}" t="inlineStr" s="{1 if r==1 else 0}"><is><t xml:space="preserve">{clean(value)}</t></is></c>' for c,value in enumerate(row,1))+'</row>'
                    stream.write(body.encode('utf-8'));count=r
                stream.write(('</sheetData>'+ (f'<autoFilter ref="A1:{column(width)}{count}"/>' if i>1 and header else '')+'</worksheet>').encode())
    return output.getvalue()


def printable_report(report, paths, missing, search=''):
    data=missing_report(report,missing,search)
    sections=[]
    for route in data['routes']:
        variations=[]
        for entry in route['variations']:
            item=entry['variation'];detail=trip_detail(paths[data['present']],item['example_trip_id'])
            fields={key:value for key,value in item.items() if key not in {'trip_ids','pattern_fingerprint','has_problem','affected_journeys','comparable_journeys'}}
            summary=''.join(f'<dt>{escape(key.replace("_"," "))}</dt><dd>{escape(json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value))}</dd>' for key,value in fields.items())
            stops=''.join(f'<tr><td>{escape(str(stop.get("sequence","")))}</td><td>{escape(stop.get("source_stop_id",""))}</td><td>{escape(stop.get("stop_name",""))}</td><td>{escape(stop.get("arrival_time", ""))}</td><td>{escape(stop.get("departure_time", ""))}</td></tr>' for stop in detail['stops'])
            trip_fields=''.join(f'<dt>{escape(key)}</dt><dd>{escape(str(value))}</dd>' for key,value in detail['trip'].items())
            variations.append(f'<article><h3>{escape(item["variation_id"])}</h3><p>{escape(entry["pair"].get("reason",""))}</p><dl>{summary}</dl><h4>Representative trip — complete attributes</h4><dl>{trip_fields}</dl><h4>Representative stop sequence</h4><table><thead><tr><th>Sequence</th><th>Stop ID</th><th>Stop name</th><th>Arrival</th><th>Departure</th></tr></thead><tbody>{stops}</tbody></table></article>')
        sections.append(f'<section><h2>Route {escape(str(route["route_short_name"]))}</h2>'+''.join(variations)+'</section>')
    sources=''.join(f'<li>{escape(label)}: {escape(json.dumps(value,ensure_ascii=False))}</li>' for label,value in data['inputs'].items())
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{escape(data['title'])} — GTFS review report</title>
<style>body{{font:11pt Arial,sans-serif;color:#183446;margin:24px}}h1{{font-size:24pt}}h2{{border-bottom:2px solid #183446;padding-top:16px}}article{{border:1px solid #ccd7df;padding:16px;margin:16px 0}}dl{{display:grid;grid-template-columns:180px 1fr;gap:6px}}dt{{font-weight:bold}}dd{{margin:0;overflow-wrap:anywhere}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccd7df;text-align:left;padding:6px;overflow-wrap:anywhere}}li{{overflow-wrap:anywhere}}thead{{display:table-header-group}}tr{{break-inside:avoid}}h2,h3,h4{{break-after:avoid}}@media print{{button,.print-help{{display:none}}body{{margin:0}}article{{border:0;padding:0}}}}@page{{size:A4;margin:16mm}}</style>
<script src="/assets/print-report.js" defer></script></head><body><button id="print-report">Print / save as PDF</button><p class="print-help">Choose Microsoft Print to PDF or Save as PDF in your browser. No upload or Java installation is required.</p><h1>{escape(data['title'])}</h1><p>{escape(DISCLAIMER)}</p><p>{data['route_count']} routes · {data['variation_count']} variations · {data['trip_count']} source trips</p><p>Audit completed: {escape(str(data['completed_at'] or ''))} · Search: {escape(search or 'All')}</p><p>Includes every listed variation and its representative trip sequence. Excel includes all underlying trip and stop-time records.</p>{''.join(sections) or '<p>No unpaired patterns match this report.</p>'}<h2>Source provenance</h2><ul>{sources}</ul></body></html>'''.encode('utf-8')
