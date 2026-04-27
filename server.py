from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse


BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BASE_DIR / ".env"


def load_dotenv_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        os.environ.setdefault(key, value)


load_dotenv_file(DOTENV_PATH)


SOURCE_ARTIFACT_PATH = BASE_DIR / "index.html"
DEFAULT_DB_PATH = Path(os.environ.get("KOUKU_KINOU_DB", BASE_DIR / "data" / "records.db"))
DEFAULT_SESSION_TTL_MINUTES = int(os.environ.get("KOUKU_KINOU_SESSION_TTL_MINUTES", "480"))
DEFAULT_ALLOWED_NETWORKS = os.environ.get("KOUKU_KINOU_ALLOWED_NETWORKS", "")
DEFAULT_AUTH_MODE = (os.environ.get("KOUKU_KINOU_AUTH_MODE", "password") or "password").strip().lower()
SESSION_COOKIE_NAME = "kouku_kinou_session"
AUTH_STATUS_PLACEHOLDER = "__AUTH_STATUS_HTML__"
DB_TIMEOUT_SECONDS = 30.0
DB_WRITE_LOCK = threading.Lock()

STATE_LINE = "let records = JSON.parse(localStorage.getItem('oralNutritionRecords') || '[]');"
SAVE_DEF = "function saveRecord() {"
SAVE_BLOCK = """records.unshift(record);\n  localStorage.setItem('oralNutritionRecords', JSON.stringify(records));\n  renderHistory();"""
DELETE_DEF = "function deleteRecord(id) {"
DELETE_BLOCK = """records = records.filter(r => r.id !== id);\n  localStorage.setItem('oralNutritionRecords', JSON.stringify(records));\n  renderHistory();"""
LOAD_FIELDS_BLOCK = """  document.getElementById('next_monitor').value = r.nextMonitor || '';\n  if (r.mnaScores) {"""
INIT_BLOCK = """document.getElementById('evalDate').value = new Date().toISOString().split('T')[0];\nrenderHistory();"""
HEADER_TOP_BLOCK = '<div class="header-top">'
AUTH_HEADER_REPLACEMENT = '<div class="header-top" style="justify-content:space-between;gap:12px">'
RESPONSIVE_REPLACEMENT = """/* RESPONSIVE */
    @media (max-width: 900px) {
        .tab-content { padding: 14px; }
        .card { padding: 16px; }
        .header-top {
            flex-wrap: wrap;
            align-items: flex-start;
            gap: 10px;
        }
        .header-top h1 { width: 100%; }
        .form-grid, .form-grid-3 { grid-template-columns: 1fr; }
        .action-bar { flex-direction: column; }
        .action-bar .btn {
            width: 100%;
            justify-content: center;
        }
    }

    @media (max-width: 600px) {
        .header-top { padding: 10px 14px; }
        .header-top h1 { font-size: 15px; }
        .tab-bar { flex-wrap: wrap; }
        .tab-btn { min-width: 50%; }
        .tab-content { padding: 12px; }
        .card { padding: 14px; }
        .toast {
            width: calc(100% - 24px);
            white-space: normal;
            border-radius: 16px;
            padding: 12px 16px;
        }
    }

    /* NOTIFICATION */"""
