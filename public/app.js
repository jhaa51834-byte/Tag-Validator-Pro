let currentMode = 'tealium';
let cachedResults = [];
let scheduleFile = null;

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`[onclick="switchTab('${tabId}')"]`).classList.add('active');
    
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`tab-${tabId}`).classList.add('active');

    if (tabId === 'scheduler') {
        loadSchedules();
        loadHistory();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // --- MANUAL TAB LOGIC ---
    const uploadBoxM = document.getElementById('uploadBoxManual');
    const fileInputM = document.getElementById('fileInputManual');
    const uploadTextM = document.getElementById('uploadTextManual');
    const runBtn = document.getElementById('runBtn');
    const logBox = document.getElementById('logBox');
    const downloadBtn = document.getElementById('downloadBtn');

    uploadBoxM.onclick = () => fileInputM.click();
    fileInputM.onchange = async (e) => {
        if (!e.target.files.length) return;
        const f = e.target.files[0];
        uploadTextM.innerText = 'Uploading...';
        const fd = new FormData();
        fd.append('file', f);
        const r = await fetch('/api/tag-validator/upload', { method: 'POST', body: fd });
        if (r.ok) {
            uploadTextM.innerHTML = '<span class="ready">' + f.name + '</span>';
            runBtn.disabled = false;
        }
    };

    runBtn.onclick = async () => {
        runBtn.disabled = true;
        runBtn.innerText = 'Validating...';
        logBox.classList.remove('hidden');
        document.getElementById('progressSection').classList.remove('hidden');

        await fetch('/api/tag-validator/run', { method: 'POST' });

        const poll = setInterval(async () => {
            const r = await fetch('/api/tag-validator/status');
            const d = await r.json();
            const logs = d.logs.filter(l => !l.includes('DeprecationWarning') && !l.includes('Pyarrow') && l.trim());
            logBox.innerHTML = logs.map(l => '<div>' + l + '</div>').join('');
            logBox.scrollTop = logBox.scrollHeight;

            const last = [...logs].reverse().find(l => l.match(/\[\d+\/\d+\]/));
            if (last) {
                const m = last.match(/\[(\d+)\/(\d+)\]/);
                if (m) {
                    const c = +m[1], t = +m[2], pct = Math.round(c / t * 100);
                    document.getElementById('progressLabel').innerText = c + '/' + t;
                    document.getElementById('progressBar').style.width = pct + '%';
                }
            }

            if (!d.running) {
                clearInterval(poll);
                runBtn.disabled = false;
                runBtn.innerText = 'Run Again';
                loadResults();
            }
        }, 800);
    };

    downloadBtn.onclick = () => window.location.href = '/api/tag-validator/download';
    renderTable();

    // --- SCHEDULER TAB LOGIC ---
    const uploadBoxS = document.getElementById('uploadBoxSchedule');
    const fileInputS = document.getElementById('fileInputSchedule');
    const uploadTextS = document.getElementById('uploadTextSchedule');
    const scheduleBtn = document.getElementById('scheduleBtn');
    const scheduleFreq = document.getElementById('scheduleFreq');

    uploadBoxS.onclick = () => fileInputS.click();
    fileInputS.onchange = (e) => {
        if (!e.target.files.length) return;
        scheduleFile = e.target.files[0];
        uploadTextS.innerHTML = '<span class="ready">' + scheduleFile.name + '</span>';
        scheduleBtn.disabled = false;
    };

    scheduleBtn.onclick = async () => {
        if (!scheduleFile) return;
        scheduleBtn.disabled = true;
        scheduleBtn.innerText = 'Creating...';
        
        const fd = new FormData();
        fd.append('file', scheduleFile);
        fd.append('frequency', scheduleFreq.value);
        
        const r = await fetch('/api/schedule/add', { method: 'POST', body: fd });
        if (r.ok) {
            scheduleFile = null;
            uploadTextS.innerText = 'Select Excel File for Automation';
            scheduleBtn.innerText = 'Create Schedule';
            loadSchedules();
        } else {
            scheduleBtn.disabled = false;
            scheduleBtn.innerText = 'Create Schedule';
            alert("Error creating schedule");
        }
    };
});

const B = v => v === 'PASS' ? '<span class="badge b-pass">PASS</span>' : '<span class="badge b-fail">FAIL</span>';
const ID = v => v ? '<span class="mono">' + v + '</span>' : '<span style="color:#d1d5db">--</span>';

