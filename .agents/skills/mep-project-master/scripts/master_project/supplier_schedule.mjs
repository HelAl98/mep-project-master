// Generic artifact-tool renderer. Consumes compilation JSON; never opens SQLite/source documents.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const args={};
for(let i=2;i<process.argv.length;i+=2) args[process.argv[i]]=process.argv[i+1];
for(const key of ['--input','--family','--output']) if(!args[key]) throw new Error(`Missing ${key}`);
const moduleRoot=args['--module-root'] || path.join(process.cwd(),'node_modules');
const resolver=createRequire(path.join(path.resolve(moduleRoot),'..','package.json'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(resolver.resolve('@oai/artifact-tool')).href);
const content=JSON.parse(await fs.readFile(args['--input'],'utf8'));
if(content.schema_version!=='mep-supplier-draft/1') throw new Error('Unsupported compilation contract');
const family=content.families.find(f=>f.family===args['--family']);
if(!family) throw new Error('Family missing');
const output=path.resolve(args['--output']);
const internal=path.join(output,'internal');
const workbook=Workbook.create();
const text=value=>value===null||value===undefined?'UNKNOWN':Array.isArray(value)?value.map(text).join('; '):typeof value==='object'?JSON.stringify(value):String(value);
const safe=value=>{const s=text(value);return s.startsWith('=')?`'${s}`:s;};
const refList=items=>[...new Set(items)].join(', ');
const impactLabel=value=>value==='UNAFFECTED_BY_DETECTED_SOURCE_CHANGES'?'No detected change':value==='POTENTIALLY_OUTDATED'?'Potentially outdated':value;
const style='#233C54';
const previews=[];
const column=n=>String.fromCharCode(65+n-1);
function table(name,headers,rows,widths){
  const sheet=workbook.worksheets.add(name);sheet.showGridLines=false;sheet.tabColor=style;
  const columns=headers.length,end=Math.max(8,rows.length+7);
  const range=sheet.getRangeByIndexes(0,0,end,columns);
  range.format.font={name:'Arial',size:10,color:'#20354A'};
  range.format.verticalAlignment='center';
  sheet.getRange('A2').values=[[`${family.family} — ${name}`]];
  sheet.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:style};
  sheet.getRange('A2').format.rowHeight=26;
  sheet.getRange('A3').values=[[content.status]];
  sheet.getRange('A3').format.font={name:'Arial',size:10,bold:true,color:'#9C4125'};
  sheet.getRange('A4').values=[[family.incomplete_status || content.project_name]];
  sheet.getRange('A4').format.font={name:'Arial',size:9,bold:family.incomplete,color:'#9C4125'};
  sheet.getRange('A5').values=[[`${content.project_name}. Assessment: ${content.currency_assessment.assessed_at||'UNKNOWN'} (saved snapshot).`]];
  sheet.getRange('A5').format.font={name:'Arial',size:9,color:'#5A6D7E'};
  sheet.getRangeByIndexes(6,0,1,columns).values=[headers];
  const actual=rows.length?rows:[headers.map((_,i)=>i===0?'No recorded values':null)];
  sheet.getRangeByIndexes(7,0,actual.length,columns).values=actual.map(row=>row.map(v=>typeof v==='number'?v:safe(v)));
  const data=sheet.getRangeByIndexes(7,0,actual.length,columns);data.format.wrapText=true;data.format.rowHeight=42;
  // Printed values are literal strings, including punctuation and placeholders. No calculated conversions.
  data.setNumberFormat('@');
  for(let col=0;col<columns;col++)sheet.getRangeByIndexes(6,col,actual.length+1,1).format.columnWidth=widths[col]||20;
  const header=sheet.getRangeByIndexes(6,0,1,columns);
  header.format={fill:style,font:{name:'Arial',bold:true,color:'#FFFFFF',size:10},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:32};
  for(let i=0;i<actual.length;i++){
    const longest=Math.max(...actual[i].map((v,j)=>Math.ceil(text(v).length/(widths[j]||20))));
    sheet.getRangeByIndexes(7+i,0,1,columns).format.rowHeight=Math.max(32,Math.min(140,16*Math.min(longest,8)+8));
  }
  const t=sheet.tables.add(`A7:${column(columns)}${actual.length+7}`,true,name.replace(/\W/g,'')+'Table');
  t.showFilterButton=true;
  sheet.freezePanes.freezeRows(7);sheet.freezePanes.freezeColumns(1);
  previews.push({sheet:name,range:`A1:${column(Math.min(columns,9))}${Math.min(end,13)}`});
  return sheet;
}
const eq=family.equipment.map(r=>[
  r.tag,r.family,r.identity_kind,r.description,r.physical_quantity_status,
  r.scheduled_quantities.length?r.scheduled_quantities.map(q=>text(q.value)+(q.unit?' '+q.unit:'')+' (unapproved declaration)').join('; '):'UNKNOWN',
  r.installation_location.length?r.installation_location.map(x=>text(x.value)).join('; '):'UNKNOWN',
  r.area_served.length?r.area_served.map(x=>text(x.value)).join('; '):'UNKNOWN',r.review_status,
  refList([r.identity_ref,...r.installation_location.map(x=>x.provenance_ref),...r.area_served.map(x=>x.provenance_ref),...r.scheduled_quantities.map(x=>x.provenance_ref)])
]);
table('Equipment',['Equipment tag','Family','Identity kind','Description','Physical quantity status','Scheduled quantity (printed)','Installation location (recorded)','Area served (recorded)','Review status','Source refs'],eq,[20,18,16,32,25,27,24,30,18,54]);
const detailed=content.options.source_reference_visibility==='detailed';
table('Parameters',['Equipment tag','Original parameter','Printed value','Printed unit','Component / context','Value status','Source file','Drawing number','Row / cell / CAD locator','Review status','Source currency / impact','Source refs',...(detailed?['Original source ID','Revision (recorded, unverified)']:[])],
  family.parameters.map(r=>[r.tag,r.name,text(r.value),r.unit,r.component_context,r.value_status,r.source.filename,r.source.drawing_number,r.source.locator,
    r.review.status,`${r.source.source_currency} / ${impactLabel(r.source.dependency_impact)}`,refList(r.provenance_refs),...(detailed?[r.source.original_file_id,r.source.revision_as_recorded]:[])]),
  [20,33,23,16,22,27,22,23,62,22,37,42,68,26]);