RENDER_HISTORY_BLOCK = (
    "function renderHistory() {\n"
    "  const tbody = document.getElementById('historyBody');\n"
    "  if (records.length === 0) {\n"
    "    tbody.innerHTML = '<tr><td colspan=\"6\"><div class=\"empty-state\"><div class=\"icon\">📂</div>保存された記録はありません</div></td></tr>';\n"
    "    return;\n"
    "  }\n"
    "  tbody.innerHTML = records.map(r => {\n"
    "    const tagClass = r.mnaLabel === '良好' ? 'tag-good' : r.mnaLabel === 'At risk' ? 'tag-risk' : r.mnaLabel === '低栄養' ? 'tag-bad' : '';\n"
    "    const oralClass = r.oralContinue && r.oralContinue.includes('継続') ? 'tag-risk' : r.oralContinue && r.oralContinue.includes('終了') ? 'tag-good' : '';\n"
    "    return `<tr>\n"
    "      <td>${r.date}</td>\n"
    "      <td><strong>${r.name}</strong><br><small style=\"color:var(--text-light)\">${r.furigana||''}</small></td>\n"
    "      <td><strong>${r.mnaScore !== null ? r.mnaScore + '/14' : '―'}</strong></td>\n"
    "      <td><span class=\"tag ${tagClass}\">${r.mnaLabel}</span></td>\n"
    "      <td><span class=\"tag ${oralClass}\">${r.oralContinue || '―'}</span></td>\n"
    "      <td>\n"
    "        <button class=\"btn btn-outline btn-sm\" onclick=\"loadRecord(${r.id})\">読込</button>\n"
    "        <button class=\"btn btn-danger btn-sm\" style=\"margin-left:4px\" onclick=\"deleteRecord(${r.id})\">削除</button>\n"
    "      </td>\n"
    "    </tr>`;\n"
    "  }).join('');\n"
    "}"
)
RENDER_HISTORY_REPLACEMENT = (
    "function renderHistory() {\n"
    "  ensureHistoryTools();\n"
    "  const tbody = document.getElementById('historyBody');\n"
    "  const filteredRecords = getFilteredRecords();\n"
    "  updateHistoryStats(filteredRecords.length);\n"
    "  renderLatestPatients(filteredRecords);\n"
    "  if (filteredRecords.length === 0) {\n"
    "    const emptyMessage = records.length === 0 ? '保存された記録はありません' : '検索条件に一致する記録はありません';\n"
    "    tbody.innerHTML = `<tr><td colspan=\"6\"><div class=\"empty-state\"><div class=\"icon\">📂</div>${emptyMessage}</div></td></tr>`;\n"
    "    return;\n"
    "  }\n"
    "  tbody.innerHTML = filteredRecords.map((r) => {\n"
    "    const tagClass = r.mnaLabel === '良好' ? 'tag-good' : r.mnaLabel === 'At risk' ? 'tag-risk' : r.mnaLabel === '低栄養' ? 'tag-bad' : '';\n"
    "    const oralClass = r.oralContinue && r.oralContinue.includes('継続') ? 'tag-risk' : r.oralContinue && r.oralContinue.includes('終了') ? 'tag-good' : '';\n"
    "    const identityLine = buildHistoryIdentityLine(r);\n"
    "    const scoreLabel = r.mnaScore !== null && r.mnaScore !== undefined ? `${r.mnaScore}/14` : '―';\n"
    "    return `<tr>\n"
    "      <td>${escapeHtml(r.date || '')}</td>\n"
    "      <td><strong>${escapeHtml(r.name || '')}</strong>${identityLine ? `<br><small style=\"color:var(--text-light)\">${identityLine}</small>` : ''}</td>\n"
    "      <td><strong>${escapeHtml(scoreLabel)}</strong></td>\n"
    "      <td><span class=\"tag ${tagClass}\">${escapeHtml(r.mnaLabel || '―')}</span></td>\n"
    "      <td><span class=\"tag ${oralClass}\">${escapeHtml(r.oralContinue || '―')}</span></td>\n"
    "      <td>\n"
    "        <button class=\"btn btn-outline btn-sm\" onclick=\"loadRecord(${Number(r.id)})\">読込</button>\n"
    "        <button class=\"btn btn-danger btn-sm\" style=\"margin-left:4px\" onclick=\"deleteRecord(${Number(r.id)})\">削除</button>\n"
    "      </td>\n"
    "    </tr>`;\n"
    "  }).join('');\n"
    "}"
)
PRINT_RECORD_BLOCK = (
        "function printRecord() {\n"
        "  updateSummary();\n"
        "  // Show all tabs for print\n"
        "  document.querySelectorAll('.tab-content').forEach(t => t.style.display = 'block');\n"
        "  window.print();\n"
        "  document.querySelectorAll('.tab-content').forEach(t => t.style.display = '');\n"
        "  document.querySelector('.tab-content.active').style.display = 'block';\n"
        "}"
)
PRINT_RECORD_REPLACEMENT = (
        "function printRecord() {\n"
        "  updateSummary();\n"
        "  const reportData = buildPrintReportData();\n"
        "  if (!reportData) {\n"
        "    return;\n"
        "  }\n"
        "  preparePrintSheet(reportData);\n"
        "  document.body.classList.add('print-mode');\n"
        "  requestAnimationFrame(() => {\n"
        "    window.print();\n"
        "    clearPrintMode();\n"
        "  });\n"
        "}"
)
PRINT_CSS_MARKER = "    /* NOTIFICATION */"
PRINT_CSS_APPEND = """  .print-sheet { display: none; }

    @page {
        size: A4 portrait;
        margin: 10mm;
    }

    @media print {
        body:not(.print-mode) .tab-content { display: none !important; }
        body:not(.print-mode) .tab-content.active { display: block !important; padding: 0; }
        body:not(.print-mode) .card { box-shadow: none; break-inside: avoid; }

        body.print-mode > * { display: none !important; }
        body.print-mode > #printSheet { display: block !important; }
        body.print-mode,
        body.print-mode #printSheet {
            background: white !important;
            color: var(--text);
            font-size: 10.5px;
            line-height: 1.45;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }
        body.print-mode #printSheet {
            width: 190mm;
            max-width: 100%;
            margin: 0 auto;
        }
        body.print-mode .print-sheet__page {
            page-break-after: avoid;
        }
        body.print-mode .print-sheet__header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 10px;
            border-bottom: 2px solid var(--primary);
            padding-bottom: 6px;
            margin-bottom: 8px;
        }
        body.print-mode .print-sheet__title {
            font-size: 18px;
            font-weight: 700;
            color: var(--primary);
            margin: 0 0 2px;
        }
        body.print-mode .print-sheet__subtitle,
        body.print-mode .print-sheet__meta {
            font-size: 10px;
            color: var(--text-light);
        }
        body.print-mode .print-sheet__meta { text-align: right; white-space: nowrap; }
        body.print-mode .print-sheet__section {
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 8px 10px;
            margin-bottom: 8px;
            break-inside: avoid;
        }
        body.print-mode .print-sheet__section-title {
            font-size: 12px;
            font-weight: 700;
            color: var(--primary);
            margin: 0 0 6px;
        }
        body.print-mode .print-sheet__info-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 6px;
        }
        body.print-mode .print-sheet__item {
            border: 1px solid #d9e4ee;
            border-radius: 8px;
            padding: 6px 8px;
            background: #fcfdff;
            min-height: 44px;
        }
        body.print-mode .print-sheet__item--wide { grid-column: span 2; }
        body.print-mode .print-sheet__label {
            font-size: 9px;
            color: var(--text-light);
            margin-bottom: 3px;
        }
        body.print-mode .print-sheet__value {
            font-size: 11px;
            font-weight: 600;
            color: var(--text);
            word-break: break-word;
        }
        body.print-mode .print-sheet__metrics {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        body.print-mode .print-sheet__metric-card {
            border-radius: 10px;
            padding: 8px 10px;
            background: var(--section-bg);
            border: 1px solid var(--border);
            min-height: 78px;
        }
        body.print-mode .print-sheet__metric-title {
            font-size: 10px;
            font-weight: 700;
            color: var(--primary);
            margin-bottom: 6px;
        }
        body.print-mode .print-sheet__metric-score {
            font-size: 18px;
            font-weight: 700;
            color: var(--primary);
            line-height: 1.1;
            margin-bottom: 4px;
        }
        body.print-mode .print-sheet__metric-line {
            font-size: 10px;
            margin-bottom: 2px;
            word-break: break-word;
        }
        body.print-mode .print-sheet__note {
            min-height: 36mm;
            max-height: 48mm;
            overflow: hidden;
            white-space: pre-wrap;
            word-break: break-word;
            font-size: 10px;
            line-height: 1.5;
        }
    }

        /* NOTIFICATION */"""

