import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';


const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
try { process.loadEnvFile?.(path.join(root, '.env')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
const url = new URL(process.env.SUPABASE_URL);
if (url.protocol !== 'https:') throw Error('Use an HTTPS Supabase URL.');
const key = process.env.SUPABASE_KEY;
if (!key) throw Error('SUPABASE_KEY is required.');
async function request(endpoint, options = {}) {
    const response = await fetch(new URL(endpoint, url), {
        ...options, redirect: 'error', headers: {apikey:key, Authorization:'Bearer '+key, ...options.headers}
    });
    if (!response.ok) throw Error('Supabase request failed with HTTP '+response.status);
    return response;
}

const schema = (await (await request('/rest/v1/',{headers:{Accept:'application/openapi+json'}})).json()).definitions;
const tables = {}, counts = {}, files = [];
for (const [table, definition] of Object.entries(schema)) {
    const keys = Object.entries(definition.properties).filter(([,col])=>col.description?.includes('<pk/>')).map(([name])=>name);
    if (!keys.length) throw Error('Cannot safely paginate table without primary key: '+table);
    const rows = [];
    let expected;
    do {
        const params = new URLSearchParams({select:'*',order:keys.join(','),offset:String(rows.length),limit:'500'});
        const response = await request('/rest/v1/'+encodeURIComponent(table)+'?'+params,{headers:{Prefer:'count=exact'}});
        const rawCount = response.headers.get('content-range')?.split('/')[1];
        if (!rawCount || !/^\d+$/.test(rawCount)) throw Error('Missing count for '+table);
        const total = Number(rawCount);
        if (expected !== undefined && total !== expected) throw Error('Row count changed during export: '+table);
        expected = total;
        const page = await response.json();
        if (!page.length && rows.length < expected) throw Error('Incomplete page: '+table);
        rows.push(...page);
    } while (rows.length < expected);
    if (rows.length !== expected || new Set(rows.map(r=>JSON.stringify(keys.map(k=>r[k])))).size !== expected)
        throw Error('Key/count mismatch: '+table);
    tables[table]=rows; counts[table]=expected;
}
const buckets = await (await request('/storage/v1/bucket')).json();
async function downloadFolder(bucket, prefix='') {
    for (let offset=0;;offset+=100) {
        const items=await (await request('/storage/v1/object/list/'+encodeURIComponent(bucket),{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({prefix,offset,limit:100,sortBy:{column:'name',order:'asc'}})
        })).json();
        for (const item of items) {
            const name=prefix?prefix+'/'+item.name:item.name;
            if (!item.id) await downloadFolder(bucket,name);
            else {
                const response=await request('/storage/v1/object/'+[bucket,...name.split('/')].map(encodeURIComponent).join('/'));
                files.push({bucket,name,data:Buffer.from(await response.arrayBuffer()).toString('base64')});
            }
        }
        if(items.length<100) break;
    }
}
for(const bucket of buckets) await downloadFolder(bucket.id);
const timestamp=new Date().toISOString();
const directory=path.join(root,'backup');
await fs.mkdir(directory,{recursive:true,mode:0o700});
const dest=path.join(directory,'supabase-export-'+timestamp.replace(/[:.]/g,'-')+'.json');
await fs.writeFile(dest,JSON.stringify({format:'liainne-supabase-v1',timestamp,schema,counts,tables,buckets,files}),{flag:'wx',mode:0o600});
console.log(path.basename(dest),Object.keys(tables).length+' tables',Object.values(counts).reduce((a,b)=>a+b,0)+' rows',files.length+' files');
