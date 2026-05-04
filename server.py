from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
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
ASSETS_DIR = BASE_DIR / "assets"


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
README_HTML_PATH = BASE_DIR / "README.html"
DEFAULT_DB_PATH = Path(os.environ.get("KOUKU_KINOU_DB", BASE_DIR / "data" / "records.db"))
DEFAULT_SESSION_TTL_MINUTES = int(os.environ.get("KOUKU_KINOU_SESSION_TTL_MINUTES", "480"))
DEFAULT_ALLOWED_NETWORKS = os.environ.get("KOUKU_KINOU_ALLOWED_NETWORKS", "")
DEFAULT_AUTH_MODE = (os.environ.get("KOUKU_KINOU_AUTH_MODE", "password") or "password").strip().lower()
SESSION_COOKIE_NAME = "kouku_kinou_session"
AUTH_STATUS_PLACEHOLDER = "__AUTH_STATUS_HTML__"
HELP_ROUTE_PATH = "/readme.html"
DB_TIMEOUT_SECONDS = 30.0
DB_WRITE_LOCK = threading.Lock()
DEFAULT_SHARED_SETTINGS = {
    "staffList": [
        "本澤　真奈美",
        "兵働　めぐみ",
        "川原　奈緒美",
        "水野　永子",
        "宇井　くるみ",
        "近藤　祥子",
        "加治木　綾華",
        "伊藤　言美",
        "間島　大心",
        "村松　由姫香",
        "権田　万智子",
        "多和　佑恭",
    ],
    "dentistList": [],
}
SHARED_SETTINGS_KEYS = tuple(DEFAULT_SHARED_SETTINGS.keys())

