const $ = id => document.getElementById(id);
const status = $('backup-status');

function preferences() {
    return Object.fromEntries(Object.keys(localStorage)
        .filter(key => key.startsWith('liainne-'))
        .map(key => [key, localStorage.getItem(key)]));
}

async function requestPersistence() {
    const message = $('persist-status');
    try {
        const granted = await navigator.storage?.persist?.();
        message.textContent = granted ? 'This browser has granted persistent storage for preferences.' :
            'Your browser manages preference storage. The SQLite database is saved separately.';
    } catch {
        message.textContent = 'This browser could not grant persistent storage.';
    }
}
$('persist-browser').onclick = requestPersistence;

$('export-backup').onclick = async () => {
    status.textContent = 'Preparing your backup…';
    try {
        const response = await fetch('/settings/backup', {cache:'no-store'});
        if (!response.ok) throw new Error('Could not export the local database.');
        const backup = await response.json();
        backup.preferences = preferences();
        const url = URL.createObjectURL(new Blob([JSON.stringify(backup)], {type:'application/json'}));
        const link = document.createElement('a');
        link.href = url;
        link.download = 'liainne-backup-' + backup.timestamp.replace(/[:.]/g,'-') + '.json';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        status.textContent = 'Backup ready. Check your downloads.';
        await requestPersistence();
    } catch (error) {
        status.textContent = error.message;
    }
};

$('import-backup').onclick = () => $('backup-file').click();
$('backup-file').onchange = async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
        const backup = JSON.parse(await file.text());
        if (backup.format !== 'liainne-local-v1') throw new Error('Choose a JSON backup exported from Settings.');
        const prefs = backup.preferences;
        if (prefs !== undefined && (!prefs || Array.isArray(prefs) || typeof prefs !== 'object' ||
            Object.entries(prefs).some(([k,v]) => !k.startsWith('liainne-') || typeof v !== 'string')))
            throw new Error('This backup has invalid preferences.');
        if (!confirm('Replace your local data with ' + file.name + '? A recovery copy of the current database will be saved first.')) return;
        status.textContent = 'Restoring and verifying records…';
        const response = await fetch('/settings/restore', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(backup)});
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Restore failed.');
        status.textContent = 'Restored. Previous database saved in backup/' + result.before_restore + '.';
        if (prefs) {
            try {
                for (const [key,value] of Object.entries(prefs)) localStorage.setItem(key,value);
            } catch {
                status.textContent += ' Browser preferences could not all be restored.';
            }
        }
        await requestPersistence();
    } catch (error) {
        status.textContent = error.message;
    } finally {
        event.target.value = '';
    }
};
