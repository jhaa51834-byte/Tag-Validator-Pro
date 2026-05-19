let currentAuditMode = 'tealium';
let cachedResults = [];
let scheduleFile = null;
let richResults = [];                 // per-scenario pixel data (source attribution)
let scenarioList = ['Necessary', 'Performance', 'Functional', 'Targeting'];
let currentScenario = 'Necessary';

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

function setAuditMode(mode) {
    currentAuditMode = mode;
    document.getElementById('modeTealium').classList.toggle('active', mode === 'tealium');
    document.getElementById('modeGA4').classList.toggle('active', mode === 'ga4');
    document.getElementById('modePixels').classList.toggle('active', mode === 'pixels');
    const tabs = document.getElementById('scenarioTabs');
    if (mode === 'pixels') {
        tabs.classList.remove('hidden');
        renderScenarioTabs();
        loadRich();
    } else {
        tabs.classList.add('hidden');
    }
    renderTable();
}

function setScenario(sc) {
    currentScenario = sc;
    document.querySelectorAll('.sc-btn').forEach(b => b.classList.toggle('active', b.dataset.sc === sc));
    renderTable();
}

function renderScenarioTabs() {
    document.getElementById('scenarioTabs').innerHTML = scenarioList.map(sc =>
        `<button class="sc-btn ${sc === currentScenario ? 'active' : ''}" data-sc="${sc}" onclick="setScenario('${sc}')">${sc}</button>`
    ).join('');
}

async function loadRich() {
    try {
        const d = await (await fetch('/api/tag-validator/results-rich')).json();
        if (d.scenarios && d.scenarios.length) scenarioList = d.scenarios;
        richResults = d.results || [];
        if (!scenarioList.includes(currentScenario)) currentScenario = scenarioList[0];
        renderScenarioTabs();
        if (currentAuditMode === 'pixels') renderTable();
    } catch { richResults = []; }
}

const SRC_CLASS = { 'Tealium': 'src-teal', 'Adobe': 'src-adobe', 'GTM / gtag': 'src-gtm', 'Hardcoded': 'src-hard' };
const srcChip = s => `<span class="src ${SRC_CLASS[s] || 'src-hard'}">${s}</span>`;

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

        // Pass mode to the run command
        await fetch('/api/tag-validator/run', { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: currentAuditMode })
        });

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
        fd.append('email', document.getElementById('scheduleEmail').value.trim());

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

    document.getElementById('testEmailBtn').onclick = async () => {
        const flash = document.getElementById('schFlash');
        flash.style.color = '#5eead4';
        flash.innerText = 'Sending test email...';
        const r = await fetch('/api/test-email', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: document.getElementById('scheduleEmail').value.trim() }),
        });
        const j = await r.json();
        flash.style.color = r.ok ? '#5eead4' : '#f87171';
        flash.innerText = r.ok ? j.message : ('Error: ' + j.error);
    };

    fetch('/api/mailer-status').then(r => r.json()).then(d => {
        document.getElementById('mailerWarn').classList.toggle('hidden', !!d.mailerReady);
    }).catch(() => {});
});

const B = v => v === 'PASS' ? '<span class="badge b-pass">PASS</span>' : '<span class="badge b-fail">FAIL</span>';
const ID = v => v ? '<span class="mono">' + v + '</span>' : '<span style="color:#d1d5db">--</span>';

async function loadResults() {
    const r = await fetch('/api/tag-validator/results');
    const d = await r.json();
    if (!d.results || !d.results.length) return;
    cachedResults = d.results;
    document.getElementById('downloadBtn').classList.remove('hidden');
    if (currentAuditMode === 'pixels') await loadRich();
    renderTable();
}