HELP_STATIC_ROUTES: dict[str, tuple[Path, str]] = {
    "/readme.html": (README_HTML_PATH, "text/html; charset=utf-8"),
    "/README.html": (README_HTML_PATH, "text/html; charset=utf-8"),
    "/README.md": (BASE_DIR / "README.md", "text/markdown; charset=utf-8"),
    "/README.pdf": (BASE_DIR / "README.pdf", "application/pdf"),
    "/DEPLOY_SYNOLOGY_JA.html": (BASE_DIR / "DEPLOY_SYNOLOGY_JA.html", "text/html; charset=utf-8"),
    "/DEPLOY_SYNOLOGY_JA.md": (BASE_DIR / "DEPLOY_SYNOLOGY_JA.md", "text/markdown; charset=utf-8"),
    "/DEPLOY_SYNOLOGY_JA.pdf": (BASE_DIR / "DEPLOY_SYNOLOGY_JA.pdf", "application/pdf"),
    "/OPERATIONS_MANUAL_PDF_JA.html": (BASE_DIR / "OPERATIONS_MANUAL_PDF_JA.html", "text/html; charset=utf-8"),
    "/OPERATIONS_MANUAL_JA.md": (BASE_DIR / "OPERATIONS_MANUAL_JA.md", "text/markdown; charset=utf-8"),
    "/OPERATIONS_MANUAL_JA.pdf": (BASE_DIR / "OPERATIONS_MANUAL_JA.pdf", "application/pdf"),
    "/TAILSCALE_CLIENT_GUIDE_JA.html": (BASE_DIR / "TAILSCALE_CLIENT_GUIDE_JA.html", "text/html; charset=utf-8"),
    "/TAILSCALE_CLIENT_GUIDE_JA.md": (BASE_DIR / "TAILSCALE_CLIENT_GUIDE_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_CLIENT_GUIDE_JA.pdf": (BASE_DIR / "TAILSCALE_CLIENT_GUIDE_JA.pdf", "application/pdf"),
    "/TAILSCALE_TABLET_GUIDE_JA.html": (BASE_DIR / "TAILSCALE_TABLET_GUIDE_JA.html", "text/html; charset=utf-8"),
    "/TAILSCALE_TABLET_GUIDE_JA.md": (BASE_DIR / "TAILSCALE_TABLET_GUIDE_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_TABLET_GUIDE_JA.pdf": (BASE_DIR / "TAILSCALE_TABLET_GUIDE_JA.pdf", "application/pdf"),
    "/TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.html": (BASE_DIR / "TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.html", "text/html; charset=utf-8"),
    "/TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md": (BASE_DIR / "TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.pdf": (BASE_DIR / "TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.pdf", "application/pdf"),
    "/TAILSCALE_TABLET_QR_SHEET_JA.html": (BASE_DIR / "TAILSCALE_TABLET_QR_SHEET_JA.html", "text/html; charset=utf-8"),
    "/TAILSCALE_TABLET_QR_SHEET_JA.md": (BASE_DIR / "TAILSCALE_TABLET_QR_SHEET_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_TABLET_QR_SHEET_JA.pdf": (BASE_DIR / "TAILSCALE_TABLET_QR_SHEET_JA.pdf", "application/pdf"),
    "/TailscaleClientLauncher.cmd": (BASE_DIR / "TailscaleClientLauncher.cmd", "text/plain; charset=utf-8"),
    "/TailscaleClientLauncher.ps1": (BASE_DIR / "TailscaleClientLauncher.ps1", "text/plain; charset=utf-8"),
    "/TailscaleClientLauncher.settings.json": (BASE_DIR / "TailscaleClientLauncher.settings.json", "application/json; charset=utf-8"),
    "/.env.example": (BASE_DIR / ".env.example", "text/plain; charset=utf-8"),
}


def resolve_latest_pdf_path(asset_path: Path) -> Path:
    if asset_path.suffix.lower() != ".pdf":
        return asset_path

    updated_path = asset_path.with_name(f"{asset_path.stem}.updated.pdf")
    if not updated_path.exists():
        return asset_path

    if asset_path.exists() and asset_path.stat().st_mtime > updated_path.stat().st_mtime:
        return asset_path

    return updated_path


def resolve_help_static_asset(request_path: str) -> tuple[Path, str] | None:
    static_asset = HELP_STATIC_ROUTES.get(request_path)
    if static_asset:
        asset_path, content_type = static_asset
        return resolve_latest_pdf_path(asset_path), content_type

    if not request_path.startswith("/assets/"):
        return None

    asset_path = (BASE_DIR / request_path.lstrip("/")).resolve()
    if not asset_path.is_relative_to(ASSETS_DIR.resolve()) or not asset_path.is_file():
        return None

    guessed_type, _ = mimetypes.guess_type(asset_path.name)
    content_type = guessed_type or "application/octet-stream"
    return asset_path, content_type

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
PATIENT_DENTIST_FIELD_NEW = '''<div class="form-group">
                <label>かかりつけ医</label>
                <input type="text" id="dentist" value="" style="display:none" aria-hidden="true">
                <select id="dentist_select" data-skip-persist="1">
                    <option value="">選択</option>
                    <option value="__custom__">その他（自由入力）</option>
                </select>
                <input type="text" id="dentist_custom" data-skip-persist="1" placeholder="かかりつけ医を入力" style="display:none;margin-top:8px">
            </div>'''
PATIENT_STAFF_FIELD_NEW = '''<div class="form-group full">
                <label>担当者</label>
                <input type="text" id="staff" value="" style="display:none" aria-hidden="true">
                <select id="staff_select" data-skip-persist="1">
                    <option value="">選択</option>
                    <option value="__custom__">その他（自由入力）</option>
                </select>
                <input type="text" id="staff_custom" data-skip-persist="1" placeholder="担当者名を入力" style="display:none;margin-top:8px">
            </div>'''
SETTINGS_TAB_HTML = '''<!-- ==================== TAB 6: 設定 ==================== -->
<div id="tab-settings" class="tab-content">
    <div class="card">
        <div class="card-header">
            <div class="icon" style="background:#fff5e8">⚙️</div>
            <div><h2>設定</h2><div class="subtitle">担当者・かかりつけ医の候補管理</div></div>
        </div>
        <div class="info-box">このサーバーで共有する候補一覧を編集します。追加・削除すると利用者情報タブのプルダウンへ即時反映されます。</div>
        <div class="settings-grid">
            <section class="settings-panel">
                <div class="settings-panel__title">担当者一覧</div>
                <div class="settings-panel__hint">初回表示時は既定の担当者名を登録しています。</div>
                <div class="settings-panel__editor">
                    <input id="staffSettingsInput" class="settings-panel__input" type="text" data-skip-persist="1" placeholder="担当者名を追加">
                    <button id="addStaffSettingButton" type="button" class="btn btn-outline">追加</button>
                </div>
                <div id="staffSettingsList" class="settings-list"></div>
            </section>
            <section class="settings-panel">
                <div class="settings-panel__title">かかりつけ医一覧</div>
                <div class="settings-panel__hint">よく使う医院名を登録しておくと患者入力が速くなります。</div>
                <div class="settings-panel__editor">
                    <input id="dentistSettingsInput" class="settings-panel__input" type="text" data-skip-persist="1" placeholder="かかりつけ医を追加">
                    <button id="addDentistSettingButton" type="button" class="btn btn-outline">追加</button>
                </div>
                <div id="dentistSettingsList" class="settings-list"></div>
            </section>
        </div>
        <div class="action-bar no-print">
            <button class="btn btn-outline" type="button" onclick="showTab('patient')">← 利用者情報へ戻る</button>
        </div>
    </div>
</div>

<!-- TOAST -->'''
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
    "  if (getSelectedPrintMode() === 'full') {\n"
    "    printAllRecordPages();\n"
    "    return;\n"
    "  }\n"
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
    .print-toolbar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        margin: 0 0 12px;
    }
    .print-toolbar__control {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: var(--text-light);
        font-size: 13px;
        font-weight: 600;
    }
    .print-toolbar__select {
        min-width: 220px;
        padding: 10px 12px;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: #fff;
        color: var(--text);
        font: inherit;
    }

    @page {
        size: A4 portrait;
        margin: 10mm;
    }

    @media print {
                body:not(.print-mode):not(.print-all-mode) .tab-content { display: none !important; }
                body:not(.print-mode):not(.print-all-mode) .tab-content.active { display: block !important; padding: 0; }
                body:not(.print-mode):not(.print-all-mode) .card { box-shadow: none; break-inside: avoid; }

                body.print-all-mode .app-header,
                body.print-all-mode .tab-bar,
                body.print-all-mode .action-bar,
                body.print-all-mode .no-print,
                body.print-all-mode #tab-history {
                        display: none !important;
                }
                body.print-all-mode .tab-content {
                        display: block !important;
                        padding: 0 !important;
                        break-before: page;
                }
                body.print-all-mode #tab-patient {
                        break-before: auto;
                }
                body.print-all-mode .card {
                        box-shadow: none;
                        break-inside: avoid;
                }
                body.print-all-mode {
                        background: white !important;
                        font-size: 12px;
                        -webkit-print-color-adjust: exact;
                        print-color-adjust: exact;
                }

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
        body.print-mode .print-sheet__metric-card--wide {
            grid-column: 1 / -1;
            min-height: auto;
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
const SETTINGS_API_ROOT = '/api/settings';
const HISTORY_FILTER_STATE = { query: '' };
let currentMnaFieldMode = '';
const DRAFT_STORAGE_KEY = 'koukuKinouDraftsV1';
const IMPORT_INPUT_ID = 'recordImportInput';
const STAGE1_STYLE_ID = 'koukuKinouStage1Styles';
const AUTOSAVE_SLOT = 'auto';
const DRAFT_SLOTS = ['patient', 'oral', 'mna', 'summary'];
const RSST_DEFAULT_SECONDS = 30;
const TREND_HISTORY_LIMIT = 5;
const NEXT_MONITOR_ALERT_DAYS = 30;
const ODK_REFERENCE_PER_SECOND = 6.0;
const CLINICAL_COMMENT_START_MARKER = '【口腔機能メモ】';
const CLINICAL_COMMENT_END_MARKER = '【口腔機能メモここまで】';
const MANAGED_SELECT_CUSTOM_VALUE = '__custom__';
const DEFAULT_STAFF_OPTIONS = ['本澤　真奈美', '兵働　めぐみ', '川原　奈緒美', '水野　永子', '宇井　くるみ', '近藤　祥子', '加治木　綾華', '伊藤　言美', '間島　大心', '村松　由姫香', '権田　万智子', '多和　佑恭'];
const MANAGED_FIELD_CONFIGS = [
    {
        fieldId: 'staff',
        selectId: 'staff_select',
        customId: 'staff_custom',
        settingKey: 'staffList',
        label: '担当者',
        settingsInputId: 'staffSettingsInput',
        settingsListId: 'staffSettingsList',
        addButtonId: 'addStaffSettingButton',
        emptyText: '登録された担当者はありません',
        addSuccessMessage: '担当者を追加しました',
        removeSuccessMessage: '担当者を削除しました',
        duplicateMessage: 'その担当者は既に登録されています',
        confirmDeleteMessage: 'この担当者を一覧から削除しますか？',
        defaults: DEFAULT_STAFF_OPTIONS,
    },
    {
        fieldId: 'dentist',
        selectId: 'dentist_select',
        customId: 'dentist_custom',
        settingKey: 'dentistList',
        label: 'かかりつけ医',
        settingsInputId: 'dentistSettingsInput',
        settingsListId: 'dentistSettingsList',
        addButtonId: 'addDentistSettingButton',
        emptyText: '登録されたかかりつけ医はありません',
        addSuccessMessage: 'かかりつけ医を追加しました',
        removeSuccessMessage: 'かかりつけ医を削除しました',
        duplicateMessage: 'そのかかりつけ医は既に登録されています',
        confirmDeleteMessage: 'このかかりつけ医を一覧から削除しますか？',
        defaults: [],
    },
];
const NON_RECORD_FIELD_IDS = new Set(['historySearch', 'printModeSelect', IMPORT_INPUT_ID, 'staff_select', 'staff_custom', 'dentist_select', 'dentist_custom', 'staffSettingsInput', 'dentistSettingsInput']);
let autosaveHandle = 0;
let rsstTimerHandle = 0;
let rsstRemainingSeconds = RSST_DEFAULT_SECONDS;
let draftListenersBound = false;
let stage2UpdateHandle = 0;
let stage2HooksInstalled = false;
let stage2ListenersBound = false;
let managedFieldHooksInstalled = false;
let latestClinicalSupportData = null;
let sharedSettingsState = { staffList: [], dentistList: [] };

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

async function fetchSharedSettings() {
    const response = await fetch(SETTINGS_API_ROOT, { cache: 'no-store' });
    if (!response.ok) {
        throw new Error(await extractErrorMessage(response, '一覧設定の取得に失敗しました'));
    }
    return response.json();
}

async function persistSharedSettings(settings) {
    const response = await fetch(SETTINGS_API_ROOT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
    });
    if (!response.ok) {
        throw new Error(await extractErrorMessage(response, '一覧設定の保存に失敗しました'));
    }
    return response.json();
}

function buildDefaultSharedSettings() {
    return {
        staffList: DEFAULT_STAFF_OPTIONS.slice(),
        dentistList: [],
    };
}

function applySharedSettingsState(settings) {
    const source = settings && typeof settings === 'object' ? settings : {};
    const defaults = buildDefaultSharedSettings();
    sharedSettingsState = {
        staffList: mergeUniqueTextValues([], Array.isArray(source.staffList) ? source.staffList : defaults.staffList),
        dentistList: mergeUniqueTextValues([], Array.isArray(source.dentistList) ? source.dentistList : defaults.dentistList),
    };
    return sharedSettingsState;
}

function buildSharedSettingsPayload(overrides = {}) {
    const source = {
        staffList: Array.isArray(overrides.staffList) ? overrides.staffList : sharedSettingsState.staffList,
        dentistList: Array.isArray(overrides.dentistList) ? overrides.dentistList : sharedSettingsState.dentistList,
    };
    return {
        staffList: mergeUniqueTextValues([], source.staffList || []),
        dentistList: mergeUniqueTextValues([], source.dentistList || []),
    };
}

async function saveSharedSettingsState(overrides = {}) {
    const saved = await persistSharedSettings(buildSharedSettingsPayload(overrides));
    return applySharedSettingsState(saved);
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
        if (element.type === 'radio' || element.type === 'checkbox' || element.type === 'file') {
            return;
        }
        if (element.dataset.skipPersist === '1' || NON_RECORD_FIELD_IDS.has(element.id)) {
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
    if (typeof syncManagedPersonSelectors === 'function') {
        syncManagedPersonSelectors();
    }
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

function buildPatientLookupKey(name, birthdate) {
    const normalizedName = normalizeSearchText(name);
    const normalizedBirthdate = String(birthdate ?? '').trim();
    return normalizedName && normalizedBirthdate ? `${normalizedName}::${normalizedBirthdate}` : '';
}

function parseYmdParts(value) {
    const match = String(value || '').trim().match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
    if (!match) {
        return null;
    }
    return {
        year: Number.parseInt(match[1], 10),
        month: Number.parseInt(match[2], 10),
        day: Number.parseInt(match[3], 10),
    };
}

function ymdPartsToUtc(parts) {
    if (!parts) {
        return null;
    }
    return Date.UTC(parts.year, parts.month - 1, parts.day);
}

function calculateAgeAtDate(birthdate, referenceDate) {
    const birth = parseYmdParts(birthdate);
    const ref = parseYmdParts(referenceDate || new Date().toISOString().slice(0, 10));
    if (!birth || !ref) {
        return null;
    }

    let age = ref.year - birth.year;
    if (ref.month < birth.month || (ref.month === birth.month && ref.day < birth.day)) {
        age -= 1;
    }
    return age >= 0 ? age : null;
}

function parseSortableDate(value) {
    const text = String(value || '').trim();
    if (!text) {
        return Number.NEGATIVE_INFINITY;
    }
    const normalized = text.length === 10 ? `${text}T00:00:00` : text;
    const timestamp = Date.parse(normalized);
    return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

function getRecordSortTimestamp(record) {
    return Math.max(
        parseSortableDate(record.date),
        parseSortableDate(record.updatedAt),
        parseSortableDate(record.savedAt),
    );
}

function compareRecordsByDateDesc(left, right) {
    return getRecordSortTimestamp(right) - getRecordSortTimestamp(left);
}

function sortRecordsByLatest(sourceRecords) {
    return [...sourceRecords].sort(compareRecordsByDateDesc);
}

function toMetricNumber(value) {
    if (value === null || value === undefined) {
        return null;
    }
    const parsed = Number.parseFloat(String(value).replace(/,/g, '').trim());
    return Number.isFinite(parsed) ? parsed : null;
}

function formatMetricValue(value, unit = '') {
    const numeric = toMetricNumber(value);
    return numeric === null ? '―' : `${numeric.toFixed(1)}${unit}`;
}

function getTrendDirection(currentValue, previousValue) {
    if (currentValue === null || previousValue === null) {
        return 'na';
    }
    const delta = currentValue - previousValue;
    if (Math.abs(delta) < 0.05) {
        return 'flat';
    }
    return delta > 0 ? 'up' : 'down';
}

function formatSignedDelta(currentValue, previousValue, unit = '') {
    if (currentValue === null || previousValue === null) {
        return '初回';
    }
    const delta = currentValue - previousValue;
    if (Math.abs(delta) < 0.05) {
        return `±0.0${unit}`;
    }
    const sign = delta > 0 ? '+' : '';
    return `${sign}${delta.toFixed(1)}${unit}`;
}

function buildTrendDeltaHtml(currentValue, previousValue, unit = '', label = '') {
    const direction = getTrendDirection(currentValue, previousValue);
    const prefix = label ? `${escapeHtml(label)}: ` : '';
    if (direction === 'na') {
        return `<span class="trend-delta trend-delta--flat">${prefix}初回</span>`;
    }
    const symbol = direction === 'up' ? '▲' : direction === 'down' ? '▼' : '■';
    return `<span class="trend-delta trend-delta--${direction}">${prefix}${symbol} ${escapeHtml(formatSignedDelta(currentValue, previousValue, unit))}</span>`;
}

function buildMetricChipHtml(label, value, tone = 'info') {
    return `
        <div class="metric-chip metric-chip--${escapeHtml(tone)}">
            <span class="metric-chip__label">${escapeHtml(label)}</span>
            <span class="metric-chip__value">${escapeHtml(value)}</span>
        </div>
    `;
}

function getBmiReference(age) {
    if (age === null) {
        return null;
    }
    if (age >= 65) {
        return { label: '65歳以上の参考帯', low: 21.5, high: 24.9 };
    }
    return { label: '成人の参考帯', low: 18.5, high: 24.9 };
}

function classifyBmiReference(bmi, reference) {
    if (bmi === null || !reference) {
        return 'info';
    }
    if (bmi < reference.low) {
        return 'alert';
    }
    if (bmi > reference.high) {
        return 'info';
    }
    return 'success';
}

function getMnaF1ScoreInfo(bmi) {
    if (bmi === null) {
        return null;
    }
    if (bmi < 19) {
        return { score: 0, label: 'BMI 19未満' };
    }
    if (bmi < 21) {
        return { score: 1, label: 'BMI 19以上 21未満' };
    }
    if (bmi < 23) {
        return { score: 2, label: 'BMI 21以上 23未満' };
    }
    return { score: 3, label: 'BMI 23以上' };
}

function parseChoiceCode(value) {
    const match = String(value || '').trim().match(/^(\\d+)/);
    if (!match) {
        return null;
    }
    return Number.parseInt(match[1], 10);
}

function getRecordFieldValue(record, id) {
    if (!record) {
        return '';
    }
    if (record.fields && Object.prototype.hasOwnProperty.call(record.fields, id)) {
        return String(record.fields[id] ?? '');
    }
    return String(record[id] ?? '');
}

function buildOralAssessmentState(readValue) {
    const q1Value = String(readValue('q1') || '').trim();
    const q2Value = String(readValue('q2') || '').trim();
    const q3Value = String(readValue('q3') || '').trim();
    const q4Value = String(readValue('q4') || '').trim();
    const q5Value = String(readValue('q5') || '').trim();
    const q6Value = String(readValue('q6') || '').trim();
    const q7Value = String(readValue('q7') || '').trim();
    const q8Value = String(readValue('q8') || '').trim();
    const q9Value = String(readValue('q9') || '').trim();
    const rsstJudgeValue = String(readValue('rsst_judge') || '').trim();
    const bukubukuValue = String(readValue('bukubuku') || '').trim();
    const guguguValue = String(readValue('gugugu') || '').trim();
    const oralContinue = String(readValue('oral_eval2') || '').trim();
    const oralPlan = String(readValue('oral_eval3') || '').trim();

    return {
        q1Value,
        q1Code: parseChoiceCode(q1Value),
        q2Value,
        q2Code: parseChoiceCode(q2Value),
        q3Value,
        q3Code: parseChoiceCode(q3Value),
        q4Value,
        q4Code: parseChoiceCode(q4Value),
        q5Value,
        q5Code: parseChoiceCode(q5Value),
        q6Value,
        q6Code: parseChoiceCode(q6Value),
        q7Value,
        q7Code: parseChoiceCode(q7Value),
        q8Value,
        q8Code: parseChoiceCode(q8Value),
        q9Value,
        q9Code: parseChoiceCode(q9Value),
        rsstCount: toMetricNumber(readValue('rsst_count')),
        rsstJudgeValue,
        rsstJudgeCode: parseChoiceCode(rsstJudgeValue),
        bukubukuValue,
        bukubukuCode: parseChoiceCode(bukubukuValue),
        guguguValue,
        guguguCode: parseChoiceCode(guguguValue),
        pa: toMetricNumber(readValue('pa')),
        ta: toMetricNumber(readValue('ta')),
        ka: toMetricNumber(readValue('ka')),
        oralContinue,
        oralPlan,
    };
}

function getCurrentOralAssessmentState() {
    return buildOralAssessmentState((id) => getFieldElementValue(id));
}

function getRecordOralAssessmentState(record) {
    return buildOralAssessmentState((id) => getRecordFieldValue(record, id));
}

function hasOralAssessmentData(state) {
    if (!state) {
        return false;
    }
    return [
        state.q1Code,
        state.q2Code,
        state.q3Code,
        state.q4Code,
        state.q5Code,
        state.q6Code,
        state.q7Code,
        state.q8Code,
        state.q9Code,
        state.rsstJudgeCode,
        state.bukubukuCode,
        state.guguguCode,
    ].some((value) => value !== null)
        || [state.rsstCount, state.pa, state.ta, state.ka].some((value) => value !== null && value > 0);
}

function classifyStage3Risk(score) {
    if (score >= 3) {
        return 'alert';
    }
    if (score >= 1) {
        return 'info';
    }
    return 'success';
}

function formatStage3DomainLabel(score) {
    if (score >= 3) {
        return '要注意';
    }
    if (score >= 1) {
        return '経過観察';
    }
    return '安定';
}

function getCleaningHabitRisk(code) {
    if (code === 1) {
        return 2;
    }
    if (code === 2) {
        return 1;
    }
    return 0;
}

function getLowOdkLabels(state) {
    return [
        ['パ', state.pa],
        ['タ', state.ta],
        ['カ', state.ka],
    ].filter(([, value]) => value !== null && value < ODK_REFERENCE_PER_SECOND)
        .map(([label, value]) => `${label} ${value.toFixed(1)}回/秒`);
}

function getComparisonHistoryRecord(history, evalDate) {
    if (!Array.isArray(history) || !history.length) {
        return null;
    }
    const normalizedEvalDate = String(evalDate || '').trim();
    if (!normalizedEvalDate) {
        return history[0] || null;
    }
    return history.find((record) => {
        const recordDate = String(record.date || '').trim();
        return recordDate && recordDate !== normalizedEvalDate;
    }) || history[0] || null;
}

function buildStage3ListHtml(items, emptyText, extraClass = '') {
    const uniqueItems = [...new Set((items || []).map((item) => String(item || '').trim()).filter(Boolean))];
    const className = extraClass ? `stage3-list ${extraClass}` : 'stage3-list';
    if (!uniqueItems.length) {
        return `<ul class="${className}"><li class="stage3-list__empty">${escapeHtml(emptyText)}</li></ul>`;
    }
    return `<ul class="${className}">${uniqueItems.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
}

function hasWorsenedCode(currentCode, previousCode) {
    return currentCode !== null && previousCode !== null && currentCode > previousCode;
}

function hasMeaningfulDrop(currentValue, previousValue, threshold) {
    if (currentValue === null || previousValue === null) {
        return false;
    }
    return currentValue <= previousValue - threshold;
}

function getDaysUntil(dateText) {
    const target = parseYmdParts(dateText);
    const today = parseYmdParts(new Date().toISOString().slice(0, 10));
    const targetUtc = ymdPartsToUtc(target);
    const todayUtc = ymdPartsToUtc(today);
    if (targetUtc === null || todayUtc === null) {
        return null;
    }
    return Math.round((targetUtc - todayUtc) / 86400000);
}

function buildNextMonitorHtml(dateText) {
    const text = String(dateText || '').trim();
    if (!text) {
        return '―';
    }
    const days = getDaysUntil(text);
    if (days === null) {
        return escapeHtml(text);
    }
    let suffix = `あと${days}日`;
    let className = '';
    if (days < 0) {
        suffix = `${Math.abs(days)}日超過`;
        className = 'monitor-status--overdue';
    } else if (days <= NEXT_MONITOR_ALERT_DAYS) {
        className = 'monitor-status--soon';
    }
    return `${escapeHtml(text)}<br><small class="monitor-status ${className}">${escapeHtml(suffix)}</small>`;
}

function getRecordPatientKey(record) {
    const explicitKey = String(record.patientKey ?? '').trim();
    if (explicitKey) {
        return explicitKey;
    }

    return buildPatientLookupKey(record.name, record.birthdate);
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

function buildPatientRecordGroups(sourceRecords) {
    const groups = new Map();
    sourceRecords.forEach((record) => {
        const key = getRecordPatientKey(record);
        if (!key) {
            return;
        }
        if (!groups.has(key)) {
            groups.set(key, []);
        }
        groups.get(key).push(record);
    });
    groups.forEach((group, key) => {
        groups.set(key, sortRecordsByLatest(group));
    });
    return groups;
}

function getLatestPatientRecords(filteredRecords) {
    const patientGroups = buildPatientRecordGroups(records);
    const latestRecords = [];
    const seen = new Set();
    sortRecordsByLatest(filteredRecords).forEach((record) => {
        const key = getRecordPatientKey(record);
        if (!key || seen.has(key)) {
            return;
        }
        seen.add(key);
        latestRecords.push((patientGroups.get(key) || [record])[0]);
    });

    return { latestRecords, patientGroups };
}

function updateLatestPatientsStats(latestRecords) {
    const latestCount = latestRecords.length;
    const stats = document.getElementById('latestPatientsStats');
    if (!stats) {
        return;
    }

    const totalPatients = countUniquePatients(records);
    const query = normalizeSearchText(HISTORY_FILTER_STATE.query);
    stats.textContent = query ? `${latestCount} / ${totalPatients}名を表示` : `${latestCount}名を表示`;

    const summary = document.getElementById('latestPatientsSummary');
    if (!summary) {
        return;
    }

    if (!latestRecords.length) {
        summary.innerHTML = '';
        return;
    }

    const bmiAttentionCount = latestRecords.filter((record) => {
        const bmi = toMetricNumber(record.bmi ?? record.fields?.bmi);
        const age = calculateAgeAtDate(record.birthdate, record.date);
        const reference = getBmiReference(age);
        return bmi !== null && reference && bmi < reference.low;
    }).length;
    const dueSoonCount = latestRecords.filter((record) => {
        const days = getDaysUntil(record.nextMonitor);
        return days !== null && days <= NEXT_MONITOR_ALERT_DAYS;
    }).length;
    const riskCount = latestRecords.filter((record) => {
        const label = String(record.mnaLabel || '').trim();
        return label && label !== '良好' && label !== '―';
    }).length;

    summary.innerHTML = [
        buildMetricChipHtml('表示中', `${latestCount}名`, 'info'),
        buildMetricChipHtml('BMI要確認', `${bmiAttentionCount}名`, bmiAttentionCount ? 'alert' : 'success'),
        buildMetricChipHtml('30日以内フォロー', `${dueSoonCount}名`, dueSoonCount ? 'alert' : 'success'),
        buildMetricChipHtml('栄養注意', `${riskCount}名`, riskCount ? 'alert' : 'success'),
    ].join('');
}

function renderLatestPatients(filteredRecords) {
    const tbody = document.getElementById('latestPatientsBody');
    if (!tbody) {
        return;
    }

    const { latestRecords, patientGroups } = getLatestPatientRecords(filteredRecords);
    updateLatestPatientsStats(latestRecords);

    if (latestRecords.length === 0) {
        const emptyMessage = records.length === 0 ? '保存された利用者はありません' : '検索条件に一致する利用者はありません';
        tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="icon">👥</div>${emptyMessage}</div></td></tr>`;
        return;
    }

    tbody.innerHTML = latestRecords.map((record) => {
        const patientKey = getRecordPatientKey(record);
        const patientHistory = patientGroups.get(patientKey) || [record];
        const previousRecord = patientHistory[1] || null;
        const tagClass = record.mnaLabel === '良好' ? 'tag-good' : record.mnaLabel === 'At risk' ? 'tag-risk' : record.mnaLabel === '低栄養' ? 'tag-bad' : '';
        const scoreLabel = record.mnaScore !== null && record.mnaScore !== undefined ? `${record.mnaScore}/14` : '―';
        const visitCount = patientHistory.length;
        const currentWeight = toMetricNumber(record.weight ?? record.fields?.weight);
        const previousWeight = previousRecord ? toMetricNumber(previousRecord.weight ?? previousRecord.fields?.weight) : null;
        const currentBmi = toMetricNumber(record.bmi ?? record.fields?.bmi);
        const previousBmi = previousRecord ? toMetricNumber(previousRecord.bmi ?? previousRecord.fields?.bmi) : null;
        const age = calculateAgeAtDate(record.birthdate, record.date);
        const identityParts = [escapeHtml(record.birthdate || '―')];
        if (age !== null) {
            identityParts.push(`${age}歳`);
        }
        if (record.furigana) {
            identityParts.push(escapeHtml(record.furigana));
        }

        const metricLines = [];
        if (currentWeight !== null) {
            metricLines.push(`<strong>${escapeHtml(formatMetricValue(currentWeight, 'kg'))}</strong>`);
        }
        if (currentBmi !== null) {
            metricLines.push(`<small class="metric-subline">BMI ${escapeHtml(formatMetricValue(currentBmi))}</small>`);
        }

        return `<tr>
          <td><strong>${escapeHtml(record.name || '')}</strong><br><small class="metric-subline">${identityParts.join(' / ')}</small></td>
          <td>${escapeHtml(record.date || '―')}</td>
          <td>${metricLines.length ? metricLines.join('<br>') : '―'}</td>
          <td>${buildTrendDeltaHtml(currentWeight, previousWeight, 'kg', '体重')}<br>${buildTrendDeltaHtml(currentBmi, previousBmi, '', 'BMI')}</td>
          <td><span class="tag ${tagClass}">${escapeHtml(record.mnaLabel || '―')}</span><br><small class="metric-subline">${escapeHtml(scoreLabel)}</small></td>
          <td>${buildNextMonitorHtml(record.nextMonitor)}</td>
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
                                <input id="historySearch" type="search" data-skip-persist="1" placeholder="氏名・ふりがな・生年月日・評価日で検索" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:#fff;font:inherit;">
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
                <div id="latestPatientsSummary" class="metric-chip-list"></div>
                <div style="overflow-x:auto;">
                    <table class="history-table" id="latestPatientsTable">
                        <thead>
                            <tr>
                                <th>氏名</th>
                                <th>最新評価日</th>
                                <th>体重 / BMI</th>
                                <th>前回比</th>
                                <th>栄養判定</th>
                                <th>次回モニタリング</th>
                                <th>評価回数</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody id="latestPatientsBody">
                            <tr><td colspan="8"><div class="empty-state"><div class="icon">👥</div>利用者データを読み込み中です</div></td></tr>
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
const PRINT_MODE_SELECT_ID = 'printModeSelect';

function ensurePrintControls() {
        const actionBar = document.querySelector('#tab-summary .card.no-print .action-bar');
        if (!actionBar || document.getElementById(PRINT_MODE_SELECT_ID)) {
                return;
        }

        const controls = document.createElement('div');
        controls.className = 'print-toolbar';
        controls.innerHTML = `
            <label class="print-toolbar__control" for="${PRINT_MODE_SELECT_ID}">
                <span>印刷方法</span>
                <select id="${PRINT_MODE_SELECT_ID}" data-skip-persist="1" class="print-toolbar__select">
                    <option value="summary">1名サマリー（A4 1枚）</option>
                    <option value="full">詳細ページ（全タブ）</option>
                </select>
            </label>
        `;

        actionBar.parentElement.insertBefore(controls, actionBar);
}

function getSelectedPrintMode() {
        const select = document.getElementById(PRINT_MODE_SELECT_ID);
        return select ? String(select.value || 'summary') : 'summary';
}

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

function splitClinicalCommentSections(value) {
    const text = String(value || '');
    const startIndex = text.indexOf(CLINICAL_COMMENT_START_MARKER);
    if (startIndex < 0) {
        return {
            before: text.trim(),
            block: '',
            after: '',
            hasBlock: false,
            isLegacyBlock: false,
        };
    }

    const endIndex = text.indexOf(CLINICAL_COMMENT_END_MARKER, startIndex + CLINICAL_COMMENT_START_MARKER.length);
    if (endIndex < 0) {
        return {
            before: text.slice(0, startIndex).trim(),
            block: text.slice(startIndex).trim(),
            after: '',
            hasBlock: true,
            isLegacyBlock: true,
        };
    }

    const blockEnd = endIndex + CLINICAL_COMMENT_END_MARKER.length;
    return {
        before: text.slice(0, startIndex).trim(),
        block: text.slice(startIndex, blockEnd).trim(),
        after: text.slice(blockEnd).trim(),
        hasBlock: true,
        isLegacyBlock: false,
    };
}

function buildClinicalCommentBlock(lines) {
    const normalizedLines = (lines || []).map((line) => String(line || '').trim()).filter(Boolean);
    if (!normalizedLines.length) {
        return '';
    }
    return [CLINICAL_COMMENT_START_MARKER, ...normalizedLines, CLINICAL_COMMENT_END_MARKER].join(String.fromCharCode(10));
}

function parseLegacyClinicalCommentBlock(block) {
    const lines = normalizeCommentBlock(
        String(block || '').replace(CLINICAL_COMMENT_START_MARKER, '')
    ).split(String.fromCharCode(10)).filter(Boolean);
    const generatedLines = [];
    const trailingManualLines = [];
    let summaryAssigned = false;

    lines.forEach((line) => {
        const isGeneratedLine = line.startsWith('所見候補:')
            || line.startsWith('変化:')
            || line.startsWith('支援方針（');
        if (isGeneratedLine) {
            generatedLines.push(line);
            return;
        }
        if (!summaryAssigned) {
            generatedLines.push(line);
            summaryAssigned = true;
            return;
        }
        trailingManualLines.push(line);
    });

    return {
        generatedBlock: buildClinicalCommentBlock(generatedLines),
        trailingText: trailingManualLines.join(String.fromCharCode(10)),
    };
}

function getPrintFriendlyComment(value) {
    const sections = splitClinicalCommentSections(value);
    if (!sections.hasBlock) {
        return sections.before;
    }
    if (sections.isLegacyBlock) {
        return sections.before;
    }
    return [sections.before, sections.after]
        .filter(Boolean)
        .join(String.fromCharCode(10) + String.fromCharCode(10));
}

function buildPrintReportData() {
    const name = getFieldElementValue('name').trim();
    const birthdate = getFieldElementValue('birthdate').trim();
    const clinicalSupportData = buildClinicalSupportData();

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
        comment: getPrintFriendlyComment(getFieldElementValue('summary_comment')),
        nextMonitor: getFieldElementValue('next_monitor'),
        clinicalPrintLines: buildClinicalPrintLines(clinicalSupportData),
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
    const clinicalPrintLines = buildPrintMetricLines(report.clinicalPrintLines || []);

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
        + '<div class="print-sheet__metric-card print-sheet__metric-card--wide"><div class="print-sheet__metric-title">臨床語化・差分要点</div>' + (clinicalPrintLines || '<div class="print-sheet__metric-line">口腔タブ未入力のため、印刷用の臨床要点は未作成です。</div>') + '</div>'
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

function printAllRecordPages() {
    clearPrintMode();
    document.body.classList.add('print-all-mode');
    requestAnimationFrame(() => {
        window.print();
        clearPrintMode();
    });
}

function clearPrintMode() {
    document.body.classList.remove('print-mode');
    document.body.classList.remove('print-all-mode');
}

function ensureStage1Styles() {
    if (document.getElementById(STAGE1_STYLE_ID)) {
        return;
    }

    const style = document.createElement('style');
    style.id = STAGE1_STYLE_ID;
    style.textContent = `
        .draft-toolbar {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-top: 10px;
            padding: 12px 14px;
            border: 1px dashed var(--border);
            border-radius: 12px;
            background: #f8fbfe;
        }
        .draft-toolbar--auto {
            background: #eef4fa;
            border-style: solid;
        }
        .draft-toolbar__buttons,
        .rsst-timer-panel__buttons {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .draft-toolbar__status,
        .data-transfer-note {
            font-size: 12px;
            color: var(--text-light);
        }
        .settings-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
            margin-top: 12px;
        }
        .settings-panel {
            border: 1px solid var(--border);
            border-radius: 12px;
            background: #fff;
            padding: 14px;
        }
        .settings-panel__title {
            font-size: 16px;
            font-weight: 700;
            color: var(--text);
        }
        .settings-panel__hint,
        .settings-list__empty {
            font-size: 12px;
            color: var(--text-light);
            margin-top: 4px;
        }
        .settings-panel__editor {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
        }
        .settings-panel__input {
            flex: 1 1 220px;
            min-width: 0;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: #fff;
            font: inherit;
        }
        .settings-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 12px;
        }
        .settings-list__item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: #f8fbfe;
        }
        .settings-list__label {
            font-size: 14px;
            color: var(--text);
            word-break: break-word;
        }
        .metric-chip-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 0 0 10px;
        }
        .metric-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 7px 10px;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: #fff;
            font-size: 12px;
        }
        .metric-chip__label {
            color: var(--text-light);
            font-weight: 600;
        }
        .metric-chip__value {
            color: var(--text);
            font-weight: 700;
        }
        .metric-chip--success {
            background: #eef9f2;
            border-color: #c7e3cf;
        }
        .metric-chip--alert {
            background: #fff6ea;
            border-color: #f0cfaa;
        }
        .metric-chip--info {
            background: #f7fbff;
        }
        .metric-subline,
        .monitor-status,
        .stage2-panel__hint,
        .stage2-panel__meta {
            font-size: 12px;
            color: var(--text-light);
        }
        .monitor-status--soon {
            color: var(--warning);
            font-weight: 700;
        }
        .monitor-status--overdue {
            color: var(--danger);
            font-weight: 700;
        }
        .trend-delta {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-size: 12px;
            font-weight: 700;
            color: var(--text-light);
        }
        .trend-delta--up {
            color: var(--primary);
        }
        .trend-delta--down {
            color: var(--warning);
        }
        .trend-delta--flat {
            color: var(--text-light);
        }
        .stage2-panel {
            margin-top: 12px;
            padding: 14px;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: #f8fbfe;
        }
        .stage2-panel__header {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-end;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 10px;
        }
        .stage2-panel__title {
            font-size: 16px;
            font-weight: 700;
            color: var(--text);
        }
        .stage2-panel__summary {
            font-size: 13px;
            line-height: 1.7;
            color: var(--text);
        }
        .stage3-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            margin-top: 12px;
        }
        .stage3-box {
            padding: 12px;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: #fff;
        }
        .stage3-box--wide {
            grid-column: 1 / -1;
        }
        .stage3-list {
            margin: 8px 0 0;
            padding-left: 18px;
            color: var(--text);
            font-size: 13px;
            line-height: 1.6;
        }
        .stage3-list li + li {
            margin-top: 6px;
        }
        .stage3-list__empty {
            list-style: none;
            margin-left: -18px;
            color: var(--text-light);
        }
        .stage3-action-bar {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 10px;
            margin: 10px 0 0;
        }
        .stage3-action-status {
            font-size: 12px;
            color: var(--text-light);
        }
        .stage3-recommendation {
            display: inline-flex;
            margin-top: 8px;
        }
        .stage3-note {
            margin-top: 10px;
            font-size: 12px;
            color: var(--text-light);
            line-height: 1.6;
        }
        .trend-table td {
            vertical-align: top;
        }
        .rsst-timer-panel {
            margin-top: 12px;
            padding: 14px;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: var(--section-bg);
        }
        .rsst-timer-panel__header {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }
        .rsst-timer-panel__display {
            font-size: 28px;
            font-weight: 700;
            color: var(--primary);
            font-family: 'Noto Serif JP', serif;
        }
        .rsst-timer-panel__hint {
            font-size: 12px;
            color: var(--text-light);
        }
        .rsst-tap-btn {
            width: 100%;
            justify-content: center;
            font-size: 20px;
            padding: 18px 20px;
            margin-top: 10px;
        }
        @media (max-width: 600px) {
            .draft-toolbar .btn,
            .rsst-timer-panel .btn,
            .settings-panel__editor .btn {
                flex: 1 1 140px;
                justify-content: center;
            }
            .settings-grid {
                grid-template-columns: 1fr;
            }
            .rsst-tap-btn {
                font-size: 18px;
            }
        }
    `;
    document.head.appendChild(style);
}

function buildEmptyMnaScores() {
    return { a: null, b: null, c: null, d: null, e: null, f: null };
}

function getActiveTabId() {
    const activeTab = document.querySelector('.tab-content.active');
    return activeTab ? String(activeTab.id || '').replace(/^tab-/, '') : 'patient';
}

function formatTimestampLabel(value) {
    if (!value) {
        return '未保存';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return String(value);
    }
    return parsed.toLocaleString('ja-JP', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function getDraftStore() {
    try {
        const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
        if (!raw) {
            return {};
        }
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
}

function setDraftStore(store) {
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(store));
}

function buildCurrentSnapshot(slot = '') {
    return {
        version: 1,
        slot,
        savedAt: new Date().toISOString(),
        activeTab: getActiveTabId(),
        fields: collectFieldValues(),
        mnaScores: { ...buildEmptyMnaScores(), ...mnaScores },
        mnaFieldMode: getSelectedMnaFieldMode() || currentMnaFieldMode || '',
    };
}

function isMeaningfulSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') {
        return false;
    }
    const fields = snapshot.fields && typeof snapshot.fields === 'object' ? snapshot.fields : {};
    const hasFieldValue = Object.values(fields).some((value) => String(value ?? '').trim() !== '');
    const scores = snapshot.mnaScores && typeof snapshot.mnaScores === 'object' ? snapshot.mnaScores : {};
    const hasScoreValue = Object.values(scores).some((value) => value !== null && value !== undefined && value !== '');
    return hasFieldValue || hasScoreValue;
}

function updateDraftStatusDisplays() {
    const store = getDraftStore();
    document.querySelectorAll('[data-draft-status]').forEach((element) => {
        const slot = element.getAttribute('data-draft-status') || '';
        const snapshot = store[slot];
        element.textContent = snapshot ? `下書き: ${formatTimestampLabel(snapshot.savedAt)}` : '下書きなし';
    });

    const autoStatus = document.getElementById('autoDraftStatus');
    if (autoStatus) {
        const autoSnapshot = store[AUTOSAVE_SLOT];
        autoStatus.textContent = autoSnapshot
            ? `自動下書き: ${formatTimestampLabel(autoSnapshot.savedAt)} / サーバー保存前の一時保存です`
            : '自動下書きなし';
    }
}

function saveDraftSlot(slot, options = {}) {
    const snapshot = buildCurrentSnapshot(slot);
    if (!isMeaningfulSnapshot(snapshot)) {
        if (!options.quiet) {
            showToast('⚠️ 下書きに保存する入力がありません');
        }
        return false;
    }

    const store = getDraftStore();
    store[slot] = snapshot;
    setDraftStore(store);
    updateDraftStatusDisplays();
    if (!options.quiet) {
        showToast(slot === AUTOSAVE_SLOT ? '📝 自動下書きを更新しました' : '📝 下書きを保存しました');
    }
    return true;
}

function restoreSnapshot(snapshot, options = {}) {
    if (!snapshot || typeof snapshot !== 'object') {
        if (!options.quiet) {
            showToast('⚠️ 読み込める下書きがありません');
        }
        return false;
    }

    restoreFieldValues(snapshot.fields || {});
    currentMnaFieldMode = snapshot.mnaFieldMode || '';
    mnaScores = { ...buildEmptyMnaScores(), ...(snapshot.mnaScores || {}) };
    restoreMnaSelections();
    calcMNAScore();
    if (typeof calcBMI === 'function') {
        calcBMI();
    }
    updateSummary();

    const targetTab = snapshot.activeTab || snapshot.slot;
    if (targetTab && DRAFT_SLOTS.includes(targetTab)) {
        showTab(targetTab);
    }

    updateDraftStatusDisplays();
    updateStage2Panels();
    if (!options.quiet) {
        showToast('📝 下書きを読み込みました');
    }
    return true;
}

function loadDraftSlot(slot, options = {}) {
    const store = getDraftStore();
    return restoreSnapshot(store[slot], options);
}

function deleteDraftSlot(slot, options = {}) {
    const store = getDraftStore();
    if (!store[slot]) {
        if (!options.quiet) {
            showToast('下書きはありません');
        }
        return false;
    }
    delete store[slot];
    setDraftStore(store);
    updateDraftStatusDisplays();
    if (!options.quiet) {
        showToast('🗑️ 下書きを削除しました');
    }
    return true;
}

function scheduleAutosave() {
    if (autosaveHandle) {
        window.clearTimeout(autosaveHandle);
    }
    autosaveHandle = window.setTimeout(() => {
        saveDraftSlot(AUTOSAVE_SLOT, { quiet: true });
    }, 900);
}

function attachDraftAutosave() {
    if (draftListenersBound) {
        return;
    }

    const handleInput = (event) => {
        const target = event.target;
        if (!target || !target.tagName || !['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) {
            return;
        }
        if (!target.id || target.dataset.skipPersist === '1' || NON_RECORD_FIELD_IDS.has(target.id) || target.type === 'file' || target.type === 'search') {
            return;
        }
        scheduleAutosave();
    };

    document.addEventListener('input', handleInput, true);
    document.addEventListener('change', handleInput, true);
    draftListenersBound = true;
}

function ensureDraftControls() {
    const actionBarConfigs = [
        { slot: 'patient', selector: '#tab-patient .action-bar.no-print' },
        { slot: 'oral', selector: '#tab-oral .action-bar.no-print' },
        { slot: 'mna', selector: '#tab-mna .action-bar.no-print' },
        { slot: 'summary', selector: '#tab-summary .card.no-print .action-bar' },
    ];

    actionBarConfigs.forEach(({ slot, selector }) => {
        const actionBar = document.querySelector(selector);
        if (!actionBar || document.querySelector(`[data-draft-slot="${slot}"]`)) {
            return;
        }

        const toolbar = document.createElement('div');
        toolbar.className = 'draft-toolbar no-print';
        toolbar.setAttribute('data-draft-slot', slot);
        toolbar.innerHTML = `
            <div class="draft-toolbar__buttons">
                <button type="button" class="btn btn-outline btn-sm" data-draft-action="save">📝 このタブを下書き保存</button>
                <button type="button" class="btn btn-outline btn-sm" data-draft-action="load">📂 下書き読込</button>
                <button type="button" class="btn btn-outline btn-sm" data-draft-action="delete">🗑️ 下書き削除</button>
            </div>
            <div class="draft-toolbar__status" data-draft-status="${slot}">下書きなし</div>
        `;
        actionBar.insertAdjacentElement('afterend', toolbar);

        toolbar.querySelector('[data-draft-action="save"]').addEventListener('click', () => saveDraftSlot(slot));
        toolbar.querySelector('[data-draft-action="load"]').addEventListener('click', () => loadDraftSlot(slot));
        toolbar.querySelector('[data-draft-action="delete"]').addEventListener('click', () => deleteDraftSlot(slot));
    });

    const summaryActionBar = document.querySelector('#tab-summary .card.no-print .action-bar');
    if (summaryActionBar && !document.getElementById('autoDraftPanel')) {
        const autoPanel = document.createElement('div');
        autoPanel.id = 'autoDraftPanel';
        autoPanel.className = 'draft-toolbar draft-toolbar--auto no-print';
        autoPanel.innerHTML = `
            <div class="draft-toolbar__buttons">
                <button type="button" class="btn btn-outline btn-sm" id="loadAutoDraftButton">📂 自動下書き読込</button>
                <button type="button" class="btn btn-outline btn-sm" id="deleteAutoDraftButton">🗑️ 自動下書き削除</button>
            </div>
            <div class="draft-toolbar__status" id="autoDraftStatus">自動下書きなし</div>
        `;
        summaryActionBar.insertAdjacentElement('afterend', autoPanel);
        autoPanel.querySelector('#loadAutoDraftButton').addEventListener('click', () => loadDraftSlot(AUTOSAVE_SLOT));
        autoPanel.querySelector('#deleteAutoDraftButton').addEventListener('click', () => deleteDraftSlot(AUTOSAVE_SLOT));
    }

    updateDraftStatusDisplays();
}

function getLocalSettingArray(key) {
    return Array.isArray(sharedSettingsState[key]) ? [...sharedSettingsState[key]] : [];
}

function setLocalSettingArray(key, values) {
    sharedSettingsState = {
        ...sharedSettingsState,
        [key]: mergeUniqueTextValues([], values || []),
    };
}

function mergeUniqueTextValues(existingValues, incomingValues) {
    const seen = new Set();
    return [...existingValues, ...incomingValues]
        .map((value) => String(value || '').trim())
        .filter((value) => {
            if (!value) {
                return false;
            }
            const normalized = value.toLowerCase();
            if (seen.has(normalized)) {
                return false;
            }
            seen.add(normalized);
            return true;
        });
}

function getManagedFieldConfigByFieldId(fieldId) {
    return MANAGED_FIELD_CONFIGS.find((config) => config.fieldId === fieldId) || null;
}

async function ensureLocalSettingsInitialized() {
    try {
        applySharedSettingsState(await fetchSharedSettings());
    } catch (error) {
        console.error(error);
        applySharedSettingsState(buildDefaultSharedSettings());
        showToast(error.message || '一覧設定の同期に失敗しました');
    }
}

function getManagedFieldNodes(config) {
    const field = document.getElementById(config.fieldId);
    const select = document.getElementById(config.selectId);
    const custom = document.getElementById(config.customId);
    if (!field || !select || !custom) {
        return null;
    }
    return { field, select, custom };
}

function toggleManagedCustomInput(nodes, visible) {
    nodes.custom.style.display = visible ? 'block' : 'none';
}

function syncManagedFieldStoredValue(config, options = {}) {
    const nodes = getManagedFieldNodes(config);
    if (!nodes) {
        return;
    }

    const selectValue = String(nodes.select.value || '');
    let storedValue = '';
    if (selectValue === MANAGED_SELECT_CUSTOM_VALUE) {
        storedValue = String(nodes.custom.value || '').trim();
        toggleManagedCustomInput(nodes, true);
    } else {
        storedValue = selectValue.trim();
        if (!storedValue) {
            nodes.custom.value = '';
        }
        toggleManagedCustomInput(nodes, false);
    }
    nodes.field.value = storedValue;

    if (options.fromUser) {
        scheduleAutosave();
    }
}

function bindManagedFieldEvents(config, nodes) {
    if (nodes.select.dataset.boundManagedField !== '1') {
        nodes.select.addEventListener('change', () => {
            if (nodes.select.value !== MANAGED_SELECT_CUSTOM_VALUE) {
                nodes.custom.value = '';
            }
            syncManagedFieldStoredValue(config, { fromUser: true });
            if (nodes.select.value === MANAGED_SELECT_CUSTOM_VALUE) {
                nodes.custom.focus();
            }
        });
        nodes.select.dataset.boundManagedField = '1';
    }

    if (nodes.custom.dataset.boundManagedField !== '1') {
        nodes.custom.addEventListener('input', () => {
            if (nodes.select.value === MANAGED_SELECT_CUSTOM_VALUE) {
                syncManagedFieldStoredValue(config, { fromUser: true });
            }
        });
        nodes.custom.dataset.boundManagedField = '1';
    }
}

function renderManagedSelectField(config) {
    const nodes = getManagedFieldNodes(config);
    if (!nodes) {
        return;
    }

    const optionValues = mergeUniqueTextValues([], getLocalSettingArray(config.settingKey));
    const storedValue = String(nodes.field.value || '').trim();
    const fragment = document.createDocumentFragment();

    const emptyOption = document.createElement('option');
    emptyOption.value = '';
    emptyOption.textContent = '選択';
    fragment.appendChild(emptyOption);

    optionValues.forEach((value) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        fragment.appendChild(option);
    });

    const customOption = document.createElement('option');
    customOption.value = MANAGED_SELECT_CUSTOM_VALUE;
    customOption.textContent = 'その他（自由入力）';
    fragment.appendChild(customOption);

    nodes.select.innerHTML = '';
    nodes.select.appendChild(fragment);

    if (storedValue && optionValues.includes(storedValue)) {
        nodes.select.value = storedValue;
        nodes.custom.value = '';
        toggleManagedCustomInput(nodes, false);
    } else if (storedValue) {
        nodes.select.value = MANAGED_SELECT_CUSTOM_VALUE;
        nodes.custom.value = storedValue;
        toggleManagedCustomInput(nodes, true);
    } else {
        nodes.select.value = '';
        nodes.custom.value = '';
        toggleManagedCustomInput(nodes, false);
    }

    bindManagedFieldEvents(config, nodes);
}

function renderStaffSelect() {
    const config = getManagedFieldConfigByFieldId('staff');
    if (config) {
        renderManagedSelectField(config);
    }
}

function renderDentistSelect() {
    const config = getManagedFieldConfigByFieldId('dentist');
    if (config) {
        renderManagedSelectField(config);
    }
}

function syncManagedPersonSelectors() {
    MANAGED_FIELD_CONFIGS.forEach((config) => renderManagedSelectField(config));
}

function renderSettingsPanel(config) {
    const list = document.getElementById(config.settingsListId);
    if (!list) {
        return;
    }

    list.innerHTML = '';
    const values = getLocalSettingArray(config.settingKey);
    if (!values.length) {
        const empty = document.createElement('div');
        empty.className = 'settings-list__empty';
        empty.textContent = config.emptyText;
        list.appendChild(empty);
        return;
    }

    values.forEach((value) => {
        const item = document.createElement('div');
        item.className = 'settings-list__item';

        const label = document.createElement('div');
        label.className = 'settings-list__label';
        label.textContent = value;
        item.appendChild(label);

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'btn btn-danger btn-sm';
        removeButton.textContent = '削除';
        removeButton.addEventListener('click', async () => {
            if (!window.confirm(config.confirmDeleteMessage)) {
                return;
            }
            const nextValues = getLocalSettingArray(config.settingKey).filter((currentValue) => currentValue !== value);
            try {
                await saveSharedSettingsState({ [config.settingKey]: nextValues });
                renderSettingsPanels();
                syncManagedPersonSelectors();
                showToast(config.removeSuccessMessage);
            } catch (error) {
                console.error(error);
                showToast(error.message || `${config.label}の保存に失敗しました`);
            }
        });
        item.appendChild(removeButton);
        list.appendChild(item);
    });
}

function renderSettingsPanels() {
    MANAGED_FIELD_CONFIGS.forEach((config) => renderSettingsPanel(config));
}

async function addManagedSettingValue(config) {
    const input = document.getElementById(config.settingsInputId);
    if (!input) {
        return;
    }

    const nextValue = String(input.value || '').trim();
    if (!nextValue) {
        showToast(`⚠️ ${config.label}を入力してください`);
        return;
    }
    if (nextValue === MANAGED_SELECT_CUSTOM_VALUE) {
        showToast('⚠️ その名称は登録できません');
        return;
    }

    const currentValues = getLocalSettingArray(config.settingKey);
    const mergedValues = mergeUniqueTextValues(currentValues, [nextValue]);
    if (mergedValues.length == currentValues.length) {
        showToast(`⚠️ ${config.duplicateMessage}`);
        return;
    }

    try {
        await saveSharedSettingsState({ [config.settingKey]: mergedValues });
        input.value = '';
        renderSettingsPanels();
        syncManagedPersonSelectors();
        showToast(config.addSuccessMessage);
    } catch (error) {
        console.error(error);
        showToast(error.message || `${config.label}の保存に失敗しました`);
    }
}

function ensureSettingsControls() {
    MANAGED_FIELD_CONFIGS.forEach((config) => {
        const input = document.getElementById(config.settingsInputId);
        const addButton = document.getElementById(config.addButtonId);
        if (!input || !addButton) {
            return;
        }

        if (addButton.dataset.boundSettingsAdd !== '1') {
            addButton.addEventListener('click', () => {
                addManagedSettingValue(config);
            });
            addButton.dataset.boundSettingsAdd = '1';
        }

        if (input.dataset.boundSettingsEnter !== '1') {
            input.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    addManagedSettingValue(config);
                }
            });
            input.dataset.boundSettingsEnter = '1';
        }
    });

    renderSettingsPanels();
}

function installManagedFieldHooks() {
    if (managedFieldHooksInstalled) {
        return;
    }

    if (typeof clearAll === 'function') {
        const originalClearAll = clearAll;
        clearAll = function(...args) {
            const result = originalClearAll.apply(this, args);
            syncManagedPersonSelectors();
            return result;
        };
        window.clearAll = clearAll;
    }

    managedFieldHooksInstalled = true;
}

function ensureImportInput() {
    let input = document.getElementById(IMPORT_INPUT_ID);
    if (input) {
        return input;
    }

    input = document.createElement('input');
    input.id = IMPORT_INPUT_ID;
    input.type = 'file';
    input.accept = '.json,application/json';
    input.style.display = 'none';
    input.dataset.skipPersist = '1';
    input.addEventListener('change', handleImportSelection);
    document.body.appendChild(input);
    return input;
}

function ensureDataTransferControls() {
    const summaryActionBar = document.querySelector('#tab-summary .card.no-print .action-bar');
    if (!summaryActionBar) {
        return;
    }

    if (!document.getElementById('exportDataButton')) {
        const exportButton = document.createElement('button');
        exportButton.type = 'button';
        exportButton.id = 'exportDataButton';
        exportButton.className = 'btn btn-outline';
        exportButton.textContent = '📤 データ書出し';
        exportButton.addEventListener('click', exportAppData);
        summaryActionBar.appendChild(exportButton);
    }

    if (!document.getElementById('importDataButton')) {
        const importButton = document.createElement('button');
        importButton.type = 'button';
        importButton.id = 'importDataButton';
        importButton.className = 'btn btn-outline';
        importButton.textContent = '📥 データ読込';
        importButton.addEventListener('click', () => {
            const input = ensureImportInput();
            input.value = '';
            input.click();
        });
        summaryActionBar.appendChild(importButton);
    }

    if (!document.getElementById('dataTransferNote')) {
        const note = document.createElement('div');
        note.id = 'dataTransferNote';
        note.className = 'data-transfer-note no-print';
        note.textContent = '共有記録・担当者一覧・かかりつけ医一覧はサーバーへ、下書きはこの端末へ保存されます。';
        summaryActionBar.insertAdjacentElement('afterend', note);
    }

    ensureImportInput();
}

async function exportAppData() {
    try {
        const latestRecords = await fetchRecords();
        const payload = {
            schemaVersion: 1,
            exportedAt: new Date().toISOString(),
            records: latestRecords,
            localData: {
                drafts: getDraftStore(),
                staffList: getLocalSettingArray('staffList'),
                dentistList: getLocalSettingArray('dentistList'),
            },
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `kouku-kinou-export-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        showToast('📤 データを書き出しました');
    } catch (error) {
        console.error(error);
        showToast(error.message || 'データの書き出しに失敗しました');
    }
}

