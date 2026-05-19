const express = require('express');
const path = require('path');
const fs = require('fs');
const multer = require('multer');
const XLSX = require('xlsx');
const { spawn } = require('child_process');
const cors = require('cors');
const cron = require('node-cron');
const { v4: uuidv4 } = require('uuid');
const nodemailer = require('nodemailer');

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const UPLOADS_DIR = path.join(__dirname, 'uploads');
const HISTORY_DIR = path.join(__dirname, 'history');
const SCHEDULES_FILE = path.join(__dirname, 'schedules.json');

if (!fs.existsSync(UPLOADS_DIR)) fs.mkdirSync(UPLOADS_DIR);
if (!fs.existsSync(HISTORY_DIR)) fs.mkdirSync(HISTORY_DIR);
if (!fs.existsSync(SCHEDULES_FILE)) fs.writeFileSync(SCHEDULES_FILE, JSON.stringify([]));

const upload = multer({ dest: 'uploads/' });

// --- Manual Run Logic ---
let validatorProcess = null;
let validatorLogs = [];

app.post('/api/tag-validator/upload', upload.single('file'), (req, res) => {
    if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
    const targetPath = path.join(__dirname, 'input_sites.xlsx');
    fs.copyFileSync(req.file.path, targetPath);
    res.json({ success: true, originalName: req.file.originalname });
});

app.post('/api/tag-validator/run', (req, res) => {
    if (validatorProcess) return res.status(400).json({ error: 'Running' });
    const mode = req.body.mode || 'tealium'; // Default to tealium if not specified
    validatorLogs = [`Starting Manual Run (${mode.toUpperCase()} MODE)...` ];
    const pyCmd = process.platform === 'win32' ? 'python' : 'python3';
    validatorProcess = spawn(pyCmd, ['-u', 'bulk_tag_validator.py', '--mode', mode], { cwd: __dirname });

    validatorProcess.stdout.on('data', d => validatorLogs.push(d.toString().trim()));
    validatorProcess.stderr.on('data', d => validatorLogs.push("ERROR: " + d.toString().trim()));
    validatorProcess.on('close', code => {
        validatorLogs.push(`Finished with code ${code}`);
        validatorProcess = null;
    });
    res.json({ success: true });
});

app.get('/api/tag-validator/status', (req, res) => {
    res.json({ running: !!validatorProcess, logs: validatorLogs.slice(-20) });
});

app.get('/api/tag-validator/results', (req, res) => {
    const p = path.join(__dirname, 'validation_results.xlsx');
    if (!fs.existsSync(p)) return res.json({ results: [] });
    const wb = XLSX.readFile(p);
    res.json({ results: XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]]) });
});

app.get('/api/tag-validator/download', (req, res) => {
    const p = path.join(__dirname, 'validation_results.xlsx');
    res.download(p, 'Results.xlsx');
});

// Rich per-scenario pixel data (source attribution) for the Pixels view
app.get('/api/tag-validator/results-rich', (req, res) => {
    const p = path.join(__dirname, 'validation_results.json');
    if (!fs.existsSync(p)) return res.json({ results: [], scenarios: [] });
    try {
        const d = JSON.parse(fs.readFileSync(p, 'utf8'));
        res.json({ results: d.results || [], scenarios: d.scenarios || [] });
    } catch {
        res.json({ results: [], scenarios: [] });
    }
});

// --- Email alerts ---
function mailerReady() {
    return !!(process.env.GMAIL_USER && process.env.GMAIL_APP_PASSWORD);
}

function analyzeFailures() {
    const p = path.join(__dirname, 'validation_results.xlsx');
    if (!fs.existsSync(p)) return { failed: [], total: 0 };
    const wb = XLSX.readFile(p);
    const rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]]);
    const failed = [];
    for (const r of rows) {
        const reasons = [];
        if (r.Error) reasons.push(String(r.Error));
        const passKeys = ['Tealium_Loaded', 'Adobe_Loaded', 'GTM_Loaded', 'GA4_Fired'];
        const present = passKeys.filter(k => k in r);
        if (present.length && !present.some(k => r[k] === 'PASS'))
            reasons.push('No analytics tag detected');
        if (r.Compliance === 'FAIL')
            reasons.push('Consent violation: pixels fired without consent');
        if (reasons.length) failed.push({ url: r.URL, reasons });
    }
    return { failed, total: rows.length };
}

