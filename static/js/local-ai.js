const $ = id => document.getElementById(id);
let config = {enabled:false, model:'qwen3:4b', reasoning:false, models:[], state:'Off'};
let refreshId = 0;

async function api(path, body, method='POST') {
    const options = body === undefined ? {} : {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
    const response = await fetch('/api/ai/'+path, {...options, cache:'no-store'});
    if (!response.ok) {
        const detail = (await response.json().catch(()=>({}))).detail;
        throw new Error(typeof detail === 'string' ? detail : 'Could not complete the local AI request.');
    }
    return response.json();
}

function display() {
    document.querySelectorAll('[data-local-ai-status]').forEach(el=>el.textContent=config.enabled ? config.state : "Off");
    document.querySelectorAll('.ask-local-ai').forEach(el=>el.hidden=!config.enabled);
    if (!$('local-ai-enabled')) return;
    $('local-ai-enabled').checked=config.enabled;
    $('local-ai-reasoning').checked=config.reasoning;
    $('local-ai-connection').textContent=config.message || config.state;
    const select=$('local-ai-model');
    const labels={'qwen3:4b':'qwen3:4b (fast)','qwen3:8b':'qwen3:8b (better quality)'};
    const visible=[...new Set([config.model,...config.models])].filter(name=>
        $('local-ai-all').checked || !name.toLowerCase().includes('coder'));
    select.replaceChildren(...visible.map(name=>new Option(labels[name]||name,name)));
    select.value=config.model;
}

async function refresh(probe=false) {
    const id=++refreshId;
    try {
        const next=await api('status'+(probe?'?probe=true':''));
        if (id===refreshId) { config=next; display(); }
    } catch {
        if(id===refreshId) {config={...config,enabled:false,state:'Unavailable',message:'Could not reach LiAInne.'}; display();}
    }
}
async function update(change) {
    const controls=['local-ai-enabled','local-ai-model','local-ai-reasoning','local-ai-test'].map($);
    controls.forEach(el=>el.disabled=true);
    try {
        await api('settings',{enabled:config.enabled,model:config.model,reasoning:config.reasoning,...change},'PUT');
        await refresh(change.enabled !== false);
    } catch(error) { display(); $('local-ai-connection').textContent=error.message; }
    finally { controls.forEach(el=>el.disabled=false); }
}
if ($('local-ai-enabled')) {
    $('local-ai-enabled').onchange=e=>update({enabled:e.target.checked});
    $('local-ai-reasoning').onchange=e=>update({reasoning:e.target.checked});
    $('local-ai-model').onchange=e=>update({model:e.target.value});
    $('local-ai-all').onchange=display;
    $('local-ai-test').onclick=()=>{ $('local-ai-connection').textContent='Testing connection…'; refresh(true); };
}
refresh();
window.addEventListener('focus',()=>refresh());

export function addAskButton(card, passage, passageNode) {
    if (!passage.trim()) return;
    const button=document.createElement('button');
    button.type='button'; button.className='ask-local-ai secondary'; button.textContent='Ask local AI';
    button.hidden=!config.enabled;
    function selection() {
        const current=window.getSelection();
        if (!current?.rangeCount || current.isCollapsed) return '';
        return passageNode.contains(current.getRangeAt(0).commonAncestorContainer) ? current.toString() : '';
    }
    let picked='';
    button.onpointerdown=()=>{picked=selection();};
    button.onclick=()=>{openPanel(picked || selection() || passage,passage); picked='';};
    card.append(button);
}

// Game's Journal page is an editor. Read only the visible draft fields when
// the user opens the panel; a selected substring wins over the whole draft.
export function addDraftAskButton(form) {
    const button=document.createElement('button');
    button.type='button'; button.className='ask-local-ai secondary';
    button.textContent='Ask local AI'; button.hidden=!config.enabled;
    button.onclick=()=>{
        const fields=[...form.querySelectorAll('textarea,input[type=text]')]
            .filter(field=>field.getClientRects().length && field.value.trim());
        const whole=fields.map(field=>field.value).join('\n\n');
        const selection=fields.map(field=>field.value.slice(field.selectionStart,field.selectionEnd)).find(Boolean);
        openPanel(selection || whole,whole);
    };
    form.after(button);
}

function openPanel(initial, whole) {
    const dialog=document.createElement('dialog');
    dialog.className='local-ai-dialog'; dialog.setAttribute('aria-labelledby','ask-title');
    dialog.innerHTML=`
    <h2 id="ask-title">Ask local AI</h2><p>Only this passage and question will be included.</p>
    <label for="ask-passage">Passage</label><textarea id="ask-passage" rows="4"></textarea>
    <button type="button" id="ask-whole">Use whole entry</button>
    <label for="ask-question">Your question</label><textarea id="ask-question" rows="2" placeholder="What patterns do you notice?"></textarea>
    <button type="button" id="ask-preview">Preview</button>
    <section id="ask-plan" hidden><h3>Exact messages to send</h3><p id="ask-model"></p><p id="ask-trunc"></p><pre id="ask-messages"></pre></section>
    <div class="ask-actions"><button type="button" id="ask-send" disabled>Send</button>
    <button type="button" id="ask-stop" hidden>Stop</button><button type="button" id="ask-close">Cancel</button></div>
    <p role="status" id="ask-status"></p><details id="ask-thought" hidden><summary>Thinking…</summary><pre></pre></details>
    <div id="ask-answer"></div><div class="ask-actions"><button type="button" id="ask-copy" hidden>Copy response</button>
    <button type="button" id="ask-save" hidden>Save as note</button></div>`;
    document.body.append(dialog); dialog.showModal();
    const p=$('ask-passage'), q=$('ask-question'), send=$('ask-send'), stop=$('ask-stop'), status=$('ask-status');
    const plan=$('ask-plan'), answer=$('ask-answer'), thought=$('ask-thought'), save=$('ask-save'), copy=$('ask-copy');
    p.value=initial; q.focus();
    let approved=null, revision=0, controller=null;
    function invalidate() {
        revision++; approved=null; send.disabled=true; plan.hidden=true;
        status.textContent=''; answer.textContent=''; thought.hidden=true;
        copy.hidden=save.hidden=true;
    }
    p.oninput=q.oninput=invalidate;
    $('ask-whole').onclick=()=>{p.value=whole; invalidate();};
    const close=()=>{controller?.abort();dialog.close();};
    $('ask-close').onclick=close;
    dialog.oncancel=e=>{e.preventDefault();close();};
    dialog.onclose=()=>{controller?.abort();dialog.remove();};
    $('ask-preview').onclick=async()=>{
        invalidate();const token=revision;
        const body={passage:p.value,question:q.value,model:config.model};
        status.textContent='Preparing preview…';
        try {
            const preview=await api('preview',body);
            if(token!==revision || !dialog.open) return;
            $('ask-model').textContent='Ollama on this computer · '+preview.model;
            $('ask-trunc').textContent=preview.cut_characters ? preview.cut_characters+' characters removed from the end to fit the context window.' : 'Full passage included.';
            $('ask-messages').textContent=preview.messages.map(m=>m.role.toUpperCase()+'\n'+m.content).join('\n\n');
            plan.hidden=false; send.disabled=false; approved=body;
            status.textContent='Preview ready. Press Send to run the model.';
        } catch(error) {if(token===revision)status.textContent=error.message;}
    };
    stop.onclick=()=>controller?.abort();
    send.onclick=async()=>{
        if(!approved || controller) return;
        controller=new AbortController();
        const active=controller;
        send.disabled=true; stop.hidden=false; save.hidden=copy.hidden=true; p.readOnly=q.readOnly=true;
        $('ask-preview').disabled=$('ask-whole').disabled=true;
        answer.textContent=''; thought.querySelector('pre').textContent=''; thought.hidden=true;
        let complete=false, note='';
        status.textContent='Waiting for Ollama…';
        function receive(line) {
            if(!line.trim())return;
            const e=JSON.parse(line);
            if(e.type==='error')throw new Error(e.text);
            if(e.type==='note'){note=e.text;status.textContent=note;}
            if(e.type==='thinking'){thought.hidden=false;thought.querySelector('pre').append(e.text);}
            if(e.type==='answer'){answer.append(e.text);status.textContent=note || 'Receiving reply…';}
            if(e.type==='done')complete=true;
        }
        try {
            const res=await fetch('/api/ai/ask',{method:'POST',headers:{'Content-Type':'application/json'},signal:active.signal,body:JSON.stringify(approved)});
            if(!res.ok)throw new Error((await res.json()).detail || 'Local AI request failed.');
            const reader=res.body.getReader(),decoder=new TextDecoder();
            let partial='';
            while(true){
                const {value,done}=await reader.read();
                partial+=decoder.decode(value,{stream:!done});
                const lines=partial.split('\n');partial=lines.pop();
                lines.forEach(receive);
                if(done){receive(partial);break;}
            }
            if(!complete)throw new Error('The stream ended early. You can try again.');
            status.textContent=(note?note+' ':'')+'Reply complete.';
        }catch(error){status.textContent=active.signal.aborted?'Stopped.':error.message;}
        finally {
            active.abort();controller=null;
            if(dialog.open) {
                stop.hidden=true;p.readOnly=q.readOnly=false;
                $('ask-preview').disabled=$('ask-whole').disabled=false;
                copy.hidden=save.hidden=!answer.textContent.trim();save.disabled=false;send.disabled=false;
            }
        }
    };
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(answer.textContent);status.textContent='Copied.';}catch{status.textContent='Select the reply to copy it.';}};
    save.onclick=async()=>{
        save.disabled=true;
        try{
            const res=await fetch('/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:answer.textContent,tags:['local-ai']})});
            if(!res.ok)throw new Error();
            status.textContent='Saved as a new note.';
            document.dispatchEvent(new Event('local-ai-note-saved'));
        }catch{save.disabled=false;status.textContent='Could not save the note. Your reply is still here.';}
    };
}