function normalizeImportedBundle(payload) {
    if (Array.isArray(payload)) {
        return { records: payload, drafts: {}, staffList: [], dentistList: [] };
    }

    const safePayload = payload && typeof payload === 'object' ? payload : {};
    const localData = safePayload.localData && typeof safePayload.localData === 'object' ? safePayload.localData : {};
    return {
        records: Array.isArray(safePayload.records) ? safePayload.records : [],
        drafts: localData.drafts && typeof localData.drafts === 'object' ? localData.drafts : (safePayload.drafts && typeof safePayload.drafts === 'object' ? safePayload.drafts : {}),
        staffList: Array.isArray(localData.staffList) ? localData.staffList : (Array.isArray(safePayload.staffList) ? safePayload.staffList : []),
        dentistList: Array.isArray(localData.dentistList) ? localData.dentistList : (Array.isArray(safePayload.dentistList) ? safePayload.dentistList : []),
    };
}

function sanitizeImportedRecord(record) {
    const cloned = JSON.parse(JSON.stringify(record || {}));
    delete cloned.id;
    delete cloned.saveMode;
    delete cloned.patientKey;
    delete cloned.assessmentKey;
    delete cloned.savedAt;
    delete cloned.updatedAt;
    delete cloned.patient;

    if (!cloned.fields || typeof cloned.fields !== 'object' || Array.isArray(cloned.fields)) {
        cloned.fields = {};
    }
    if (!cloned.fields.name && cloned.name) {
        cloned.fields.name = cloned.name;
    }
    if (!cloned.fields.furigana && cloned.furigana) {
        cloned.fields.furigana = cloned.furigana;
    }
    if (!cloned.fields.birthdate && cloned.birthdate) {
        cloned.fields.birthdate = cloned.birthdate;
    }
    if (!cloned.fields.evalDate && cloned.date) {
        cloned.fields.evalDate = cloned.date;
    }
    return cloned;
}