table('Outstanding',['Equipment tag','Outstanding information','Saved finding / missing value','Status','Source refs'],
  family.issues.map(r=>[r.tag,r.item,r.detail,r.status,refList(r.provenance_refs)]),[20,36,100,35,46]);
table('Specifications',['Section','Section title','Clause (stored)','Category','Applicability status','Source file','Physical PDF page','Source refs'],
  family.specifications.map(r=>[r.section,r.section_title,r.clause,r.category,r.applicability_status,r.source.filename,r.physical_pdf_page,refList(r.provenance_refs)]),[15,32,20,42,22,24,18,44]);
if(family.optional_context.length)table('Optional context',['Equipment tag','Role','Original context','Relationship status','Source file','Source refs'],
  family.optional_context.map(r=>[r.tag,r.role,r.text,r.status,r.source.filename,refList(r.provenance_refs)]),[20,18,100,25,24,45]);
workbook.recalculate();
const inspect=await workbook.inspect({kind:'table',range:'Equipment!A7:J10',include:'values,formulas',tableMaxRows:4,tableMaxCols:10,maxChars:2500});
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:2000});
await fs.writeFile(path.join(internal,'spreadsheet-inspection.ndjson'),inspect.ndjson+'\n'+errors.ndjson,'utf8');
for(const item of previews){
  const preview=await workbook.render({sheetName:item.sheet,range:item.range,scale:1,format:'png'});
  await fs.writeFile(path.join(internal,'preview-'+item.sheet.replace(/\W/g,'-')+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
const sourcePreview=await workbook.render({sheetName:'Parameters',range:`G7:L${Math.min(13,Math.max(8,family.parameters.length+7))}`,scale:1,format:'png'});
await fs.writeFile(path.join(internal,'preview-Parameter-sources.png'),new Uint8Array(await sourcePreview.arrayBuffer()));
const destination=path.join(output,'Equipment Technical Schedule.xlsx');
try{await fs.access(destination);throw new Error('Output already exists');}catch(error){if(error.code!=='ENOENT')throw error;}
const file=await SpreadsheetFile.exportXlsx(workbook);await file.save(destination);
// The runtime may emit an inspection sidecar. It is an internal audit, never a supplier document.
try{await fs.rename(destination+'.inspect.ndjson',path.join(internal,'xlsx-export-inspection.ndjson'));}
catch(error){if(error.code!=='ENOENT')throw error;}
console.log(JSON.stringify({status:'EXPORTED_DRAFT',file:destination,sheets:previews.map(p=>p.sheet),parameters:family.parameters.length}));