CLIENT_BRIDGE = """
const API_ROOT = '/api/records';
const HISTORY_FILTER_STATE = { query: '' };
let currentMnaFieldMode = '';

async function readJsonIfAvailable(response) {
    const contentType = response.headers.get('Content-Type') || '';
    if (!contentType.includes('application/json')) {
        return null;
    }
    return response.json();
}

async function extractErrorMessage(response, fallbackMessage) {
    const payload = await readJsonIfAvailable(response);
    if (payload && typeof payload.error === 'string' && payload.error) {
        return payload.error;
    }
    if (payload && typeof payload.detail === 'string' && payload.detail) {
        return payload.detail;
    }
    return fallbackMessage;
}

async function fetchRecords() {
    const response = await fetch(API_ROOT, { cache: 'no-store' });
    if (!response.ok) {
        throw new Error(await extractErrorMessage(response, '記録の取得に失敗しました'));
    }
    return response.json();
}

async function persistRecord(record) {
    const response = await fetch(API_ROOT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(record)
    });
    if (!response.ok) {
        throw new Error(await extractErrorMessage(response, '記録の保存に失敗しました'));
    }
    return response.json();
}

async function removeRecord(id) {
    const response = await fetch(`${API_ROOT}/${id}`, { method: 'DELETE' });
    if (!response.ok) {
        throw new Error(await extractErrorMessage(response, '記録の削除に失敗しました'));
    }
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeSearchText(value) {
    return String(value ?? '').trim().replace(/\\s+/g, ' ').toLowerCase();
}

function getSelectedMnaFieldMode() {
    if (document.querySelector('#mna_f2_group input[name="mna_f"]:checked')) {
        return 'f2';
    }
    if (document.querySelector('#mna_f1_group input[name="mna_f"]:checked')) {
        return 'f1';
    }
    return '';
}

function collectFieldValues() {
    const fields = {};
    document.querySelectorAll('input[id], select[id], textarea[id]').forEach((element) => {
        if (element.type === 'radio' || element.type === 'checkbox') {
            return;
        }
        fields[element.id] = element.value;
    });
    return fields;
}

function restoreFieldValues(fields) {
    Object.entries(fields || {}).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (!element) {
            return;
        }
        if (element.type === 'radio' || element.type === 'checkbox') {
            return;
        }
        element.value = value ?? '';
    });
}

function restoreMnaSelections() {
    document.querySelectorAll('.radio-option').forEach((option) => option.classList.remove('selected'));
    document.querySelectorAll('input[type="radio"]').forEach((input) => {
        input.checked = false;
    });

    Object.entries(mnaScores).forEach(([key, value]) => {
        if (value === null || value === undefined) {
            return;
        }

        if (key === 'f') {
            const selector = currentMnaFieldMode === 'f2'
                ? '#mna_f2_group input[name="mna_f"]'
                : '#mna_f1_group input[name="mna_f"]';
            document.querySelectorAll(selector).forEach((input) => {
                if (Number.parseInt(input.value, 10) === value) {
                    input.checked = true;
                    const option = input.closest('.radio-option');
                    if (option) {
                        option.classList.add('selected');
                    }
                }
            });
            return;
        }

        const names = [`mna_${key}`];
        names.forEach((name) => {
            document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
                if (Number.parseInt(input.value, 10) === value) {
                    input.checked = true;
                    const option = input.closest('.radio-option');
                    if (option) {
                        option.classList.add('selected');
                    }
                }
            });
        });
    });
}

function buildHistoryIdentityLine(record) {
    const parts = [];
    if (record.birthdate) {
        parts.push(`生年月日: ${escapeHtml(record.birthdate)}`);
    }
    if (record.furigana) {
        parts.push(escapeHtml(record.furigana));
    }
    return parts.join(' / ');
}

function getRecordPatientKey(record) {
    const explicitKey = String(record.patientKey ?? '').trim();
    if (explicitKey) {
        return explicitKey;
    }

    const normalizedName = normalizeSearchText(record.name);
    const birthdate = String(record.birthdate ?? '').trim();
    return normalizedName && birthdate ? `${normalizedName}::${birthdate}` : '';
}

function countUniquePatients(sourceRecords) {
    const patientKeys = new Set();
    sourceRecords.forEach((record) => {
        const key = getRecordPatientKey(record);
        if (key) {
            patientKeys.add(key);
        }
    });
    return patientKeys.size;
}

function getLatestPatientRecords(filteredRecords) {
    const patientCounts = new Map();
    records.forEach((record) => {
        const key = getRecordPatientKey(record);
        if (!key) {
            return;
        }
        patientCounts.set(key, (patientCounts.get(key) ?? 0) + 1);
    });

    const latestRecords = [];
    const seen = new Set();
    filteredRecords.forEach((record) => {
        const key = getRecordPatientKey(record);
        if (!key || seen.has(key)) {
            return;
        }
        seen.add(key);
        latestRecords.push(record);
    });

    return { latestRecords, patientCounts };
}

function updateLatestPatientsStats(latestCount) {
    const stats = document.getElementById('latestPatientsStats');
    if (!stats) {
        return;
    }

    const totalPatients = countUniquePatients(records);
    const query = normalizeSearchText(HISTORY_FILTER_STATE.query);
    stats.textContent = query ? `${latestCount} / ${totalPatients}名を表示` : `${latestCount}名を表示`;
}

function renderLatestPatients(filteredRecords) {
    const tbody = document.getElementById('latestPatientsBody');
    if (!tbody) {
        return;
    }

    const { latestRecords, patientCounts } = getLatestPatientRecords(filteredRecords);
    updateLatestPatientsStats(latestRecords.length);

    if (latestRecords.length === 0) {
        const emptyMessage = records.length === 0 ? '保存された利用者はありません' : '検索条件に一致する利用者はありません';
        tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="icon">👥</div>${emptyMessage}</div></td></tr>`;
        return;
    }

    tbody.innerHTML = latestRecords.map((record) => {
        const patientKey = getRecordPatientKey(record);
        const tagClass = record.mnaLabel === '良好' ? 'tag-good' : record.mnaLabel === 'At risk' ? 'tag-risk' : record.mnaLabel === '低栄養' ? 'tag-bad' : '';
        const scoreLabel = record.mnaScore !== null && record.mnaScore !== undefined ? `${record.mnaScore}/14` : '―';
        const visitCount = patientCounts.get(patientKey) ?? 1;
        return `<tr>
          <td><strong>${escapeHtml(record.name || '')}</strong>${record.furigana ? `<br><small style="color:var(--text-light)">${escapeHtml(record.furigana)}</small>` : ''}</td>
          <td>${escapeHtml(record.birthdate || '―')}</td>
          <td>${escapeHtml(record.date || '')}</td>
          <td><strong>${escapeHtml(scoreLabel)}</strong></td>
          <td><span class="tag ${tagClass}">${escapeHtml(record.mnaLabel || '―')}</span></td>
          <td>${visitCount}件</td>
          <td><button class="btn btn-outline btn-sm" onclick="loadRecord(${Number(record.id)})">最新を読込</button></td>
        </tr>`;
    }).join('');
}

function getFilteredRecords() {
    const query = normalizeSearchText(HISTORY_FILTER_STATE.query);
    if (!query) {
        return records;
    }

    return records.filter((record) => {
        const candidates = [
            record.name,
            record.furigana,
            record.birthdate,
            record.date,
            record.oralContinue,
            record.mnaLabel,
        ];
        return candidates.some((value) => normalizeSearchText(value).includes(query));
    });
}

function updateHistoryStats(filteredCount) {
    const stats = document.getElementById('historyStats');
    if (!stats) {
        return;
    }

    const query = normalizeSearchText(HISTORY_FILTER_STATE.query);
    stats.textContent = query ? `${filteredCount} / ${records.length}件を表示` : `${records.length}件を表示`;
}

function ensureHistoryTools() {
    const historyTable = document.getElementById('historyTable');
    if (!historyTable || document.getElementById('historySearch')) {
        return;
    }

    const historyWrapper = historyTable.parentElement;
    const historyCard = historyWrapper.parentElement;

    const toolbar = document.createElement('div');
    toolbar.style.display = 'flex';
    toolbar.style.flexWrap = 'wrap';
    toolbar.style.alignItems = 'center';
    toolbar.style.justifyContent = 'space-between';
    toolbar.style.gap = '10px';
    toolbar.style.margin = '0 0 14px';

    toolbar.innerHTML = `
      <label style="display:flex;align-items:center;gap:8px;flex:1 1 280px;min-width:220px;">
        <span style="font-size:13px;color:var(--text-light);white-space:nowrap;">利用者検索</span>
                <input id="historySearch" type="search" placeholder="氏名・ふりがな・生年月日・評価日で検索" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:#fff;font:inherit;">
      </label>
      <div id="historyStats" style="font-size:12px;color:var(--text-light);white-space:nowrap;"></div>
    `;

        const patientPanel = document.createElement('div');
        patientPanel.id = 'latestPatientsPanel';
        patientPanel.style.margin = '0 0 14px';
        patientPanel.innerHTML = `
            <div style="border:1px solid var(--border);border-radius:12px;background:var(--section-bg);padding:14px 14px 10px;">
                <div style="display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:10px;margin-bottom:10px;">
                    <div>
                        <div style="font-size:16px;font-weight:700;color:var(--text);">患者別最新評価</div>
                        <div style="font-size:12px;color:var(--text-light);">同じ利用者ごとに最新の評価日だけをまとめて表示します。</div>
                    </div>
                    <div id="latestPatientsStats" style="font-size:12px;color:var(--text-light);white-space:nowrap;"></div>
                </div>
                <div style="overflow-x:auto;">
                    <table class="history-table" id="latestPatientsTable">
                        <thead>
                            <tr>
                                <th>氏名</th>
                                <th>生年月日</th>
                                <th>最新評価日</th>
                                <th>MNA Score</th>
                                <th>栄養判定</th>
                                <th>評価回数</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody id="latestPatientsBody">
                            <tr><td colspan="7"><div class="empty-state"><div class="icon">👥</div>利用者データを読み込み中です</div></td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        historyCard.insertBefore(toolbar, historyWrapper);
        historyCard.insertBefore(patientPanel, historyWrapper);

    const searchInput = document.getElementById('historySearch');
        searchInput.value = HISTORY_FILTER_STATE.query;
    searchInput.addEventListener('input', (event) => {
        HISTORY_FILTER_STATE.query = event.target.value || '';
        renderHistory();
    });
}

const PRINT_SHEET_ID = 'printSheet';

function getFieldElementValue(id) {
    const element = document.getElementById(id);
    if (!element) {
        return '';
    }
    if ('value' in element) {
        return String(element.value || '');
    }
    return String(element.textContent || '');
}

function formatDisplayValue(value) {
    const text = String(value || '').trim();
    return text || '―';
}

function ensurePrintSheet() {
    let sheet = document.getElementById(PRINT_SHEET_ID);
    if (!sheet) {
        sheet = document.createElement('section');
        sheet.id = PRINT_SHEET_ID;
        sheet.className = 'print-sheet';
        document.body.appendChild(sheet);
    }
    return sheet;
}

function buildPrintItem(label, value, wide = false) {
    const className = wide ? 'print-sheet__item print-sheet__item--wide' : 'print-sheet__item';
    return '<div class="' + className + '"><div class="print-sheet__label">' + escapeHtml(label) + '</div><div class="print-sheet__value">' + escapeHtml(formatDisplayValue(value)) + '</div></div>';
}

function buildPrintReportData() {
    const name = getFieldElementValue('name').trim();
    const birthdate = getFieldElementValue('birthdate').trim();

    if (!name) {
        showToast('⚠️ 氏名を入力してください');
        return null;
    }
    if (!birthdate) {
        showToast('⚠️ 生年月日を入力してください');
        return null;
    }

    return {
        name,
        furigana: getFieldElementValue('furigana'),
        birthdate,
        gender: getFieldElementValue('gender'),
        evalDate: getFieldElementValue('evalDate'),
        staff: getFieldElementValue('staff'),
        dentist: getFieldElementValue('dentist'),
        denture: getFieldElementValue('denture'),
        weight: getFieldElementValue('weight'),
        height: getFieldElementValue('height'),
        bmi: getFieldElementValue('bmi'),
        oralSummary: getFieldElementValue('oral_summary_text'),
        oralContinue: getFieldElementValue('oral_eval2'),
        oralPlan: getFieldElementValue('oral_eval3'),
        mnaScore: getFieldElementValue('mna_summary_num'),
        mnaResult: getFieldElementValue('mna_summary_result'),
        comment: getFieldElementValue('summary_comment'),
        nextMonitor: getFieldElementValue('next_monitor'),
    };
}

function buildPrintMetricLines(values) {
    return values
        .map((value) => String(value || '').trim())
        .filter((value, index, items) => value && items.indexOf(value) === index)
        .map((value) => '<div class="print-sheet__metric-line">' + escapeHtml(value) + '</div>')
        .join('');
}

function buildPrintSheetHtml(report) {
    const headerMeta = [
        report.furigana ? 'ふりがな: ' + formatDisplayValue(report.furigana) : '',
        '生年月日: ' + formatDisplayValue(report.birthdate),
        '評価日: ' + formatDisplayValue(report.evalDate),
    ].filter(Boolean).join(' / ');

    const infoGrid = [
        buildPrintItem('性別', report.gender),
        buildPrintItem('担当者', report.staff),
        buildPrintItem('体重 (kg)', report.weight),
        buildPrintItem('身長 (cm)', report.height),
        buildPrintItem('BMI', report.bmi),
        buildPrintItem('義歯', report.denture),
        buildPrintItem('歯科医', report.dentist, true),
        buildPrintItem('次回モニタリング', report.nextMonitor, true),
    ].join('');

    const oralLines = buildPrintMetricLines([report.oralSummary, report.oralContinue, report.oralPlan]);
    const mnaLines = '<div class="print-sheet__metric-score">' + escapeHtml(formatDisplayValue(report.mnaScore)) + '</div>'
        + '<div class="print-sheet__metric-line">' + escapeHtml(formatDisplayValue(report.mnaResult)) + '</div>';

    return '<div class="print-sheet__page">'
        + '<div class="print-sheet__header">'
        + '<div><div class="print-sheet__title">口腔機能・栄養評価記録</div><div class="print-sheet__subtitle">印刷対象は現在表示中の 1 名分のみです</div></div>'
        + '<div class="print-sheet__meta">' + escapeHtml(formatDisplayValue(headerMeta)) + '</div>'
        + '</div>'
        + '<div class="print-sheet__section">'
        + '<div class="print-sheet__section-title">利用者情報</div>'
        + '<div class="print-sheet__value" style="font-size:16px;color:var(--primary);margin-bottom:6px;">' + escapeHtml(formatDisplayValue(report.name)) + '</div>'
        + '<div class="print-sheet__info-grid">' + infoGrid + '</div>'
        + '</div>'
        + '<div class="print-sheet__metrics">'
        + '<div class="print-sheet__metric-card"><div class="print-sheet__metric-title">口腔機能評価</div>' + (oralLines || '<div class="print-sheet__metric-line">未入力</div>') + '</div>'
        + '<div class="print-sheet__metric-card"><div class="print-sheet__metric-title">MNA-SF</div>' + mnaLines + '</div>'
        + '</div>'
        + '<div class="print-sheet__section">'
        + '<div class="print-sheet__section-title">コメント・支援方針</div>'
        + '<div class="print-sheet__note">' + escapeHtml(formatDisplayValue(report.comment)) + '</div>'
        + '</div>'
        + '</div>';
}

function preparePrintSheet(report) {
    const sheet = ensurePrintSheet();
    sheet.innerHTML = buildPrintSheetHtml(report);
}

function clearPrintMode() {
    document.body.classList.remove('print-mode');
}

window.addEventListener('afterprint', clearPrintMode);

async function initializeApp() {
    ensureHistoryTools();
    try {
        records = await fetchRecords();
    } catch (error) {
        console.error(error);
        showToast(error.message || '同期に失敗しました');
    }
    renderHistory();
}
""".strip()