async function clearSharedRecords() {
    const existingRecords = await fetchRecords();
    for (const record of existingRecords) {
        await removeRecord(record.id);
    }
}

function normalizeDraftStore(rawStore) {
    if (!rawStore || typeof rawStore !== 'object' || Array.isArray(rawStore)) {
        return {};
    }
    const normalized = {};
    Object.entries(rawStore).forEach(([slot, snapshot]) => {
        if (snapshot && typeof snapshot === 'object' && !Array.isArray(snapshot)) {
            normalized[String(slot)] = snapshot;
        }
    });
    return normalized;
}

async function applyImportedLocalData(bundle, replaceLocalData) {
    const incomingDrafts = normalizeDraftStore(bundle.drafts);
    const nextDrafts = replaceLocalData ? incomingDrafts : { ...getDraftStore(), ...incomingDrafts };
    setDraftStore(nextDrafts);

    const nextStaffList = replaceLocalData
        ? mergeUniqueTextValues([], bundle.staffList || [])
        : mergeUniqueTextValues(getLocalSettingArray('staffList'), bundle.staffList || []);
    const nextDentistList = replaceLocalData
        ? mergeUniqueTextValues([], bundle.dentistList || [])
        : mergeUniqueTextValues(getLocalSettingArray('dentistList'), bundle.dentistList || []);
    await saveSharedSettingsState({
        staffList: nextStaffList,
        dentistList: nextDentistList,
    });

    if (typeof renderStaffSelect === 'function') {
        renderStaffSelect();
    }
    if (typeof renderDentistSelect === 'function') {
        renderDentistSelect();
    }
    if (typeof renderSettingsPanels === 'function') {
        renderSettingsPanels();
    }
    updateDraftStatusDisplays();
}