async function sendAlertEmail(recipients, label) {
    if (!mailerReady()) throw new Error('GMAIL_USER / GMAIL_APP_PASSWORD env not set');
    if (!recipients) throw new Error('No recipient email configured');
    const { failed, total } = analyzeFailures();
    const ok = total - failed.length;
    const when = new Date().toLocaleString();
    const rows = failed.length
        ? failed.map(f => `<tr><td style="padding:6px 10px;border:1px solid #ddd">${f.url}</td>` +
            `<td style="padding:6px 10px;border:1px solid #ddd;color:#b91c1c">${f.reasons.join('<br>')}</td></tr>`).join('')
        : `<tr><td colspan="2" style="padding:10px;color:#16a34a">All sites passed.</td></tr>`;
    const html = `
      <div style="font-family:Arial,sans-serif;color:#1e293b">
        <h2 style="margin:0 0 4px">Tag Validation — Scheduled Run Complete</h2>
        <p style="color:#64748b;margin:0 0 6px">${label || ''} · ${when}</p>
        <p><b>Total:</b> ${total} &nbsp;|&nbsp; <b style="color:#16a34a">Passed:</b> ${ok}
           &nbsp;|&nbsp; <b style="color:#b91c1c">Failed:</b> ${failed.length}</p>
        <h3 style="margin:14px 0 6px">Failed Websites</h3>
        <table style="border-collapse:collapse;font-size:13px">
          <tr style="background:#f1f5f9">
            <th style="padding:6px 10px;border:1px solid #ddd;text-align:left">Website</th>
            <th style="padding:6px 10px;border:1px solid #ddd;text-align:left">Reason</th></tr>
          ${rows}
        </table>
        <p style="color:#94a3b8;font-size:12px;margin-top:16px">Full report attached.</p>
      </div>`;
    const xlsxPath = path.join(__dirname, 'validation_results.xlsx');
    const transport = nodemailer.createTransport({
        service: 'gmail',
        auth: { user: process.env.GMAIL_USER, pass: process.env.GMAIL_APP_PASSWORD },
    });
    await transport.sendMail({
        from: process.env.GMAIL_USER,
        to: recipients,
        subject: `[Tag Validator] Run complete — ${failed.length} failed of ${total}`,
        html,
        attachments: fs.existsSync(xlsxPath)
            ? [{ filename: 'Tag-Validation-Report.xlsx', path: xlsxPath }] : [],
    });
    return { total, failed: failed.length };
}

app.get('/api/mailer-status', (req, res) => res.json({ mailerReady: mailerReady() }));

app.post('/api/test-email', async (req, res) => {
    try {
        const r = await sendAlertEmail((req.body && req.body.email), 'Manual test');
        res.json({ success: true, message: `Test email sent (${r.failed} failed / ${r.total})` });
    } catch (e) {
        res.status(400).json({ error: e.message });
    }
});

// --- Scheduling Logic ---
const activeCronJobs = {};

function getSchedules() {
    try {
        return JSON.parse(fs.readFileSync(SCHEDULES_FILE, 'utf8'));
    } catch {
        return [];
    }
}

function saveSchedules(data) {
    fs.writeFileSync(SCHEDULES_FILE, JSON.stringify(data, null, 2));
}

function getCronExpression(frequency) {
    switch (frequency) {
        case 'hourly': return '0 * * * *';
        case 'daily': return '0 0 * * *';
        case 'weekly': return '0 0 * * 0';
        case 'monthly': return '0 0 1 * *';
        case 'every_minute': return '* * * * *'; // For testing
        default: return '0 0 * * *';
    }
}