MNA_RESTORE_PATTERN = re.compile(
    r"\s+// Re-render MNA selections\n\s+\['a','b','c','d','e'\]\.forEach\(k => \{.*?\n\s+calcMNAScore\(\);",
    re.S,
)
RESPONSIVE_PATTERN = re.compile(
    r"/\* RESPONSIVE \*/\s*@media \(max-width: 600px\) \{\s*\.form-grid, \.form-grid-3 \{ grid-template-columns: 1fr; \}\s*\.header-top h1 \{ font-size: 15px; \}\s*\}\s*/\* NOTIFICATION \*/",
    re.S,
)


Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(slots=True)
class AuthConfig:
    enabled: bool
    mode: str
    password: str | None
    secure_cookie: bool
    session_ttl_minutes: int
    allowed_networks: list[Network]
    trust_proxy: bool


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"Expected snippet not found: {old[:60]}")
    return text.replace(old, new, 1)


def extract_embedded_html(wrapper_html: str) -> str:
    start = wrapper_html.find(r"\u003c!DOCTYPE html\u003e")
    if start == -1:
        raise RuntimeError("Embedded artifact start marker not found")

    end = wrapper_html.find('"])</script><script', start)
    if end == -1:
        raise RuntimeError("Embedded artifact end marker not found")

    raw = wrapper_html[start:end]
    return json.loads(f'"{raw}"')