async function handleImportSelection(event) {
    const input = event.target;
    const file = input.files && input.files[0];
    if (!file) {
        return;
    }

    try {
        const rawText = await file.text();
        const payload = JSON.parse(rawText);
        const bundle = normalizeImportedBundle(payload);
        const replaceSharedRecords = window.confirm([
            '共有記録を全件置換しますか？',
            'OK = 置換 / キャンセル = 追加',
        ].join('\\n'));
        const replaceLocalData = window.confirm([
            '下書き（この端末）と担当者一覧・かかりつけ医一覧（共有）を置換しますか？',
            'OK = 置換 / キャンセル = 既存へ追加',
        ].join('\\n'));

        if (replaceSharedRecords) {
            await clearSharedRecords();
        }

        let importedCount = 0;
        let failedCount = 0;
        for (const record of bundle.records) {
            try {
                await persistRecord(sanitizeImportedRecord(record));
                importedCount += 1;
            } catch (error) {
                console.error(error);
                failedCount += 1;
            }
        }

        await applyImportedLocalData(bundle, replaceLocalData);
        records = await fetchRecords();
        renderHistory();
        showToast(failedCount > 0 ? `📥 ${importedCount}件取込 / ${failedCount}件失敗` : `📥 ${importedCount}件を取り込みました`);
    } catch (error) {
        console.error(error);
        showToast(error.message || 'データの読み込みに失敗しました');
    } finally {
        input.value = '';
    }
}

function getRsstCountInput() {
    return document.getElementById('rsst_count');
}

function getRsstTimeInput() {
    return document.getElementById('rsst_time');
}

function updateRsstDisplay() {
    const display = document.getElementById('rsstTimerDisplay');
    if (!display) {
        return;
    }
    display.textContent = `${rsstRemainingSeconds}秒`;
}

function resetRsstTimer(options = {}) {
    if (rsstTimerHandle) {
        window.clearInterval(rsstTimerHandle);
        rsstTimerHandle = 0;
    }
    rsstRemainingSeconds = RSST_DEFAULT_SECONDS;
    const timeInput = getRsstTimeInput();
    const countInput = getRsstCountInput();
    if (timeInput) {
        timeInput.value = String(RSST_DEFAULT_SECONDS);
    }
    if (countInput) {
        countInput.value = '0';
    }
    updateRsstDisplay();
    if (!options.quiet) {
        showToast('⏱️ RSSTタイマーをリセットしました');
    }
}

function incrementRsstCount() {
    const countInput = getRsstCountInput();
    if (!countInput) {
        return;
    }
    const current = Number.parseInt(countInput.value || '0', 10) || 0;
    countInput.value = String(current + 1);
    countInput.dispatchEvent(new Event('input', { bubbles: true }));
}

function startRsstTimer() {
    if (rsstTimerHandle) {
        return;
    }

    const timeInput = getRsstTimeInput();
    if (timeInput) {
        timeInput.value = String(RSST_DEFAULT_SECONDS);
    }
    rsstRemainingSeconds = RSST_DEFAULT_SECONDS;
    updateRsstDisplay();

    rsstTimerHandle = window.setInterval(() => {
        rsstRemainingSeconds -= 1;
        updateRsstDisplay();
        if (rsstRemainingSeconds <= 0) {
            window.clearInterval(rsstTimerHandle);
            rsstTimerHandle = 0;
            showToast('✅ RSST 30秒計測が終了しました');
        }
    }, 1000);
}

function ensureRsstTimerTools() {
    const rsstJudge = document.getElementById('rsst_judge');
    if (!rsstJudge || document.getElementById('rsstTimerPanel')) {
        return;
    }

    const anchor = rsstJudge.closest('.form-group');
    if (!anchor) {
        return;
    }

    const panel = document.createElement('div');
    panel.id = 'rsstTimerPanel';
    panel.className = 'rsst-timer-panel';
    panel.innerHTML = `
        <div class="rsst-timer-panel__header">
            <div>
                <div class="section-label" style="margin:0 0 6px 0;">RSST 30秒タイマー</div>
                <div class="rsst-timer-panel__hint">開始後は大きなカウントボタンで回数を加算できます。</div>
            </div>
            <div class="rsst-timer-panel__display" id="rsstTimerDisplay">30秒</div>
        </div>
        <div class="rsst-timer-panel__buttons">
            <button type="button" class="btn btn-primary" id="rsstTimerStartButton">▶ 開始</button>
            <button type="button" class="btn btn-outline" id="rsstTimerResetButton">↺ リセット</button>
        </div>
        <button type="button" class="btn btn-accent rsst-tap-btn" id="rsstTapButton">＋ 1 回カウント</button>
    `;
    anchor.insertAdjacentElement('afterend', panel);

    panel.querySelector('#rsstTimerStartButton').addEventListener('click', startRsstTimer);
    panel.querySelector('#rsstTimerResetButton').addEventListener('click', () => resetRsstTimer());
    panel.querySelector('#rsstTapButton').addEventListener('click', incrementRsstCount);
    resetRsstTimer({ quiet: true });
}

function getCurrentPatientFormState() {
    const name = getFieldElementValue('name').trim();
    const birthdate = getFieldElementValue('birthdate').trim();
    const evalDate = getFieldElementValue('evalDate').trim() || new Date().toISOString().slice(0, 10);
    const weight = toMetricNumber(getFieldElementValue('weight'));
    const height = toMetricNumber(getFieldElementValue('height'));
    let bmi = toMetricNumber(getFieldElementValue('bmi'));
    if (bmi === null && weight !== null && height !== null && height > 0) {
        bmi = Number((weight / ((height / 100) ** 2)).toFixed(1));
    }
    return {
        name,
        birthdate,
        evalDate,
        weight,
        height,
        bmi,
        patientKey: buildPatientLookupKey(name, birthdate),
    };
}

function ensureBmiSupportPanel() {
    const bmiInput = document.getElementById('bmi');
    if (!bmiInput || document.getElementById('nutritionSupportPanel')) {
        return;
    }

    const patientGrid = bmiInput.closest('.form-grid');
    if (!patientGrid) {
        return;
    }

    const panel = document.createElement('div');
    panel.id = 'nutritionSupportPanel';
    panel.className = 'stage2-panel';
    panel.innerHTML = `
        <div class="stage2-panel__header">
            <div>
                <div class="stage2-panel__title">BMI サポート</div>
                <div class="stage2-panel__hint">年齢帯の参考帯と MNA F1 の目安を表示します。</div>
            </div>
        </div>
        <div id="nutritionSupportChips" class="metric-chip-list"></div>
        <div id="nutritionSupportSummary" class="stage2-panel__summary">生年月日・体重・身長を入力すると参考表示を出します。</div>
    `;
    patientGrid.insertAdjacentElement('afterend', panel);
}

function ensurePatientTrendPanel() {
    const summaryCard = document.querySelector('#tab-summary > .card');
    const divider = summaryCard ? summaryCard.querySelector('.divider') : null;
    if (!summaryCard || !divider || document.getElementById('patientTrendPanel')) {
        return;
    }

    const panel = document.createElement('div');
    panel.id = 'patientTrendPanel';
    panel.className = 'stage2-panel';
    panel.innerHTML = `
        <div class="stage2-panel__header">
            <div>
                <div class="stage2-panel__title">体重・BMI 推移</div>
                <div class="stage2-panel__hint">保存済みの同一利用者履歴から直近の変化を表示します。</div>
            </div>
            <div id="patientTrendMeta" class="stage2-panel__meta"></div>
        </div>
        <div id="patientTrendSummary" class="metric-chip-list"></div>
        <div style="overflow-x:auto;">
            <table class="history-table trend-table">
                <thead>
                    <tr>
                        <th>評価日</th>
                        <th>体重</th>
                        <th>BMI</th>
                        <th>体重差</th>
                        <th>BMI差</th>
                        <th>栄養判定</th>
                    </tr>
                </thead>
                <tbody id="patientTrendBody">
                    <tr><td colspan="6"><div class="empty-state"><div class="icon">📈</div>利用者を選ぶと推移を表示します</div></td></tr>
                </tbody>
            </table>
        </div>
    `;
    divider.insertAdjacentElement('beforebegin', panel);
}

function ensureStage2Panels() {
    ensureBmiSupportPanel();
    ensurePatientTrendPanel();
}

function ensureClinicalSupportPanel() {
    const summaryCard = document.querySelector('#tab-summary > .card');
    const divider = summaryCard ? summaryCard.querySelector('.divider') : null;
    const trendPanel = document.getElementById('patientTrendPanel');
    if (!summaryCard || !divider || document.getElementById('clinicalSupportPanel')) {
        return;
    }

    const panel = document.createElement('div');
    panel.id = 'clinicalSupportPanel';
    panel.className = 'stage2-panel stage3-panel';
    panel.innerHTML = `
        <div class="stage2-panel__header">
            <div>
                <div class="stage2-panel__title">臨床語化・差分アシスト</div>
                <div class="stage2-panel__hint">現在の入力から所見候補と食形態の提案を整理します。</div>
            </div>
            <div id="clinicalSupportMeta" class="stage2-panel__meta"></div>
        </div>
        <div id="clinicalSupportChips" class="metric-chip-list"></div>
        <div id="clinicalSupportSummary" class="stage2-panel__summary">口腔タブを入力すると臨床語化を表示します。</div>
        <div class="stage3-action-bar">
            <button type="button" class="btn btn-outline" id="applyClinicalCommentButton">📝 コメント欄へ追記</button>
            <button type="button" class="btn btn-outline" id="convertLegacyClinicalCommentButton">🔁 旧形式メモを変換</button>
            <div id="clinicalCommentActionStatus" class="stage3-action-status">既存コメントは残したまま末尾へ追記します。</div>
        </div>
        <div class="stage3-grid">
            <section class="stage3-box">
                <div class="section-label">所見候補</div>
                <div id="clinicalFindingList"></div>
            </section>
            <section class="stage3-box">
                <div class="section-label">差分アラート</div>
                <div id="clinicalAlertList"></div>
            </section>
            <section class="stage3-box stage3-box--wide">
                <div class="section-label">食形態提案</div>
                <div id="foodRecommendationLabel" class="stage3-recommendation"></div>
                <div id="foodRecommendationList"></div>
                <div class="stage3-note">提案は記録補助です。最終判断は主治医・歯科医師・ST等と確認してください。</div>
            </section>
        </div>
    `;

    const applyButton = panel.querySelector('#applyClinicalCommentButton');
    if (applyButton) {
        applyButton.addEventListener('click', applyClinicalCommentDraft);
    }
    const convertButton = panel.querySelector('#convertLegacyClinicalCommentButton');
    if (convertButton) {
        convertButton.addEventListener('click', convertLegacyClinicalCommentBlock);
    }

    if (trendPanel) {
        trendPanel.insertAdjacentElement('afterend', panel);
        return;
    }
    divider.insertAdjacentElement('beforebegin', panel);
}

function ensureStage3Panels() {
    ensureClinicalSupportPanel();
}

function stripTerminalPunctuation(value) {
    let text = String(value || '').trim();
    while (text) {
        const lastChar = text.slice(-1);
        if (lastChar === '。' || lastChar === '．' || lastChar === '、' || lastChar === ',') {
            text = text.slice(0, -1).trim();
            continue;
        }
        break;
    }
    return text;
}

function ensureSentenceText(value) {
    const text = String(value || '').trim();
    if (!text) {
        return '';
    }
    const lastChar = text.slice(-1);
    if (lastChar === '。' || lastChar === '！' || lastChar === '？') {
        return text;
    }
    return `${text}。`;
}

function isActionableStage3Message(value) {
    const text = String(value || '').trim();
    if (!text) {
        return false;
    }
    return ![
        '入力すると',
        '入力後に',
        '今回保存後から',
        '保存済み履歴がない',
        '氏名と生年月日を入力すると',
        '前回比較の準備が整う',
    ].some((snippet) => text.includes(snippet));
}

function joinCommentItems(items, limit) {
    const selected = (items || [])
        .map((item) => stripTerminalPunctuation(item))
        .filter(Boolean)
        .slice(0, limit);
    if (!selected.length) {
        return '';
    }
    return `${selected.join('、')}。`;
}

function normalizeCommentBlock(value) {
    return String(value || '')
    .split(String.fromCharCode(10))
        .map((line) => line.trim())
        .filter(Boolean)
    .join(String.fromCharCode(10));
}

function stripClinicalCommentMarkers(value) {
    return normalizeCommentBlock(
        String(value || '')
            .replace(CLINICAL_COMMENT_START_MARKER, '')
            .replace(CLINICAL_COMMENT_END_MARKER, '')
    );
}

function buildClinicalCommentDraft(data) {
    if (!data || data.recommendationLabel === '入力待ち') {
        return '';
    }

    const summaryLine = ensureSentenceText(
        String(data.summaryText || '')
            .split('。')
            .map((item) => item.trim())
            .filter((item) => item && !item.includes('診断ではなく') && !item.includes('保存記録を基準に表示'))
            .join('。')
    );
    const findingText = joinCommentItems((data.findingItems || []).filter((item) => isActionableStage3Message(item)), 3);
    const alertText = joinCommentItems((data.alertItems || []).filter((item) => isActionableStage3Message(item)), 2);
    const recommendationText = joinCommentItems((data.recommendationItems || []).filter((item) => isActionableStage3Message(item)), 2);

    const lines = [];
    if (summaryLine) {
        lines.push(summaryLine);
    }
    if (findingText) {
        lines.push(`所見候補: ${findingText}`);
    }
    if (alertText) {
        lines.push(`変化: ${alertText}`);
    }
    if (recommendationText) {
        lines.push(`支援方針（${data.recommendationLabel}）: ${recommendationText}`);
    }

    return buildClinicalCommentBlock(lines);
}

