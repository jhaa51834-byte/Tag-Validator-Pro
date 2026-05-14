const express = require('express');
const path = require('path');
const fs = require('fs');
const multer = require('multer');
const XLSX = require('xlsx');
const { spawn } = require('child_process');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 4000;


app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Multer setup
const upload = multer({ dest: 'uploads/' });

app.post('/api/tag-validator/upload', upload.single('file'), (req, res) => {
    if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
    const targetPath = path.join(__dirname, 'input_sites.xlsx');
    fs.copyFileSync(req.file.path, targetPath);
    res.json({ success: true });
});

let validatorProcess = null;
let validatorLogs = [];

app.post('/api/tag-validator/run', (req, res) => {
    if (validatorProcess) return res.status(400).json({ error: 'Running' });
    validatorLogs = ["Starting..."];
    const pyCmd = process.platform === 'win32' ? 'python' : 'python3';
    validatorProcess = spawn(pyCmd, ['-u', 'bulk_tag_validator.py'], { cwd: __dirname });


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

app.listen(PORT, () => console.log(`Tag Validator running at http://localhost:${PORT}`));