def transform_client_html(
    html: str,
    auth_enabled: bool = False,
    auth_status_html: str | None = None,
) -> str:
    html = replace_once(
        html,
        STATE_LINE,
        "let records = [];\n\n" + CLIENT_BRIDGE,
    )
    html = replace_once(html, SAVE_DEF, "async function saveRecord() {")
    html = replace_once(
        html,
        SAVE_BLOCK,
        """record.fields = collectFieldValues();
    record.mnaFieldMode = getSelectedMnaFieldMode();
    if (!record.fields.birthdate) {
        showToast('⚠️ 生年月日を入力してください');
        return;
    }
    let savedRecord;
  try {
        savedRecord = await persistRecord(record);
    records = await fetchRecords();
    renderHistory();
  } catch (error) {
    console.error(error);
        showToast(error.message || '同期に失敗しました');
    return;
    }
    showToast(savedRecord.saveMode === 'updated' ? '♻️ 同一利用者・同一評価日の記録を更新しました' : '💾 記録を保存しました');""",
    )
    html = replace_once(html, DELETE_DEF, "async function deleteRecord(id) {")
    html = replace_once(
        html,
        DELETE_BLOCK,
        """try {
    await removeRecord(id);
    records = await fetchRecords();
    renderHistory();
  } catch (error) {
    console.error(error);
    showToast('削除の同期に失敗しました');
    return;
  }""",
    )
    html = replace_once(
        html,
        LOAD_FIELDS_BLOCK,
                """  document.getElementById('next_monitor').value = r.nextMonitor || '';
    currentMnaFieldMode = '';
    mnaScores = { a: null, b: null, c: null, d: null, e: null, f: null };
    restoreMnaSelections();
    calcMNAScore();
  restoreFieldValues(r.fields);
    updateSummary();
    currentMnaFieldMode = r.mnaFieldMode || '';
  if (r.mnaScores) {""",
    )

    html, count = MNA_RESTORE_PATTERN.subn(
        """
    restoreMnaSelections();
    calcMNAScore();
    updateSummary();""",
        html,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Expected MNA restore block not found")

    html = replace_once(html, INIT_BLOCK, """document.getElementById('evalDate').value = new Date().toISOString().split('T')[0];
initializeApp();""")
    html, count = RESPONSIVE_PATTERN.subn(RESPONSIVE_REPLACEMENT, html, count=1)
    if count != 1:
        raise RuntimeError("Expected responsive block not found")
    html = replace_once(html, PRINT_CSS_MARKER, PRINT_CSS_APPEND)
    html = replace_once(html, RENDER_HISTORY_BLOCK, RENDER_HISTORY_REPLACEMENT)
    html = replace_once(html, PRINT_RECORD_BLOCK, PRINT_RECORD_REPLACEMENT)
    if auth_enabled:
        html = replace_once(html, HEADER_TOP_BLOCK, AUTH_HEADER_REPLACEMENT)
        html = replace_once(
            html,
            '<span class="badge">Ver 1.0</span>',
            auth_status_html
            or '<div style="display:flex;align-items:center;gap:8px"><span class="badge">Ver 1.0</span><a href="/logout" class="badge" style="text-decoration:none;background:#fff1ea;color:#8a3b21">ログアウト</a></div>',
        )
    return html


def build_client_template(auth_enabled: bool = False) -> str:
    wrapper_html = SOURCE_ARTIFACT_PATH.read_text(encoding="utf-8")
    embedded_html = extract_embedded_html(wrapper_html)
    return transform_client_html(
        embedded_html,
        auth_enabled=auth_enabled,
        auth_status_html=AUTH_STATUS_PLACEHOLDER if auth_enabled else None,
    )


def render_client_html(client_template: str, auth_status_html: str | None = None) -> str:
    if AUTH_STATUS_PLACEHOLDER not in client_template:
        return client_template
    return client_template.replace(AUTH_STATUS_PLACEHOLDER, auth_status_html or '<span class="badge">Ver 1.0</span>')


def prepare_client_templates() -> dict[str, str]:
    return {
        "public": build_client_template(auth_enabled=False),
        "auth": build_client_template(auth_enabled=True),
    }


def build_client_html(
    auth_enabled: bool = False,
    auth_status_html: str | None = None,
) -> str:
    template = build_client_template(auth_enabled=auth_enabled)
    return render_client_html(template, auth_status_html=auth_status_html)


def build_login_html(
    error_message: str | None = None,
    next_target: str = "/",
    description: str | None = None,
    hint: str | None = None,
) -> str:
    message_html = ""
    if error_message:
        message_html = f'<p style="margin:0 0 16px;color:#9f2f1c;background:#fff0ec;border:1px solid #f3c6b8;border-radius:10px;padding:12px 14px">{escape(error_message)}</p>'

    next_value = escape(next_target, quote=True)
    description_html = escape(description or "NAS 上で共有運用するため、ログイン後に記録画面へ入る構成にしています。")
    hint_html = escape(hint or "パスワードは環境変数 KOUKU_KINOU_PASSWORD で設定します。")
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ログイン | 口腔機能・栄養評価システム</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f2ea;
      --panel: #fffdf9;
      --border: #e7d7c4;
      --text: #3f3024;
      --muted: #6f5b4c;
      --accent: #c76b3c;
      --accent-dark: #a8542a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
      background: radial-gradient(circle at top, #fff7ef 0, var(--bg) 52%, #efe3d4 100%);
      color: var(--text);
      display: grid;
      place-items: center;
      padding: 24px;
    }}
    .panel {{
      width: min(420px, 100%);
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow: 0 22px 50px rgba(81, 52, 32, 0.12);
      padding: 28px;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      background: #fff3e5;
      color: var(--accent-dark);
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 14px;
    }}
    h1 {{ margin: 0 0 10px; font-size: 28px; line-height: 1.3; }}
    p {{ margin: 0 0 20px; color: var(--muted); line-height: 1.6; }}
    label {{ display: block; font-size: 14px; font-weight: 700; margin-bottom: 8px; }}
    input {{
      width: 100%;
      padding: 14px 16px;
      border-radius: 12px;
      border: 1px solid var(--border);
      font: inherit;
      background: #fff;
    }}
    button {{
      width: 100%;
      margin-top: 18px;
      border: 0;
      border-radius: 12px;
      padding: 14px 18px;
      font: inherit;
      font-weight: 700;
      color: #fff;
      background: linear-gradient(135deg, var(--accent), var(--accent-dark));
      cursor: pointer;
    }}
    button:hover {{ filter: brightness(1.03); }}
    .hint {{ margin-top: 14px; font-size: 12px; color: var(--muted); }}
  </style>
</head>
<body>
  <section class="panel">
    <div class="eyebrow">認証が必要です</div>
    <h1>口腔機能・栄養評価システム</h1>
        <p>{description_html}</p>
    {message_html}
    <form method="post" action="/login">
      <input type="hidden" name="next" value="{next_value}">
      <label for="password">パスワード</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">ログイン</button>
    </form>
        <div class="hint">{hint_html}</div>
  </section>
</body>
</html>
"""


def build_message_html(title: str, message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(title)}</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#f7f2ea; color:#3f3024; font-family:"Yu Gothic UI", sans-serif; padding:24px; }}
    main {{ max-width:420px; background:#fffdf9; border:1px solid #e7d7c4; border-radius:18px; padding:28px; box-shadow:0 18px 40px rgba(81, 52, 32, 0.1); }}
    h1 {{ margin:0 0 10px; font-size:28px; }}
    p {{ margin:0; line-height:1.7; color:#6f5b4c; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(title)}</h1>
    <p>{escape(message)}</p>
  </main>
</body>
</html>
"""


def parse_allowed_networks(raw_items: list[str]) -> list[Network]:
    networks: list[Network] = []
    for raw_item in raw_items:
        for item in raw_item.split(","):
            candidate = item.strip()
            if not candidate:
                continue
            networks.append(ipaddress.ip_network(candidate, strict=False))
    return networks


