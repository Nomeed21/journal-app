import { addAskButton } from "./local-ai.js";
import { initializeTheme } from "./theme.js";
initializeTheme();

const $ = id => document.getElementById(id);
let summary, journalOffset = 0, taskOffset = 0;
const dirty = () => ['note','priority','reflection-text'].some(id => $(id).value.trim()) || $('mood').value;
window.addEventListener('beforeunload', e => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });
async function api(url, data, method = 'POST') {
    let res;
    try { res = await fetch(url, data === undefined ? {} : {method, headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); }
    catch { throw new Error('Could not connect. Your text is still here. Please try again.'); }
    if (!res.ok) throw new Error('Could not connect or save. Your text is still here. Please try again.');
    return res.json();
}
function status(id, text, error = false) { $(id).textContent = text; $(id).classList.toggle('error',error); }
function dismissWelcome() {
    $('welcome').hidden = true;
    try { localStorage.setItem('liainne-welcome-dismissed', summary?.last_entry_date || ''); } catch {}
}
async function loadSummary() {
    try {
        summary = await api('/calm/summary');
        let dismissed; try { dismissed = localStorage.getItem('liainne-welcome-dismissed'); } catch {}
        $('welcome').hidden = !summary.welcome_back || dismissed === summary.last_entry_date;
        status('participation',`${summary.recorded_entries} recorded moments across ${summary.recorded_days} days.`);
    } catch { status('participation','Could not load progress. Try reopening Progress.',true); }
}
async function navigate() {
    const page = ['today','journal','progress','tasks','settings'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'today';
    document.querySelectorAll('main>section').forEach(s => s.hidden = s.id !== page);
    document.querySelectorAll('body>nav a').forEach(a => { if(a.hash === '#'+page) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current'); });
    document.title = `LiAInne — ${page[0].toUpperCase()+page.slice(1)}`;
    if(page==='journal') {journalOffset=0; await loadJournal();}
    if(page==='tasks') {taskOffset=0; await loadTasks();}
    if(page==='progress') await loadSummary();
}
window.addEventListener('hashchange',navigate);
$('start-today').onclick = () => { dismissWelcome(); $('note').focus(); };
$('dismiss-welcome').onclick = dismissWelcome;
$('review-older').onclick = () => {dismissWelcome(); location.hash='tasks';};
$('write-gap').onclick = () => {dismissWelcome(); $('note').placeholder='What would you like to remember about the time away?'; $('note').focus();};
$('reflection-type').onchange = () => { $('reflection-prompt').textContent = {free:'What is on your mind?',morning:'What would support you today?',night:'What would you like to remember from today?'}[$('reflection-type').value]; };
$('checkin').onsubmit = async e => {
    e.preventDefault();
    const content = [$('note').value.trim(), $('priority').value.trim() ? 'Priority for today: '+$('priority').value.trim() : '', $('reflection-text').value.trim()].filter(Boolean).join('\n\n');
    const mood = $('mood').value ? Number($('mood').value) : null;
    if(!content && mood===null) {status('save-status','Write a note or choose a mood to save.',true); $('note').focus(); return;}
    $('checkin').querySelectorAll('input,textarea,select,button').forEach(el=>el.disabled=true); status('save-status','Saving…');
    try {
        await api('/entries',{title:'',content,mood,energy:null,focus:null,entry_type:$('reflection-text').value.trim() ? $('reflection-type').value : 'free',tags:[]});
        $('checkin').reset(); $('reflection').open=false;
        status('save-status','Saved. You’re done for today.'); $('welcome').hidden=true;
        // No follow-up analysis, generated tasks, or new commitments.
    } catch(err) { status('save-status',err.message,true); }
    finally { $('checkin').querySelectorAll('input,textarea,select,button').forEach(el=>el.disabled=false); }
};
$('selected-task').onclick = () => {
    const note=$('note'), text=note.value.slice(note.selectionStart,note.selectionEnd).trim();
    if(!text) {status('task-status','Select the words in your note you want to turn into a task.');return;}
    $('task-title').value=text.slice(0,500); $('task-draft').hidden=false; $('task-title').focus();
};
$('cancel-task').onclick=()=>{$('task-draft').hidden=true;};
$('create-task').onclick=async()=>{
    $('create-task').disabled=true;
    try {await api('/calm/tasks',{title:$('task-title').value}); $('task-draft').hidden=true; status('task-status','Task created. You can find it in Tasks.');}
    catch(err){status('task-status',err.message,true);}finally{$('create-task').disabled=false;}
};
function el(tag,text) {const node=document.createElement(tag); if(text!==undefined)node.textContent=text; return node;}
function button(text,action){const b=el('button',text);b.className='secondary';b.onclick=action;return b;}
async function loadJournal() {
    const list=$('journal-list'); if(!journalOffset) list.replaceChildren(el('p','Loading your journal…'));
    try {
        const rows=await api('/calm/journal?offset='+journalOffset); if(!journalOffset)list.replaceChildren();
        if(!rows.length&&!journalOffset)list.append(el('p','Your first note can be a single sentence. It will appear here.'));
        for(const row of rows){const a=el('article');a.append(el('time',new Date(row.created_at).toLocaleString()),el('h2',row.title||'A recorded moment'),el('p',row.content||''),Object.assign(el('p',row.mood==null?'Mood not recorded':`Mood: ${row.mood}/5`),{className:'entry-metadata'}));addAskButton(a, row.content || (row.mood == null ? '' : 'Mood: '+row.mood+'/5'), a.querySelector('p'));list.append(a);}
        journalOffset+=rows.length;$('more-journal').hidden=rows.length<50;
    }catch{list.append(el('p','Could not load entries. Reopen Journal to try again.'));}
}
$('more-journal').onclick=async()=>{$('more-journal').disabled=true;await loadJournal();$('more-journal').disabled=false;};
async function moveTask(row,data,article) {
    article.querySelectorAll('button').forEach(b=>b.disabled=true);
    try {
        const result=await api(`/calm/tasks/${row.id}/placement`,data,'PUT');
        status('placement-status','Task updated.');
        const undo=button('Undo last move',async()=>{undo.disabled=true;try{await api(`/calm/tasks/${row.id}/placement`,result.previous,'PUT');status('placement-status','Move undone.');taskOffset=0;await loadTasks();}catch(err){status('placement-status',err.message,true);undo.disabled=false;}});
        $('placement-status').append(' ',undo);taskOffset=0;await loadTasks();
    }catch(err){status('placement-status',err.message,true);article.querySelectorAll('button').forEach(b=>b.disabled=false);}
}
async function loadTasks(){
    const list=$('task-list');if(!taskOffset)list.replaceChildren(el('p','Loading tasks…'));
    try{
        const rows=await api('/calm/tasks?offset='+taskOffset);if(!taskOffset)list.replaceChildren();
        if(!rows.length&&!taskOffset)list.append(el('p','No tasks here. You do not need one to journal.'));
        for(const row of rows){
            const a=el('article'), controls=el('div');controls.className='actions';
            a.append(el('h2',row.title),el('p',`${row.is_completed?'Completed':row.section==='archived'?'Archived':'Open'}${row.due_date?' · Scheduled '+row.due_date:''}`));
            if(!row.is_completed){
                const date=el('input');date.type='date';date.setAttribute('aria-label','Postpone '+row.title+' to date');
                controls.append(button('Bring to today',()=>moveTask(row,{section:'daily',due_date:summary?.today||new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Manila',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())},a)),date,button('Postpone',()=>{if(!date.value){date.focus();date.reportValidity();status('placement-status','Choose a date first.');return;}moveTask(row,{section:'weekly',due_date:date.value},a);}),button(row.section==='archived'?'Restore':'Archive',()=>moveTask(row,{section:row.section==='archived'?'weekly':'archived',due_date:row.due_date},a)));
                a.append(controls);
            }list.append(a);
        }taskOffset+=rows.length;$('more-tasks').hidden=rows.length<50;
    }catch{list.append(el('p','Could not load tasks. Reopen Tasks to try again.'));}
}
$('more-tasks').onclick=async()=>{$('more-tasks').disabled=true;await loadTasks();$('more-tasks').disabled=false;};
$('add-manual-task').onclick=async()=>{const b=$('add-manual-task');b.disabled=true;try{await api('/calm/tasks',{title:$('manual-task').value});$('manual-task').value='';status('placement-status','Task created.');taskOffset=0;await loadTasks();}catch(err){status('placement-status',err.message,true);}finally{b.disabled=false;}};
$('date-label').textContent=new Intl.DateTimeFormat(undefined,{weekday:'long',month:'long',day:'numeric',timeZone:'Asia/Manila'}).format(new Date());
loadSummary();navigate();

document.addEventListener('local-ai-note-saved', () => {
    if (!$('journal').hidden) { journalOffset=0; loadJournal(); }
});