function executeScheduledJob(schedule) {
    console.log(`[Scheduler] Executing job ${schedule.id} (${schedule.filename})`);
    
    // Copy the scheduled input file to the main input file location
    const inputPath = path.join(__dirname, 'input_sites.xlsx');
    if (fs.existsSync(schedule.filePath)) {
        fs.copyFileSync(schedule.filePath, inputPath);
    } else {
        console.log(`[Scheduler] File missing for job ${schedule.id}`);
        return;
    }

    const pyCmd = process.platform === 'win32' ? 'python' : 'python3';
    const proc = spawn(pyCmd, ['-u', 'bulk_tag_validator.py'], { cwd: __dirname });
    
    proc.on('close', code => {
        console.log(`[Scheduler] Job ${schedule.id} finished with code ${code}`);
        const resultFile = path.join(__dirname, 'validation_results.xlsx');
        if (fs.existsSync(resultFile)) {
            const dateStr = new Date().toISOString().replace(/[:.]/g, '-');
            const historyName = `Schedule_${schedule.id.substring(0, 4)}_${dateStr}.xlsx`;
            const historyPath = path.join(HISTORY_DIR, historyName);
            fs.copyFileSync(resultFile, historyPath);
            
            // Update last run time + send the alert email
            const schedules = getSchedules();
            const idx = schedules.findIndex(s => s.id === schedule.id);
            const recipient = (idx !== -1 ? schedules[idx].email : schedule.email) || '';
            if (recipient && mailerReady()) {
                sendAlertEmail(recipient, `Schedule ${schedule.id.substring(0, 4)} (${schedule.filename})`)
                    .then(r => {
                        if (idx !== -1) schedules[idx].lastStatus =
                            `Emailed ${recipient} — ${r.failed} failed / ${r.total}`;
                        if (idx !== -1) saveSchedules(schedules);
                    })
                    .catch(e => {
                        if (idx !== -1) { schedules[idx].lastStatus = 'Email failed: ' + e.message; saveSchedules(schedules); }
                        console.log('[Scheduler] Email error:', e.message);
                    });
            } else if (recipient) {
                if (idx !== -1) schedules[idx].lastStatus = 'Email skipped: GMAIL env not set';
                console.log('[Scheduler] Email skipped: GMAIL_USER/GMAIL_APP_PASSWORD not set');
            }
            if (idx !== -1) {
                schedules[idx].lastRun = new Date().toISOString();
                saveSchedules(schedules);
            }
        }
    });
}

function initCronJobs() {
    const schedules = getSchedules();
    schedules.forEach(schedule => {
        const expr = getCronExpression(schedule.frequency);
        if (cron.validate(expr)) {
            const job = cron.schedule(expr, () => executeScheduledJob(schedule));
            activeCronJobs[schedule.id] = job;
        }
    });
    console.log(`[Scheduler] Initialized ${schedules.length} scheduled jobs.`);
}

app.post('/api/schedule/add', upload.single('file'), (req, res) => {
    if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
    const frequency = req.body.frequency || 'daily';
    const email = (req.body.email || '').trim();

    const scheduleId = uuidv4();
    const storedFilePath = path.join(UPLOADS_DIR, `sched_${scheduleId}.xlsx`);
    fs.renameSync(req.file.path, storedFilePath);

    const newSchedule = {
        id: scheduleId,
        filename: req.file.originalname,
        filePath: storedFilePath,
        frequency: frequency,
        email: email,
        createdAt: new Date().toISOString(),
        lastRun: null,
        lastStatus: ''
    };

    const schedules = getSchedules();
    schedules.push(newSchedule);
    saveSchedules(schedules);

    const expr = getCronExpression(frequency);
    const job = cron.schedule(expr, () => executeScheduledJob(newSchedule));
    activeCronJobs[scheduleId] = job;

    res.json({ success: true, schedule: newSchedule });
});

app.get('/api/schedule/list', (req, res) => {
    res.json({ schedules: getSchedules() });
});

app.delete('/api/schedule/cancel/:id', (req, res) => {
    const id = req.params.id;
    if (activeCronJobs[id]) {
        activeCronJobs[id].stop();
        delete activeCronJobs[id];
    }
    const schedules = getSchedules().filter(s => s.id !== id);
    saveSchedules(schedules);
    res.json({ success: true });
});

app.get('/api/schedule/history', (req, res) => {
    const files = fs.readdirSync(HISTORY_DIR).filter(f => f.endsWith('.xlsx'));
    const history = files.map(f => {
        const stats = fs.statSync(path.join(HISTORY_DIR, f));
        return {
            filename: f,
            date: stats.mtime.toISOString(),
            size: stats.size
        };
    }).sort((a, b) => new Date(b.date) - new Date(a.date));
    res.json({ history });
});

app.get('/api/schedule/download/:filename', (req, res) => {
    const p = path.join(HISTORY_DIR, req.params.filename);
    if (fs.existsSync(p)) res.download(p);
    else res.status(404).json({ error: 'Not found' });
});

initCronJobs();

app.listen(PORT, () => console.log(`Tag Validator running at http://localhost:${PORT}`));