def build_auth_config(args: argparse.Namespace) -> AuthConfig:
    env_allowed_networks = [DEFAULT_ALLOWED_NETWORKS] if DEFAULT_ALLOWED_NETWORKS else []
    allowed_networks = parse_allowed_networks(env_allowed_networks + args.allowed_networks)

    valid_modes = {"password", "tailscale", "tailscale-or-password"}
    auth_mode = (args.auth_mode or "password").strip().lower()
    if auth_mode not in valid_modes:
        valid_values = ", ".join(sorted(valid_modes))
        raise SystemExit(f"Unsupported auth mode: {auth_mode}. Use one of: {valid_values}")

    enabled = not args.no_auth
    password = args.password
    if enabled and auth_mode in {"password", "tailscale-or-password"} and not password:
        raise SystemExit(
            "Authentication is enabled. Set KOUKU_KINOU_PASSWORD or pass --password, or start with --no-auth."
        )

    return AuthConfig(
        enabled=enabled,
        mode=auth_mode if enabled else "none",
        password=password,
        secure_cookie=args.secure_cookie,
        session_ttl_minutes=args.session_ttl_minutes,
        allowed_networks=allowed_networks,
        trust_proxy=args.trust_proxy,
    )


def safe_redirect_target(value: str | None) -> str:
    if not value:
        return "/"
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_date_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def normalize_display_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.strip().split())


def normalize_date_field(
    value: object,
    *,
    field_label: str,
    required: bool = False,
    allow_invalid_empty: bool = False,
) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{field_label}を入力してください。")
        return ""

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        if allow_invalid_empty:
            return ""
        raise ValueError(f"{field_label}は YYYY-MM-DD 形式で入力してください。") from error


def build_patient_key(name: str, birthdate: str) -> str:
    normalized_name = normalize_display_text(name).casefold()
    if not normalized_name or not birthdate:
        return ""
    return f"{normalized_name}::{birthdate}"


def build_assessment_key(patient_key: str, eval_date: str) -> str:
    if not patient_key or not eval_date:
        return ""
    return f"{patient_key}::{eval_date}"


def dump_record_payload(record: dict) -> str:
    serializable = dict(record)
    serializable.pop("id", None)
    serializable.pop("saveMode", None)
    return json.dumps(serializable, ensure_ascii=False)


def prepare_record_payload(
    payload: dict,
    *,
    default_saved_at: str | None = None,
    default_eval_date: str | None = None,
    allow_incomplete: bool = False,
) -> dict:
    record = dict(payload)
    record.pop("id", None)
    record.pop("saveMode", None)

    raw_fields = record.get("fields")
    fields = dict(raw_fields) if isinstance(raw_fields, dict) else {}

    name = normalize_display_text(record.get("name") or fields.get("name") or "")
    if not name and not allow_incomplete:
        raise ValueError("氏名を入力してください。")

    furigana = normalize_display_text(record.get("furigana") or fields.get("furigana") or "")
    birthdate = normalize_date_field(
        fields.get("birthdate") or record.get("birthdate") or "",
        field_label="生年月日",
        required=not allow_incomplete,
        allow_invalid_empty=allow_incomplete,
    )
    fallback_eval_date = normalize_date_field(
        default_eval_date or current_date_iso(),
        field_label="評価日",
        allow_invalid_empty=True,
    ) or current_date_iso()
    eval_date = normalize_date_field(
        record.get("date") or fields.get("evalDate") or fallback_eval_date,
        field_label="評価日",
        allow_invalid_empty=allow_incomplete,
    ) or fallback_eval_date

    saved_at = str(record.get("savedAt") or default_saved_at or current_timestamp())
    updated_at = str(record.get("updatedAt") or saved_at)
    patient_key = build_patient_key(name, birthdate)
    assessment_key = build_assessment_key(patient_key, eval_date)

    record["name"] = name
    record["furigana"] = furigana
    record["birthdate"] = birthdate
    record["date"] = eval_date
    record["patientKey"] = patient_key
    record["assessmentKey"] = assessment_key
    record["savedAt"] = saved_at
    record["updatedAt"] = updated_at
    record["patient"] = {
        "key": patient_key,
        "name": name,
        "furigana": furigana,
        "birthdate": birthdate,
    }

    fields["name"] = name
    fields["furigana"] = furigana
    fields["evalDate"] = eval_date
    if birthdate:
        fields["birthdate"] = birthdate
    record["fields"] = fields
    return record


def ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(row[1] == column_name for row in rows):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def reconcile_record_metadata(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT id, created_at, updated_at, payload FROM records ORDER BY id DESC"
    ).fetchall()
    seen_assessment_keys: set[str] = set()
    duplicate_row_ids: list[int] = []

    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError:
            continue

        saved_at = str(payload.get("savedAt") or row["created_at"] or current_timestamp())
        updated_at = str(payload.get("updatedAt") or row["updated_at"] or saved_at)
        record = prepare_record_payload(
            payload,
            default_saved_at=saved_at,
            default_eval_date=saved_at[:10],
            allow_incomplete=True,
        )
        record["savedAt"] = saved_at
        record["updatedAt"] = updated_at

        assessment_key = record.get("assessmentKey") or None
        if assessment_key and assessment_key in seen_assessment_keys:
            duplicate_row_ids.append(row["id"])
            continue
        if assessment_key:
            seen_assessment_keys.add(assessment_key)

        connection.execute(
            """
            UPDATE records
            SET created_at = ?, updated_at = ?, eval_date = ?, patient_key = ?, assessment_key = ?, payload = ?
            WHERE id = ?
            """,
            (
                record["savedAt"],
                record["updatedAt"],
                record.get("date") or None,
                record.get("patientKey") or None,
                assessment_key,
                dump_record_payload(record),
                row["id"],
            ),
        )

    if duplicate_row_ids:
        placeholders = ", ".join("?" for _ in duplicate_row_ids)
        connection.execute(f"DELETE FROM records WHERE id IN ({placeholders})", duplicate_row_ids)


def ensure_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with DB_WRITE_LOCK:
        with sqlite3.connect(db_path, timeout=DB_TIMEOUT_SECONDS) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(f"PRAGMA busy_timeout = {int(DB_TIMEOUT_SECONDS * 1000)}")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    eval_date TEXT,
                    patient_key TEXT,
                    assessment_key TEXT,
                    payload TEXT NOT NULL
                )
                """
            )
            ensure_column(connection, "records", "updated_at", "updated_at TEXT")
            ensure_column(connection, "records", "eval_date", "eval_date TEXT")
            ensure_column(connection, "records", "patient_key", "patient_key TEXT")
            ensure_column(connection, "records", "assessment_key", "assessment_key TEXT")
            reconcile_record_metadata(connection)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_records_eval_date ON records(eval_date DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_records_patient_key ON records(patient_key)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_records_assessment_key ON records(assessment_key)")
            connection.commit()


def open_connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=DB_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA busy_timeout = {int(DB_TIMEOUT_SECONDS * 1000)}")
    return connection


def list_records(db_path: Path) -> list[dict]:
    with open_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, payload
            FROM records
            ORDER BY COALESCE(eval_date, '') DESC, COALESCE(updated_at, created_at) DESC, id DESC
            """
        ).fetchall()

    records: list[dict] = []
    for row in rows:
        payload = json.loads(row["payload"])
        payload["id"] = row["id"]
        records.append(payload)
    return records


