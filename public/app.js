let currentMode = 'tealium';
let cachedResults = [];

function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === mode);
    });
    renderTable();
}

document.addEventListener('DOMContentLoaded', () => {
    const uploadBox = document.getElementById('uploadBox');
    const fileInput = document.getElementById('fileInput');
    const uploadText = document.getElementById('uploadText');
    const runBtn = document.getElementById('runBtn');
    const logBox = document.getElementById('logBox');
    const downloadBtn = document.getElementById('downloadBtn');

    uploadBox.onclick = () => fileInput.click();
    fileInput.onchange = async (e) => {
        if (!e.target.files.length) return;
        const f = e.target.files[0];
        uploadText.innerText = 'Uploading...';
        const fd = new FormData();
        fd.append('file', f);
        const r = await fetch('/api/tag-validator/upload', { method: 'POST', body: fd });
        if (r.ok) {
            uploadText.innerHTML = '<span class="ready">' + f.name + '</span>';
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
                    document.getElementById('percentLabel').innerText = pct + '%';
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

    // Initial render
    renderTable();
});

const B = v => v === 'PASS'
    ? '<span class="badge b-pass">PASS</span>'
    : '<span class="badge b-fail">FAIL</span>';

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
    const head = document.getElementById('tableHead');
    const body = document.getElementById('resultsBody');
    const statsBar = document.getElementById('statsBar');

    if (currentMode === 'tealium') {
        head.innerHTML = `
            <tr>
                <th rowspan="2">#</th>
                <th rowspan="2">URL</th>
                <th colspan="5" class="h-teal" style="text-align:center;">TEALIUM</th>
                <th colspan="3" class="h-adobe" style="text-align:center;">ADOBE ANALYTICS</th>
            </tr>
            <tr>
                <th class="h-teal">Loaded</th><th class="h-teal">Account</th><th class="h-teal">Profile</th><th class="h-teal">Env</th><th class="h-teal">View Tag</th>
                <th class="h-adobe">Loaded</th><th class="h-adobe">Report Suite</th><th class="h-adobe">Page View</th>
            </tr>`;
    } else {
        head.innerHTML = `
            <tr>
                <th rowspan="2">#</th>
                <th rowspan="2">URL</th>
                <th colspan="2" class="h-gtm" style="text-align:center;">GTM</th>
                <th colspan="3" class="h-ga4" style="text-align:center;">GA4</th>
            </tr>
            <tr>
                <th class="h-gtm">Loaded</th><th class="h-gtm">Container ID</th>
                <th class="h-ga4">Fired</th><th class="h-ga4">Measurement ID</th><th class="h-ga4">Page View</th>
            </tr>`;
    }

    if (!cachedResults.length) {
        body.innerHTML = '<tr><td colspan="10" class="empty-msg">Upload a file and run validation</td></tr>';
        statsBar.classList.add('hidden');
        return;
    }

    // Stats
    let st = { teal: 0, gtm: 0, ga4: 0, adobe: 0 };
    cachedResults.forEach(r => {
        if (r.Tealium_Loaded === 'PASS') st.teal++;
        if (r.GTM_Loaded === 'PASS') st.gtm++;
        if (r.GA4_Fired === 'PASS') st.ga4++;
        if (r.Adobe_Loaded === 'PASS') st.adobe++;
    });

    statsBar.classList.remove('hidden');
    if (currentMode === 'tealium') {
        statsBar.innerHTML = `
            <div class="stat"><div class="stat-dot dot-teal"></div><div><div class="stat-val val-teal">${st.teal}/${cachedResults.length}</div><div class="stat-lbl">Tealium Loaded</div></div></div>
            <div class="stat"><div class="stat-dot dot-adobe"></div><div><div class="stat-val val-adobe">${st.adobe}/${cachedResults.length}</div><div class="stat-lbl">Adobe Loaded</div></div></div>
        `;
    } else {
        statsBar.innerHTML = `
            <div class="stat"><div class="stat-dot dot-gtm"></div><div><div class="stat-val val-gtm">${st.gtm}/${cachedResults.length}</div><div class="stat-lbl">GTM Loaded</div></div></div>
            <div class="stat"><div class="stat-dot dot-ga4"></div><div><div class="stat-val val-ga4">${st.ga4}/${cachedResults.length}</div><div class="stat-lbl">GA4 Fired</div></div></div>
        `;
    }

    document.getElementById('totalCount').innerText = cachedResults.length + ' sites';

    // Table rows
    if (currentMode === 'tealium') {
        body.innerHTML = cachedResults.map((r, i) => `<tr>
            <td>${i + 1}</td>
            <td class="url-col" title="${r.URL}">${r.URL}</td>
            <td>${B(r.Tealium_Loaded)}</td>
            <td>${ID(r.Tealium_Account)}</td>
            <td>${ID(r.Tealium_Profile)}</td>
            <td>${ID(r.Tealium_Env)}</td>
            <td>${B(r.Tealium_View_Fired)}</td>
            <td>${B(r.Adobe_Loaded)}</td>
            <td>${ID(r.Adobe_ReportSuite)}</td>
            <td>${B(r.Adobe_PageView)}</td>
        </tr>`).join('');
    } else {
        body.innerHTML = cachedResults.map((r, i) => `<tr>
            <td>${i + 1}</td>
            <td class="url-col" title="${r.URL}">${r.URL}</td>
            <td>${B(r.GTM_Loaded)}</td>
            <td>${ID(r.GTM_ID)}</td>
            <td>${B(r.GA4_Fired)}</td>
            <td>${ID(r.GA4_Measurement_ID)}</td>
            <td>${B(r.GA4_PageView)}</td>
        </tr>`).join('');
    }
}