function buildClinicalPrintLines(data) {
    if (!data || data.recommendationLabel === '入力待ち') {
        return ['所見: 口腔タブ未入力のため、臨床語化・差分要点は未作成です。'];
    }

    const findingText = joinCommentItems((data.findingItems || []).filter((item) => isActionableStage3Message(item)), 2);
    const actionableAlerts = (data.alertItems || []).filter((item) => isActionableStage3Message(item));
    const safeAlert = (data.alertItems || []).find((item) => {
        return item.includes('前回保存に口腔詳細がない')
            || item.includes('保存済み履歴がない')
            || item.includes('氏名と生年月日を入力すると');
    });
    let alertText = '';
    if (actionableAlerts.length) {
        alertText = joinCommentItems(actionableAlerts, safeAlert ? 1 : 2);
        if (safeAlert) {
            alertText = `${alertText} ${ensureSentenceText(stripTerminalPunctuation(safeAlert))}`.trim();
        }
    } else if (safeAlert) {
        alertText = ensureSentenceText(stripTerminalPunctuation(safeAlert));
    }

    const recommendationText = joinCommentItems((data.recommendationItems || []).filter((item) => isActionableStage3Message(item)), 1);
    const lines = [];
    lines.push(findingText ? `所見: ${findingText}` : '所見: 顕著な口腔所見候補は少なく、経過観察中心です。');
    if (alertText) {
        lines.push(`変化: ${alertText}`);
    }
    lines.push(recommendationText ? `食形態: ${data.recommendationLabel}。${recommendationText}` : `食形態: ${data.recommendationLabel}。`);
    return lines.slice(0, 3);
}

function updateClinicalCommentActionState(data) {
    const button = document.getElementById('applyClinicalCommentButton');
    const convertButton = document.getElementById('convertLegacyClinicalCommentButton');
    const status = document.getElementById('clinicalCommentActionStatus');
    if (!button || !convertButton || !status) {
        return;
    }

    const draft = normalizeCommentBlock(data ? data.commentDraft : '');
    const hasDraft = Boolean(draft);
    const sections = splitClinicalCommentSections(getFieldElementValue('summary_comment'));
    const hasLegacyBlock = sections.hasBlock && sections.isLegacyBlock;
    button.disabled = !hasDraft || hasLegacyBlock;
    convertButton.disabled = !hasLegacyBlock;
    if (hasLegacyBlock) {
        status.textContent = '旧形式の口腔機能メモがあります。変換すると後続の手入力を残したまま新形式へ切り替えます。';
        return;
    }
    status.textContent = hasDraft
        ? '既存コメントは残したまま末尾へ追記します。'
        : '口腔項目が不足しているため、まだ追記できません。';
}

function convertLegacyClinicalCommentBlock() {
    const commentField = document.getElementById('summary_comment');
    if (!commentField) {
        showToast('⚠️ コメント欄が見つかりません');
        return;
    }

    const currentValue = String(commentField.value || '').trim();
    const sections = splitClinicalCommentSections(currentValue);
    if (!sections.hasBlock || !sections.isLegacyBlock) {
        showToast('ℹ️ 変換が必要な旧形式メモは見つかりません');
        return;
    }

    const legacy = parseLegacyClinicalCommentBlock(sections.block);
    const paragraphGap = String.fromCharCode(10) + String.fromCharCode(10);
    commentField.value = [sections.before, legacy.generatedBlock, legacy.trailingText, sections.after]
        .filter(Boolean)
        .join(paragraphGap);
    commentField.dispatchEvent(new Event('input', { bubbles: true }));
    commentField.dispatchEvent(new Event('change', { bubbles: true }));
    commentField.focus();
    if (typeof commentField.setSelectionRange === 'function') {
        const cursor = commentField.value.length;
        commentField.setSelectionRange(cursor, cursor);
    }
    updateClinicalCommentActionState(latestClinicalSupportData || buildClinicalSupportData());
    showToast(legacy.trailingText
        ? '🔁 旧形式メモを変換し、後続の手入力を残しました'
        : '🔁 旧形式メモを新形式へ変換しました');
}

function applyClinicalCommentDraft() {
    const commentField = document.getElementById('summary_comment');
    if (!commentField) {
        showToast('⚠️ コメント欄が見つかりません');
        return;
    }

    const data = latestClinicalSupportData || buildClinicalSupportData();
    const draft = normalizeCommentBlock(data ? data.commentDraft : '');
    if (!draft) {
        showToast('⚠️ 反映できる所見候補がまだありません');
        return;
    }

    const currentValue = String(commentField.value || '').trim();
    const sections = splitClinicalCommentSections(currentValue);
    const normalizedDraft = stripClinicalCommentMarkers(draft);
    const normalizedExistingBlock = stripClinicalCommentMarkers(sections.block);
    if (sections.hasBlock && normalizedExistingBlock === normalizedDraft) {
        commentField.focus();
        showToast('ℹ️ 同じ所見候補はすでにコメント欄へ反映済みです');
        return;
    }

    const paragraphGap = String.fromCharCode(10) + String.fromCharCode(10);
    if (sections.hasBlock && sections.isLegacyBlock) {
        commentField.focus();
        showToast('⚠️ 旧形式の口腔機能メモがあります。先に「旧形式メモを変換」を実行してください');
        return;
    }

    if (sections.hasBlock) {
        commentField.value = [sections.before, draft, sections.after].filter(Boolean).join(paragraphGap);
    } else {
        commentField.value = currentValue ? currentValue + paragraphGap + draft : draft;
    }
    commentField.dispatchEvent(new Event('input', { bubbles: true }));
    commentField.dispatchEvent(new Event('change', { bubbles: true }));
    commentField.focus();
    if (typeof commentField.setSelectionRange === 'function') {
        const cursor = commentField.value.length;
        commentField.setSelectionRange(cursor, cursor);
    }
    updateClinicalCommentActionState(latestClinicalSupportData || buildClinicalSupportData());
    if (sections.hasBlock) {
        showToast('📝 口腔機能メモを更新しました');
        return;
    }
    showToast(currentValue ? '📝 所見候補をコメント欄へ追記しました' : '📝 所見候補をコメント欄へ反映しました');
}

function buildClinicalSupportData() {
    const patientState = getCurrentPatientFormState();
    const oralState = getCurrentOralAssessmentState();
    const history = patientState.patientKey ? (buildPatientRecordGroups(records).get(patientState.patientKey) || []) : [];
    const comparisonRecord = getComparisonHistoryRecord(history, patientState.evalDate);
    const comparisonOralState = comparisonRecord ? getRecordOralAssessmentState(comparisonRecord) : null;
    const hasCurrentOralData = hasOralAssessmentData(oralState);
    const hasPreviousOralData = hasOralAssessmentData(comparisonOralState);
    const previousWeight = comparisonRecord ? toMetricNumber(comparisonRecord.weight ?? comparisonRecord.fields?.weight) : null;
    const previousBmi = comparisonRecord ? toMetricNumber(comparisonRecord.bmi ?? comparisonRecord.fields?.bmi) : null;
    const findingItems = [];
    const alertItems = [];
    const recommendationItems = [];
    let chewingRisk = 0;
    let swallowRisk = 0;
    let hygieneRisk = 0;
    let functionRisk = 0;

    const metaText = comparisonRecord && comparisonRecord.date
        ? `比較基準 ${comparisonRecord.date}`
        : history.length
            ? '比較基準 最新保存'
            : '';

    if (!hasCurrentOralData) {
        if (!patientState.patientKey) {
            alertItems.push('氏名と生年月日を入力すると前回比較ができます。');
        } else if (!comparisonRecord) {
            alertItems.push('保存済み履歴がないため、今回保存後から差分比較ができます。');
        } else if (!hasPreviousOralData) {
            alertItems.push('前回保存に口腔詳細がないため、今回保存後から口腔差分が有効になります。');
        }

        return {
            chips: history.length ? [buildMetricChipHtml('保存履歴', `${history.length}件`, history.length ? 'success' : 'info')] : [],
            summaryText: patientState.name
                ? '口腔タブの問診・RSST・うがい・オーラルディアドコキネシスを入力すると臨床語化を表示します。'
                : '利用者情報と口腔項目を入力すると臨床語化を表示します。',
            findingItems: ['口腔タブの入力後に所見候補を生成します。'],
            alertItems: alertItems.length ? alertItems : ['口腔項目を入力すると差分判定を表示します。'],
            recommendationTone: 'info',
            recommendationLabel: '入力待ち',
            recommendationItems: ['問診・RSST・うがい・オーラルディアドコキネシスを入力すると、食形態の提案を表示します。'],
            metaText,
            commentDraft: '',
        };
    }

    if (oralState.q1Code === 2) {
        chewingRisk += 2;
        findingItems.push('硬い食品の咀嚼困難を認めます。');
    }
    if (oralState.q4Code === 2) {
        chewingRisk += 1;
        findingItems.push('片側での咬合支持低下があり、咀嚼効率の低下が示唆されます。');
    } else if (oralState.q4Code === 3) {
        chewingRisk += 2;
        findingItems.push('両側での咬合支持が不十分で、食塊形成低下に留意が必要です。');
    }
    if (oralState.q5Code !== null && oralState.q5Code >= 4) {
        findingItems.push('過去1か月の全身状態は低下寄りの自己評価です。');
    }
    if (oralState.q6Code !== null && oralState.q6Code >= 4) {
        chewingRisk += 1;
        findingItems.push('本人評価で口腔状態の低下感がみられます。');
    }
    if (oralState.q2Code === 2) {
        swallowRisk += 3;
        findingItems.push('水分でのむせがあり、嚥下時の安全性に留意が必要です。');
    }
    if (oralState.q9Code !== null && oralState.q9Code >= 2) {
        swallowRisk += oralState.q9Code;
        findingItems.push('むせ症状があり、食事場面での観察強化が必要です。');
    }
    if (oralState.rsstCount !== null && oralState.rsstCount > 0) {
        if (oralState.rsstCount <= 2) {
            swallowRisk += 3;
            findingItems.push(`RSST ${oralState.rsstCount.toFixed(0)}回/30秒で嚥下反復の低下が疑われます。`);
        } else if (oralState.rsstCount <= 3) {
            swallowRisk += 1;
            findingItems.push(`RSST ${oralState.rsstCount.toFixed(0)}回/30秒で境界域です。`);
        }
    }
    if (oralState.rsstJudgeCode === 2) {
        swallowRisk += 1;
        findingItems.push('RSST 判定はやや不十分です。');
    } else if (oralState.rsstJudgeCode === 3) {
        swallowRisk += 2;
        findingItems.push('RSST 判定は不十分です。');
    }
    if (oralState.q3Code === 2) {
        hygieneRisk += 2;
        findingItems.push('口腔乾燥の訴えがあり、保湿と水分調整が必要です。');
    }
    if (oralState.q7Code === 2) {
        hygieneRisk += 1;
        findingItems.push('口臭があり、清掃状態や乾燥の確認が必要です。');
    }
    if (oralState.q8Code !== null) {
        hygieneRisk += getCleaningHabitRisk(oralState.q8Code);
        if (oralState.q8Code === 1) {
            findingItems.push('日常の口腔清掃習慣が乏しく、口腔ケア支援の余地があります。');
        } else if (oralState.q8Code === 2) {
            findingItems.push('口腔清掃習慣は限定的です。');
        }
    }

    const gargleNotes = [];
    if (oralState.bukubukuCode === 2) {
        functionRisk += 1;
        gargleNotes.push('ブクブクうがいがやや不十分');
    } else if (oralState.bukubukuCode === 3) {
        functionRisk += 2;
        gargleNotes.push('ブクブクうがいが不十分');
    }
    if (oralState.guguguCode === 2) {
        functionRisk += 1;
        gargleNotes.push('ぐぐぐうがいがやや不十分');
    } else if (oralState.guguguCode === 3) {
        functionRisk += 2;
        gargleNotes.push('ぐぐぐうがいが不十分');
    }
    if (gargleNotes.length) {
        findingItems.push(`${gargleNotes.join('、')}です。`);
    }

    const lowOdkLabels = getLowOdkLabels(oralState);
    if (lowOdkLabels.length) {
        functionRisk += lowOdkLabels.length;
        findingItems.push(`${lowOdkLabels.join('、')}でオーラルディアドコキネシス低下を認めます。`);
    }

    const summaryParts = [];
    if (swallowRisk >= 3) {
        summaryParts.push('嚥下リスクへの配慮が必要です。');
    }
    if (chewingRisk >= 2) {
        summaryParts.push('咀嚼効率の低下が示唆されます。');
    }
    if (hygieneRisk >= 2) {
        summaryParts.push('口腔乾燥・衛生面の介入優先度が高めです。');
    }
    if (functionRisk >= 2) {
        summaryParts.push('口唇・舌機能の経過観察または訓練継続が望まれます。');
    }
    if (!summaryParts.length) {
        summaryParts.push('現時点で顕著な口腔機能低下を示す入力は多くありません。');
    }
    if (comparisonRecord && comparisonRecord.date) {
        summaryParts.push(`差分は ${comparisonRecord.date} の保存記録を基準に表示しています。`);
    }
    summaryParts.push('診断ではなく記録補助として利用してください。');

    if (!patientState.patientKey) {
        alertItems.push('氏名と生年月日を入力すると前回比較ができます。');
    } else if (!comparisonRecord) {
        alertItems.push('保存済み履歴がないため、今回保存後から差分比較ができます。');
    } else {
        if (hasMeaningfulDrop(patientState.weight, previousWeight, 1.0)) {
            alertItems.push(`体重が前回 ${previousWeight.toFixed(1)}kg から ${patientState.weight.toFixed(1)}kg に低下しています。`);
        }
        if (hasMeaningfulDrop(patientState.bmi, previousBmi, 0.5)) {
            alertItems.push(`BMI が前回 ${previousBmi.toFixed(1)} から ${patientState.bmi.toFixed(1)} に低下しています。`);
        }

        if (!hasPreviousOralData) {
            alertItems.push('前回保存に口腔詳細がないため、今回保存後から口腔差分が有効になります。');
        } else {
            if (comparisonOralState.q2Code === 1 && oralState.q2Code === 2) {
                alertItems.push('水分でのむせが前回より新たに入力されています。');
            }
            if (comparisonOralState.q3Code === 1 && oralState.q3Code === 2) {
                alertItems.push('口腔乾燥が前回より強く疑われます。');
            }
            if (hasWorsenedCode(oralState.q4Code, comparisonOralState.q4Code)) {
                alertItems.push('咬合支持が前回より低下しています。');
            }
            if (hasWorsenedCode(oralState.q6Code, comparisonOralState.q6Code) && oralState.q6Code >= 4) {
                alertItems.push('口腔健康の自己評価が前回より悪化しています。');
            }
            if (hasWorsenedCode(oralState.q9Code, comparisonOralState.q9Code)) {
                alertItems.push('むせ症状が前回より増えています。');
            }
            if (hasMeaningfulDrop(oralState.rsstCount, comparisonOralState.rsstCount, 1)) {
                alertItems.push(`RSST が前回 ${comparisonOralState.rsstCount.toFixed(0)}回/30秒 から ${oralState.rsstCount.toFixed(0)}回/30秒 に低下しています。`);
            }
            if (hasWorsenedCode(oralState.rsstJudgeCode, comparisonOralState.rsstJudgeCode)) {
                alertItems.push('RSST の専門職判定が前回より悪化しています。');
            }
            if (hasWorsenedCode(oralState.bukubukuCode, comparisonOralState.bukubukuCode)
                || hasWorsenedCode(oralState.guguguCode, comparisonOralState.guguguCode)) {
                alertItems.push('含嗽機能が前回より低下しています。');
            }
            if (getCleaningHabitRisk(oralState.q8Code) > getCleaningHabitRisk(comparisonOralState.q8Code)) {
                alertItems.push('口腔清掃習慣が前回より低下しています。');
            }

            const odkDrops = [
                ['パ', oralState.pa, comparisonOralState.pa],
                ['タ', oralState.ta, comparisonOralState.ta],
                ['カ', oralState.ka, comparisonOralState.ka],
            ].filter(([, currentValue, previousValue]) => {
                return currentValue !== null && previousValue !== null
                    && (currentValue < ODK_REFERENCE_PER_SECOND && previousValue >= ODK_REFERENCE_PER_SECOND
                        || currentValue <= previousValue - 0.5);
            }).map(([label, currentValue, previousValue]) => `${label} ${previousValue.toFixed(1)}→${currentValue.toFixed(1)}`);
            if (odkDrops.length) {
                alertItems.push(`オーラルディアドコキネシスが低下しています（${odkDrops.join(' / ')}）。`);
            }
        }
    }

    if (!alertItems.length) {
        alertItems.push('前回保存から大きな悪化所見は現時点で目立ちません。');
    }

    const totalRisk = chewingRisk + swallowRisk + hygieneRisk + functionRisk;
    let recommendationTone = 'success';
    let recommendationLabel = '現行食形態を基本に継続観察';
    if (swallowRisk >= 6 || totalRisk >= 10) {
        recommendationTone = 'alert';
        recommendationLabel = '食形態の再評価を優先';
        recommendationItems.push('ペースト・ムース食やとろみ付与を含め、まとまりやすい食形態を主治医・ST等と再評価します。');
        recommendationItems.push('食事時は姿勢調整、一口量の制限、見守り強化を優先します。');
    } else if (swallowRisk >= 3 || totalRisk >= 6) {
        recommendationTone = 'alert';
        recommendationLabel = 'やわらか食・水分調整を優先';
        recommendationItems.push('硬い物・ばらける物は控え、やわらかくまとまりやすい食形態を優先します。');
        recommendationItems.push('汁物や水分は一口量と姿勢を調整し、必要時はとろみを検討します。');
    } else if (chewingRisk >= 2 || hygieneRisk >= 2 || functionRisk >= 2) {
        recommendationTone = 'info';
        recommendationLabel = '現行食をベースに食べやすさを調整';
        recommendationItems.push('硬さ・大きさ・水分量を本人の咀嚼しやすさに合わせて調整します。');
    }

    if (oralState.q3Code === 2) {
        recommendationItems.push('口腔乾燥があるため、食前後の保湿や水分併用を検討します。');
    }
    if (chewingRisk >= 2) {
        recommendationItems.push('硬い食品や繊維の強い食品より、やわらかくまとまりやすい献立を優先します。');
    }
    if (swallowRisk >= 3) {
        recommendationItems.push('食事時は頸部前屈や座位保持など、嚥下しやすい姿勢の確認を行います。');
    }
    if (hygieneRisk >= 2 || functionRisk >= 2) {
        recommendationItems.push('食後の口腔ケアと含嗽をセットで計画します。');
    }
    if (!recommendationItems.length) {
        recommendationItems.push('現行食形態を基本に継続し、むせや食事量の変化を経過観察します。');
    }

    const chips = [
        buildMetricChipHtml('咀嚼', formatStage3DomainLabel(chewingRisk), classifyStage3Risk(chewingRisk)),
        buildMetricChipHtml('嚥下', formatStage3DomainLabel(swallowRisk), classifyStage3Risk(swallowRisk)),
        buildMetricChipHtml('衛生・乾燥', formatStage3DomainLabel(hygieneRisk), classifyStage3Risk(hygieneRisk)),
        buildMetricChipHtml('口唇・舌機能', formatStage3DomainLabel(functionRisk), classifyStage3Risk(functionRisk)),
    ];
    if (comparisonRecord && comparisonRecord.date) {
        chips.push(buildMetricChipHtml('比較基準', comparisonRecord.date, 'info'));
    }
    if (history.length) {
        chips.push(buildMetricChipHtml('保存履歴', `${history.length}件`, 'info'));
    }

    const data = {
        chips,
        summaryText: summaryParts.join(' '),
        findingItems,
        alertItems,
        recommendationTone,
        recommendationLabel,
        recommendationItems,
        metaText,
    };
    data.commentDraft = buildClinicalCommentDraft(data);
    return data;
}