async function loadResults() {
    const r = await fetch('/api/tag-validator/results');
    const d = await r.json();
    if (!d.results || !d.results.length) return;
    cachedResults = d.results;
    document.getElementById('downloadBtn').classList.remove('hidden');
    renderTable();
}

function renderTable() {
    const body = document.getElementById('resultsBody');
    const statsBar = document.getElementById('statsBar');

    if (!cachedResults.length) {
        body.innerHTML = '<tr><td colspan="13" class="empty-msg">Upload a file and run validation</td></tr>';
        statsBar.classList.add('hidden');
        return;
    }

    let st = { teal: 0, adobe: 0, ga4: 0 };
    cachedResults.forEach(r => {
        if (r.Tealium_Loaded === 'PASS') st.teal++;
        if (r.Adobe_Loaded === 'PASS') st.adobe++;
        if (r.GA4_Fired === 'PASS') st.ga4++;
    });

    statsBar.classList.remove('hidden');
    statsBar.innerHTML = `
        <div class="stat"><div class="stat-dot dot-teal"></div><div><div class="stat-val val-teal">${st.teal}/${cachedResults.length}</div><div class="stat-lbl">Tealium Loaded</div></div></div>
        <div class="stat"><div class="stat-dot dot-adobe"></div><div><div class="stat-val val-adobe">${st.adobe}/${cachedResults.length}</div><div class="stat-lbl">Adobe Loaded</div></div></div>
        <div class="stat"><div class="stat-dot" style="background:#60a5fa; color:#60a5fa;"></div><div><div class="stat-val" style="color:#93c5fd;">${st.ga4}/${cachedResults.length}</div><div class="stat-lbl">GA4 Loaded</div></div></div>
    `;

    body.innerHTML = cachedResults.map((r, i) => `<tr>
        <td>${i + 1}</td>
        <td class="url-col" title="${r.URL}">${r.URL}</td>
        <td>${B(r.Tealium_Loaded)}</td>
        <td>${ID(r.Tealium_Account)}</td>
        <td>${ID(r.Tealium_Profile)}</td>
        <td>${ID(r.Tealium_Env)}</td>
        <td>${B(r.Adobe_Loaded)}</td>
        <td>${ID(r.Adobe_ReportSuite)}</td>
        <td>${B(r.Adobe_PageView)}</td>
        <td>${B(r.Adobe_LinkClick)}</td>
        <td>${B(r.GA4_Fired)}</td>
        <td>${B(r.GA4_PageView)}</td>
        <td>${B(r.GA4_LinkClick)}</td>
    </tr>`).join('');
}

async function loadSchedules() {
    const r = await fetch('/api/schedule/list');
    const d = await r.json();
    const tbody = document.getElementById('schedulesBody');
    if (!d.schedules || !d.schedules.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">No active schedules</td></tr>';
        return;
    }
    
    tbody.innerHTML = d.schedules.map(s => `
        <tr>
            <td class="mono">${s.id.substring(0,8)}</td>
            <td>${s.filename}</td>
            <td><span class="badge b-pass" style="background:rgba(139,92,246,0.1);color:#a78bfa;border-color:rgba(139,92,246,0.3);">${s.frequency}</span></td>
            <td>${new Date(s.createdAt).toLocaleString()}</td>
            <td>${s.lastRun ? new Date(s.lastRun).toLocaleString() : 'Never'}</td>
            <td><button class="btn btn-danger" onclick="cancelSchedule('${s.id}')">Cancel</button></td>
        </tr>
    `).join('');
}

async function cancelSchedule(id) {
    if (!confirm('Are you sure you want to cancel this schedule?')) return;
    await fetch('/api/schedule/cancel/' + id, { method: 'DELETE' });
    loadSchedules();
}

async function loadHistory() {
    const r = await fetch('/api/schedule/history');
    const d = await r.json();
    const tbody = document.getElementById('historyBody');
    if (!d.history || !d.history.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-msg">No automated runs yet</td></tr>';
        return;
    }
    
    tbody.innerHTML = d.history.map(h => `
        <tr>
            <td>${h.filename}</td>
            <td>${new Date(h.date).toLocaleString()}</td>
            <td>${(h.size / 1024).toFixed(1)} KB</td>
            <td><button class="btn btn-download" style="padding:6px 12px" onclick="window.location.href='/api/schedule/download/${h.filename}'">Download</button></td>
        </tr>
    `).join('');
}