function renderTable() {
    const head = document.getElementById('tableHead');
    const body = document.getElementById('resultsBody');
    const statsBar = document.getElementById('statsBar');

    if (currentAuditMode === 'pixels') {
        head.innerHTML = `
            <tr>
                <th>#</th><th>URL</th>
                <th class="h-pix">Marketing Pixel</th>
                <th class="h-pix">Fires</th>
                <th class="h-pix">Fired From (Source)</th>
                <th style="text-align:center;">Compliance</th>
            </tr>
        `;
    } else if (currentAuditMode === 'tealium') {
        head.innerHTML = `
            <tr>
                <th rowspan="2">#</th><th rowspan="2">URL</th>
                <th colspan="4" class="h-teal" style="text-align:center;">TEALIUM ANALYTICS</th>
                <th colspan="3" class="h-adobe" style="text-align:center;">ADOBE ANALYTICS</th>
            </tr>
            <tr>
                <th class="h-teal">Loaded</th><th class="h-teal">Account</th><th class="h-teal">Profile</th><th class="h-teal">Env</th>
                <th class="h-adobe">Loaded</th><th class="h-adobe">Report Suite</th><th class="h-adobe">Page View</th>
            </tr>
        `;
    } else {
        head.innerHTML = `
            <tr>
                <th rowspan="2">#</th><th rowspan="2">URL</th>
                <th colspan="2" class="h-adobe" style="text-align:center; background:rgba(255,255,255,0.05)">GTM</th>
                <th colspan="3" class="h-adobe" style="text-align:center; background: rgba(59, 130, 246, 0.15); color: #60a5fa;">GA4</th>
            </tr>
            <tr>
                <th style="background:rgba(255,255,255,0.03)">Loaded</th><th style="background:rgba(255,255,255,0.03)">GTM ID</th>
                <th class="h-adobe" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa;">Fired</th>
                <th class="h-adobe" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa;">Measurement ID</th>
                <th class="h-adobe" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa;">Page View</th>
            </tr>
        `;
    }

    if (!cachedResults.length) {
        const ec = currentAuditMode === 'pixels' ? 6 : (currentAuditMode === 'tealium' ? 9 : 7);
        body.innerHTML = `<tr><td colspan="${ec}" class="empty-msg">Upload a file and run validation</td></tr>`;
        statsBar.classList.add('hidden');
        return;
    }

    let st = { teal: 0, adobe: 0, ga4: 0, compliant: 0, violations: 0 };
    cachedResults.forEach(r => {
        if (r.Tealium_Loaded === 'PASS') st.teal++;
        if (r.Adobe_Loaded === 'PASS') st.adobe++;
        if (r.GA4_Fired === 'PASS') st.ga4++;
        if (r.Compliance === 'PASS') st.compliant++;
        if (r.Compliance === 'FAIL') st.violations++;
    });

    statsBar.classList.remove('hidden');
    if (currentAuditMode === 'pixels') {
        const fires = cachedResults.reduce((a, r) => a + (Number(r[currentScenario + '_Count']) || 0), 0);
        statsBar.innerHTML = `
            <div class="stat"><div class="stat-dot" style="background:#60a5fa;color:#60a5fa;"></div><div><div class="stat-val" style="color:#93c5fd;">${fires}</div><div class="stat-lbl">Pixel Fires · ${currentScenario}</div></div></div>
            <div class="stat"><div class="stat-dot dot-teal"></div><div><div class="stat-val val-teal">${st.compliant}/${cachedResults.length}</div><div class="stat-lbl">Compliant (no pixels w/o consent)</div></div></div>
            <div class="stat"><div class="stat-dot" style="background:#ef4444;color:#ef4444;"></div><div><div class="stat-val" style="color:#f87171;">${st.violations}/${cachedResults.length}</div><div class="stat-lbl">Violations (pixels on Necessary)</div></div></div>
        `;
    } else if (currentAuditMode === 'tealium') {
        statsBar.innerHTML = `<div class="stat"><div class="stat-dot dot-teal"></div><div><div class="stat-val val-teal">${st.teal}/${cachedResults.length}</div><div class="stat-lbl">Tealium Detected</div></div></div>`;
    } else {
        statsBar.innerHTML = `
            <div class="stat"><div class="stat-dot dot-adobe"></div><div><div class="stat-val val-adobe">${st.adobe}/${cachedResults.length}</div><div class="stat-lbl">Adobe Detected</div></div></div>
            <div class="stat"><div class="stat-dot" style="background:#60a5fa; color:#60a5fa;"></div><div><div class="stat-val" style="color:#93c5fd;">${st.ga4}/${cachedResults.length}</div><div class="stat-lbl">GA4 Detected</div></div></div>
        `;
    }

    const PIX = v => (!v || v === 'None')
        ? '<span style="color:#64748b">None</span>'
        : '<span class="mono" style="white-space:normal">' + v + '</span>';

    if (currentAuditMode === 'pixels') {
        const richByUrl = {};
        richResults.forEach(x => { richByUrl[x.URL] = x; });
        let html = '';
        cachedResults.forEach((r, i) => {
            const rich = richByUrl[r.URL];
            const px = (rich && rich.scenarios && rich.scenarios[currentScenario]) || [];
            const comp = `<td style="text-align:center" ${px.length ? `rowspan="${px.length}"` : ''}>${B(r.Compliance)}</td>`;
            if (!px.length) {
                html += `<tr><td>${i + 1}</td><td class="url-col" title="${r.URL}">${r.URL}</td>
                    <td colspan="3" style="color:#64748b">No marketing pixels fired</td>${comp}</tr>`;
            } else {
                px.forEach((p, j) => {
                    html += `<tr>
                        ${j === 0 ? `<td rowspan="${px.length}">${i + 1}</td>
                          <td rowspan="${px.length}" class="url-col" title="${r.URL}">${r.URL}</td>` : ''}
                        <td><b>${p.name}</b></td>
                        <td><span class="badge b-count">${p.count}</span></td>
                        <td>${(p.sources || []).map(srcChip).join(' ')}</td>
                        ${j === 0 ? comp : ''}</tr>`;
                });
            }
        });
        body.innerHTML = html;
        return;
    }

    body.innerHTML = cachedResults.map((r, i) => {
        if (currentAuditMode === 'tealium') {
            return `<tr>
                <td>${i + 1}</td>
                <td class="url-col" title="${r.URL}">${r.URL}</td>
                <td>${B(r.Tealium_Loaded)}</td>
                <td>${ID(r.Tealium_Account)}</td>
                <td>${ID(r.Tealium_Profile)}</td>
                <td>${ID(r.Tealium_Env)}</td>
                <td>${B(r.Adobe_Loaded)}</td>
                <td>${ID(r.Adobe_ReportSuite)}</td>
                <td>${B(r.Adobe_PageView)}</td>
            </tr>`;
        } else {
            return `<tr>
                <td>${i + 1}</td>
                <td class="url-col" title="${r.URL}">${r.URL}</td>
                <td>${B(r.GTM_Loaded)}</td>
                <td>${ID(r.GTM_ID)}</td>
                <td>${B(r.GA4_Fired)}</td>
                <td>${ID(r.GA4_Measurement_ID)}</td>
                <td>${B(r.GA4_PageView)}</td>
            </tr>`;
        }
    }).join('');
}

async function loadSchedules() {
    const r = await fetch('/api/schedule/list');
    const d = await r.json();
    const tbody = document.getElementById('schedulesBody');
    if (!d.schedules || !d.schedules.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">No active schedules</td></tr>';
        return;
    }

    tbody.innerHTML = d.schedules.map(s => `
        <tr>
            <td class="mono">${s.id.substring(0,8)}</td>
            <td>${s.filename}</td>
            <td><span class="badge b-pass" style="background:rgba(139,92,246,0.1);color:#a78bfa;border-color:rgba(139,92,246,0.3);">${s.frequency}</span></td>
            <td>${s.email ? s.email : '<span style="color:#64748b">—</span>'}</td>
            <td>${new Date(s.createdAt).toLocaleString()}</td>
            <td>${s.lastRun ? new Date(s.lastRun).toLocaleString() : 'Never'}</td>
            <td style="white-space:normal;max-width:220px;font-size:0.7rem;color:#94a3b8">${s.lastStatus || '—'}</td>
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