function renderClinicalSupportPanel() {
    const chips = document.getElementById('clinicalSupportChips');
    const summary = document.getElementById('clinicalSupportSummary');
    const findings = document.getElementById('clinicalFindingList');
    const alerts = document.getElementById('clinicalAlertList');
    const recommendationLabel = document.getElementById('foodRecommendationLabel');
    const recommendationList = document.getElementById('foodRecommendationList');
    const meta = document.getElementById('clinicalSupportMeta');
    if (!chips || !summary || !findings || !alerts || !recommendationLabel || !recommendationList || !meta) {
        return;
    }

    const data = buildClinicalSupportData();
    latestClinicalSupportData = data;
    chips.innerHTML = data.chips.join('');
    summary.textContent = data.summaryText;
    findings.innerHTML = buildStage3ListHtml(data.findingItems, '入力後に所見候補を表示します。');
    alerts.innerHTML = buildStage3ListHtml(data.alertItems, '前回比較の準備が整うと差分を表示します。');
    recommendationLabel.innerHTML = buildMetricChipHtml('提案レベル', data.recommendationLabel, data.recommendationTone);
    recommendationList.innerHTML = buildStage3ListHtml(data.recommendationItems, '入力後に食形態提案を表示します。');
    meta.textContent = data.metaText;
    updateClinicalCommentActionState(data);
}

function buildNutritionSupportText(state, age, bmi, reference, mnaInfo, latestSavedRecord) {
    if (!state.birthdate) {
        return '生年月日を入力すると年齢帯の参考帯を表示します。';
    }
    if (bmi === null) {
        return '体重と身長を入力すると BMI と MNA F1 の目安を表示します。';
    }

    const parts = [`現在の BMI は ${bmi.toFixed(1)} です。`];
    if (reference) {
        if (bmi < reference.low) {
            parts.push(`${reference.label} ${reference.low.toFixed(1)}〜${reference.high.toFixed(1)} を下回るため、体重減少や摂取量の変化を確認してください。`);
        } else if (bmi > reference.high) {
            parts.push(`${reference.label} ${reference.low.toFixed(1)}〜${reference.high.toFixed(1)} を上回っています。活動量や食事量と合わせて確認してください。`);
        } else {
            parts.push(`${reference.label} の範囲内です。`);
        }
    }
    if (mnaInfo) {
        parts.push(`MNA F1 では ${mnaInfo.score}点の目安です（${mnaInfo.label}）。`);
    }
    if (latestSavedRecord && latestSavedRecord.date) {
        parts.push(`保存済み最新評価日は ${latestSavedRecord.date} です。`);
    }
    parts.push('診断ではなく経過観察の参考表示です。');
    return parts.join(' ');
}

function renderNutritionSupportPanel() {
    const chips = document.getElementById('nutritionSupportChips');
    const summary = document.getElementById('nutritionSupportSummary');
    if (!chips || !summary) {
        return;
    }

    const state = getCurrentPatientFormState();
    const age = calculateAgeAtDate(state.birthdate, state.evalDate);
    const reference = getBmiReference(age);
    const mnaInfo = getMnaF1ScoreInfo(state.bmi);
    const history = state.patientKey ? (buildPatientRecordGroups(records).get(state.patientKey) || []) : [];
    const latestSavedRecord = history[0] || null;
    const latestSavedWeight = latestSavedRecord ? toMetricNumber(latestSavedRecord.weight ?? latestSavedRecord.fields?.weight) : null;

    const chipItems = [];
    if (age !== null) {
        chipItems.push(buildMetricChipHtml('年齢', `${age}歳`, 'info'));
    }
    if (state.bmi !== null) {
        chipItems.push(buildMetricChipHtml('現在BMI', state.bmi.toFixed(1), classifyBmiReference(state.bmi, reference)));
    }
    if (reference) {
        chipItems.push(buildMetricChipHtml(reference.label, `${reference.low.toFixed(1)}〜${reference.high.toFixed(1)}`, 'info'));
    }
    if (mnaInfo) {
        chipItems.push(buildMetricChipHtml('MNA F1 目安', `${mnaInfo.score}点`, mnaInfo.score <= 1 ? 'alert' : 'success'));
    }
    if (latestSavedRecord && latestSavedRecord.date) {
        chipItems.push(buildMetricChipHtml('前回保存', latestSavedRecord.date, 'info'));
    }
    if (state.weight !== null && latestSavedWeight !== null) {
        const tone = getTrendDirection(state.weight, latestSavedWeight) === 'down' ? 'alert' : 'info';
        chipItems.push(buildMetricChipHtml('前回比体重', formatSignedDelta(state.weight, latestSavedWeight, 'kg'), tone));
    }

    chips.innerHTML = chipItems.join('');
    summary.textContent = buildNutritionSupportText(state, age, state.bmi, reference, mnaInfo, latestSavedRecord);
}

function renderPatientTrendPanel() {
    const summary = document.getElementById('patientTrendSummary');
    const meta = document.getElementById('patientTrendMeta');
    const body = document.getElementById('patientTrendBody');
    if (!summary || !meta || !body) {
        return;
    }

    const state = getCurrentPatientFormState();
    if (!state.patientKey) {
        meta.textContent = '';
        summary.innerHTML = '';
        body.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="icon">📈</div>氏名と生年月日を入力すると推移を表示します</div></td></tr>';
        return;
    }

    const history = (buildPatientRecordGroups(records).get(state.patientKey) || []).slice(0, TREND_HISTORY_LIMIT);
    const latestSavedRecord = history[0] || null;
    const latestSavedWeight = latestSavedRecord ? toMetricNumber(latestSavedRecord.weight ?? latestSavedRecord.fields?.weight) : null;
    const latestSavedBmi = latestSavedRecord ? toMetricNumber(latestSavedRecord.bmi ?? latestSavedRecord.fields?.bmi) : null;

    const summaryChips = [];
    if (state.weight !== null) {
        summaryChips.push(buildMetricChipHtml('現在体重', `${state.weight.toFixed(1)}kg`, 'info'));
    } else if (latestSavedWeight !== null) {
        summaryChips.push(buildMetricChipHtml('最新保存体重', `${latestSavedWeight.toFixed(1)}kg`, 'info'));
    }
    if (state.bmi !== null) {
        summaryChips.push(buildMetricChipHtml('現在BMI', state.bmi.toFixed(1), 'info'));
    } else if (latestSavedBmi !== null) {
        summaryChips.push(buildMetricChipHtml('最新保存BMI', latestSavedBmi.toFixed(1), 'info'));
    }
    if (state.weight !== null && latestSavedWeight !== null) {
        const tone = getTrendDirection(state.weight, latestSavedWeight) === 'down' ? 'alert' : 'info';
        summaryChips.push(buildMetricChipHtml('前回比体重', formatSignedDelta(state.weight, latestSavedWeight, 'kg'), tone));
    }
    if (state.bmi !== null && latestSavedBmi !== null) {
        const tone = getTrendDirection(state.bmi, latestSavedBmi) === 'down' ? 'alert' : 'info';
        summaryChips.push(buildMetricChipHtml('前回比BMI', formatSignedDelta(state.bmi, latestSavedBmi, ''), tone));
    }
    summaryChips.push(buildMetricChipHtml('保存履歴', `${history.length}件`, history.length ? 'success' : 'info'));
    summary.innerHTML = summaryChips.join('');

    if (!history.length) {
        meta.textContent = '保存済み履歴 0件';
        body.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="icon">📈</div>この利用者の保存済み履歴はまだありません</div></td></tr>';
        return;
    }

    meta.textContent = `保存済み ${history.length}件 / 最新 ${history[0].date || '―'}`;
    body.innerHTML = history.map((record, index) => {
        const olderRecord = history[index + 1] || null;
        const weight = toMetricNumber(record.weight ?? record.fields?.weight);
        const olderWeight = olderRecord ? toMetricNumber(olderRecord.weight ?? olderRecord.fields?.weight) : null;
        const bmi = toMetricNumber(record.bmi ?? record.fields?.bmi);
        const olderBmi = olderRecord ? toMetricNumber(olderRecord.bmi ?? olderRecord.fields?.bmi) : null;
        const tagClass = record.mnaLabel === '良好' ? 'tag-good' : record.mnaLabel === 'At risk' ? 'tag-risk' : record.mnaLabel === '低栄養' ? 'tag-bad' : '';
        const scoreLabel = record.mnaScore !== null && record.mnaScore !== undefined ? `${record.mnaScore}/14` : '―';
        return `
            <tr>
                <td><strong>${escapeHtml(record.date || '―')}</strong>${record.nextMonitor ? `<br><small class="metric-subline">次回 ${escapeHtml(record.nextMonitor)}</small>` : ''}</td>
                <td>${escapeHtml(formatMetricValue(weight, 'kg'))}</td>
                <td>${escapeHtml(formatMetricValue(bmi))}</td>
                <td>${buildTrendDeltaHtml(weight, olderWeight, 'kg')}</td>
                <td>${buildTrendDeltaHtml(bmi, olderBmi, '')}</td>
                <td><span class="tag ${tagClass}">${escapeHtml(record.mnaLabel || '―')}</span><br><small class="metric-subline">${escapeHtml(scoreLabel)}</small></td>
            </tr>
        `;
    }).join('');
}

function updateStage2Panels() {
    renderNutritionSupportPanel();
    renderPatientTrendPanel();
    renderClinicalSupportPanel();
}

function scheduleStage2Update() {
    if (stage2UpdateHandle) {
        return;
    }
    stage2UpdateHandle = window.requestAnimationFrame(() => {
        stage2UpdateHandle = 0;
        updateStage2Panels();
    });
}

function attachStage2InputListeners() {
    if (stage2ListenersBound) {
        return;
    }

    const watchIds = new Set([
        'name',
        'birthdate',
        'evalDate',
        'weight',
        'height',
        'bmi',
        'q1',
        'q2',
        'q3',
        'q4',
        'q5',
        'q6',
        'q7',
        'q8',
        'q9',
        'rsst_count',
        'rsst_judge',
        'bukubuku',
        'gugugu',
        'pa',
        'ta',
        'ka',
    ]);
    const handleChange = (event) => {
        const target = event.target;
        if (!target || !watchIds.has(target.id)) {
            return;
        }
        scheduleStage2Update();
    };

    document.addEventListener('input', handleChange, true);
    document.addEventListener('change', handleChange, true);
    stage2ListenersBound = true;
}

function installStage2Hooks() {
    if (stage2HooksInstalled) {
        return;
    }

    if (typeof loadRecord === 'function') {
        const originalLoadRecord = loadRecord;
        loadRecord = function(...args) {
            const result = originalLoadRecord.apply(this, args);
            const recordId = Number(args[0]);
            const loadedRecord = Array.isArray(records)
                ? records.find((record) => Number(record.id) === recordId)
                : null;
            if (loadedRecord) {
                if (typeof calcBMI === 'function') {
                    calcBMI();
                }
                currentMnaFieldMode = loadedRecord.mnaFieldMode || '';
                mnaScores = { ...buildEmptyMnaScores(), ...(loadedRecord.mnaScores || {}) };
                restoreMnaSelections();
                calcMNAScore();
                updateSummary();
            }
            scheduleStage2Update();
            return result;
        };
        window.loadRecord = loadRecord;
    }

    if (typeof selectMNA === 'function') {
        const originalSelectMNA = selectMNA;
        selectMNA = function(...args) {
            const result = originalSelectMNA.apply(this, args);
            currentMnaFieldMode = getSelectedMnaFieldMode() || currentMnaFieldMode || '';
            updateSummary();
            scheduleStage2Update();
            return result;
        };
        window.selectMNA = selectMNA;
    }

    if (typeof renderHistory === 'function') {
        const originalRenderHistory = renderHistory;
        renderHistory = function(...args) {
            const result = originalRenderHistory.apply(this, args);
            scheduleStage2Update();
            return result;
        };
        window.renderHistory = renderHistory;
    }

    stage2HooksInstalled = true;
}

window.addEventListener('afterprint', clearPrintMode);