def create_record(db_path: Path, payload: dict) -> dict:
    now = current_timestamp()
    record = prepare_record_payload(
        payload,
        default_saved_at=now,
        default_eval_date=current_date_iso(),
        allow_incomplete=False,
    )
    record["updatedAt"] = now

    with DB_WRITE_LOCK:
        with open_connection(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                "SELECT id, created_at, payload FROM records WHERE assessment_key = ?",
                (record["assessmentKey"],),
            ).fetchone()

            if existing_row:
                try:
                    existing_payload = json.loads(existing_row["payload"])
                except json.JSONDecodeError:
                    existing_payload = {}
                record["savedAt"] = str(existing_payload.get("savedAt") or existing_row["created_at"] or now)
                record_id = existing_row["id"]
                save_mode = "updated"
                connection.execute(
                    """
                    UPDATE records
                    SET created_at = ?, updated_at = ?, eval_date = ?, patient_key = ?, assessment_key = ?, payload = ?
                    WHERE id = ?
                    """,
                    (
                        record["savedAt"],
                        record["updatedAt"],
                        record["date"],
                        record["patientKey"],
                        record["assessmentKey"],
                        dump_record_payload(record),
                        record_id,
                    ),
                )
            else:
                save_mode = "created"
                cursor = connection.execute(
                    """
                    INSERT INTO records (created_at, updated_at, eval_date, patient_key, assessment_key, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["savedAt"],
                        record["updatedAt"],
                        record["date"],
                        record["patientKey"],
                        record["assessmentKey"],
                        dump_record_payload(record),
                    ),
                )
                record_id = cursor.lastrowid

            connection.commit()

    record["id"] = record_id
    record["saveMode"] = save_mode
    return record


def delete_record(db_path: Path, record_id: int) -> bool:
    with DB_WRITE_LOCK:
        with open_connection(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("DELETE FROM records WHERE id = ?", (record_id,))
            connection.commit()
            return cursor.rowcount > 0


def check_health(db_path: Path, client_templates: dict[str, str]) -> tuple[HTTPStatus, dict[str, object]]:
    try:
        public_template = client_templates.get("public", "")
        auth_template = client_templates.get("auth", "")
        if not public_template:
            raise RuntimeError("public client template is not prepared")
        if AUTH_STATUS_PLACEHOLDER not in auth_template:
            raise RuntimeError("auth client template is not prepared")

        with open_connection(db_path) as connection:
            record_count = connection.execute("SELECT COUNT(*) AS count FROM records").fetchone()["count"]

        return HTTPStatus.OK, {
            "status": "ok",
            "records": record_count,
            "checks": {
                "database": "ok",
                "clientTemplates": "ok",
            },
        }
    except Exception as error:
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "status": "error",
            "error": str(error),
        }


class KoukuKinouHandler(BaseHTTPRequestHandler):
    server_version = "KoukuKinou/1.0"

    @property
    def db_path(self) -> Path:
        return self.server.db_path  # type: ignore[attr-defined]

    @property
    def auth_config(self) -> AuthConfig:
        return self.server.auth_config  # type: ignore[attr-defined]

    @property
    def sessions(self) -> dict[str, datetime]:
        return self.server.sessions  # type: ignore[attr-defined]

    @property
    def session_lock(self) -> threading.Lock:
        return self.server.session_lock  # type: ignore[attr-defined]

    @property
    def client_templates(self) -> dict[str, str]:
        return self.server.client_templates  # type: ignore[attr-defined]

    def allows_tailscale_auth(self) -> bool:
        return self.auth_config.enabled and self.auth_config.mode in {"tailscale", "tailscale-or-password"}

    def allows_password_auth(self) -> bool:
        return self.auth_config.enabled and self.auth_config.mode in {"password", "tailscale-or-password"}

    def get_tailscale_identity(self) -> dict[str, str] | None:
        if not self.allows_tailscale_auth():
            return None

        login = self.headers.get("Tailscale-User-Login", "").strip()
        if not login:
            return None

        name = self.headers.get("Tailscale-User-Name", "").strip() or login
        return {"login": login, "name": name}

    def build_auth_status_html(self) -> str:
        identity = self.get_tailscale_identity()
        if identity:
            return '<span class="badge">Ver 1.0</span>'

        if self.allows_password_auth():
            return (
                '<div style="display:flex;align-items:center;gap:8px">'
                '<span class="badge">Ver 1.0</span>'
                '<a href="/logout" class="badge" style="text-decoration:none;background:#fff1ea;color:#8a3b21">ログアウト</a>'
                "</div>"
            )

        return '<span class="badge">Ver 1.0</span>'

    def build_login_description(self) -> str:
        if self.auth_config.mode == "tailscale-or-password":
            return "通常は Tailscale の HTTPS URL から開くと自動認証されます。ここでは管理用パスワードでも入れます。"
        return "NAS 上で共有運用するため、ログイン後に記録画面へ入る構成にしています。"

    def build_login_hint(self) -> str:
        if self.auth_config.mode == "tailscale-or-password":
            return "管理用パスワードは環境変数 KOUKU_KINOU_PASSWORD で設定します。"
        return "パスワードは環境変数 KOUKU_KINOU_PASSWORD で設定します。"

    def respond_tailscale_required(self, api: bool) -> None:
        message = "このアプリは Tailscale の HTTPS URL から開いたときだけ利用できます。Tailscale を接続して ts.net の URL から開いてください。"
        if api:
            self.respond_json(
                {"error": "Tailscale authentication required", "detail": message},
                status=HTTPStatus.UNAUTHORIZED,
            )
            return
        self.respond_html(
            build_message_html("Tailscale 接続が必要です", message),
            status=HTTPStatus.UNAUTHORIZED,
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/health":
            status, payload = check_health(self.db_path, self.client_templates)
            self.respond_json(payload, status=status)
            return

        if not self.is_client_allowed():
            self.respond_access_denied(api=parsed.path.startswith("/api/"))
            return

        if parsed.path == "/login":
            if not self.auth_config.enabled:
                self.respond_redirect("/")
                return
            if self.is_authenticated():
                self.respond_redirect("/")
                return
            if not self.allows_password_auth():
                self.respond_tailscale_required(api=False)
                return
            next_target = safe_redirect_target(parse_qs(parsed.query).get("next", ["/"])[0])
            self.respond_html(
                build_login_html(
                    next_target=next_target,
                    description=self.build_login_description(),
                    hint=self.build_login_hint(),
                )
            )
            return

        if parsed.path == "/logout":
            if self.get_tailscale_identity():
                self.clear_session()
                self.respond_html(
                    build_message_html(
                        "Tailscale 接続中です",
                        "Tailscale 経由の認証はブラウザー内のログアウト対象ではありません。接続を終えるには Tailscale を切断するか、このページを閉じてください。",
                    )
                )
                return
            self.clear_session()
            self.respond_redirect(
                "/login",
                extra_headers=[("Set-Cookie", self.make_session_cookie("", max_age=0))],
            )
            return

        if parsed.path in {"/", "/index.html"}:
            if not self.ensure_authenticated(api=False):
                return
            template_key = "auth" if self.auth_config.enabled else "public"
            self.respond_html(
                render_client_html(
                    self.client_templates[template_key],
                    auth_status_html=self.build_auth_status_html(),
                )
            )
            return

        if parsed.path == "/api/records":
            if not self.ensure_authenticated(api=True):
                return
            try:
                self.respond_json(list_records(self.db_path))
            except sqlite3.Error as error:
                self.respond_json({"error": f"記録一覧の取得に失敗しました: {error}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.respond_not_found()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if not self.is_client_allowed():
            self.respond_access_denied(api=parsed.path.startswith("/api/"))
            return

        if parsed.path == "/login":
            self.handle_login()
            return

        if parsed.path != "/api/records":
            self.respond_not_found()
            return

        if not self.ensure_authenticated(api=True):
            return

        try:
            payload = self.read_json_body()
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
        except ValueError as error:
            self.respond_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            record = create_record(self.db_path, payload)
        except ValueError as error:
            self.respond_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        except sqlite3.Error as error:
            self.respond_json({"error": f"記録の保存に失敗しました: {error}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        status = HTTPStatus.OK if record.get("saveMode") == "updated" else HTTPStatus.CREATED
        self.respond_json(record, status=status)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)

        if not self.is_client_allowed():
            self.respond_access_denied(api=parsed.path.startswith("/api/"))
            return

        match = re.fullmatch(r"/api/records/(\d+)", parsed.path)
        if not match:
            self.respond_not_found()
            return

        if not self.ensure_authenticated(api=True):
            return

        record_id = int(match.group(1))
        try:
            deleted = delete_record(self.db_path, record_id)
        except sqlite3.Error as error:
            self.respond_json({"error": f"記録の削除に失敗しました: {error}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if not deleted:
            self.respond_json({"error": "Record not found"}, status=HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def read_json_body(self) -> object:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b""
        if not raw:
            raise ValueError("Request body is empty")
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Request body is not valid JSON") from error

    def read_form_body(self) -> dict[str, str]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b""
        if not raw:
            return {}
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items()}

    def respond_html(
        self,
        content: str,
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        if extra_headers:
            for header_name, header_value in extra_headers:
                self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(data)

    def respond_json(
        self,
        payload: object,
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        if extra_headers:
            for header_name, header_value in extra_headers:
                self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(data)

    def respond_redirect(
        self,
        location: str,
        status: HTTPStatus = HTTPStatus.SEE_OTHER,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        if extra_headers:
            for header_name, header_value in extra_headers:
                self.send_header(header_name, header_value)
        self.end_headers()

    def respond_not_found(self) -> None:
        self.respond_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def respond_access_denied(self, api: bool) -> None:
        if api:
            self.respond_json({"error": "Access denied"}, status=HTTPStatus.FORBIDDEN)
            return
        self.respond_html(
            build_message_html("アクセス拒否", "この端末またはネットワークからの接続は許可されていません。"),
            status=HTTPStatus.FORBIDDEN,
        )

    def handle_login(self) -> None:
        if not self.auth_config.enabled:
            self.respond_redirect("/")
            return
        if not self.allows_password_auth():
            self.respond_tailscale_required(api=False)
            return

        form = self.read_form_body()
        password = form.get("password", "")
        next_target = safe_redirect_target(form.get("next"))
        if not self.auth_config.password or not secrets.compare_digest(password, self.auth_config.password):
            self.respond_html(
                build_login_html(
                    "パスワードが違います。",
                    next_target=next_target,
                    description=self.build_login_description(),
                    hint=self.build_login_hint(),
                ),
                status=HTTPStatus.UNAUTHORIZED,
            )
            return

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.auth_config.session_ttl_minutes)
        with self.session_lock:
            self.prune_expired_sessions(now=datetime.now(timezone.utc))
            self.sessions[token] = expires_at

        self.respond_redirect(
            next_target,
            extra_headers=[
                (
                    "Set-Cookie",
                    self.make_session_cookie(token, max_age=self.auth_config.session_ttl_minutes * 60),
                )
            ],
        )

    def ensure_authenticated(self, api: bool) -> bool:
        if not self.auth_config.enabled:
            return True
        if self.is_authenticated():
            return True
        if self.auth_config.mode == "tailscale":
            self.respond_tailscale_required(api=api)
            return False
        if api:
            self.respond_json({"error": "Authentication required"}, status=HTTPStatus.UNAUTHORIZED)
            return False
        next_target = quote(self.path if self.path else "/", safe="/?=&")
        self.respond_redirect(f"/login?next={next_target}")
        return False

    def is_authenticated(self) -> bool:
        if not self.auth_config.enabled:
            return True

        if self.get_tailscale_identity():
            return True

        if not self.allows_password_auth():
            return False

        token = self.get_session_token()
        if not token:
            return False

        now = datetime.now(timezone.utc)
        with self.session_lock:
            self.prune_expired_sessions(now=now)
            return token in self.sessions

    def clear_session(self) -> None:
        token = self.get_session_token()
        if not token:
            return
        with self.session_lock:
            self.sessions.pop(token, None)

    def prune_expired_sessions(self, now: datetime) -> None:
        expired_tokens = [token for token, expires_at in self.sessions.items() if expires_at <= now]
        for token in expired_tokens:
            self.sessions.pop(token, None)

    def get_session_token(self) -> str | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        cookie = SimpleCookie()
        cookie.load(raw_cookie)
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def make_session_cookie(self, token: str, max_age: int) -> str:
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE_NAME] = token
        morsel = cookie[SESSION_COOKIE_NAME]
        morsel["path"] = "/"
        morsel["httponly"] = True
        morsel["samesite"] = "Strict"
        morsel["max-age"] = str(max_age)
        if max_age == 0:
            morsel["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        if self.auth_config.secure_cookie:
            morsel["secure"] = True
        return cookie.output(header="").strip()

    def is_client_allowed(self) -> bool:
        if not self.auth_config.allowed_networks:
            return True

        try:
            client_ip = ipaddress.ip_address(self.get_client_ip())
        except ValueError:
            return False
        return any(client_ip in network for network in self.auth_config.allowed_networks)

    def get_client_ip(self) -> str:
        if self.auth_config.trust_proxy:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return self.client_address[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the oral assessment app with shared SQLite storage")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--auth-mode", default=DEFAULT_AUTH_MODE)
    parser.add_argument("--password", default=os.environ.get("KOUKU_KINOU_PASSWORD"))
    parser.add_argument("--no-auth", action="store_true", default=os.environ.get("KOUKU_KINOU_NO_AUTH") == "1")
    parser.add_argument("--session-ttl-minutes", type=int, default=DEFAULT_SESSION_TTL_MINUTES)
    parser.add_argument("--secure-cookie", action="store_true", default=os.environ.get("KOUKU_KINOU_SECURE_COOKIE") == "1")
    parser.add_argument("--allowed-networks", action="append", default=[])
    parser.add_argument("--trust-proxy", action="store_true", default=os.environ.get("KOUKU_KINOU_TRUST_PROXY") == "1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    auth_config = build_auth_config(args)
    ensure_database(args.db)
    client_templates = prepare_client_templates()
    server = ThreadingHTTPServer((args.host, args.port), KoukuKinouHandler)
    server.daemon_threads = True
    server.db_path = args.db  # type: ignore[attr-defined]
    server.auth_config = auth_config  # type: ignore[attr-defined]
    server.client_templates = client_templates  # type: ignore[attr-defined]
    server.sessions = {}  # type: ignore[attr-defined]
    server.session_lock = threading.Lock()  # type: ignore[attr-defined]
    print(f"Serving on http://{args.host}:{args.port}")
    if auth_config.enabled:
        print("Authentication: enabled")
        print(f"Authentication mode: {auth_config.mode}")
        if auth_config.allowed_networks:
            print("Allowed networks:", ", ".join(str(network) for network in auth_config.allowed_networks))
    else:
        print("Authentication: disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()