async function initializeApp() {
    ensureStage1Styles();
    await ensureLocalSettingsInitialized();
    syncManagedPersonSelectors();
    ensureSettingsControls();
    ensureHistoryTools();
    ensurePrintControls();
    ensureDraftControls();
    ensureDataTransferControls();
    ensureRsstTimerTools();
    ensureStage2Panels();
    ensureStage3Panels();
    attachDraftAutosave();
    attachStage2InputListeners();
    installManagedFieldHooks();
    installStage2Hooks();
    try {
        records = await fetchRecords();
    } catch (error) {
        console.error(error);
        showToast(error.message || '同期に失敗しました');
    }
    renderHistory();
    updateDraftStatusDisplays();
    updateStage2Panels();
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
ORAL_EVAL_SECTION_PATTERN = re.compile(
    r'''<div class="form-group" style="margin-bottom:10px">\s*<label>① [^<]*</label>\s*<select id="oral_eval1"><option value="">選択</option><option>あり</option><option>なし</option></select>\s*</div>\s*<div class="form-group" style="margin-bottom:10px">\s*<label>② 事業またはサービスの継続の必要性</label>\s*<select id="oral_eval2"><option value="">選択</option><option>あり（継続）</option><option>なし（終了）</option></select>\s*</div>\s*<div class="form-group" style="margin-bottom:10px">\s*<label>③ 事業またはサービスの継続の必要性（モニタリング後）</label>\s*<select id="oral_eval3"><option value="">選択</option><option>あり（継続）</option><option>なし（終了）</option></select>\s*</div>\s*<div class="form-group">\s*<label>⑤ 備考</label>\s*<textarea id="oral_biko" placeholder="備考・その他特記事項"></textarea>\s*</div>''',
        re.S,
)
OBSERVATION_Q10_PATTERN = re.compile(
    r'''<div class="form-group" style="margin-bottom:10px">\s*<label>食事中の食べこぼし</label>\s*<select id="q10"><option value="">選択</option><option>1\.最高</option><option>2\.やや重篤</option><option>3\.ふつう</option><option>4\.やや良い</option><option>5\.乏しい</option></select>\s*</div>\s*<div class="form-group" style="margin-bottom:10px">\s*<label>特記事項</label>''',
    re.S,
)
GARGLE_BLOCK_PATTERN = re.compile(
    r'''<p class="section-label" style="margin-top:14px">⑤ ブクブクうがい / ぐぐぐうがい</p>\s*<div class="form-grid">\s*<div class="form-group">\s*<label>ブクブクうがい</label>\s*<select id="bukubuku"><option value="">選択</option><option>1できる</option><option>2やや不十分</option><option>3不十分</option></select>\s*</div>\s*<div class="form-group">\s*<label>ぐぐぐうがい</label>\s*<select id="gugugu"><option value="">選択</option><option>1できる</option><option>2やや不十分</option><option>3不十分</option></select>\s*</div>\s*</div>\s*<p class="section-label" style="margin-top:14px">⑥ オーラルジスキネジア</p>''',
    re.S,
)
SWALLOWING_BLOCK_PATTERN = re.compile(
    r'''<p class="section-label" style="margin-top:14px">⑦ 飲み込み</p>\s*<div class="form-grid">\s*<div class="form-group">\s*<label>口のかわき</label>\s*<select id="dryness"><option value="">選択</option><option>その他</option><option>あり</option><option>なし</option></select>\s*</div>\s*<div class="form-group">\s*<label>口臭</label>\s*<select id="halitosis"><option value="">選択</option><option>あり</option><option>なし</option></select>\s*</div>\s*<div class="form-group">\s*<label>会話</label>\s*<select id="conversation"><option value="">選択</option><option>かむ</option><option>のむ</option><option>できる</option></select>\s*</div>\s*<div class="form-group">\s*<label>歯みがき</label>\s*<select id="toothbrushing"><option value="">選択</option><option>食べこぼし</option><option>あり</option><option>なし</option></select>\s*</div>\s*</div>\s*<div class="form-group" style="margin-top:12px">\s*<label>⑧ 特記事項等</label>\s*<textarea id="oral_note2" placeholder="専門職によるアセスメントの特記事項"></textarea>\s*</div>''',
    re.S,
)
OBSERVATION_Q10_BLOCK = '''    <div class="form-group" style="margin-bottom:10px">
            <label>食事中の食べこぼし</label>
            <select id="q10"><option value="">選択</option><option>1.最高</option><option>2.やや重篤</option><option>3.ふつう</option><option>4.やや良い</option><option>5.乏しい</option></select>
        </div>
        <div class="form-group" style="margin-bottom:10px">
            <label>特記事項</label>'''
OBSERVATION_Q10_REPLACEMENT = '''    <div class="form-group" style="margin-bottom:10px">
            <label>食事中の食べこぼし</label>
            <select id="q10"><option value="">選択</option><option>1.最高</option><option>2.やや重篤</option><option>3.ふつう</option><option>4.やや良い</option><option>5.乏しい</option></select>
        </div>
        <div class="form-group" style="margin-bottom:10px">
            <label>表情の豊さ</label>
            <select id="q11"><option value="">選択</option><option>1.豊富</option><option>2.やや豊富</option><option>3.ふつう</option><option>4.やや乏しい</option><option>5.乏しい</option></select>
        </div>
        <div class="form-group" style="margin-bottom:10px">
            <label>特記事項</label>'''
ASSESSMENT_LABEL_A3_OLD = '    <p class="section-label">② 舌や頬粘膜のようす</p>'
ASSESSMENT_LABEL_A3_NEW = '    <p class="section-label">② 歯や義歯のよごれ</p>'
ASSESSMENT_LABEL_A4_OLD = '    <p class="section-label">③ 舌の動きのようす</p>'
ASSESSMENT_LABEL_A4_NEW = '    <p class="section-label">③ 舌のよごれ</p>'
GARGLE_BLOCK_OLD = '''    <p class="section-label" style="margin-top:14px">⑤ ブクブクうがい / ぐぐぐうがい</p>
        <div class="form-grid">
            <div class="form-group">
                <label>ブクブクうがい</label>
                <select id="bukubuku"><option value="">選択</option><option>1できる</option><option>2やや不十分</option><option>3不十分</option></select>
            </div>
            <div class="form-group">
                <label>ぐぐぐうがい</label>
                <select id="gugugu"><option value="">選択</option><option>1できる</option><option>2やや不十分</option><option>3不十分</option></select>
            </div>
        </div>

        <p class="section-label" style="margin-top:14px">⑥ オーラルジスキネジア</p>'''
GARGLE_BLOCK_NEW = '''    <p class="section-label" style="margin-top:14px">⑤ ブクブクうがい</p>
        <div class="form-group" style="margin-bottom:10px">
            <label>ブクブクうがい</label>
            <select id="bukubuku"><option value="">選択</option><option>1できる</option><option>2やや不十分</option><option>3不十分</option></select>
        </div>

        <p class="section-label" style="margin-top:14px">⑥ オーラルジスキネジア</p>'''
SWALLOWING_BLOCK_OLD = '''    <p class="section-label" style="margin-top:14px">⑦ 飲み込み</p>
        <div class="form-grid">
            <div class="form-group">
                <label>口のかわき</label>
                <select id="dryness"><option value="">選択</option><option>その他</option><option>あり</option><option>なし</option></select>
            </div>
            <div class="form-group">
                <label>口臭</label>
                <select id="halitosis"><option value="">選択</option><option>あり</option><option>なし</option></select>
            </div>
            <div class="form-group">
                <label>会話</label>
                <select id="conversation"><option value="">選択</option><option>かむ</option><option>のむ</option><option>できる</option></select>
            </div>
            <div class="form-group">
                <label>歯みがき</label>
                <select id="toothbrushing"><option value="">選択</option><option>食べこぼし</option><option>あり</option><option>なし</option></select>
            </div>
        </div>

        <div class="form-group" style="margin-top:12px">
            <label>⑧ 特記事項等</label>
            <textarea id="oral_note2" placeholder="専門職によるアセスメントの特記事項"></textarea>
        </div>'''
SWALLOWING_BLOCK_NEW = '''    <div class="form-group" style="margin-top:12px">
            <label>⑧ 特記事項等</label>
            <textarea id="oral_note2" placeholder="専門職によるアセスメントの特記事項"></textarea>
        </div>'''
ORAL_EVAL_SECTION_REPLACEMENT = '''    <div class="form-group" style="margin-bottom:10px">
            <label>① 事業またはサービスを継続しないことによる口腔機能の著しい低下のおそれ</label>
            <select id="oral_eval1"><option value="">選択</option><option>あり</option><option>なし</option></select>
        </div>
        <div class="form-group" style="margin-bottom:10px">
            <label>② 事業またはサービスの継続の必要性</label>
            <select id="oral_eval2"><option value="">選択</option><option>あり（継続）</option><option>なし（終了）</option></select>
        </div>
        <div class="form-group">
            <label>③ 備考</label>
            <textarea id="oral_biko" placeholder="備考・その他特記事項"></textarea>
        </div>'''


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


def build_status_badges_html(*, include_logout: bool = False) -> str:
    controls = [
        '<span class="badge">Ver 1.0</span>',
        (
            '<a href="#" onclick="showTab(\'settings\');return false;" '
            'class="badge" style="text-decoration:none;display:inline-flex;align-items:center;justify-content:center;min-width:32px" '
            'title="設定" aria-label="設定">⚙</a>'
        ),
        (
            f'<a href="{HELP_ROUTE_PATH}" target="_blank" rel="noopener noreferrer" '
            'class="badge" style="text-decoration:none;display:inline-flex;align-items:center;justify-content:center;min-width:32px" '
            'title="ヘルプ" aria-label="ヘルプ">?</a>'
        ),
    ]
    if include_logout:
        controls.append(
            '<a href="/logout" class="badge" style="text-decoration:none;background:#fff1ea;color:#8a3b21">ログアウト</a>'
        )
    return '<div style="display:flex;align-items:center;gap:8px">' + ''.join(controls) + '</div>'


def extract_embedded_html(wrapper_html: str) -> str:
    start = wrapper_html.find(r"\u003c!DOCTYPE html\u003e")
    if start == -1:
        normalized = wrapper_html.lstrip().lower()
        if normalized.startswith("<!doctype html") and (
            'id="tab-patient"' in wrapper_html
            or "let records = JSON.parse(localStorage.getItem('oralNutritionRecords') || '[]');" in wrapper_html
        ):
            return wrapper_html
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
    html = replace_once(html, HEADER_TOP_BLOCK, AUTH_HEADER_REPLACEMENT)
    html = replace_once(
        html,
        '<span class="badge">Ver 1.0</span>',
        auth_status_html or AUTH_STATUS_PLACEHOLDER,
    )
    html, count = re.subn(
        r'<div class="form-group">\s*<label>かかりつけ歯科医</label>\s*<input type="text" id="dentist" placeholder="○○歯科クリニック">\s*</div>',
        PATIENT_DENTIST_FIELD_NEW,
        html,
        count=1,
    )
    if count != 1:
        raise RuntimeError('Expected patient dentist field not found')
    html, count = re.subn(
        r'<div class="form-group full">\s*<label>担当者名</label>\s*<input type="text" id="staff" placeholder="担当スタッフ名">\s*</div>',
        PATIENT_STAFF_FIELD_NEW,
        html,
        count=1,
    )
    if count != 1:
        raise RuntimeError('Expected patient staff field not found')
    html = replace_once(html, '<!-- TOAST -->', SETTINGS_TAB_HTML)
    html, count = OBSERVATION_Q10_PATTERN.subn(OBSERVATION_Q10_REPLACEMENT, html, count=1)
    if count != 1:
        raise RuntimeError('Expected q10 observation block not found')
    html = replace_once(html, ASSESSMENT_LABEL_A3_OLD, ASSESSMENT_LABEL_A3_NEW)
    html = replace_once(html, ASSESSMENT_LABEL_A4_OLD, ASSESSMENT_LABEL_A4_NEW)
    html, count = GARGLE_BLOCK_PATTERN.subn(GARGLE_BLOCK_NEW, html, count=1)
    if count != 1:
        raise RuntimeError('Expected gargle block not found')
    html, count = SWALLOWING_BLOCK_PATTERN.subn(SWALLOWING_BLOCK_NEW, html, count=1)
    if count != 1:
        raise RuntimeError('Expected swallowing block not found')
    html, count = ORAL_EVAL_SECTION_PATTERN.subn(ORAL_EVAL_SECTION_REPLACEMENT, html, count=1)
    if count != 1:
        raise RuntimeError('Expected oral evaluation section not found')
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
    return client_template.replace(AUTH_STATUS_PLACEHOLDER, auth_status_html or build_status_badges_html())


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


def normalize_shared_setting_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []

    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        dedupe_key = text.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_values.append(text)
    return normalized_values


def normalize_shared_settings_payload(payload: object) -> dict[str, list[str]]:
    source = payload if isinstance(payload, dict) else {}
    return {
        key: normalize_shared_setting_values(source.get(key, DEFAULT_SHARED_SETTINGS[key]))
        for key in SHARED_SETTINGS_KEYS
    }


def seed_default_shared_settings(connection: sqlite3.Connection) -> None:
    now = current_timestamp()
    for key, values in DEFAULT_SHARED_SETTINGS.items():
        connection.execute(
            """
            INSERT INTO shared_settings (setting_key, updated_at, setting_value)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO NOTHING
            """,
            (key, now, json.dumps(values, ensure_ascii=False)),
        )


def list_shared_settings(db_path: Path) -> dict[str, list[str]]:
    settings = {key: list(values) for key, values in DEFAULT_SHARED_SETTINGS.items()}
    with open_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT setting_key, setting_value FROM shared_settings WHERE setting_key IN (?, ?)",
            SHARED_SETTINGS_KEYS,
        ).fetchall()

    for row in rows:
        key = str(row["setting_key"] or "")
        if key not in settings:
            continue
        try:
            parsed_value = json.loads(row["setting_value"])
        except json.JSONDecodeError:
            parsed_value = settings[key]
        settings[key] = normalize_shared_setting_values(parsed_value)

    return settings


def save_shared_settings(db_path: Path, payload: object) -> dict[str, list[str]]:
    settings = normalize_shared_settings_payload(payload)
    now = current_timestamp()

    with DB_WRITE_LOCK:
        with open_connection(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for key in SHARED_SETTINGS_KEYS:
                connection.execute(
                    """
                    INSERT INTO shared_settings (setting_key, updated_at, setting_value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        setting_value = excluded.setting_value
                    """,
                    (key, now, json.dumps(settings[key], ensure_ascii=False)),
                )
            connection.commit()

    return settings


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shared_settings (
                    setting_key TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    setting_value TEXT NOT NULL
                )
                """
            )
            ensure_column(connection, "records", "updated_at", "updated_at TEXT")
            ensure_column(connection, "records", "eval_date", "eval_date TEXT")
            ensure_column(connection, "records", "patient_key", "patient_key TEXT")
            ensure_column(connection, "records", "assessment_key", "assessment_key TEXT")
            reconcile_record_metadata(connection)
            seed_default_shared_settings(connection)
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
            return build_status_badges_html()

        if self.allows_password_auth():
            return build_status_badges_html(include_logout=True)

        return build_status_badges_html()

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

        static_asset = resolve_help_static_asset(parsed.path)
        if static_asset:
            if not self.ensure_authenticated(api=False):
                return
            self.respond_file(static_asset[0], static_asset[1])
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

        if parsed.path == "/api/settings":
            if not self.ensure_authenticated(api=True):
                return
            try:
                self.respond_json(list_shared_settings(self.db_path))
            except sqlite3.Error as error:
                self.respond_json({"error": f"一覧設定の取得に失敗しました: {error}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
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

        if parsed.path not in {"/api/records", "/api/settings"}:
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

        if parsed.path == "/api/settings":
            try:
                settings = save_shared_settings(self.db_path, payload)
            except sqlite3.Error as error:
                self.respond_json({"error": f"一覧設定の保存に失敗しました: {error}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self.respond_json(settings, status=HTTPStatus.OK)
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

    def respond_file(
        self,
        file_path: Path,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.respond_not_found()
            return
        data = file_path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
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