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

load_dotenv_file(DOTENV_PATH)


SOURCE_ARTIFACT_PATH = BASE_DIR / "index.html"
README_HTML_PATH = BASE_DIR / "README.html"
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR_RESOLVED = ASSETS_DIR.resolve()
DEFAULT_DB_PATH = Path(os.environ.get("KOUKU_KINOU_DB", BASE_DIR / "data" / "records.db"))
DEFAULT_SESSION_TTL_MINUTES = int(os.environ.get("KOUKU_KINOU_SESSION_TTL_MINUTES", "480"))
DEFAULT_ALLOWED_NETWORKS = os.environ.get("KOUKU_KINOU_ALLOWED_NETWORKS", "")
DEFAULT_AUTH_MODE = (os.environ.get("KOUKU_KINOU_AUTH_MODE", "password") or "password").strip().lower()
SESSION_COOKIE_NAME = "kouku_kinou_session"
AUTH_STATUS_PLACEHOLDER = "__AUTH_STATUS_HTML__"
HELP_ROUTE_PATH = "/readme.html"
DB_TIMEOUT_SECONDS = 30.0
DB_WRITE_LOCK = threading.Lock()
CLIENT_HTML_MODE_LEGACY_SOURCE = "legacy-source"
CLIENT_HTML_MODE_MANAGED = "managed"
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

ASSET_CONTENT_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml; charset=utf-8",
    ".webp": "image/webp",
}
HELP_STATIC_ROUTES = {
    HELP_ROUTE_PATH: (README_HTML_PATH, "text/html; charset=utf-8"),
    "/README.html": (README_HTML_PATH, "text/html; charset=utf-8"),
    "/README.md": (BASE_DIR / "README.md", "text/markdown; charset=utf-8"),
    "/DEPLOY_SYNOLOGY_JA.md": (BASE_DIR / "DEPLOY_SYNOLOGY_JA.md", "text/markdown; charset=utf-8"),
    "/OPERATIONS_MANUAL_JA.md": (BASE_DIR / "OPERATIONS_MANUAL_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_CLIENT_GUIDE_JA.md": (BASE_DIR / "TAILSCALE_CLIENT_GUIDE_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_TABLET_GUIDE_JA.md": (BASE_DIR / "TAILSCALE_TABLET_GUIDE_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md": (BASE_DIR / "TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md", "text/markdown; charset=utf-8"),
    "/TAILSCALE_TABLET_QR_SHEET_JA.md": (BASE_DIR / "TAILSCALE_TABLET_QR_SHEET_JA.md", "text/markdown; charset=utf-8"),
    "/TailscaleClientLauncher.cmd": (BASE_DIR / "TailscaleClientLauncher.cmd", "text/plain; charset=utf-8"),
    "/TailscaleClientLauncher.ps1": (BASE_DIR / "TailscaleClientLauncher.ps1", "text/plain; charset=utf-8"),
    "/TailscaleClientLauncher.settings.json": (BASE_DIR / "TailscaleClientLauncher.settings.json", "application/json; charset=utf-8"),
    "/.env.example": (BASE_DIR / ".env.example", "text/plain; charset=utf-8"),
}
STATE_LINE = "let records = JSON.parse(localStorage.getItem('oralNutritionRecords') || '[]');"
SAVE_DEF = "function saveRecord() {"
SAVE_BLOCK = """records.unshift(record);\n  localStorage.setItem('oralNutritionRecords', JSON.stringify(records));\n  renderHistory();"""
DELETE_DEF = "function deleteRecord(id) {"
DELETE_BLOCK = """records = records.filter(r => r.id !== id);\n  localStorage.setItem('oralNutritionRecords', JSON.stringify(records));\n  renderHistory();"""
LOAD_FIELDS_BLOCK = """  document.getElementById('next_monitor').value = r.nextMonitor || '';\n  if (r.mnaScores) {"""
INIT_BLOCK = """document.getElementById('evalDate').value = new Date().toISOString().split('T')[0];\nrenderHistory();"""
HEADER_TOP_BLOCK = '<div class="header-top">'
AUTH_HEADER_REPLACEMENT = '<div class="header-top" style="justify-content:space-between;gap:12px">'
LOGOUT_BADGE_HTML = '<a href="/logout" class="badge" style="text-decoration:none;background:#fff1ea;color:#8a3b21">ログアウト</a>'
HEADER_STATUS_BLOCK_PATTERN = re.compile(
    r'(<div class="header-top"[^>]*>\s*<h1>.*?</h1>\s*)(<div style="display:flex;align-items:center;gap:8px">.*?</div>)(\s*</div>)',
    re.DOTALL,
)
MANAGED_CLIENT_MARKERS = (
    "let records = [];",
    "const API_ROOT = '/api/records';",
    "const SETTINGS_API_ROOT = '/api/settings';",
    "async function fetchRecords() {",
    "async function persistRecord(record) {",
    "initializeApp();",
)
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
        }
    }

    /* NOTIFICATION */"""
PATIENT_DENTIST_FIELD_NEW = '''<div class="form-group">
                <label>かかりつけ歯科</label>
                <select id="dentist_has">
                    <option value="">選択</option>
                    <option value="あり">あり</option>
                    <option value="なし">なし</option>
                </select>
                <div id="dentist_name_group" style="display:none;margin-top:8px" aria-hidden="true">
                    <input type="text" id="dentist" value="" style="display:none" aria-hidden="true">
                    <select id="dentist_select" data-skip-persist="1">
                        <option value="">選択</option>
                        <option value="__custom__">その他（自由入力）</option>
                    </select>
                    <input type="text" id="dentist_custom" data-skip-persist="1" placeholder="歯科名を入力" style="display:none;margin-top:8px">
                </div>
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
<div class="tab-content" id="tab-settings">
    <div class="card">
            <div><h2>設定</h2><div class="subtitle">担当者・かかりつけ歯科の候補管理</div></div>
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
                <div class="settings-panel__title">かかりつけ歯科一覧</div>
                <div class="settings-panel__hint">よく使う歯科名を登録しておくと患者入力が速くなります。</div>
                <div class="settings-panel__editor">
                    <input id="dentistSettingsInput" class="settings-panel__input" type="text" data-skip-persist="1" placeholder="かかりつけ歯科を追加">
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
    "  const filteredRecords = getFilteredRecords();\n"
    "  updateHistoryStats(filteredRecords.length);\n"
    "  renderActiveHistoryView(filteredRecords);\n"
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
                .toast { display: none !important; }

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
        body.print-mode .print-sheet__section--comment {
            break-inside: auto;
            page-break-inside: auto;
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
            max-height: none;
            overflow: visible;
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
const HISTORY_FILTER_STATE = { query: '', view: 'latest', sort: 'evalDate' };
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
const NUTRITION_COMMENT_START_MARKER = '【栄養アセスメント】';
const NUTRITION_COMMENT_END_MARKER = '【栄養アセスメントここまで】';
const NUTRITION_SELECTION_FIELD_ID = 'nutrition_selection_state';
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
        label: 'かかりつけ歯科',
        settingsInputId: 'dentistSettingsInput',
        settingsListId: 'dentistSettingsList',
        addButtonId: 'addDentistSettingButton',
        emptyText: '登録されたかかりつけ歯科はありません',
        addSuccessMessage: 'かかりつけ歯科を追加しました',
        removeSuccessMessage: 'かかりつけ歯科を削除しました',
        duplicateMessage: 'そのかかりつけ歯科は既に登録されています',
        confirmDeleteMessage: 'このかかりつけ歯科を一覧から削除しますか？',
        defaults: [],
    },
];
const NON_RECORD_FIELD_IDS = new Set(['historySearch', 'historyViewSelect', 'historySortSelect', 'printModeSelect', IMPORT_INPUT_ID, 'staff_select', 'staff_custom', 'dentist_select', 'dentist_custom', 'staffSettingsInput', 'dentistSettingsInput']);
const FOOD_STAPLE_OPTIONS = ['米飯', '軟飯', '粥', 'ペースト', 'ゼリー'];
const FOOD_MAIN_OPTIONS = ['常食', '軟菜', '一口大カット', '刻み', 'ソフト', 'ペースト', 'ゼリー'];
const WATER_TEXTURE_OPTIONS = ['とろみなし', '軽度とろみ（フレンチドレッシング状）', '中等度とろみ（とんかつソース状）', '重度とろみ（ケチャップ状）'];
const NUTRITION_ACTION_ROLE_LABELS = {
    patientFamily: '① 本人・家族への対応',
    rehab: '② リハビリ対応',
    rehabSt: '② リハビリ対応（ST）',
    rehabPt: '② リハビリ対応（PT）',
    rehabOt: '② リハビリ対応（OT）',
    ns: '③ 看護師対応',
};
const NUTRITION_ACTION_ROLE_KEYS = ['patientFamily', 'rehabSt', 'rehabPt', 'rehabOt', 'ns'];
const NUTRITION_REHAB_ROLE_CONFIGS = [
    { key: 'rehabSt', shortLabel: 'ST' },
    { key: 'rehabPt', shortLabel: 'PT' },
    { key: 'rehabOt', shortLabel: 'OT' },
];
const NUTRITION_GUIDANCE_LIBRARY = {
    under: {
        label: '低栄養 / 低栄養リスク',
        chipTone: 'alert',
        causes: {
            weight: {
                icon: '⚖️',
                label: '体重減少・るいそう',
                patientFamily: [
                    '1回の食事量が少なくても、回数を増やして補うことを説明する',
                    '高カロリー・高タンパク食品や栄養補助食品の活用を提案する',
                ],
                st: [
                    '摂食嚥下機能と食べやすい食形態を評価する',
                    '食事姿勢や代償手段を調整する',
                ],
                pt: [
                    '食事時の座位保持と体幹・頸部アライメントを調整する',
                ],
                ot: [
                    '食具操作や自助具、配膳環境を整えて摂取量を確保する',
                ],
                ns: [
                    '体重と食事摂取率を定期モニタリングする',
                    '医師・管理栄養士・NSTへ早期共有する',
                ],
            },
            dysphagia: {
                icon: '🍵',
                label: '摂食・嚥下障害',
                patientFamily: [
                    'ゆっくり少量ずつ食べることと食事姿勢を説明する',
                    'とろみや食形態調整の理由を丁寧に共有する',
                ],
                st: [
                    'VE/VFを含む嚥下評価を検討する',
                    '食形態ととろみ濃度を再評価する',
                ],
                pt: [
                    '安全に摂食できる座位・移乗方法と呼吸状態を確認する',
                ],
                ot: [
                    '一口量や食具選択、食事ペースを調整する',
                ],
                ns: [
                    '食事中・食後のむせやSpO2変化を観察する',
                    '口腔ケアと食後の体位管理を徹底する',
                ],
            },
            anorexia: {
                icon: '🍽️',
                label: '食欲不振・摂取量低下',
                patientFamily: [
                    '少量高頻度で食べられる時間帯を活かすよう提案する',
                    '食前口腔ケアや食事環境づくりを案内する',
                ],
                st: [
                    '食行動や先行期の問題を評価する',
                    '嗜好や食感を活かして食べる意欲を引き出す',
                ],
                pt: [
                    '離床や日中活動を整え、食欲につながる生活リズムをつくる',
                ],
                ot: [
                    '食事への注意を向けやすい環境づくりと食事動作支援を行う',
                ],
                ns: [
                    '摂取量と好みの変化を記録する',
                    '薬剤影響や心理面の要因を確認する',
                ],
            },
            oral: {
                icon: '🦷',
                label: '口腔機能低下',
                patientFamily: [
                    '義歯不適合や口腔乾燥時は歯科相談を勧める',
                    '毎食後の口腔ケアと保湿を説明する',
                ],
                st: [
                    '舌圧・口唇・咀嚼機能を評価する',
                    '口腔機能訓練と食形態調整を行う',
                ],
                pt: [
                    '咀嚼しやすい姿勢と休息配分を調整する',
                ],
                ot: [
                    '口腔ケアや食具操作を続けやすい手順と環境を整える',
                ],
                ns: [
                    '口腔ケア介助と義歯管理を行う',
                    '歯科・歯科衛生士との連携を調整する',
                ],
            },
            cognitive: {
                icon: '🧠',
                label: '認知機能低下・行動変化',
                patientFamily: [
                    '一品ずつ出す、手づかみ食にするなど環境調整を提案する',
                    '静かな食事環境と無理強いしない関わりを共有する',
                ],
                st: [
                    '認知機能と摂食行動の関連を評価する',
                    '介助方法を家族・スタッフで統一する',
                ],
                pt: [
                    '覚醒度と座位保持を整え、食事場面への参加を支える',
                ],
                ot: [
                    '注意が向きやすい配置や手順の単純化で摂食行動を支援する',
                ],
                ns: [
                    '見守りと声かけ、食事環境調整を行う',
                    '拒食のタイミングや背景を記録し家族支援につなげる',
                ],
            },
        },
    },
    over: {
        label: '過栄養',
        chipTone: 'info',
        causes: {
            overeating: {
                icon: '🍱',
                label: '過食・摂取量過多',
                patientFamily: [
                    '食べる速度をゆっくりにし、小さい食器を使う工夫を提案する',
                    '間食の内容とタイミングを記録して見直す',
                ],
                st: [
                    '摂食ペースや丸飲み傾向を評価する',
                    '食行動修正に向けた関わり方を整理する',
                ],
                pt: [
                    '食後の安全な活動や運動習慣を提案する',
                ],
                ot: [
                    '早食いを防ぐ食具・配膳方法と間食管理を整える',
                ],
                ns: [
                    '食事量・間食量と体重推移を定期記録する',
                    '管理栄養士・医師と連携して量の調整を検討する',
                ],
            },
            imbalance: {
                icon: '🥗',
                label: '栄養バランスの偏り',
                patientFamily: [
                    '主食・主菜・副菜をそろえる目安を説明する',
                    '甘い飲料を水やお茶へ切り替えることを提案する',
                ],
                st: [
                    '食べやすさと偏食の関連を評価する',
                    '咀嚼能力に合うバランス食の形態を提案する',
                ],
                pt: [
                    '活動量に見合った摂取量かを確認し、継続しやすい運動を提案する',
                ],
                ot: [
                    '買い物・配膳・記録など生活行為から食習慣を見直す',
                ],
                ns: [
                    '食事内容と血液データを継続確認する',
                    '服薬と食事内容の相互作用を確認する',
                ],
            },
            activity: {
                icon: '🚶',
                label: '活動量低下・代謝低下',
                patientFamily: [
                    '座位体操や食後の短時間活動を提案する',
                    '転倒に配慮した安全な活動環境を整える',
                ],
                st: [
                    '姿勢・体幹機能や食事中の疲労を評価する',
                    'PT・OTと連携した包括的リハビリを検討する',
                ],
                pt: [
                    '歩行・移動・体力を評価し活動量向上を支援する',
                ],
                ot: [
                    '家事や余暇を活かして座位時間を減らす工夫を行う',
                ],
                ns: [
                    '活動量を増やす環境整備と声かけを行う',
                    '体重・体組成・褥瘡リスクを定期確認する',
                ],
            },
            oral_hygiene: {
                icon: '🦠',
                label: '口腔衛生・生活習慣関連',
                patientFamily: [
                    '食後・就寝前の口腔ケアと歯科受診を勧める',
                    '糖分の多い飲食物の摂取頻度を見直す',
                ],
                st: [
                    '口腔内環境と唾液クリアランスを評価する',
                    '歯科・歯科衛生士との連携を調整する',
                ],
                pt: [
                    '食後に口腔ケアしやすい姿勢と動線を整える',
                ],
                ot: [
                    'セルフケア手順の見える化と道具選択を支援する',
                ],
                ns: [
                    '口腔内の炎症や口臭の変化を観察する',
                    'GERDや睡眠時無呼吸の兆候を観察し共有する',
                ],
            },
        },
    },
};
const ORAL_REFERENCE_IMAGE_CONFIG = {
    a3: {
        title: '歯や義歯の汚れ 参考画像',
        src: '/assets/manual_beginner/oral_reference_teeth_photo.jpg',
        alt: '歯や義歯の汚れを3段階で示した参考画像。1 ない、2 ある、3 多い。',
        note: '1 ない / 2 ある / 3 多い の目安',
    },
    a4: {
        title: '舌の汚れ 参考画像',
        src: '/assets/manual_beginner/oral_reference_tongue_photo.jpg',
        alt: '舌の汚れを3段階で示した参考画像。1 ない、2 ある、3 多い。',
        note: '1 ない / 2 ある / 3 多い の目安',
    },
};
const BIRTHDATE_YEAR_MIN = 1900;
const EVAL_DATE_YEAR_RANGE_PAST = 20;
const EVAL_DATE_YEAR_RANGE_FUTURE = 2;
const NEXT_MONITOR_YEAR_RANGE = 6;
const ODK_TIMER_SECONDS = 10;
const ORAL_SELECT_CONFIG = {
    q6: {
        label: 'お口の健康状態',
        options: [
            { value: '1', label: '良い: 口や歯のことで苦痛や不自由は感じていない' },
            { value: '2', label: 'やや良い: 口や歯のことで苦痛や不自由を殆ど感じていない' },
            { value: '3', label: 'ふつう: 時折不自由を感じることはあるが、調子が良いこともある' },
            { value: '4', label: 'やや悪い: 口や歯のことでしばしば苦痛や不自由を感じる' },
            { value: '5', label: '悪い: 口や歯のことでいつも苦痛や不自由を感じる' },
        ],
    },
    q7: {
        label: '口臭',
        options: [
            { value: '1', label: 'ない: 口臭を全くまたは殆ど感じない' },
            { value: '2', label: '弱い: 口臭はあるが、弱く我慢できる程度' },
            { value: '3', label: '強い: 近づかなくても口臭を感じる、会話しにくい' },
        ],
    },
    q8: {
        label: '口腔清掃習慣',
        options: [
            { value: '3', label: 'ある: 毎日の自発的な口腔ケア行動がある' },
            { value: '2', label: '多少ある: 毎日ではないが、週に数回は自発的な口腔ケア行動がある' },
            { value: '1', label: 'ない: 声かけしないと全く口腔ケア行動を行わない' },
        ],
    },
    q9: {
        label: 'むせ（食事中や食後のむせ）',
        options: [
            { value: '1', label: 'ない: 特に認めない' },
            { value: '2', label: '多少ある: 時々むせがある' },
            { value: '3', label: 'ある: むせにより食事が中断してしまう' },
        ],
    },
    q10: {
        label: '食べこぼし（食事中）',
        options: [
            { value: '1', label: 'ない: 食べこぼしが全くない、ほとんどない' },
            { value: '2', label: '多少ある: 殆ど毎回少量の食べこぼしがある' },
            { value: '3', label: 'ある: 殆ど毎日食べこぼしがある、目立つ' },
        ],
    },
    q11: {
        label: '表情の豊かさ',
        options: [
            { value: '1', label: '豊富: 頬や口角が上がった、はっきりとした笑顔が多い' },
            { value: '2', label: 'やや豊富: 頬や口角がやや上がった笑顔が多い' },
            { value: '3', label: 'ふつう: どちらともいえない' },
            { value: '4', label: 'やや乏しい: 表情の変化が少ない、笑顔がわかりにくい' },
            { value: '5', label: '乏しい: 表情が殆ど変化しない、笑顔が殆どない' },
        ],
    },
    a1: {
        label: '右側・咬合の収縮の確認',
        options: [
            { value: '1', label: '強い: 指先が強く押される、硬くなっているのが明確に触診できる' },
            { value: '2', label: '弱い: 指先が弱く押される、硬くなっているのが殆ど触診できない' },
            { value: '3', label: '無し: 指先が押される感覚がない' },
        ],
    },
    a2: {
        label: '左側・咬合の収縮の確認',
        options: [
            { value: '1', label: '強い: 指先が強く押される、硬くなっているのが明確に触診できる' },
            { value: '2', label: '弱い: 指先が弱く押される、硬くなっているのが殆ど触診できない' },
            { value: '3', label: '無し: 指先が押される感覚がない' },
        ],
    },
    a3: {
        label: '② 歯や義歯の汚れ',
        options: [
            { value: '1', label: 'ない: 歯と歯の間、歯と歯肉の境目に汚れが見られない' },
            { value: '2', label: 'ある: 歯と歯の間、歯と歯肉の境目に白色〜クリーム色の汚れがみられる' },
            { value: '3', label: '多い: 歯と歯の間、歯と歯肉の境目以外にも汚れや食物残渣がみられる' },
        ],
    },
    a4: {
        label: '③ 舌の汚れ',
        options: [
            { value: '1', label: 'ない: 舌全体が一様な赤色〜ピンク色をしている' },
            { value: '2', label: 'ある: 舌の一部（半分未満）が白色、黄色、褐色など汚れに覆われている' },
            { value: '3', label: '多い: 舌の半分以上が白色、黄色、褐色など汚れに覆われている' },
        ],
    },
    rsst_judge: {
        label: '専門職の判断（RSST）',
        options: [
            { value: '1', label: '問題なし: 30秒で3回以上' },
            { value: '2', label: '問題あり: 30秒で3回未満' },
        ],
    },
    bukubuku: {
        label: 'ブクブクうがい',
        options: [
            { value: '1', label: 'できる: 頬を何度も膨らまし、同時に舌も動かすことができる' },
            { value: '2', label: '不十分: 頬の膨らましが小さい（1回または2回程度）、舌の動きが弱い' },
            { value: '3', label: 'できない: 唇を閉じることができない、頬の膨らましができない' },
        ],
    },
    oral_eval2: {
        label: '② 事業またはサービスの継続の必要性',
        options: [
            { value: 'あり（継続） 口腔清掃・唾液分泌・咀嚼・嚥下・食事摂取などの口腔機能の低下が認められる状態の者', label: 'あり（継続）: 口腔清掃・唾液分泌・咀嚼・嚥下・食事摂取などの口腔機能の低下が認められる状態の者' },
            { value: 'あり（継続） 口腔機能向上サービスを継続しないことにより、口腔機能が著しく低下するおそれのある者', label: 'あり（継続）: 口腔機能向上サービスを継続しないことにより、口腔機能が著しく低下するおそれのある者' },
            { value: 'なし（終了） 口腔機能向上の効果が十分であり、自立した状態', label: 'なし（終了）: 口腔機能向上の効果が十分であり、自立した状態' },
        ],
    },
    oral_eval3: {
        label: '③ 事業またはサービスの継続の必要性（モニタリング後）',
        options: [
            { value: 'あり（継続）', label: 'あり（継続）' },
            { value: 'なし（終了）', label: 'なし（終了）' },
        ],
    },
};
let autosaveHandle = 0;
let rsstTimerHandle = 0;
let rsstRemainingSeconds = RSST_DEFAULT_SECONDS;
let odkTimerHandles = { pa: 0, ta: 0, ka: 0 };
let odkRemainingSeconds = { pa: ODK_TIMER_SECONDS, ta: ODK_TIMER_SECONDS, ka: ODK_TIMER_SECONDS };
let draftListenersBound = false;
let stage2UpdateHandle = 0;
let stage2HooksInstalled = false;
let stage2ListenersBound = false;
let summaryHooksInstalled = false;
let managedFieldHooksInstalled = false;
let latestClinicalSupportData = null;
let latestNutritionAssessmentData = null;
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

function getCompatibleSelectValue(selectElement, rawValue) {
    const text = String(rawValue ?? '').trim();
    if (!text) {
        return '';
    }

    const directMatch = Array.from(selectElement.options).find((option) => option.value === text);
    if (directMatch) {
        return directMatch.value;
    }

    const numericCode = parseChoiceCode(text);
    if (numericCode !== null) {
        const codedMatch = Array.from(selectElement.options).find((option) => parseChoiceCode(option.value) === numericCode);
        if (codedMatch) {
            return codedMatch.value;
        }
    }

    if (selectElement.id === 'oral_eval2' && text === 'あり（継続）') {
        return 'あり（継続） 口腔清掃・唾液分泌・咀嚼・嚥下・食事摂取などの口腔機能の低下が認められる状態';
    }
    if (selectElement.id === 'oral_eval2' && text === 'なし（終了）') {
        return 'なし（終了） 口腔機能向上の効果が十分であり、自立した状態';
    }
    return text;
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
        if (element.tagName === 'SELECT') {
            element.value = getCompatibleSelectValue(element, value);
            return;
        }
        element.value = value ?? '';
    });
    if (typeof syncManagedPersonSelectors === 'function') {
        syncManagedPersonSelectors();
    }
    if (typeof syncDentistPresenceField === 'function') {
        syncDentistPresenceField({ preserveValue: true });
    }
    if (typeof syncCustomDateSelectors === 'function') {
        syncCustomDateSelectors();
    }
    if (typeof syncOdkHelperFieldsFromRates === 'function') {
        syncOdkHelperFieldsFromRates();
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

function getHistoryDisplayMode() {
    return HISTORY_FILTER_STATE.view === 'records' ? 'records' : 'latest';
}

function getHistorySortMode() {
    return String(HISTORY_FILTER_STATE.sort || 'evalDate').trim() || 'evalDate';
}

function getHistoryDisplayConfig() {
    if (getHistoryDisplayMode() === 'records') {
        return {
            title: '評価日一覧',
            hint: '評価日の新しい順や優先順で、主要項目だけを縦に読みやすく整理しています。',
        };
    }
    return {
        title: '患者別最新評価',
        hint: '同じ利用者ごとに最新の評価日だけをまとめて表示します。',
    };
}

function updateHistoryDisplayHeading() {
    const title = document.getElementById('historyDisplayTitle');
    const hint = document.getElementById('historyDisplayHint');
    const config = getHistoryDisplayConfig();
    if (title) {
        title.textContent = config.title;
    }
    if (hint) {
        hint.textContent = config.hint;
    }
}

function compareTextAsc(left, right) {
    return String(left || '').localeCompare(String(right || ''), 'ja');
}

function getHistoryNameSortKey(record) {
    return String(record.furigana || record.name || '').trim();
}

function getNutritionSortRank(label) {
    const text = String(label || '').trim();
    if (text === '低栄養') {
        return 0;
    }
    if (text === 'At risk') {
        return 1;
    }
    if (text === '良好') {
        return 2;
    }
    return 3;
}

function getNextMonitorSortValue(record) {
    const text = String(record?.nextMonitor || '').trim();
    if (!text) {
        return Number.POSITIVE_INFINITY;
    }
    if (isYearMonthValue(text)) {
        const parts = parseYearMonthParts(text);
        return parts ? Date.UTC(parts.year, parts.month - 1, 1) : Number.POSITIVE_INFINITY;
    }
    const parts = parseYmdParts(text);
    return parts ? Date.UTC(parts.year, parts.month - 1, parts.day) : Number.POSITIVE_INFINITY;
}

function compareRecordsByHistorySort(left, right) {
    const sortMode = getHistorySortMode();
    if (sortMode === 'name') {
        const byName = compareTextAsc(getHistoryNameSortKey(left), getHistoryNameSortKey(right));
        return byName || compareRecordsByDateDesc(left, right);
    }
    if (sortMode === 'nutrition') {
        const byNutrition = getNutritionSortRank(left?.mnaLabel) - getNutritionSortRank(right?.mnaLabel);
        return byNutrition || compareRecordsByDateDesc(left, right);
    }
    if (sortMode === 'nextMonitor') {
        const byNextMonitor = getNextMonitorSortValue(left) - getNextMonitorSortValue(right);
        if (!Number.isNaN(byNextMonitor) && byNextMonitor !== 0) {
            return byNextMonitor;
        }
        return compareTextAsc(getHistoryNameSortKey(left), getHistoryNameSortKey(right)) || compareRecordsByDateDesc(left, right);
    }
    return compareRecordsByDateDesc(left, right);
}

function sortRecordsForHistoryDisplay(sourceRecords) {
    return [...sourceRecords].sort(compareRecordsByHistorySort);
}

function getNutritionTagClass(label) {
    const text = String(label || '').trim();
    if (text === '良好') {
        return 'tag-good';
    }
    if (text === 'At risk') {
        return 'tag-risk';
    }
    if (text === '低栄養') {
        return 'tag-bad';
    }
    return '';
}

function getOralContinueTagClass(label) {
    const text = String(label || '').trim();
    if (!text) {
        return '';
    }
    if (text.includes('終了')) {
        return 'tag-good';
    }
    if (text.includes('再評価')) {
        return 'tag-bad';
    }
    if (text.includes('継続')) {
        return 'tag-risk';
    }
    return '';
}

function buildHistoryFieldHtml(label, valueHtml) {
    return `
        <section class="history-field">
            <div class="history-field__label">${escapeHtml(label)}</div>
            <div class="history-field__value">${valueHtml}</div>
        </section>
    `;
}

function buildHistoryTagBlockHtml(text, className = '', note = '') {
    const valueText = String(text || '').trim();
    const noteText = String(note || '').trim();
    if (!valueText) {
        return '―';
    }
    const tagClass = className ? `tag ${className}` : 'tag';
    return `
        <div class="history-tag-block">
            <span class="${tagClass}">${escapeHtml(valueText)}</span>
            ${noteText ? `<div class="history-field__note">${escapeHtml(noteText)}</div>` : ''}
        </div>
    `;
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

function parseYearMonthParts(value) {
    const text = String(value || '').trim();
    const monthOnlyMatch = text.match(/^(\\d{4})-(\\d{2})$/);
    if (monthOnlyMatch) {
        return {
            year: Number.parseInt(monthOnlyMatch[1], 10),
            month: Number.parseInt(monthOnlyMatch[2], 10),
        };
    }

    const fullDateParts = parseYmdParts(text);
    if (!fullDateParts) {
        return null;
    }
    return {
        year: fullDateParts.year,
        month: fullDateParts.month,
    };
}

function isYearMonthValue(value) {
    return /^(\\d{4})-(\\d{2})$/.test(String(value || '').trim());
}

function formatYearMonthDisplay(value) {
    const parts = parseYearMonthParts(value);
    if (!parts) {
        return String(value || '').trim();
    }
    return `${parts.year}年${parts.month}月`;
}

function getMonthsUntil(value) {
    const parts = parseYearMonthParts(value);
    if (!parts) {
        return null;
    }
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;
    return (parts.year - currentYear) * 12 + (parts.month - currentMonth);
}

function isNextMonitorDueSoon(value) {
    const text = String(value || '').trim();
    if (!text) {
        return false;
    }
    if (isYearMonthValue(text)) {
        const months = getMonthsUntil(text);
        return months !== null && months <= 1;
    }
    const days = getDaysUntil(text);
    return days !== null && days <= NEXT_MONITOR_ALERT_DAYS;
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
    const q10Value = String(readValue('q10') || '').trim();
    const q11Value = String(readValue('q11') || '').trim();
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
        q10Value,
        q10Code: parseChoiceCode(q10Value),
        q11Value,
        q11Code: parseChoiceCode(q11Value),
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
        state.q10Code,
        state.q11Code,
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

function hasMeaningfulRise(currentValue, previousValue, threshold) {
    if (currentValue === null || previousValue === null) {
        return false;
    }
    return currentValue >= previousValue + threshold;
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
    if (isYearMonthValue(text)) {
        const months = getMonthsUntil(text);
        if (months === null) {
            return escapeHtml(formatYearMonthDisplay(text));
        }
        let suffix = months === 0 ? '今月予定' : `${months}か月後`;
        let className = '';
        if (months < 0) {
            suffix = `${Math.abs(months)}か月超過`;
            className = 'monitor-status--overdue';
        } else if (months <= 1) {
            className = 'monitor-status--soon';
        }
        return `${escapeHtml(formatYearMonthDisplay(text))}<br><small class="monitor-status ${className}">${escapeHtml(suffix)}</small>`;
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
    const stats = document.getElementById('historyDisplayStats');
    if (!stats) {
        return;
    }

    const totalPatients = countUniquePatients(records);
    const query = normalizeSearchText(HISTORY_FILTER_STATE.query);
    stats.textContent = query ? `${latestCount} / ${totalPatients}名を表示` : `${latestCount}名を表示`;

    const summary = document.getElementById('historyDisplaySummary');
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
        return isNextMonitorDueSoon(record.nextMonitor);
    }).length;
    const riskCount = latestRecords.filter((record) => {
        const label = String(record.mnaLabel || '').trim();
        return label && label !== '良好' && label !== '―';
    }).length;

    summary.innerHTML = [
        buildMetricChipHtml('表示中', `${latestCount}名`, 'info'),
        buildMetricChipHtml('BMI要確認', `${bmiAttentionCount}名`, bmiAttentionCount ? 'alert' : 'success'),
        buildMetricChipHtml('近日フォロー', `${dueSoonCount}名`, dueSoonCount ? 'alert' : 'success'),
        buildMetricChipHtml('栄養注意', `${riskCount}名`, riskCount ? 'alert' : 'success'),
    ].join('');
}

function updateHistoryRecordStats(filteredRecords) {
    const stats = document.getElementById('historyDisplayStats');
    if (!stats) {
        return;
    }

    const query = normalizeSearchText(HISTORY_FILTER_STATE.query);
    stats.textContent = query ? `${filteredRecords.length} / ${records.length}件を表示` : `${filteredRecords.length}件を表示`;

    const summary = document.getElementById('historyDisplaySummary');
    if (!summary) {
        return;
    }

    if (!filteredRecords.length) {
        summary.innerHTML = '';
        return;
    }

    const dueSoonCount = filteredRecords.filter((record) => isNextMonitorDueSoon(record.nextMonitor)).length;
    const riskCount = filteredRecords.filter((record) => {
        const label = String(record.mnaLabel || '').trim();
        return label && label !== '良好' && label !== '―';
    }).length;
    const reEvalCount = filteredRecords.filter((record) => String(record.oralContinue || '').includes('再評価')).length;

    summary.innerHTML = [
        buildMetricChipHtml('表示中', `${filteredRecords.length}件`, 'info'),
        buildMetricChipHtml('栄養注意', `${riskCount}件`, riskCount ? 'alert' : 'success'),
        buildMetricChipHtml('近日フォロー', `${dueSoonCount}件`, dueSoonCount ? 'alert' : 'success'),
        buildMetricChipHtml('要再評価', `${reEvalCount}件`, reEvalCount ? 'alert' : 'success'),
    ].join('');
}

function buildLatestPatientCardHtml(record, patientHistory) {
    const previousRecord = patientHistory[1] || null;
    const visitCount = patientHistory.length;
    const currentWeight = toMetricNumber(record.weight ?? record.fields?.weight);
    const previousWeight = previousRecord ? toMetricNumber(previousRecord.weight ?? previousRecord.fields?.weight) : null;
    const currentBmi = toMetricNumber(record.bmi ?? record.fields?.bmi);
    const previousBmi = previousRecord ? toMetricNumber(previousRecord.bmi ?? previousRecord.fields?.bmi) : null;
    const age = calculateAgeAtDate(record.birthdate, record.date);
    const identityParts = [];
    if (record.birthdate) {
        identityParts.push(escapeHtml(record.birthdate));
    }
    if (age !== null) {
        identityParts.push(`${age}歳`);
    }
    if (record.furigana) {
        identityParts.push(escapeHtml(record.furigana));
    }

    const metricParts = [];
    if (currentWeight !== null) {
        metricParts.push(`<strong>${escapeHtml(formatMetricValue(currentWeight, 'kg'))}</strong>`);
    }
    if (currentBmi !== null) {
        metricParts.push(`<div class="history-field__note">BMI ${escapeHtml(formatMetricValue(currentBmi))}</div>`);
    }

    const nutritionLabel = String(record.mnaLabel || '').trim() || '―';
    const scoreLabel = record.mnaScore !== null && record.mnaScore !== undefined ? `${record.mnaScore}/14` : 'MNA未入力';

    return `
        <article class="history-card history-card--latest">
            <div class="history-card__header">
                <div class="history-card__lead">
                    <div class="history-card__title">${escapeHtml(record.name || '名称未設定')}</div>
                    <div class="history-card__subline">${identityParts.length ? identityParts.join(' / ') : '患者情報なし'}</div>
                </div>
                <div class="history-card__date-block">
                    <div class="history-card__date-label">最新評価日</div>
                    <div class="history-card__date">${escapeHtml(record.date || '―')}</div>
                </div>
            </div>
            <div class="history-card__grid">
                ${buildHistoryFieldHtml('体重 / BMI', metricParts.length ? metricParts.join('') : '―')}
                ${buildHistoryFieldHtml('前回比', [
                    buildTrendDeltaHtml(currentWeight, previousWeight, 'kg', '体重'),
                    buildTrendDeltaHtml(currentBmi, previousBmi, '', 'BMI'),
                ].join('<br>'))}
                ${buildHistoryFieldHtml('栄養判定', buildHistoryTagBlockHtml(nutritionLabel, getNutritionTagClass(nutritionLabel), scoreLabel))}
                ${buildHistoryFieldHtml('次回モニタリング', buildNextMonitorHtml(record.nextMonitor))}
            </div>
            <div class="history-card__footer">
                <div class="history-card__chips">${buildMetricChipHtml('評価回数', `${visitCount}件`, visitCount > 1 ? 'info' : 'success')}</div>
                <div class="history-card__actions">
                    <button class="btn btn-outline btn-sm" onclick="loadRecord(${Number(record.id)})">最新を読込</button>
                </div>
            </div>
        </article>
    `;
}

function buildHistoryRecordCardHtml(record) {
    const identityLine = buildHistoryIdentityLine(record) || '患者情報なし';
    const nutritionLabel = String(record.mnaLabel || '').trim() || '―';
    const oralLabel = String(record.oralContinue || '').trim() || '―';
    const scoreLabel = record.mnaScore !== null && record.mnaScore !== undefined ? `${record.mnaScore}/14` : 'MNA未入力';

    return `
        <article class="history-card history-card--record">
            <div class="history-card__header">
                <div class="history-card__lead">
                    <div class="history-card__title-row">
                        <div class="history-card__date-pill">${escapeHtml(record.date || '―')}</div>
                        <div class="history-card__title">${escapeHtml(record.name || '名称未設定')}</div>
                    </div>
                    <div class="history-card__subline">${identityLine}</div>
                </div>
                <div class="history-card__actions">
                    <button class="btn btn-outline btn-sm" onclick="loadRecord(${Number(record.id)})">読込</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteRecord(${Number(record.id)})">削除</button>
                </div>
            </div>
            <div class="history-card__grid history-card__grid--compact">
                ${buildHistoryFieldHtml('栄養判定', buildHistoryTagBlockHtml(nutritionLabel, getNutritionTagClass(nutritionLabel), scoreLabel))}
                ${buildHistoryFieldHtml('口腔継続', buildHistoryTagBlockHtml(oralLabel, getOralContinueTagClass(oralLabel)))}
                ${buildHistoryFieldHtml('次回モニタリング', buildNextMonitorHtml(record.nextMonitor))}
            </div>
        </article>
    `;
}

function renderHistoryRecords(filteredRecords) {
    const container = document.getElementById('historyDisplayBody');
    if (!container) {
        return;
    }

    updateHistoryDisplayHeading();
    updateHistoryRecordStats(filteredRecords);

    if (filteredRecords.length === 0) {
        const emptyMessage = records.length === 0 ? '保存された記録はありません' : '検索条件に一致する記録はありません';
        container.innerHTML = `<div class="empty-state"><div class="icon">📂</div>${emptyMessage}</div>`;
        return;
    }

    container.innerHTML = sortRecordsForHistoryDisplay(filteredRecords)
        .map((record) => buildHistoryRecordCardHtml(record))
        .join('');
}

function renderLatestPatients(filteredRecords) {
    const container = document.getElementById('historyDisplayBody');
    if (!container) {
        return;
    }

    const { latestRecords, patientGroups } = getLatestPatientRecords(filteredRecords);
    updateHistoryDisplayHeading();
    updateLatestPatientsStats(latestRecords);

    if (latestRecords.length === 0) {
        const emptyMessage = records.length === 0 ? '保存された利用者はありません' : '検索条件に一致する利用者はありません';
        container.innerHTML = `<div class="empty-state"><div class="icon">👥</div>${emptyMessage}</div>`;
        return;
    }

    container.innerHTML = sortRecordsForHistoryDisplay(latestRecords).map((record) => {
        const patientKey = getRecordPatientKey(record);
        const patientHistory = patientGroups.get(patientKey) || [record];
        return buildLatestPatientCardHtml(record, patientHistory);
    }).join('');
}

function renderActiveHistoryView(filteredRecords) {
    if (getHistoryDisplayMode() === 'records') {
        renderHistoryRecords(filteredRecords);
        return;
    }
    renderLatestPatients(filteredRecords);
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
    historyWrapper.classList.add('history-records-wrapper');
    historyWrapper.hidden = true;
    historyWrapper.setAttribute('aria-hidden', 'true');
    Array.from(historyTable.querySelectorAll('thead th')).forEach((header) => header.classList.add('history-table__heading'));
    [0, 2, 3, 4, 5].forEach((index) => {
        historyTable.querySelector(`thead th:nth-child(${index + 1})`)?.classList.add('history-table__nowrap');
    });

    const toolbar = document.createElement('div');
    toolbar.className = 'history-toolbar';

    toolbar.innerHTML = `
      <label class="history-toolbar__search">
        <span class="history-toolbar__label">利用者検索</span>
        <input id="historySearch" class="history-toolbar__input" type="search" data-skip-persist="1" placeholder="氏名・ふりがな・生年月日・評価日で検索">
      </label>
      <div id="historyStats" class="history-stats"></div>
    `;

    const patientPanel = document.createElement('section');
    patientPanel.id = 'historyDisplayPanel';
    patientPanel.className = 'history-panel';
    patientPanel.innerHTML = `
        <div class="history-panel__header">
            <div>
                <div id="historyDisplayTitle" class="history-panel__title">患者別最新評価</div>
                <div id="historyDisplayHint" class="history-section-hint">同じ利用者ごとに最新の評価日だけをまとめて表示します。</div>
            </div>
            <div id="historyDisplayStats" class="history-stats"></div>
        </div>
        <div class="history-panel__summary-bar">
            <div id="historyDisplaySummary" class="metric-chip-list"></div>
            <div class="history-panel__controls">
                <label class="history-toolbar__field">
                    <span class="history-toolbar__label">表示</span>
                    <select id="historyViewSelect" class="history-toolbar__select" data-skip-persist="1">
                        <option value="latest">患者別最新評価</option>
                        <option value="records">評価日一覧</option>
                    </select>
                </label>
                <label class="history-toolbar__field">
                    <span class="history-toolbar__label">並び替え</span>
                    <select id="historySortSelect" class="history-toolbar__select" data-skip-persist="1">
                        <option value="evalDate">評価日</option>
                        <option value="name">氏名</option>
                        <option value="nutrition">栄養判定</option>
                        <option value="nextMonitor">次回モニタリング</option>
                    </select>
                </label>
            </div>
        </div>
        <div id="historyDisplayBody" class="history-card-list">
            <div class="empty-state"><div class="icon">👥</div>利用者データを読み込み中です</div>
        </div>
    `;

    historyCard.insertBefore(toolbar, historyWrapper);
    historyCard.insertBefore(patientPanel, historyWrapper);

    const searchInput = document.getElementById('historySearch');
    const viewSelect = document.getElementById('historyViewSelect');
    const sortSelect = document.getElementById('historySortSelect');
    searchInput.value = HISTORY_FILTER_STATE.query;
    viewSelect.value = getHistoryDisplayMode();
    sortSelect.value = getHistorySortMode();
    searchInput.addEventListener('input', (event) => {
        HISTORY_FILTER_STATE.query = event.target.value || '';
        renderHistory();
    });
    viewSelect.addEventListener('change', (event) => {
        HISTORY_FILTER_STATE.view = event.target.value === 'records' ? 'records' : 'latest';
        renderHistory();
    });
    sortSelect.addEventListener('change', (event) => {
        HISTORY_FILTER_STATE.sort = String(event.target.value || 'evalDate').trim() || 'evalDate';
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

function padDatePart(value) {
    return String(value || '').padStart(2, '0');
}

function getDaysInMonth(year, month) {
    if (!year || !month) {
        return 31;
    }
    return new Date(Number(year), Number(month), 0).getDate();
}

function renderSelectOptions(selectElement, options, placeholderLabel, formatter = null) {
    if (!selectElement) {
        return;
    }
    const placeholder = `<option value="">${escapeHtml(placeholderLabel)}</option>`;
    const renderedOptions = options.map((option) => {
        const value = String(option.value);
        const label = formatter ? formatter(option) : String(option.label ?? option.value);
        return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
    }).join('');
    selectElement.innerHTML = placeholder + renderedOptions;
}

function buildPatientSelectGroup(id, label, options) {
    const group = document.createElement('div');
    group.className = 'form-group';
    group.id = `${id}_group`;
    group.innerHTML = `<label>${escapeHtml(label)}</label><select id="${id}"><option value="">選択</option></select>`;
    const select = group.querySelector('select');
    renderSelectOptions(
        select,
        options.map((option) => ({ value: option })),
        '選択',
        (option) => option.value,
    );
    return group;
}

function ensurePatientAgeField(anchorGroup) {
    let ageGroup = document.getElementById('patientAgeGroup');
    if (!ageGroup) {
        ageGroup = document.createElement('div');
        ageGroup.className = 'form-group';
        ageGroup.id = 'patientAgeGroup';
        ageGroup.innerHTML = '<label>年齢（自動計算）</label><input type="text" id="patientAgeDisplay" data-skip-persist="1" readonly style="background:#f0f4f8;font-weight:700;">';
        anchorGroup.insertAdjacentElement('afterend', ageGroup);
    }
}

function updatePatientAgeDisplay() {
    const ageDisplay = document.getElementById('patientAgeDisplay');
    if (!ageDisplay) {
        return;
    }
    const birthdate = getFieldElementValue('birthdate').trim();
    const evalDate = getFieldElementValue('evalDate').trim() || new Date().toISOString().slice(0, 10);
    const age = calculateAgeAtDate(birthdate, evalDate);
    ageDisplay.value = age === null ? '' : `${age}歳`;
}

function ensureDateSelectorRow(groupElement, rowId, html) {
    let row = document.getElementById(rowId);
    if (row) {
        return row;
    }
    row = document.createElement('div');
    row.id = rowId;
    row.className = 'date-selector-row';
    row.style.display = 'flex';
    row.style.flexWrap = 'wrap';
    row.style.alignItems = 'center';
    row.style.gap = '8px';
    row.style.marginTop = '8px';
    row.innerHTML = html;
    groupElement.appendChild(row);
    return row;
}

function populateBirthdateYearMonthSelectors() {
    const yearSelect = document.getElementById('birthdate_year');
    const monthSelect = document.getElementById('birthdate_month');
    if (!yearSelect || !monthSelect || yearSelect.dataset.ready === '1') {
        return;
    }
    const currentYear = new Date().getFullYear();
    renderSelectOptions(
        yearSelect,
        Array.from({ length: currentYear - BIRTHDATE_YEAR_MIN + 1 }, (_, index) => ({ value: String(currentYear - index) })),
        '年',
        (option) => option.value,
    );
    renderSelectOptions(
        monthSelect,
        Array.from({ length: 12 }, (_, index) => ({ value: padDatePart(index + 1), label: `${index + 1}` })),
        '月',
        (option) => option.label,
    );
    yearSelect.dataset.ready = '1';
}

function populateBirthdateDaySelector(selectedDay = '') {
    const year = document.getElementById('birthdate_year')?.value || '';
    const month = document.getElementById('birthdate_month')?.value || '';
    const daySelect = document.getElementById('birthdate_day');
    if (!daySelect) {
        return;
    }
    const dayCount = getDaysInMonth(year, month);
    renderSelectOptions(
        daySelect,
        Array.from({ length: dayCount }, (_, index) => ({ value: padDatePart(index + 1), label: `${index + 1}` })),
        '日',
        (option) => option.label,
    );
    daySelect.value = selectedDay && Number(selectedDay) <= dayCount ? padDatePart(selectedDay) : '';
}

function syncBirthdateHiddenFromSelectors() {
    const hiddenInput = document.getElementById('birthdate');
    const year = document.getElementById('birthdate_year')?.value || '';
    const month = document.getElementById('birthdate_month')?.value || '';
    const day = document.getElementById('birthdate_day')?.value || '';
    if (!hiddenInput) {
        return;
    }
    hiddenInput.value = year && month && day ? `${year}-${month}-${day}` : '';
    hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
    updatePatientAgeDisplay();
}

function syncBirthdateSelectorsFromHidden() {
    const hiddenInput = document.getElementById('birthdate');
    if (!hiddenInput) {
        return;
    }
    populateBirthdateYearMonthSelectors();
    const parts = parseYmdParts(hiddenInput.value);
    const yearSelect = document.getElementById('birthdate_year');
    const monthSelect = document.getElementById('birthdate_month');
    if (!yearSelect || !monthSelect) {
        return;
    }
    yearSelect.value = parts ? String(parts.year) : '';
    monthSelect.value = parts ? padDatePart(parts.month) : '';
    populateBirthdateDaySelector(parts ? parts.day : '');
    updatePatientAgeDisplay();
}

function ensureBirthdateSelector() {
    const birthInput = document.getElementById('birthdate');
    if (!birthInput) {
        return;
    }
    const birthGroup = birthInput.closest('.form-group');
    if (!birthGroup) {
        return;
    }
    birthInput.type = 'hidden';
    birthInput.style.display = 'none';
    birthInput.setAttribute('aria-hidden', 'true');
    birthInput.tabIndex = -1;
    const label = birthGroup.querySelector('label');
    if (label) {
        label.textContent = '生年月日';
    }
    ensureDateSelectorRow(
        birthGroup,
        'birthdateSelectorRow',
        '<select id="birthdate_year" data-skip-persist="1" style="flex:1 1 110px;min-width:90px;"></select><span>年</span><select id="birthdate_month" data-skip-persist="1" style="width:88px;"></select><span>月</span><select id="birthdate_day" data-skip-persist="1" style="width:88px;"></select><span>日</span>',
    );
    ensurePatientAgeField(birthGroup);
    populateBirthdateYearMonthSelectors();
    populateBirthdateDaySelector();

    const yearSelect = document.getElementById('birthdate_year');
    const monthSelect = document.getElementById('birthdate_month');
    const daySelect = document.getElementById('birthdate_day');
    if (yearSelect && !yearSelect.dataset.boundBirthdate) {
        const handleChange = () => {
            populateBirthdateDaySelector(daySelect?.value || '');
            syncBirthdateHiddenFromSelectors();
        };
        yearSelect.addEventListener('change', handleChange);
        monthSelect?.addEventListener('change', handleChange);
        daySelect?.addEventListener('change', syncBirthdateHiddenFromSelectors);
        yearSelect.dataset.boundBirthdate = '1';
    }
    syncBirthdateSelectorsFromHidden();
}

function populateEvalDateYearMonthSelectors() {
    const yearSelect = document.getElementById('evalDate_year');
    const monthSelect = document.getElementById('evalDate_month');
    if (!yearSelect || !monthSelect || yearSelect.dataset.ready === '1') {
        return;
    }
    const currentYear = new Date().getFullYear();
    const startYear = currentYear + EVAL_DATE_YEAR_RANGE_FUTURE;
    const optionCount = EVAL_DATE_YEAR_RANGE_PAST + EVAL_DATE_YEAR_RANGE_FUTURE + 1;
    renderSelectOptions(
        yearSelect,
        Array.from({ length: optionCount }, (_, index) => ({ value: String(startYear - index) })),
        '年',
        (option) => option.value,
    );
    renderSelectOptions(
        monthSelect,
        Array.from({ length: 12 }, (_, index) => ({ value: padDatePart(index + 1), label: `${index + 1}` })),
        '月',
        (option) => option.label,
    );
    yearSelect.dataset.ready = '1';
}

function populateEvalDateDaySelector(selectedDay = '') {
    const year = document.getElementById('evalDate_year')?.value || '';
    const month = document.getElementById('evalDate_month')?.value || '';
    const daySelect = document.getElementById('evalDate_day');
    if (!daySelect) {
        return;
    }
    const dayCount = getDaysInMonth(year, month);
    renderSelectOptions(
        daySelect,
        Array.from({ length: dayCount }, (_, index) => ({ value: padDatePart(index + 1), label: `${index + 1}` })),
        '日',
        (option) => option.label,
    );
    daySelect.value = selectedDay && Number(selectedDay) <= dayCount ? padDatePart(selectedDay) : '';
}

function syncEvalDateHiddenFromSelectors() {
    const hiddenInput = document.getElementById('evalDate');
    const year = document.getElementById('evalDate_year')?.value || '';
    const month = document.getElementById('evalDate_month')?.value || '';
    const day = document.getElementById('evalDate_day')?.value || '';
    if (!hiddenInput) {
        return;
    }
    hiddenInput.value = year && month && day ? `${year}-${month}-${day}` : '';
    hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
    updatePatientAgeDisplay();
}

function syncEvalDateSelectorsFromHidden() {
    const hiddenInput = document.getElementById('evalDate');
    if (!hiddenInput) {
        return;
    }
    populateEvalDateYearMonthSelectors();
    const parts = parseYmdParts(hiddenInput.value);
    const yearSelect = document.getElementById('evalDate_year');
    const monthSelect = document.getElementById('evalDate_month');
    if (!yearSelect || !monthSelect) {
        return;
    }
    yearSelect.value = parts ? String(parts.year) : '';
    monthSelect.value = parts ? padDatePart(parts.month) : '';
    populateEvalDateDaySelector(parts ? parts.day : '');
}

function ensureEvalDateSelector() {
    const evalDateInput = document.getElementById('evalDate');
    if (!evalDateInput) {
        return;
    }
    const evalDateGroup = evalDateInput.closest('.form-group');
    if (!evalDateGroup) {
        return;
    }
    evalDateInput.type = 'hidden';
    evalDateInput.style.display = 'none';
    evalDateInput.setAttribute('aria-hidden', 'true');
    evalDateInput.tabIndex = -1;
    const label = evalDateGroup.querySelector('label');
    if (label) {
        label.textContent = '評価日';
    }
    ensureDateSelectorRow(
        evalDateGroup,
        'evalDateSelectorRow',
        '<select id="evalDate_year" data-skip-persist="1" style="flex:1 1 110px;min-width:90px;"></select><span>年</span><select id="evalDate_month" data-skip-persist="1" style="width:88px;"></select><span>月</span><select id="evalDate_day" data-skip-persist="1" style="width:88px;"></select><span>日</span>',
    );
    populateEvalDateYearMonthSelectors();
    populateEvalDateDaySelector();

    const yearSelect = document.getElementById('evalDate_year');
    const monthSelect = document.getElementById('evalDate_month');
    const daySelect = document.getElementById('evalDate_day');
    if (yearSelect && !yearSelect.dataset.boundEvalDate) {
        const handleChange = () => {
            populateEvalDateDaySelector(daySelect?.value || '');
            syncEvalDateHiddenFromSelectors();
        };
        yearSelect.addEventListener('change', handleChange);
        monthSelect?.addEventListener('change', handleChange);
        daySelect?.addEventListener('change', syncEvalDateHiddenFromSelectors);
        yearSelect.dataset.boundEvalDate = '1';
    }
    syncEvalDateSelectorsFromHidden();
}

function populateNextMonitorSelectors() {
    const yearSelect = document.getElementById('next_monitor_year');
    const monthSelect = document.getElementById('next_monitor_month');
    if (!yearSelect || !monthSelect || yearSelect.dataset.ready === '1') {
        return;
    }
    const currentYear = new Date().getFullYear();
    renderSelectOptions(
        yearSelect,
        Array.from({ length: NEXT_MONITOR_YEAR_RANGE + 2 }, (_, index) => ({ value: String(currentYear - 1 + index) })),
        '年',
        (option) => option.value,
    );
    renderSelectOptions(
        monthSelect,
        Array.from({ length: 12 }, (_, index) => ({ value: padDatePart(index + 1), label: `${index + 1}` })),
        '月',
        (option) => option.label,
    );
    yearSelect.dataset.ready = '1';
}

function syncNextMonitorHiddenFromSelectors() {
    const hiddenInput = document.getElementById('next_monitor');
    const year = document.getElementById('next_monitor_year')?.value || '';
    const month = document.getElementById('next_monitor_month')?.value || '';
    if (!hiddenInput) {
        return;
    }
    hiddenInput.value = year && month ? `${year}-${month}` : '';
    hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
}

function syncNextMonitorSelectorsFromHidden() {
    const hiddenInput = document.getElementById('next_monitor');
    if (!hiddenInput) {
        return;
    }
    populateNextMonitorSelectors();
    const parts = parseYearMonthParts(hiddenInput.value);
    const yearSelect = document.getElementById('next_monitor_year');
    const monthSelect = document.getElementById('next_monitor_month');
    if (!yearSelect || !monthSelect) {
        return;
    }
    yearSelect.value = parts ? String(parts.year) : '';
    monthSelect.value = parts ? padDatePart(parts.month) : '';
    if (parts) {
        hiddenInput.value = `${parts.year}-${padDatePart(parts.month)}`;
    }
}

function ensureNextMonitorSelector() {
    const nextMonitorInput = document.getElementById('next_monitor');
    if (!nextMonitorInput) {
        return;
    }
    const nextMonitorGroup = nextMonitorInput.closest('.form-group');
    if (!nextMonitorGroup) {
        return;
    }
    nextMonitorInput.type = 'hidden';
    nextMonitorInput.style.display = 'none';
    nextMonitorInput.setAttribute('aria-hidden', 'true');
    nextMonitorInput.tabIndex = -1;
    const label = nextMonitorGroup.querySelector('label');
    if (label) {
        label.textContent = '次回モニタリング予定年月';
    }
    ensureDateSelectorRow(
        nextMonitorGroup,
        'nextMonitorSelectorRow',
        '<select id="next_monitor_year" data-skip-persist="1" style="flex:1 1 120px;min-width:96px;"></select><span>年</span><select id="next_monitor_month" data-skip-persist="1" style="width:88px;"></select><span>月</span>',
    );
    populateNextMonitorSelectors();

    const yearSelect = document.getElementById('next_monitor_year');
    const monthSelect = document.getElementById('next_monitor_month');
    if (yearSelect && !yearSelect.dataset.boundNextMonitor) {
        const handleChange = () => syncNextMonitorHiddenFromSelectors();
        yearSelect.addEventListener('change', handleChange);
        monthSelect?.addEventListener('change', handleChange);
        yearSelect.dataset.boundNextMonitor = '1';
    }
    syncNextMonitorSelectorsFromHidden();
}

function ensurePatientFieldOrder() {
    const furiganaInput = document.getElementById('furigana');
    const nameInput = document.getElementById('name');
    if (!furiganaInput || !nameInput) {
        return;
    }
    const furiganaGroup = furiganaInput.closest('.form-group');
    const nameGroup = nameInput.closest('.form-group');
    const patientGrid = furiganaGroup?.parentElement;
    if (!furiganaGroup || !nameGroup || !patientGrid) {
        return;
    }
    patientGrid.insertBefore(nameGroup, furiganaGroup);
    const nameLabel = nameGroup.querySelector('label');
    if (nameLabel) {
        nameLabel.textContent = '氏名';
    }
    const furiganaLabel = furiganaGroup.querySelector('label');
    if (furiganaLabel) {
        furiganaLabel.textContent = 'ふりがな';
    }
}

function removeLegacyServiceFields() {
    ['serviceStart', 'serviceEnd'].forEach((id) => {
        const element = document.getElementById(id);
        const group = element?.closest('.form-group');
        if (group) {
            group.remove();
        }
    });
}

function ensureFoodTextureFields() {
    const bmiInput = document.getElementById('bmi');
    if (!bmiInput || document.getElementById('food_staple')) {
        return;
    }
    const bmiGroup = bmiInput.closest('.form-group');
    if (!bmiGroup) {
        return;
    }
    const stapleGroup = buildPatientSelectGroup('food_staple', '現在の食形態（主食）', FOOD_STAPLE_OPTIONS);
    const mainGroup = buildPatientSelectGroup('food_main', '現在の食形態（主菜）', FOOD_MAIN_OPTIONS);
    const waterGroup = buildPatientSelectGroup('water_texture', '現在の水分形態', WATER_TEXTURE_OPTIONS);
    bmiGroup.insertAdjacentElement('afterend', stapleGroup);
    stapleGroup.insertAdjacentElement('afterend', mainGroup);
    mainGroup.insertAdjacentElement('afterend', waterGroup);
}

function syncCustomDateSelectors() {
    syncBirthdateSelectorsFromHidden();
    syncEvalDateSelectorsFromHidden();
    syncNextMonitorSelectorsFromHidden();
    updatePatientAgeDisplay();
}

function ensurePatientFormEnhancements() {
    ensurePatientFieldOrder();
    ensureBirthdateSelector();
    ensureEvalDateSelector();
    ensureFoodTextureFields();
    removeLegacyServiceFields();
    ensureNextMonitorSelector();
    bindDentistPresenceField();
    syncDentistPresenceField({ preserveValue: true });
    const evalDateInput = document.getElementById('evalDate');
    if (evalDateInput && !evalDateInput.dataset.boundAgeDisplay) {
        evalDateInput.addEventListener('input', updatePatientAgeDisplay);
        evalDateInput.dataset.boundAgeDisplay = '1';
    }
    updatePatientAgeDisplay();
}

function findNearestSectionLabelElement(fieldElement) {
    let cursor = fieldElement?.closest('.form-group') || fieldElement?.parentElement || null;
    while (cursor) {
        let sibling = cursor.previousElementSibling;
        while (sibling) {
            if (sibling.classList?.contains('section-label')) {
                return sibling;
            }
            const nested = typeof sibling.querySelector === 'function' ? sibling.querySelector('.section-label') : null;
            if (nested) {
                return nested;
            }
            sibling = sibling.previousElementSibling;
        }
        cursor = cursor.parentElement;
    }
    return null;
}

function applySelectConfig(fieldId, config, options = {}) {
    const selectElement = document.getElementById(fieldId);
    if (!selectElement || selectElement.tagName !== 'SELECT' || !config) {
        return;
    }
    const currentValue = String(selectElement.value || '').trim();
    renderSelectOptions(selectElement, config.options || [], '選択', (option) => option.label);
    const label = selectElement.closest('.form-group')?.querySelector('label');
    if (label && config.label && !options.useSectionLabelOnly) {
        label.textContent = config.label;
    }
    if (config.label && options.sectionLabel) {
        const sectionLabel = findNearestSectionLabelElement(selectElement);
        if (sectionLabel) {
            sectionLabel.textContent = config.label;
        }
    }
    selectElement.value = getCompatibleSelectValue(selectElement, currentValue);
}

function ensureOralEvaluationFields() {
    const oralEval2 = document.getElementById('oral_eval2');
    if (!oralEval2) {
        return;
    }

    const oralEval2Group = oralEval2.closest('.form-group');
    let oralEval3 = document.getElementById('oral_eval3');
    if (!oralEval3 && oralEval2Group) {
        const group = document.createElement('div');
        group.className = 'form-group';
        group.style.marginBottom = '10px';
        group.innerHTML = '<label>③ 事業またはサービスの継続の必要性（モニタリング後）</label><select id="oral_eval3"><option value="">選択</option></select>';
        oralEval2Group.insertAdjacentElement('afterend', group);
        oralEval3 = group.querySelector('select');
    }

    const oralBiko = document.getElementById('oral_biko');
    const oralBikoLabel = oralBiko?.closest('.form-group')?.querySelector('label');
    if (oralBikoLabel) {
        oralBikoLabel.textContent = '④ 備考';
    }

    applySelectConfig('oral_eval2', ORAL_SELECT_CONFIG.oral_eval2);
    applySelectConfig('oral_eval3', ORAL_SELECT_CONFIG.oral_eval3);
}

function ensureOralDyskinesiaInlineLayout() {
    const paInput = document.getElementById('pa');
    const taInput = document.getElementById('ta');
    const kaInput = document.getElementById('ka');
    const paGroup = paInput?.closest('.form-group');
    const taGroup = taInput?.closest('.form-group');
    const kaGroup = kaInput?.closest('.form-group');
    const container = paGroup?.parentElement;
    if (!paGroup || !taGroup || !kaGroup || !container) {
        return;
    }
    if (!container.contains(taGroup) || !container.contains(kaGroup)) {
        return;
    }
    container.classList.add('odk-inline-grid');
    [paGroup, taGroup, kaGroup].forEach((group) => group.classList.add('odk-inline-grid__item'));
}

function getOdkHelperLabel(fieldId) {
    return fieldId === 'pa' ? 'パ' : fieldId === 'ta' ? 'タ' : 'カ';
}

function getOdkCountInput(fieldId) {
    return document.getElementById(`${fieldId}_count`);
}

function getOdkTimerDisplay(fieldId) {
    return document.getElementById(`${fieldId}TimerDisplay`);
}

function updateOdkDisplay(fieldId) {
    const display = getOdkTimerDisplay(fieldId);
    if (!display) {
        return;
    }
    display.textContent = `${odkRemainingSeconds[fieldId]}秒`;
}

function syncOdkRateFromCount(fieldId) {
    const countInput = getOdkCountInput(fieldId);
    const rateInput = document.getElementById(fieldId);
    if (!countInput || !rateInput) {
        return;
    }
    const count = Number.parseInt(countInput.value || '0', 10) || 0;
    rateInput.value = count > 0 ? (count / ODK_TIMER_SECONDS).toFixed(1) : '';
    rateInput.dispatchEvent(new Event('input', { bubbles: true }));
}

function resetOdkTimer(fieldId, options = {}) {
    if (odkTimerHandles[fieldId]) {
        window.clearInterval(odkTimerHandles[fieldId]);
        odkTimerHandles[fieldId] = 0;
    }
    odkRemainingSeconds[fieldId] = ODK_TIMER_SECONDS;
    const countInput = getOdkCountInput(fieldId);
    if (countInput) {
        countInput.value = '0';
    }
    const rateInput = document.getElementById(fieldId);
    if (rateInput) {
        rateInput.value = '';
        rateInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    updateOdkDisplay(fieldId);
    if (!options.quiet) {
        showToast(`⏱️ ${getOdkHelperLabel(fieldId)} 10秒タイマーをリセットしました`);
    }
}

function incrementOdkCount(fieldId) {
    const countInput = getOdkCountInput(fieldId);
    if (!countInput) {
        return;
    }
    const current = Number.parseInt(countInput.value || '0', 10) || 0;
    countInput.value = String(current + 1);
    syncOdkRateFromCount(fieldId);
}

function startOdkTimer(fieldId) {
    if (odkTimerHandles[fieldId]) {
        return;
    }
    resetOdkTimer(fieldId, { quiet: true });
    odkRemainingSeconds[fieldId] = ODK_TIMER_SECONDS;
    updateOdkDisplay(fieldId);

    odkTimerHandles[fieldId] = window.setInterval(() => {
        odkRemainingSeconds[fieldId] -= 1;
        updateOdkDisplay(fieldId);
        if (odkRemainingSeconds[fieldId] <= 0) {
            window.clearInterval(odkTimerHandles[fieldId]);
            odkTimerHandles[fieldId] = 0;
            showToast(`✅ ${getOdkHelperLabel(fieldId)} 10秒計測が終了しました`);
        }
    }, 1000);
}

function syncOdkHelperFieldsFromRates() {
    ['pa', 'ta', 'ka'].forEach((fieldId) => {
        odkRemainingSeconds[fieldId] = ODK_TIMER_SECONDS;
        updateOdkDisplay(fieldId);
        const countInput = getOdkCountInput(fieldId);
        const rateValue = toMetricNumber(getFieldElementValue(fieldId));
        if (countInput) {
            countInput.value = rateValue !== null ? String(Math.round(rateValue * ODK_TIMER_SECONDS)) : '0';
        }
    });
}

function ensureOralReferencePanel(fieldId, config) {
    const selectElement = document.getElementById(fieldId);
    const group = selectElement?.closest('.form-group');
    if (!group || !config) {
        return;
    }

    let panel = document.getElementById(`${fieldId}ReferencePanel`);
    if (!panel) {
        panel = document.createElement('div');
        panel.id = `${fieldId}ReferencePanel`;
        panel.className = 'oral-reference-panel no-print';
        panel.innerHTML = `
            <div class="oral-reference-panel__header">
                <div class="section-label" style="margin:0;">${escapeHtml(config.title || '参考画像')}</div>
                <div class="oral-reference-panel__hint">${escapeHtml(config.note || '')}</div>
            </div>
            <img class="oral-reference-panel__image" src="${escapeHtml(config.src || '')}" alt="${escapeHtml(config.alt || config.title || '参考画像')}" loading="lazy">
        `;
        group.insertAdjacentElement('afterend', panel);
    }

    const image = panel.querySelector('img');
    if (image && !image.dataset.boundFallback) {
        image.addEventListener('error', () => {
            image.remove();
            panel.classList.add('oral-reference-panel--missing');
            const fallback = document.createElement('div');
            fallback.className = 'oral-reference-panel__fallback';
            fallback.textContent = '参考画像ファイルを配置するとここに表示されます。';
            panel.appendChild(fallback);
        }, { once: true });
        image.dataset.boundFallback = '1';
    }
}

function ensureOralReferencePanels() {
    Object.entries(ORAL_REFERENCE_IMAGE_CONFIG).forEach(([fieldId, config]) => {
        ensureOralReferencePanel(fieldId, config);
    });
}

function ensureOdkTimerTools() {
    const odkGrid = document.getElementById('pa')?.closest('.form-grid');
    if (!odkGrid || document.getElementById('odkTimerPanel')) {
        return;
    }

    const panel = document.createElement('div');
    panel.id = 'odkTimerPanel';
    panel.className = 'rsst-timer-panel';
    panel.style.marginTop = '12px';
    panel.innerHTML = `
        <div class="rsst-timer-panel__header">
            <div>
                <div class="section-label" style="margin:0 0 6px 0;">パ・タ・カ 10秒タイマー</div>
                <div class="rsst-timer-panel__hint">開始後は各音のカウントボタンで回数を加算し、10秒後に回/秒へ換算します。</div>
            </div>
        </div>
        <div class="odk-timer-grid">
            ${['pa', 'ta', 'ka'].map((fieldId) => `
                <div class="odk-timer-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                        <strong>${getOdkHelperLabel(fieldId)}</strong>
                        <span id="${fieldId}TimerDisplay" class="rsst-timer-panel__display" style="min-width:auto;padding:6px 10px;">10秒</span>
                    </div>
                    <div class="form-group" style="margin:0;">
                        <label style="font-size:12px;">カウント</label>
                        <input type="number" id="${fieldId}_count" data-skip-persist="1" value="0" readonly>
                    </div>
                    <div class="rsst-timer-panel__buttons">
                        <button type="button" class="btn btn-primary" id="${fieldId}TimerStartButton">▶ 開始</button>
                        <button type="button" class="btn btn-outline" id="${fieldId}TimerResetButton">↺ リセット</button>
                    </div>
                    <button type="button" class="btn btn-accent rsst-tap-btn" id="${fieldId}TapButton">＋ 1 回</button>
                </div>
            `).join('')}
        </div>
    `;
    odkGrid.insertAdjacentElement('afterend', panel);

    ['pa', 'ta', 'ka'].forEach((fieldId) => {
        panel.querySelector(`#${fieldId}TimerStartButton`)?.addEventListener('click', () => startOdkTimer(fieldId));
        panel.querySelector(`#${fieldId}TimerResetButton`)?.addEventListener('click', () => resetOdkTimer(fieldId));
        panel.querySelector(`#${fieldId}TapButton`)?.addEventListener('click', () => incrementOdkCount(fieldId));
    });
    syncOdkHelperFieldsFromRates();
}

function ensureOralAssessmentEnhancements() {
    applySelectConfig('q6', ORAL_SELECT_CONFIG.q6);
    applySelectConfig('q7', ORAL_SELECT_CONFIG.q7);
    applySelectConfig('q8', ORAL_SELECT_CONFIG.q8);
    applySelectConfig('q9', ORAL_SELECT_CONFIG.q9);
    applySelectConfig('q10', ORAL_SELECT_CONFIG.q10);
    applySelectConfig('q11', ORAL_SELECT_CONFIG.q11);
    applySelectConfig('a1', ORAL_SELECT_CONFIG.a1);
    applySelectConfig('a2', ORAL_SELECT_CONFIG.a2);
    applySelectConfig('a3', ORAL_SELECT_CONFIG.a3, { sectionLabel: true, useSectionLabelOnly: true });
    applySelectConfig('a4', ORAL_SELECT_CONFIG.a4, { sectionLabel: true, useSectionLabelOnly: true });
    applySelectConfig('rsst_judge', ORAL_SELECT_CONFIG.rsst_judge);
    applySelectConfig('bukubuku', ORAL_SELECT_CONFIG.bukubuku);
    const chewingSectionLabel = findNearestSectionLabelElement(document.getElementById('a1'));
    if (chewingSectionLabel) {
        chewingSectionLabel.textContent = '① 咬合の確認（収縮）';
    }
    ensureOralEvaluationFields();
    ensureOralDyskinesiaInlineLayout();
    ensureOralReferencePanels();
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

function splitMarkedCommentSections(value, startMarker, endMarker) {
    const text = String(value || '');
    const startIndex = text.indexOf(startMarker);
    if (startIndex < 0) {
        return {
            before: text.trim(),
            block: '',
            after: '',
            hasBlock: false,
            isLegacyBlock: false,
        };
    }

    const endIndex = text.indexOf(endMarker, startIndex + startMarker.length);
    if (endIndex < 0) {
        return {
            before: text.slice(0, startIndex).trim(),
            block: text.slice(startIndex).trim(),
            after: '',
            hasBlock: true,
            isLegacyBlock: true,
        };
    }

    const blockEnd = endIndex + endMarker.length;
    return {
        before: text.slice(0, startIndex).trim(),
        block: text.slice(startIndex, blockEnd).trim(),
        after: text.slice(blockEnd).trim(),
        hasBlock: true,
        isLegacyBlock: false,
    };
}

function buildMarkedCommentBlock(lines, startMarker, endMarker) {
    const normalizedLines = (lines || []).map((line) => String(line || '').trim()).filter(Boolean);
    if (!normalizedLines.length) {
        return '';
    }
    return [startMarker, ...normalizedLines, endMarker].join(String.fromCharCode(10));
}

function splitClinicalCommentSections(value) {
    return splitMarkedCommentSections(value, CLINICAL_COMMENT_START_MARKER, CLINICAL_COMMENT_END_MARKER);
}

function splitNutritionCommentSections(value) {
    return splitMarkedCommentSections(value, NUTRITION_COMMENT_START_MARKER, NUTRITION_COMMENT_END_MARKER);
}

function buildClinicalCommentBlock(lines) {
    return buildMarkedCommentBlock(lines, CLINICAL_COMMENT_START_MARKER, CLINICAL_COMMENT_END_MARKER);
}

function buildNutritionCommentBlock(lines) {
    return buildMarkedCommentBlock(lines, NUTRITION_COMMENT_START_MARKER, NUTRITION_COMMENT_END_MARKER);
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
    const clinicalSections = splitClinicalCommentSections(value);
    let visibleText = '';
    if (!clinicalSections.hasBlock) {
        visibleText = clinicalSections.before;
    } else if (clinicalSections.isLegacyBlock) {
        visibleText = clinicalSections.before;
    } else {
        visibleText = [clinicalSections.before, clinicalSections.after]
            .filter(Boolean)
            .join(String.fromCharCode(10) + String.fromCharCode(10));
    }

    const nutritionSections = splitNutritionCommentSections(visibleText);
    if (!nutritionSections.hasBlock) {
        return visibleText;
    }
    if (nutritionSections.isLegacyBlock) {
        return [nutritionSections.before, stripNutritionCommentMarkers(nutritionSections.block)]
            .filter(Boolean)
            .join(String.fromCharCode(10) + String.fromCharCode(10));
    }
    return [nutritionSections.before, stripNutritionCommentMarkers(nutritionSections.block), nutritionSections.after]
        .filter(Boolean)
        .join(String.fromCharCode(10) + String.fromCharCode(10));
}

function buildPrintReportData() {
    const name = getFieldElementValue('name').trim();
    const birthdate = getFieldElementValue('birthdate').trim();
    const evalDate = getFieldElementValue('evalDate');
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
        age: calculateAgeAtDate(birthdate, evalDate),
        gender: getFieldElementValue('gender'),
        evalDate,
        staff: getFieldElementValue('staff'),
        dentistHas: getFieldElementValue('dentist_has'),
        dentist: getFieldElementValue('dentist'),
        dentistDisplay: (() => {
            const hasDentist = getFieldElementValue('dentist_has').trim();
            const dentistName = getFieldElementValue('dentist').trim();
            if (hasDentist === 'なし') {
                return 'なし';
            }
            if (hasDentist === 'あり') {
                return dentistName || '歯科名未入力';
            }
            return dentistName;
        })(),
        denture: getFieldElementValue('denture'),
        weight: getFieldElementValue('weight'),
        height: getFieldElementValue('height'),
        bmi: getFieldElementValue('bmi'),
        foodStaple: getFieldElementValue('food_staple'),
        foodMain: getFieldElementValue('food_main'),
        waterTexture: getFieldElementValue('water_texture'),
        oralSummary: getFieldElementValue('oral_summary_text'),
        oralContinue: getFieldElementValue('oral_eval2'),
        oralPlan: getFieldElementValue('oral_eval3'),
        mnaScore: getFieldElementValue('mna_summary_num'),
        mnaResult: getFieldElementValue('mna_summary_result'),
        comment: getPrintFriendlyComment(getFieldElementValue('summary_comment')),
        nextMonitor: formatYearMonthDisplay(getFieldElementValue('next_monitor')),
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
        buildPrintItem('年齢', report.age === null || report.age === undefined ? '' : `${report.age}歳`),
        buildPrintItem('担当者', report.staff),
        buildPrintItem('体重 (kg)', report.weight),
        buildPrintItem('身長 (cm)', report.height),
        buildPrintItem('BMI', report.bmi),
        buildPrintItem('義歯', report.denture),
        buildPrintItem('かかりつけ歯科', report.dentistDisplay, true),
        buildPrintItem('主食', report.foodStaple),
        buildPrintItem('主菜', report.foodMain),
        buildPrintItem('水分形態', report.waterTexture, true),
        buildPrintItem('次回モニタリング', report.nextMonitor, true),
    ].join('');

    const oralLines = buildPrintMetricLines(report.oralSummary ? [report.oralSummary] : [report.oralContinue, report.oralPlan]);
    const mnaLines = '<div class="print-sheet__metric-score">' + escapeHtml(formatDisplayValue(report.mnaScore)) + '</div>'
        + '<div class="print-sheet__metric-line">' + escapeHtml(formatDisplayValue(report.mnaResult)) + '</div>';
    const clinicalPrintLines = buildPrintMetricLines(report.clinicalPrintLines || []);

    return '<div class="print-sheet__page">'
        + '<div class="print-sheet__header">'
        + '<div><div class="print-sheet__title">口腔機能・栄養評価記録</div><div class="print-sheet__subtitle">印刷対象は現在表示中の 1 名分のみです</div></div>'
        + '<div class="print-sheet__meta">' + escapeHtml(formatDisplayValue(headerMeta)) + '</div>'
        + '</div>'
        + '<div class="print-sheet__section print-sheet__section--comment">'
        + '<div class="print-sheet__section-title">利用者情報</div>'
        + '<div class="print-sheet__value" style="font-size:16px;color:var(--primary);margin-bottom:6px;">' + escapeHtml(formatDisplayValue(report.name)) + '</div>'
        + '<div class="print-sheet__info-grid">' + infoGrid + '</div>'
        + '</div>'
        + '<div class="print-sheet__metrics">'
        + '<div class="print-sheet__metric-card"><div class="print-sheet__metric-title">口腔機能評価</div>' + (oralLines || '<div class="print-sheet__metric-line">未入力</div>') + '</div>'
        + '<div class="print-sheet__metric-card"><div class="print-sheet__metric-title">MNA-SF</div>' + mnaLines + '</div>'
        + '<div class="print-sheet__metric-card print-sheet__metric-card--wide"><div class="print-sheet__metric-title">差分アシスト</div>' + (clinicalPrintLines || '<div class="print-sheet__metric-line">差分アラートはまだありません。</div>') + '</div>'
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
        .summary-identity-name,
        .summary-identity-date,
        .summary-identity-subline,
        #mna_summary_result,
        .metric-chip,
        .stage2-panel__meta,
        .monitor-status,
        .history-table__nowrap,
        .history-cell--nowrap,
        .history-table th {
            white-space: nowrap;
            word-break: keep-all;
            overflow-wrap: normal;
        }
        .summary-identity-name {
            margin-bottom: 2px !important;
        }
        .summary-identity-subline {
            margin-bottom: 10px;
            font-size: 13px;
            color: var(--text-light);
        }
        .summary-identity-date {
            margin-bottom: 16px !important;
        }
        .history-table--enhanced {
            min-width: 720px;
        }
        .history-table--enhanced th,
        .history-table--enhanced td {
            vertical-align: top;
        }
        .history-table--enhanced .tag,
        .history-table--enhanced .btn,
        .history-table--enhanced .metric-subline {
            white-space: nowrap;
        }
        .history-toolbar {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin: 0 0 14px;
        }
        .history-toolbar__search {
            display: flex;
            align-items: center;
            gap: 8px;
            flex: 1 1 320px;
            min-width: 220px;
        }
        .history-toolbar__field {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: nowrap;
        }
        .history-toolbar__label,
        .history-stats,
        .history-section-hint {
            font-size: 12px;
            color: var(--text-light);
        }
        .history-toolbar__label {
            flex: 0 0 auto;
            white-space: nowrap;
        }
        .history-toolbar__input {
            width: 100%;
            min-width: 0;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: #fff;
            font: inherit;
        }
        .history-toolbar__select {
            flex: 1 1 auto;
            min-width: 170px;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: #fff;
            color: var(--text);
            font: inherit;
        }
        .history-panel {
            margin: 0 0 14px;
            padding: 14px;
            border: 1px solid var(--border);
            border-radius: 16px;
            background: linear-gradient(180deg, #f8fbfe 0%, #ffffff 100%);
        }
        .history-panel__summary-bar {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 10px;
            margin-top: 10px;
        }
        .history-panel__controls {
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 8px 10px;
        }
        .history-panel__header,
        .history-section-header {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-end;
            justify-content: space-between;
            gap: 10px;
        }
        .history-section-header {
            margin: 0 0 10px;
        }
        .history-panel__title,
        .history-section-title {
            font-size: 16px;
            font-weight: 700;
            color: var(--text);
        }
        .history-card-list {
            display: grid;
            gap: 12px;
            margin-top: 12px;
        }
        .history-card {
            padding: 14px;
            border: 1px solid var(--border);
            border-radius: 14px;
            background: #fff;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
        }
        .history-card__header {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
        }
        .history-card__lead {
            min-width: 0;
            flex: 1 1 260px;
        }
        .history-card__title-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 8px 10px;
        }
        .history-card__title {
            font-size: 16px;
            font-weight: 700;
            color: var(--text);
        }
        .history-card__subline {
            margin-top: 4px;
            font-size: 12px;
            color: var(--text-light);
            word-break: break-word;
        }
        .history-card__date-block {
            min-width: 140px;
            padding: 10px 12px;
            border: 1px solid #d9e8f4;
            border-radius: 12px;
            background: #f7fbff;
        }
        .history-card__date-label {
            font-size: 11px;
            color: var(--text-light);
        }
        .history-card__date {
            margin-top: 4px;
            font-size: 15px;
            font-weight: 700;
            color: var(--primary);
        }
        .history-card__date-pill {
            display: inline-flex;
            align-items: center;
            padding: 6px 10px;
            border-radius: 999px;
            background: #eef4fa;
            color: var(--primary);
            font-size: 12px;
            font-weight: 700;
        }
        .history-card__grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 10px;
            margin-top: 12px;
        }
        .history-card__grid--compact {
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        }
        .history-field {
            min-width: 0;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: var(--section-bg);
        }
        .history-field__label {
            font-size: 11px;
            font-weight: 700;
            color: var(--text-light);
        }
        .history-field__value {
            margin-top: 6px;
            font-size: 13px;
            line-height: 1.6;
            color: var(--text);
            white-space: normal;
            word-break: break-word;
        }
        .history-field__value strong {
            font-size: 16px;
            color: var(--text);
        }
        .history-field__note {
            margin-top: 4px;
            font-size: 12px;
            color: var(--text-light);
        }
        .history-tag-block {
            display: grid;
            justify-items: start;
            gap: 4px;
        }
        .history-card__footer {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-top: 12px;
        }
        .history-card__chips,
        .history-card__actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .history-card__actions .btn {
            white-space: nowrap;
        }
        .history-table--records {
            min-width: 0;
            border-collapse: separate;
        }
        .history-table--records thead {
            display: none;
        }
        .history-table--records tbody {
            display: block;
        }
        .history-table--records tr,
        .history-table--records td {
            display: block;
            width: 100%;
        }
        .history-table--records tr + tr {
            margin-top: 12px;
        }
        .history-table--records td {
            padding: 0;
            border: 0;
            background: transparent;
        }
        .history-table--records tr:hover td {
            background: transparent;
        }
        .history-records-wrapper {
            overflow: visible;
        }
        .odk-inline-grid {
            display: grid !important;
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 10px;
            align-items: end;
        }
        .odk-inline-grid__item {
            min-width: 0;
        }
        .odk-timer-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
        }
        .odk-timer-card {
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 10px;
            background: #fff;
            display: flex;
            flex-direction: column;
            gap: 8px;
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
        .nutrition-cause-grid {
            display: grid;
            gap: 12px;
            margin-top: 12px;
        }
        .nutrition-cause-card {
            background: #fff;
        }
        .nutrition-cause-card__header {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }
        .nutrition-cause-card__title {
            font-weight: 700;
            color: var(--text);
        }
        .nutrition-cause-card__mode {
            display: inline-flex;
        }
        .nutrition-cause-card__subhead {
            margin-top: 10px;
            font-size: 12px;
            font-weight: 700;
            color: var(--text-light);
        }
        .nutrition-action-grid {
            display: grid;
            gap: 10px;
            margin-top: 12px;
        }
        .nutrition-action-group {
            padding: 10px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: var(--section-bg);
        }
        .nutrition-action-group__title {
            font-size: 12px;
            font-weight: 700;
            color: var(--text-light);
            margin-bottom: 8px;
        }
        .nutrition-action-subgrid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
        }
        .nutrition-action-subgroup {
            padding: 10px;
            border: 1px solid #d9e8f4;
            border-radius: 10px;
            background: #fff;
        }
        .nutrition-action-subtitle {
            margin-bottom: 8px;
            font-size: 12px;
            font-weight: 700;
            color: #2f5675;
        }
        .nutrition-action-list {
            display: grid;
            gap: 8px;
        }
        .nutrition-action-item {
            display: grid;
            grid-template-columns: 18px minmax(0, 1fr);
            gap: 8px;
            align-items: start;
            font-size: 13px;
            line-height: 1.6;
            color: var(--text);
        }
        .nutrition-action-item input {
            margin-top: 3px;
        }
        .nutrition-empty {
            color: var(--text-light);
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
        .oral-reference-panel {
            margin: 10px 0 14px;
            padding: 12px;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: #fff;
        }
        .oral-reference-panel__header {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 8px;
        }
        .oral-reference-panel__hint {
            font-size: 12px;
            color: var(--text-light);
        }
        .oral-reference-panel__image {
            display: block;
            width: 100%;
            max-width: 820px;
            margin: 0 auto;
            border: 1px solid #e5eaf1;
            border-radius: 10px;
            background: #fff;
        }
        .oral-reference-panel__fallback {
            padding: 18px 16px;
            border: 1px dashed var(--border);
            border-radius: 10px;
            background: var(--section-bg);
            color: var(--text-light);
            font-size: 13px;
            text-align: center;
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
            .settings-panel__editor .btn,
            .history-card__actions .btn {
                flex: 1 1 140px;
                justify-content: center;
            }
            .settings-grid {
                grid-template-columns: 1fr;
            }
            .history-toolbar__search,
            .history-toolbar__field,
            .history-card__lead,
            .history-card__date-block,
            .history-card__chips,
            .history-card__actions,
            .history-panel__controls {
                width: 100%;
            }
            .history-toolbar__select {
                min-width: 0;
                width: auto;
            }
            .history-card__grid {
                grid-template-columns: 1fr;
            }
            .odk-inline-grid,
            .odk-timer-grid {
                grid-template-columns: 1fr !important;
            }
            .oral-reference-panel {
                padding: 10px;
            }
            .rsst-tap-btn {
                font-size: 18px;
            }
            .nutrition-preview-panel {
                top: 8px;
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

function syncDentistPresenceField(options = {}) {
    const presenceField = document.getElementById('dentist_has');
    const dentistField = document.getElementById('dentist');
    const selectField = document.getElementById('dentist_select');
    const customField = document.getElementById('dentist_custom');
    const dentistGroup = document.getElementById('dentist_name_group');
    if (!presenceField || !dentistField || !dentistGroup) {
        return;
    }

    const hasStoredDentist = Boolean(String(dentistField.value || '').trim());
    if (!presenceField.value && hasStoredDentist) {
        presenceField.value = 'あり';
    }

    const isVisible = presenceField.value === 'あり';
    dentistGroup.style.display = isVisible ? 'block' : 'none';
    dentistGroup.setAttribute('aria-hidden', isVisible ? 'false' : 'true');

    if (!isVisible && (presenceField.value === 'なし' || !options.preserveValue)) {
        dentistField.value = '';
        if (selectField) {
            selectField.value = '';
        }
        if (customField) {
            customField.value = '';
            customField.style.display = 'none';
        }
    }

    if (isVisible && typeof renderDentistSelect === 'function') {
        renderDentistSelect();
    }
}

function bindDentistPresenceField() {
    const presenceField = document.getElementById('dentist_has');
    if (!presenceField || presenceField.dataset.boundDentistPresence === '1') {
        return;
    }

    presenceField.addEventListener('change', () => {
        syncDentistPresenceField();
        scheduleAutosave();
    });
    presenceField.dataset.boundDentistPresence = '1';
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

    if (config.fieldId === 'dentist') {
        const presenceField = document.getElementById('dentist_has');
        if (presenceField && storedValue && presenceField.value !== 'あり') {
            presenceField.value = 'あり';
        }
        syncDentistPresenceField({ preserveValue: true });
    }

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
    syncDentistPresenceField({ preserveValue: true });
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
        note.textContent = '共有記録・担当者一覧・かかりつけ歯科一覧はサーバーへ、下書きはこの端末へ保存されます。';
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
            '下書き（この端末）と担当者一覧・かかりつけ歯科一覧（共有）を置換しますか？',
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
        foodStaple: getFieldElementValue('food_staple').trim(),
        foodMain: getFieldElementValue('food_main').trim(),
        waterTexture: getFieldElementValue('water_texture').trim(),
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
            <table class="history-table history-table--enhanced trend-table">
                <thead>
                    <tr>
                        <th class="history-table__nowrap">評価日</th>
                        <th class="history-table__nowrap">体重</th>
                        <th class="history-table__nowrap">BMI</th>
                        <th class="history-table__nowrap">体重差</th>
                        <th class="history-table__nowrap">BMI差</th>
                        <th class="history-table__nowrap">栄養判定</th>
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
                <div class="stage2-panel__title">差分アシスト</div>
                <div class="stage2-panel__hint">前回保存との差分から要確認点を自動で整理し、コメント欄へ反映します。</div>
            </div>
            <div id="clinicalSupportMeta" class="stage2-panel__meta"></div>
        </div>
        <div id="clinicalSupportSummary" class="stage2-panel__summary">利用者情報と口腔項目を入力すると差分アラートを表示します。</div>
        <section class="stage3-box stage3-box--wide" style="margin-top:12px;">
            <div class="section-label">差分アラート</div>
            <div id="clinicalAlertList"></div>
        </section>
    `;

    if (trendPanel) {
        trendPanel.insertAdjacentElement('afterend', panel);
        return;
    }
    divider.insertAdjacentElement('beforebegin', panel);
}

function ensureNutritionAssessmentPanel() {
    const summaryCard = document.querySelector('#tab-summary > .card');
    const divider = summaryCard ? summaryCard.querySelector('.divider') : null;
    const clinicalPanel = document.getElementById('clinicalSupportPanel');
    const trendPanel = document.getElementById('patientTrendPanel');
    if (!summaryCard || !divider || document.getElementById('nutritionAssessmentPanel')) {
        return;
    }

    const panel = document.createElement('div');
    panel.id = 'nutritionAssessmentPanel';
    panel.className = 'stage2-panel stage3-panel';
    panel.innerHTML = `
        <div class="stage2-panel__header">
            <div>
                <div class="stage2-panel__title">栄養アセスメント・提案</div>
                <div class="stage2-panel__hint">BMI・MNA-SF・口腔機能をもとに自動評価し、原因候補と対応方針をコメント欄へ反映します。</div>
            </div>
        </div>
        <input type="hidden" id="${NUTRITION_SELECTION_FIELD_ID}" value="{}">
        <div id="nutritionAssessmentChips" class="metric-chip-list"></div>
        <div id="nutritionAssessmentSummary" class="stage2-panel__summary">BMI・MNA-SF・口腔機能を入力すると自動評価を表示します。</div>
        <div id="nutritionAssessmentCards" class="nutrition-cause-grid"></div>
    `;

    if (panel.dataset.boundNutritionPanel !== '1') {
        panel.addEventListener('change', (event) => {
            const target = event.target;
            if (!target || target.type !== 'checkbox') {
                return;
            }
            const actionKey = String(target.getAttribute('data-nutrition-key') || '').trim();
            if (!actionKey) {
                return;
            }
            const nextState = getNutritionSelectionState();
            nextState[actionKey] = Boolean(target.checked);
            setNutritionSelectionState(nextState, { fromUser: true });
            renderNutritionAssessmentPanel();
        });
        panel.dataset.boundNutritionPanel = '1';
    }

    if (clinicalPanel) {
        clinicalPanel.insertAdjacentElement('beforebegin', panel);
        return;
    }
    if (trendPanel) {
        trendPanel.insertAdjacentElement('afterend', panel);
        return;
    }
    divider.insertAdjacentElement('beforebegin', panel);
}

function ensureStage3Panels() {
    ensureClinicalSupportPanel();
    ensureNutritionAssessmentPanel();
}

function getNutritionSelectionState() {
    const field = document.getElementById(NUTRITION_SELECTION_FIELD_ID);
    if (!field) {
        return {};
    }
    try {
        const parsed = JSON.parse(String(field.value || '{}'));
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
}

function setNutritionSelectionState(state, options = {}) {
    const field = document.getElementById(NUTRITION_SELECTION_FIELD_ID);
    if (!field) {
        return;
    }
    const normalized = {};
    Object.entries(state || {}).forEach(([key, value]) => {
        const normalizedKey = String(key || '').trim();
        if (!normalizedKey) {
            return;
        }
        normalized[normalizedKey] = value !== false;
    });
    const nextValue = JSON.stringify(normalized);
    if (field.value === nextValue) {
        return;
    }
    field.value = nextValue;
    if (options.fromUser) {
        scheduleAutosave();
    }
}

function getMnaScoreValue(key) {
    const rawValue = mnaScores && Object.prototype.hasOwnProperty.call(mnaScores, key) ? mnaScores[key] : null;
    if (rawValue === null || rawValue === undefined || rawValue === '') {
        return null;
    }
    const numeric = Number(rawValue);
    return Number.isFinite(numeric) ? numeric : null;
}

function buildNutritionActionKey(modeId, causeId, role, index) {
    return [modeId, causeId, role, index].join('::');
}

function dedupeTextItems(items) {
    return [...new Set((items || []).map((item) => String(item || '').trim()).filter(Boolean))];
}

function buildNutritionCause(modeId, causeId, reasons) {
    const modeConfig = NUTRITION_GUIDANCE_LIBRARY[modeId];
    const causeConfig = modeConfig && modeConfig.causes ? modeConfig.causes[causeId] : null;
    const normalizedReasons = dedupeTextItems(reasons);
    if (!causeConfig || !normalizedReasons.length) {
        return null;
    }
    return {
        modeId,
        causeId,
        icon: causeConfig.icon,
        label: causeConfig.label,
        reasons: normalizedReasons,
        patientFamily: causeConfig.patientFamily || [],
        rehabSt: causeConfig.st || [],
        rehabPt: causeConfig.pt || [],
        rehabOt: causeConfig.ot || [],
        ns: causeConfig.ns || [],
        modeLabel: modeConfig.label,
        modeTone: modeConfig.chipTone,
    };
}

function getNutritionActionItems(cause, role) {
    return cause && Array.isArray(cause[role]) ? cause[role] : [];
}

function countNutritionCauseActions(cause) {
    return NUTRITION_ACTION_ROLE_KEYS.reduce((sum, role) => sum + getNutritionActionItems(cause, role).length, 0);
}

function countSelectedNutritionCauseActions(cause, selectionState) {
    return NUTRITION_ACTION_ROLE_KEYS.reduce((sum, role) => {
        return sum + getNutritionActionItems(cause, role).reduce((roleSum, item, index) => {
            const actionKey = buildNutritionActionKey(cause.modeId, cause.causeId, role, index);
            return roleSum + (selectionState[actionKey] !== false ? 1 : 0);
        }, 0);
    }, 0);
}

function buildNutritionActionListHtml(cause, role, selectionState) {
    const items = getNutritionActionItems(cause, role);
    if (!items.length) {
        return '<div class="stage3-note">該当する提案はありません。</div>';
    }
    return items.map((item, index) => {
        const actionKey = buildNutritionActionKey(cause.modeId, cause.causeId, role, index);
        const checked = selectionState[actionKey] !== false ? 'checked' : '';
        return `
            <label class="nutrition-action-item">
                <input type="checkbox" data-nutrition-key="${escapeHtml(actionKey)}" ${checked}>
                <span>${escapeHtml(item)}</span>
            </label>
        `;
    }).join('');
}

function buildNutritionAssessmentData() {
    const patientState = getCurrentPatientFormState();
    const oralState = getCurrentOralAssessmentState();
    const age = calculateAgeAtDate(patientState.birthdate, patientState.evalDate);
    const bmiReference = getBmiReference(age);
    const mnaState = getCurrentMnaSummaryState();
    const history = patientState.patientKey ? (buildPatientRecordGroups(records).get(patientState.patientKey) || []) : [];
    const comparisonRecord = getComparisonHistoryRecord(history, patientState.evalDate);
    const previousWeight = comparisonRecord ? toMetricNumber(comparisonRecord.weight ?? comparisonRecord.fields?.weight) : null;
    const previousBmi = comparisonRecord ? toMetricNumber(comparisonRecord.bmi ?? comparisonRecord.fields?.bmi) : null;
    const lowOdkLabels = getLowOdkLabels(oralState);
    const mnaA = getMnaScoreValue('a');
    const mnaB = getMnaScoreValue('b');
    const mnaC = getMnaScoreValue('c');
    const mnaD = getMnaScoreValue('d');
    const mnaE = getMnaScoreValue('e');
    const modes = [];
    const causes = [];

    const underReasons = [];
    if (mnaState.score !== null && mnaState.score <= 7) {
        underReasons.push(`MNA-SF ${mnaState.score}点で低栄養が疑われます`);
    } else if (mnaState.score !== null && mnaState.score <= 11) {
        underReasons.push(`MNA-SF ${mnaState.score}点で低栄養リスクがあります`);
    }
    if (patientState.bmi !== null && bmiReference && patientState.bmi < bmiReference.low) {
        underReasons.push(`BMI ${patientState.bmi.toFixed(1)} が ${bmiReference.label} ${bmiReference.low.toFixed(1)} 未満です`);
    }
    if (hasMeaningfulDrop(patientState.weight, previousWeight, 1.0)) {
        underReasons.push(`体重が前回 ${previousWeight.toFixed(1)}kg から ${patientState.weight.toFixed(1)}kg に低下しています`);
    }

    if (underReasons.length) {
        const weightReasons = [];
        if (patientState.bmi !== null && bmiReference && patientState.bmi < bmiReference.low) {
            weightReasons.push(`BMI ${patientState.bmi.toFixed(1)} が基準を下回っています`);
        }
        if (hasMeaningfulDrop(patientState.weight, previousWeight, 1.0)) {
            weightReasons.push(`体重が前回より ${(previousWeight - patientState.weight).toFixed(1)}kg 低下しています`);
        }
        if (hasMeaningfulDrop(patientState.bmi, previousBmi, 0.5)) {
            weightReasons.push(`BMI が前回より ${(previousBmi - patientState.bmi).toFixed(1)} 低下しています`);
        }
        if (mnaB !== null && mnaB <= 2) {
            weightReasons.push('MNA-SF の体重減少項目が低下側です');
        }
        if (mnaState.score !== null && mnaState.score <= 11) {
            weightReasons.push(`MNA-SF ${mnaState.score}点です`);
        }

        const dysphagiaReasons = [];
        if (oralState.q2Code === 2) {
            dysphagiaReasons.push('水分でのむせがあります');
        }
        if (oralState.q9Code !== null && oralState.q9Code >= 2) {
            dysphagiaReasons.push('食事中や食後のむせが入力されています');
        }
        if (oralState.rsstCount !== null && oralState.rsstCount <= 3) {
            dysphagiaReasons.push(`RSST ${oralState.rsstCount.toFixed(0)}回/30秒で境界域以下です`);
        }
        if (oralState.rsstJudgeCode === 2) {
            dysphagiaReasons.push('RSST の専門職判断が問題ありです');
        }
        if (patientState.waterTexture && patientState.waterTexture !== 'とろみなし') {
            dysphagiaReasons.push(`現在の水分形態は ${patientState.waterTexture} です`);
        }

        const anorexiaReasons = [];
        if (mnaA !== null && mnaA <= 1) {
            anorexiaReasons.push('MNA-SF の食欲・食事量項目が低下側です');
        }
        if (mnaD === 0) {
            anorexiaReasons.push('最近の急性疾患・ストレス要因が示唆されます');
        }
        if (oralState.q5Code !== null && oralState.q5Code >= 4) {
            anorexiaReasons.push('全身状態の自己評価が低下側です');
        }

        const oralReasons = [];
        if (oralState.q3Code === 2) {
            oralReasons.push('口腔乾燥があります');
        }
        if (oralState.q8Code !== null && oralState.q8Code <= 2) {
            oralReasons.push('口腔清掃習慣が十分ではありません');
        }
        if (oralState.q4Code !== null && oralState.q4Code >= 2) {
            oralReasons.push('咬合支持の低下がみられます');
        }
        if (oralState.q10Code !== null && oralState.q10Code >= 2) {
            oralReasons.push('食べこぼしがみられます');
        }
        if ((oralState.bukubukuCode !== null && oralState.bukubukuCode >= 2)
            || (oralState.guguguCode !== null && oralState.guguguCode >= 2)) {
            oralReasons.push('含嗽機能の低下がみられます');
        }
        if (lowOdkLabels.length) {
            oralReasons.push(`${lowOdkLabels.join('、')} で口唇・舌機能低下がみられます`);
        }

        const cognitiveReasons = [];
        if (mnaE !== null && mnaE <= 1) {
            cognitiveReasons.push('MNA-SF の神経心理項目が低下側です');
        }
        if (oralState.q11Code !== null && oralState.q11Code >= 4) {
            cognitiveReasons.push('表情変化が少なく注意低下が疑われます');
        }

        const underCauses = [
            buildNutritionCause('under', 'weight', weightReasons.length ? weightReasons : underReasons),
            buildNutritionCause('under', 'dysphagia', dysphagiaReasons),
            buildNutritionCause('under', 'anorexia', anorexiaReasons),
            buildNutritionCause('under', 'oral', oralReasons),
            buildNutritionCause('under', 'cognitive', cognitiveReasons),
        ].filter(Boolean);

        const underModeLabel = mnaState.score !== null && mnaState.score <= 7 ? '低栄養' : '低栄養リスク';
        modes.push({ id: 'under', label: underModeLabel, tone: 'alert', reasons: dedupeTextItems(underReasons), causes: underCauses });
        causes.push(...underCauses);
    }

    const overReasons = [];
    if (patientState.bmi !== null && bmiReference && patientState.bmi > bmiReference.high) {
        overReasons.push(`BMI ${patientState.bmi.toFixed(1)} が ${bmiReference.label} ${bmiReference.high.toFixed(1)} を上回っています`);
    }
    if (hasMeaningfulRise(patientState.weight, previousWeight, 1.0)) {
        overReasons.push(`体重が前回 ${previousWeight.toFixed(1)}kg から ${patientState.weight.toFixed(1)}kg に増加しています`);
    }

    if (overReasons.length) {
        const overeatingReasons = [];
        if (patientState.bmi !== null && bmiReference && patientState.bmi > bmiReference.high) {
            overeatingReasons.push(`BMI ${patientState.bmi.toFixed(1)} が基準を上回っています`);
        }
        if (hasMeaningfulRise(patientState.weight, previousWeight, 1.0)) {
            overeatingReasons.push(`体重が前回より ${formatSignedDelta(patientState.weight, previousWeight, 'kg')} 増加しています`);
        }
        if (hasMeaningfulRise(patientState.bmi, previousBmi, 0.5)) {
            overeatingReasons.push(`BMI が前回より ${formatSignedDelta(patientState.bmi, previousBmi, '')} 増加しています`);
        }

        const imbalanceReasons = [];
        if (patientState.bmi !== null && patientState.bmi >= 25) {
            imbalanceReasons.push('BMI 25 以上で、量だけでなく内容の見直しが必要です');
        }
        if (patientState.foodStaple || patientState.foodMain) {
            imbalanceReasons.push(`現在の食形態は ${[patientState.foodStaple, patientState.foodMain].filter(Boolean).join(' / ')} です`);
        }
        if (mnaState.score !== null && mnaState.score >= 12 && patientState.bmi !== null && bmiReference && patientState.bmi > bmiReference.high) {
            imbalanceReasons.push('MNA-SF は保たれていますが BMI 高値です');
        }

        const activityReasons = [];
        if (mnaC !== null && mnaC <= 1) {
            activityReasons.push('MNA-SF の移動能力項目が低下側です');
        }
        if (oralState.q11Code !== null && oralState.q11Code >= 4) {
            activityReasons.push('活動性や表情の低下がみられます');
        }
        if (mnaD === 0) {
            activityReasons.push('最近の急性疾患・ストレスで活動量低下が疑われます');
        }

        const hygieneReasons = [];
        if (oralState.q7Code !== null && oralState.q7Code >= 2) {
            hygieneReasons.push('口臭があります');
        }
        if (oralState.q8Code !== null && oralState.q8Code <= 2) {
            hygieneReasons.push('口腔清掃習慣が十分ではありません');
        }
        if (oralState.q3Code === 2) {
            hygieneReasons.push('口腔乾燥があります');
        }

        const overCauses = [
            buildNutritionCause('over', 'overeating', overeatingReasons.length ? overeatingReasons : overReasons),
            buildNutritionCause('over', 'imbalance', imbalanceReasons.length ? imbalanceReasons : overReasons),
            buildNutritionCause('over', 'activity', activityReasons),
            buildNutritionCause('over', 'oral_hygiene', hygieneReasons),
        ].filter(Boolean);

        modes.push({ id: 'over', label: '過栄養', tone: 'info', reasons: dedupeTextItems(overReasons), causes: overCauses });
        causes.push(...overCauses);
    }

    const chips = [];
    if (patientState.bmi !== null) {
        chips.push(buildMetricChipHtml('BMI', patientState.bmi.toFixed(1), classifyBmiReference(patientState.bmi, bmiReference)));
    }
    if (mnaState.score !== null) {
        chips.push(buildMetricChipHtml('MNA-SF', `${mnaState.score}点`, classifyMnaSummaryTone(mnaState.score)));
    }
    modes.forEach((mode) => {
        chips.push(buildMetricChipHtml('自動評価', mode.label, mode.tone));
    });
    if (causes.length) {
        chips.push(buildMetricChipHtml('原因候補', `${causes.length}件`, causes.length >= 3 ? 'alert' : 'info'));
    }

    const summaryText = !modes.length
        ? 'BMI・MNA-SF・口腔機能の入力から、低栄養・過栄養の原因候補と提案を自動表示します。'
        : `自動評価: ${modes.map((mode) => mode.label).join(' / ')}。気になる領域: ${dedupeTextItems(causes.map((cause) => cause.label)).join('、')}。`;

    return {
        modes,
        causes,
        chips,
        summaryText,
    };
}

function buildNutritionCommentDraft(data, selectionState) {
    if (!data || !data.causes || !data.causes.length) {
        return '';
    }

    const modeLabels = dedupeTextItems((data.modes || []).map((mode) => mode.label));
    const causeLabels = dedupeTextItems((data.causes || []).map((cause) => cause.label));
    const reasonLines = dedupeTextItems((data.causes || []).flatMap((cause) => cause.reasons || []));
    const selectedByRole = { patientFamily: [], rehabSt: [], rehabPt: [], rehabOt: [], ns: [] };

    (data.causes || []).forEach((cause) => {
        NUTRITION_ACTION_ROLE_KEYS.forEach((role) => {
            getNutritionActionItems(cause, role).forEach((item, index) => {
                const actionKey = buildNutritionActionKey(cause.modeId, cause.causeId, role, index);
                if (selectionState[actionKey] !== false) {
                    selectedByRole[role].push(item);
                }
            });
        });
    });

    const lines = [];
    lines.push(`自動評価: ${modeLabels.join(' / ')}。気になる領域: ${causeLabels.join('、')}。`);
    if (reasonLines.length) {
        lines.push(`抽出根拠: ${joinCommentItems(reasonLines, 4)}`);
    }
    NUTRITION_ACTION_ROLE_KEYS.forEach((role) => {
        const items = dedupeTextItems(selectedByRole[role]).slice(0, 4);
        if (!items.length) {
            return;
        }
        lines.push(`${NUTRITION_ACTION_ROLE_LABELS[role]}: ${items.join('、')}。`);
    });
    return buildNutritionCommentBlock(lines);
}

function syncNutritionCommentDraft(data, selectionState) {
    const commentField = document.getElementById('summary_comment');
    if (!commentField) {
        return;
    }

    const draft = normalizeCommentBlock(buildNutritionCommentDraft(data, selectionState));
    const currentValue = String(commentField.value || '').trim();
    const sections = splitNutritionCommentSections(currentValue);
    const paragraphGap = String.fromCharCode(10) + String.fromCharCode(10);
    let nextValue = currentValue;

    if (!draft) {
        if (!sections.hasBlock) {
            return;
        }
        nextValue = [sections.before, sections.after].filter(Boolean).join(paragraphGap);
    } else {
        nextValue = [sections.before, draft, sections.after].filter(Boolean).join(paragraphGap);
    }

    if (nextValue === currentValue) {
        return;
    }

    commentField.value = nextValue;
    commentField.dispatchEvent(new Event('input', { bubbles: true }));
    commentField.dispatchEvent(new Event('change', { bubbles: true }));
}

function renderNutritionAssessmentPanel() {
    ensureNutritionAssessmentPanel();

    const chips = document.getElementById('nutritionAssessmentChips');
    const summary = document.getElementById('nutritionAssessmentSummary');
    const cards = document.getElementById('nutritionAssessmentCards');
    if (!chips || !summary || !cards) {
        return;
    }

    const data = buildNutritionAssessmentData();
    const selectionState = getNutritionSelectionState();

    chips.innerHTML = data.chips.join('');
    summary.textContent = data.summaryText;

    if (!data.causes.length) {
        cards.innerHTML = '<section class="stage3-box nutrition-empty">低栄養・過栄養の評価条件を満たすと、ここに原因候補と対応方針を表示します。</section>';
        latestNutritionAssessmentData = data;
        syncNutritionCommentDraft(data, selectionState);
        return;
    }

    cards.innerHTML = data.causes.map((cause) => {
        const roleHtml = `
            <div class="nutrition-action-group">
                <div class="nutrition-action-group__title">${escapeHtml(NUTRITION_ACTION_ROLE_LABELS.patientFamily)}</div>
                <div class="nutrition-action-list">${buildNutritionActionListHtml(cause, 'patientFamily', selectionState)}</div>
            </div>
            <div class="nutrition-action-group">
                <div class="nutrition-action-group__title">${escapeHtml(NUTRITION_ACTION_ROLE_LABELS.rehab)}</div>
                <div class="nutrition-action-subgrid">
                    ${NUTRITION_REHAB_ROLE_CONFIGS.map((roleConfig) => `
                        <div class="nutrition-action-subgroup">
                            <div class="nutrition-action-subtitle">${escapeHtml(roleConfig.shortLabel)}</div>
                            <div class="nutrition-action-list">${buildNutritionActionListHtml(cause, roleConfig.key, selectionState)}</div>
                        </div>
                    `).join('')}
                </div>
            </div>
            <div class="nutrition-action-group">
                <div class="nutrition-action-group__title">${escapeHtml(NUTRITION_ACTION_ROLE_LABELS.ns)}</div>
                <div class="nutrition-action-list">${buildNutritionActionListHtml(cause, 'ns', selectionState)}</div>
            </div>
        `;

        return `
            <section class="stage3-box nutrition-cause-card">
                <div class="nutrition-cause-card__header">
                    <div class="nutrition-cause-card__title">${escapeHtml(`${cause.icon} ${cause.label}`)}</div>
                    <div class="nutrition-cause-card__mode">${buildMetricChipHtml('評価', cause.modeLabel, cause.modeTone)}</div>
                </div>
                <div class="nutrition-cause-card__subhead">抽出根拠</div>
                ${buildStage3ListHtml(cause.reasons, '現入力では根拠を抽出できませんでした')}
                <div class="nutrition-action-grid">${roleHtml}</div>
            </section>
        `;
    }).join('');

    const draft = buildNutritionCommentDraft(data, selectionState);
    const totalSelectableCount = data.causes.reduce((sum, cause) => sum + countNutritionCauseActions(cause), 0);
    const selectedCount = data.causes.reduce((sum, cause) => sum + countSelectedNutritionCauseActions(cause, selectionState), 0);
    if (totalSelectableCount > 0) {
        summary.textContent = `${data.summaryText} ${selectedCount} / ${totalSelectableCount} 件を総合評価コメントへ自動反映しています。`;
    }
    latestNutritionAssessmentData = { ...data, commentDraft: draft };
    syncNutritionCommentDraft(data, selectionState);
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

function stripMarkedCommentMarkers(value, startMarker, endMarker) {
    return normalizeCommentBlock(
        String(value || '')
            .replace(startMarker, '')
            .replace(endMarker, '')
    );
}

function stripClinicalCommentMarkers(value) {
    return stripMarkedCommentMarkers(value, CLINICAL_COMMENT_START_MARKER, CLINICAL_COMMENT_END_MARKER);
}

function stripNutritionCommentMarkers(value) {
    return stripMarkedCommentMarkers(value, NUTRITION_COMMENT_START_MARKER, NUTRITION_COMMENT_END_MARKER);
}

function buildClinicalCommentDraft(data) {
    if (!data) {
        return '';
    }

    const alertItems = dedupeTextItems(data.alertItems || []);
    if (!alertItems.length) {
        return '';
    }

    return buildClinicalCommentBlock([
        `差分アラート: ${joinCommentItems(alertItems, 3)}`,
    ]);
}

function buildClinicalPrintLines(data) {
    if (!data) {
        return ['差分アラート: 比較に必要な入力が不足しています。'];
    }

    const alertItems = dedupeTextItems(data.alertItems || []);
    if (!alertItems.length) {
        return ['差分アラート: 前回比較の準備が整うとここに表示します。'];
    }

    return [`差分アラート: ${joinCommentItems(alertItems, 3)}`];
}

function buildClinicalAlertSummary(alertItems) {
    const items = dedupeTextItems(alertItems || []);
    if (!items.length) {
        return '前回比較の準備が整うと差分アラートを表示します。';
    }
    if (items.length === 1) {
        return ensureSentenceText(stripTerminalPunctuation(items[0]));
    }
    return `前回保存との差分から ${items.length} 件の要確認を抽出しました。`;
}

function syncClinicalCommentDraft(data) {
    const commentField = document.getElementById('summary_comment');
    if (!commentField) {
        return;
    }

    const draft = normalizeCommentBlock(buildClinicalCommentDraft(data));
    const currentValue = String(commentField.value || '').trim();
    const sections = splitClinicalCommentSections(currentValue);
    const paragraphGap = String.fromCharCode(10) + String.fromCharCode(10);
    let before = sections.before;
    let after = sections.after;

    if (sections.hasBlock && sections.isLegacyBlock) {
        const legacy = parseLegacyClinicalCommentBlock(sections.block);
        after = [legacy.trailingText, sections.after].filter(Boolean).join(paragraphGap);
    }

    let nextValue = currentValue;
    if (!draft) {
        if (!sections.hasBlock) {
            return;
        }
        nextValue = [before, after].filter(Boolean).join(paragraphGap);
    } else {
        nextValue = [before, draft, after].filter(Boolean).join(paragraphGap);
    }

    if (nextValue === currentValue) {
        return;
    }

    commentField.value = nextValue;
    commentField.dispatchEvent(new Event('input', { bubbles: true }));
    commentField.dispatchEvent(new Event('change', { bubbles: true }));
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
    const age = calculateAgeAtDate(patientState.birthdate, patientState.evalDate);
    const bmiReference = getBmiReference(age);
    const mnaState = getCurrentMnaSummaryState();
    const nutritionGuidance = buildNutritionGuidance(patientState, bmiReference, mnaState);
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

        if (nutritionGuidance.note) {
            alertItems.push(`MNA-SF 0〜7点のため ${nutritionGuidance.note} を確認してください。`);
        }

        const chips = history.length ? [buildMetricChipHtml('保存履歴', `${history.length}件`, history.length ? 'success' : 'info')] : [];
        if (patientState.bmi !== null) {
            chips.push(buildMetricChipHtml('BMI', patientState.bmi.toFixed(1), classifyBmiReference(patientState.bmi, bmiReference)));
        }
        if (mnaState.score !== null) {
            chips.push(buildMetricChipHtml('MNA-SF', `${mnaState.score}点`, classifyMnaSummaryTone(mnaState.score)));
        }
        if (nutritionGuidance.note) {
            chips.push(buildMetricChipHtml('栄養詳細', nutritionGuidance.note, 'alert'));
        }

        return {
            chips,
            summaryText: buildClinicalAlertSummary(alertItems.length ? alertItems : ['口腔項目を入力すると差分判定を表示します。']),
            findingItems: nutritionGuidance.issueItems.length ? nutritionGuidance.issueItems : ['口腔タブの入力後に所見候補を生成します。'],
            alertItems: alertItems.length ? alertItems : ['口腔項目を入力すると差分判定を表示します。'],
            recommendationTone: mnaState.needsPocketNutrition ? 'alert' : 'info',
            recommendationLabel: nutritionGuidance.actionItems.length
                ? (mnaState.needsPocketNutrition ? '栄養評価の再確認を優先' : '栄養状態を継続観察')
                : '入力待ち',
            recommendationItems: nutritionGuidance.actionItems.length
                ? nutritionGuidance.actionItems
                : ['問診・RSST・うがい・オーラルディアドコキネシスを入力すると、食形態の提案を表示します。'],
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
        swallowRisk += 2;
        findingItems.push('RSST の専門職判断は問題ありです。');
    }
    if (oralState.q3Code === 2) {
        hygieneRisk += 2;
        findingItems.push('口腔乾燥の訴えがあり、保湿と水分調整が必要です。');
    }
    if (oralState.q7Code === 2) {
        hygieneRisk += 1;
        findingItems.push('軽度の口臭があり、清掃状態や乾燥の確認が必要です。');
    } else if (oralState.q7Code === 3) {
        hygieneRisk += 2;
        findingItems.push('強い口臭があり、清掃状態や乾燥の確認を優先します。');
    }
    if (oralState.q8Code !== null) {
        hygieneRisk += getCleaningHabitRisk(oralState.q8Code);
        if (oralState.q8Code === 1) {
            findingItems.push('日常の口腔清掃習慣が乏しく、口腔ケア支援の余地があります。');
        } else if (oralState.q8Code === 2) {
            findingItems.push('口腔清掃習慣は限定的です。');
        }
    }
    if (oralState.q10Code === 2) {
        chewingRisk += 1;
        findingItems.push('少量の食べこぼしがあり、食塊保持の観察が必要です。');
    } else if (oralState.q10Code === 3) {
        chewingRisk += 2;
        functionRisk += 1;
        findingItems.push('食べこぼしが目立ち、口唇・頬・舌の協調低下に留意が必要です。');
    }
    if (oralState.q11Code === 4) {
        functionRisk += 1;
        findingItems.push('表情変化が少なく、口唇・頬の活動性低下が示唆されます。');
    } else if (oralState.q11Code === 5) {
        functionRisk += 2;
        findingItems.push('表情が乏しく、口唇・頬の活動性低下が強く示唆されます。');
    }

    const gargleNotes = [];
    if (oralState.bukubukuCode === 2) {
        functionRisk += 1;
        gargleNotes.push('ブクブクうがいが不十分');
    } else if (oralState.bukubukuCode === 3) {
        functionRisk += 2;
        gargleNotes.push('ブクブクうがいができない');
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
            if (hasWorsenedCode(oralState.q10Code, comparisonOralState.q10Code)) {
                alertItems.push('食べこぼしが前回より増えています。');
            }
            if (hasWorsenedCode(oralState.q11Code, comparisonOralState.q11Code) && oralState.q11Code >= 4) {
                alertItems.push('表情の乏しさが前回より目立っています。');
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
    if (nutritionGuidance.issueItems.length) {
        findingItems.push(...nutritionGuidance.issueItems);
        summaryParts.push(`栄養課題として ${nutritionGuidance.issueItems.join(' ')}`);
    }
    if (nutritionGuidance.actionItems.length) {
        recommendationItems.push(...nutritionGuidance.actionItems);
    }
    if (nutritionGuidance.note) {
        alertItems.push(`MNA-SF 0〜7点のため ${nutritionGuidance.note} を確認してください。`);
        summaryParts.push(nutritionGuidance.note);
    }
    if (!recommendationItems.length) {
        recommendationItems.push('現行食形態を基本に継続し、むせや食事量の変化を経過観察します。');
    }

    if (nutritionGuidance.actionItems.length && recommendationTone === 'success') {
        recommendationTone = mnaState.needsPocketNutrition ? 'alert' : 'info';
        recommendationLabel = mnaState.needsPocketNutrition ? '栄養評価の再確認を優先' : '栄養状態を含めて継続観察';
    }
    const diagnosisNoteIndex = summaryParts.findIndex((item) => item.includes('診断ではなく記録補助として利用してください。'));
    if (diagnosisNoteIndex >= 0 && diagnosisNoteIndex !== summaryParts.length - 1) {
        const [diagnosisNote] = summaryParts.splice(diagnosisNoteIndex, 1);
        summaryParts.push(diagnosisNote);
    }

    const chips = [
        buildMetricChipHtml('咀嚼', formatStage3DomainLabel(chewingRisk), classifyStage3Risk(chewingRisk)),
        buildMetricChipHtml('嚥下', formatStage3DomainLabel(swallowRisk), classifyStage3Risk(swallowRisk)),
        buildMetricChipHtml('衛生・乾燥', formatStage3DomainLabel(hygieneRisk), classifyStage3Risk(hygieneRisk)),
        buildMetricChipHtml('口唇・舌機能', formatStage3DomainLabel(functionRisk), classifyStage3Risk(functionRisk)),
    ];
    if (patientState.bmi !== null) {
        chips.push(buildMetricChipHtml('BMI', patientState.bmi.toFixed(1), classifyBmiReference(patientState.bmi, bmiReference)));
    }
    if (mnaState.score !== null) {
        chips.push(buildMetricChipHtml('MNA-SF', `${mnaState.score}点`, classifyMnaSummaryTone(mnaState.score)));
    }
    if (nutritionGuidance.note) {
        chips.push(buildMetricChipHtml('栄養詳細', nutritionGuidance.note, 'alert'));
    }
    if (comparisonRecord && comparisonRecord.date) {
        chips.push(buildMetricChipHtml('比較基準', comparisonRecord.date, 'info'));
    }
    if (history.length) {
        chips.push(buildMetricChipHtml('保存履歴', `${history.length}件`, 'info'));
    }

    const data = {
        chips,
        summaryText: buildClinicalAlertSummary(alertItems),
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
    const summary = document.getElementById('clinicalSupportSummary');
    const alerts = document.getElementById('clinicalAlertList');
    const meta = document.getElementById('clinicalSupportMeta');
    if (!summary || !alerts || !meta) {
        return;
    }

    const data = buildClinicalSupportData();
    latestClinicalSupportData = data;
    summary.textContent = data.summaryText;
    alerts.innerHTML = buildStage3ListHtml(data.alertItems, '前回比較の準備が整うと差分を表示します。');
    meta.textContent = data.metaText;
    syncClinicalCommentDraft(data);
}

function parseDisplayedScore(value) {
    const match = String(value || '').trim().match(/(\\d+(?:\\.\\d+)?)/);
    if (!match) {
        return null;
    }
    return Number.parseFloat(match[1]);
}

function classifyMnaSummaryTone(score) {
    if (score === null) {
        return 'info';
    }
    if (score <= 7) {
        return 'alert';
    }
    if (score <= 11) {
        return 'info';
    }
    return 'success';
}

function getCurrentMnaSummaryState() {
    const score = parseDisplayedScore(getFieldElementValue('mna_summary_num'));
    const rawLabel = String(getFieldElementValue('mna_summary_result') || '').replace('【ポケニュー評価へ】', '').trim();
    const fallbackLabel = score === null ? '' : score <= 7 ? '低栄養' : score <= 11 ? 'At risk' : '良好';
    return {
        score,
        label: rawLabel || fallbackLabel,
        needsPocketNutrition: score !== null && score <= 7,
    };
}

function buildNutritionGuidance(state, reference, mnaState) {
    const issueItems = [];
    const actionItems = [];

    if (state.bmi !== null && reference) {
        if (state.bmi < reference.low) {
            issueItems.push(`BMI が ${reference.label} ${reference.low.toFixed(1)} 未満で、体重減少や摂取不足に注意が必要です。`);
            actionItems.push('食事量・間食・補助食品の活用、体重推移の確認を行います。');
        } else if (state.bmi > reference.high) {
            issueItems.push(`BMI が ${reference.label} ${reference.high.toFixed(1)} を上回っています。`);
            actionItems.push('活動量、食事量、体重推移を合わせて確認します。');
        }
    }

    if (mnaState.score !== null) {
        if (mnaState.score <= 7) {
            issueItems.push(`MNA-SF ${mnaState.score}点で低栄養の可能性があります。`);
            actionItems.push('【ポケニュー評価へ】を目安に詳細評価や多職種連携を検討します。');
        } else if (mnaState.score <= 11) {
            issueItems.push(`MNA-SF ${mnaState.score}点で低栄養リスクがあります。`);
            actionItems.push('摂取量、水分量、食事形態、体重変化を定期確認します。');
        }
    }

    const currentDiet = [state.foodStaple, state.foodMain].filter(Boolean).join(' / ');
    const currentWater = String(state.waterTexture || '').trim();
    if ((issueItems.length || actionItems.length) && (currentDiet || currentWater)) {
        const dietLabel = currentDiet ? `食形態（${currentDiet}）` : '';
        const waterLabel = currentWater ? `水分形態（${currentWater}）` : '';
        actionItems.push(`${[dietLabel, waterLabel].filter(Boolean).join('・')}が現在の状態に合っているかを確認します。`);
    }

    if (!issueItems.length && !actionItems.length && (state.bmi !== null || mnaState.score !== null)) {
        issueItems.push('大きな栄養リスクは現時点で強く示されていません。');
        actionItems.push('現行の食形態・水分形態と体重推移を継続観察します。');
    }

    return {
        issueItems: [...new Set(issueItems)],
        actionItems: [...new Set(actionItems)],
        note: mnaState.needsPocketNutrition ? '【ポケニュー評価へ】' : '',
    };
}

function buildNutritionSupportText(state, age, bmi, reference, mnaInfo, latestSavedRecord, mnaState) {
    if (!state.birthdate) {
        return '生年月日を入力すると年齢帯の参考帯を表示します。';
    }
    if (bmi === null) {
        return '体重と身長を入力すると BMI と MNA F1 の目安を表示します。';
    }

    const parts = [`現在の BMI は ${bmi.toFixed(1)} です。`];
    const nutritionGuidance = buildNutritionGuidance(state, reference, mnaState);
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
    if (mnaState.score !== null) {
        parts.push(`MNA-SF は ${mnaState.score}点（${mnaState.label || '判定確認中'}）です。`);
    }
    if (nutritionGuidance.issueItems.length) {
        parts.push(`栄養課題: ${nutritionGuidance.issueItems.join(' ')}`);
    }
    if (nutritionGuidance.actionItems.length) {
        parts.push(`対応案: ${nutritionGuidance.actionItems.join(' ')}`);
    }
    if (nutritionGuidance.note) {
        parts.push(nutritionGuidance.note);
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
    const mnaState = getCurrentMnaSummaryState();
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
    if (mnaState.score !== null) {
        chipItems.push(buildMetricChipHtml('MNA-SF', `${mnaState.score}点`, classifyMnaSummaryTone(mnaState.score)));
    } else if (mnaInfo) {
        chipItems.push(buildMetricChipHtml('MNA F1 目安', `${mnaInfo.score}点`, mnaInfo.score <= 1 ? 'alert' : 'success'));
    }
    if (mnaState.needsPocketNutrition) {
        chipItems.push(buildMetricChipHtml('栄養詳細', '【ポケニュー評価へ】', 'alert'));
    }
    if (latestSavedRecord && latestSavedRecord.date) {
        chipItems.push(buildMetricChipHtml('前回保存', latestSavedRecord.date, 'info'));
    }
    if (state.weight !== null && latestSavedWeight !== null) {
        const tone = getTrendDirection(state.weight, latestSavedWeight) === 'down' ? 'alert' : 'info';
        chipItems.push(buildMetricChipHtml('前回比体重', formatSignedDelta(state.weight, latestSavedWeight, 'kg'), tone));
    }

    chips.innerHTML = chipItems.join('');
    summary.textContent = buildNutritionSupportText(state, age, state.bmi, reference, mnaInfo, latestSavedRecord, mnaState);
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
                <td class="history-cell--nowrap"><strong>${escapeHtml(record.date || '―')}</strong>${record.nextMonitor ? `<br><small class="metric-subline">次回 ${escapeHtml(record.nextMonitor)}</small>` : ''}</td>
                <td class="history-cell--nowrap">${escapeHtml(formatMetricValue(weight, 'kg'))}</td>
                <td class="history-cell--nowrap">${escapeHtml(formatMetricValue(bmi))}</td>
                <td class="history-cell--nowrap">${buildTrendDeltaHtml(weight, olderWeight, 'kg')}</td>
                <td class="history-cell--nowrap">${buildTrendDeltaHtml(bmi, olderBmi, '')}</td>
                <td class="history-cell--nowrap"><span class="tag ${tagClass}">${escapeHtml(record.mnaLabel || '―')}</span><br><small class="metric-subline">${escapeHtml(scoreLabel)}</small></td>
            </tr>
        `;
    }).join('');
}

function updateStage2Panels() {
    renderNutritionSupportPanel();
    renderPatientTrendPanel();
    renderClinicalSupportPanel();
    renderNutritionAssessmentPanel();
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
        'food_staple',
        'food_main',
        'water_texture',
        'q1',
        'q2',
        'q3',
        'q4',
        'q5',
        'q6',
        'q7',
        'q8',
        'q9',
        'q10',
        'q11',
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
            scheduleStage2Update();
            return result;
        };
        window.loadRecord = loadRecord;
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

function setSummaryFieldText(id, text) {
    const element = document.getElementById(id);
    if (!element) {
        return;
    }
    if ('value' in element) {
        element.value = text;
        return;
    }
    element.textContent = text;
}

function summarizeOralEval2Value(value) {
    const text = String(value || '').trim();
    if (!text) {
        return '未入力';
    }
    if (text.startsWith('あり（継続） 口腔清掃')) {
        return 'あり（継続） 口腔機能低下あり';
    }
    if (text.startsWith('あり（継続） 口腔機能向上サービス')) {
        return 'あり（継続） 中止で著しい低下のおそれ';
    }
    if (text.startsWith('なし（終了）')) {
        return 'なし（終了） 自立';
    }
    return text;
}

function ensureSummaryIdentitySubline() {
    const nameElement = document.getElementById('summary_name');
    const dateElement = document.getElementById('summary_date');
    if (!nameElement || !dateElement || !dateElement.parentElement) {
        return null;
    }
    nameElement.classList.add('summary-identity-name');
    dateElement.classList.add('summary-identity-date');
    let subline = document.getElementById('summaryIdentitySubline');
    if (!subline) {
        subline = document.createElement('div');
        subline.id = 'summaryIdentitySubline';
        subline.className = 'summary-identity-subline';
        dateElement.parentElement.insertBefore(subline, dateElement);
    }
    return subline;
}

function updateSummaryIdentityFields() {
    const nameText = getFieldElementValue('name').trim() || '―';
    const furiganaText = getFieldElementValue('furigana').trim() || '―';
    const subline = ensureSummaryIdentitySubline();
    if (subline) {
        subline.textContent = `氏名/ふりがな: ${nameText} / ${furiganaText}`;
    }
    const dateElement = document.getElementById('summary_date');
    if (dateElement) {
        dateElement.textContent = `評価日: ${getFieldElementValue('evalDate').trim() || '―'}`;
    }
}

function buildEnhancedOralSummaryText() {
    const oralEval1 = getFieldElementValue('oral_eval1').trim();
    const oralEval2 = getFieldElementValue('oral_eval2').trim();
    const oralEval3 = getFieldElementValue('oral_eval3').trim();
    if (![oralEval1, oralEval2, oralEval3].some(Boolean)) {
        return '';
    }
    return [
        `① 著しい低下のおそれ: ${oralEval1 || '未入力'}`,
        `② 継続必要性: ${summarizeOralEval2Value(oralEval2)}`,
        `③ モニタリング後: ${oralEval3 || '未入力'}`,
    ].join(' / ');
}

function updateEnhancedSummaryFields() {
    updateSummaryIdentityFields();

    const oralSummaryText = buildEnhancedOralSummaryText();
    if (oralSummaryText) {
        if (document.getElementById('oral_summary_text')) {
            setSummaryFieldText('oral_summary_text', oralSummaryText);
        } else {
            setSummaryFieldText('oral_summary_box', oralSummaryText);
        }
    }

    const mnaState = getCurrentMnaSummaryState();
    const baseText = String(getFieldElementValue('mna_summary_result') || '').replace('【ポケニュー評価へ】', '').trim();
    if (mnaState.score !== null || baseText) {
        const nextText = mnaState.needsPocketNutrition
            ? `${baseText || '低栄養の可能性があります'} 【ポケニュー評価へ】`
            : baseText;
        if (nextText) {
            setSummaryFieldText('mna_summary_result', nextText);
        }
    }
}

function ensureSummaryFieldCompatibility() {
    const oralSummaryBox = document.getElementById('oral_summary_box');
    if (oralSummaryBox && !document.getElementById('oral_summary_text')) {
        const initialText = String(oralSummaryBox.textContent || '').trim();
        oralSummaryBox.textContent = '';
        const valueElement = document.createElement('div');
        valueElement.id = 'oral_summary_text';
        valueElement.textContent = initialText || '口腔機能タブを入力してください';
        oralSummaryBox.appendChild(valueElement);
    }
}

function installSummaryHooks() {
    if (summaryHooksInstalled) {
        return;
    }

    ensureSummaryFieldCompatibility();

    if (typeof updateSummary === 'function') {
        const originalUpdateSummary = updateSummary;
        updateSummary = function(...args) {
            const result = originalUpdateSummary.apply(this, args);
            updateEnhancedSummaryFields();
            scheduleStage2Update();
            return result;
        };
        window.updateSummary = updateSummary;
    }

    if (typeof calcMNAScore === 'function') {
        const originalCalcMNAScore = calcMNAScore;
        calcMNAScore = function(...args) {
            const result = originalCalcMNAScore.apply(this, args);
            updateEnhancedSummaryFields();
            scheduleStage2Update();
            return result;
        };
        window.calcMNAScore = calcMNAScore;
    }

    summaryHooksInstalled = true;
    updateEnhancedSummaryFields();
}

window.addEventListener('afterprint', clearPrintMode);

async function initializeApp() {
    ensureStage1Styles();
    await ensureLocalSettingsInitialized();
    syncManagedPersonSelectors();
    ensurePatientFormEnhancements();
    ensureOralAssessmentEnhancements();
    ensureSummaryFieldCompatibility();
    ensureSettingsControls();
    ensureHistoryTools();
    ensurePrintControls();
    ensureDraftControls();
    ensureDataTransferControls();
    ensureStage2Panels();
    ensureStage3Panels();
    attachDraftAutosave();
    attachStage2InputListeners();
    installManagedFieldHooks();
    installStage2Hooks();
    installSummaryHooks();
    try {
        records = await fetchRecords();
    } catch (error) {
        console.error(error);
        showToast(error.message || '同期に失敗しました');
    }
    renderHistory();
    syncCustomDateSelectors();
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


@dataclass(slots=True)
class ClientTemplateState:
    templates: dict[str, str]
    source_mtime_ns: int | None


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
        controls.append(LOGOUT_BADGE_HTML)
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


def detect_client_html_mode(html: str) -> str:
    if STATE_LINE in html:
        return CLIENT_HTML_MODE_LEGACY_SOURCE

    if all(marker in html for marker in MANAGED_CLIENT_MARKERS):
        return CLIENT_HTML_MODE_MANAGED

    raise RuntimeError(
        "Unsupported client HTML format. Expected either the legacy source artifact or a managed Claude-generated client HTML with API integration."
    )


def extract_client_html_and_mode(wrapper_html: str) -> tuple[str, str]:
    embedded_html = extract_embedded_html(wrapper_html)
    return embedded_html, detect_client_html_mode(embedded_html)


def build_client_template_from_wrapper_html(
    wrapper_html: str,
    auth_enabled: bool = False,
) -> str:
    embedded_html, mode = extract_client_html_and_mode(wrapper_html)
    if mode == CLIENT_HTML_MODE_MANAGED:
        if auth_enabled:
            match = HEADER_STATUS_BLOCK_PATTERN.search(embedded_html)
            if not match:
                raise RuntimeError("Managed client auth status block not found")
            return embedded_html[:match.start(2)] + AUTH_STATUS_PLACEHOLDER + embedded_html[match.end(2):]
        return embedded_html
    return transform_client_html(
        embedded_html,
        auth_enabled=auth_enabled,
        auth_status_html=AUTH_STATUS_PLACEHOLDER if auth_enabled else None,
    )


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
    return build_client_template_from_wrapper_html(wrapper_html, auth_enabled=auth_enabled)


def render_client_html(client_template: str, auth_status_html: str | None = None) -> str:
    if AUTH_STATUS_PLACEHOLDER not in client_template:
        if auth_status_html and "ログアウト" in auth_status_html and "ログアウト" not in client_template:
            match = HEADER_STATUS_BLOCK_PATTERN.search(client_template)
            if match:
                status_block = match.group(2)
                if status_block.endswith("</div>"):
                    status_block = status_block[:-6] + LOGOUT_BADGE_HTML + "</div>"
                    return client_template[:match.start(2)] + status_block + client_template[match.end(2):]
        return client_template
    return client_template.replace(AUTH_STATUS_PLACEHOLDER, auth_status_html or build_status_badges_html())


def prepare_client_templates() -> dict[str, str]:
    return {
        "public": build_client_template(auth_enabled=False),
        "auth": build_client_template(auth_enabled=True),
    }


def get_source_artifact_mtime_ns() -> int | None:
    try:
        return SOURCE_ARTIFACT_PATH.stat().st_mtime_ns
    except OSError:
        return None


def build_client_template_state() -> ClientTemplateState:
    return ClientTemplateState(
        templates=prepare_client_templates(),
        source_mtime_ns=get_source_artifact_mtime_ns(),
    )


def get_live_client_templates(server: ThreadingHTTPServer) -> dict[str, str]:
    with server.client_templates_lock:  # type: ignore[attr-defined]
        state = server.client_template_state  # type: ignore[attr-defined]
        current_mtime_ns = get_source_artifact_mtime_ns()
        if current_mtime_ns == state.source_mtime_ns and state.templates:
            return state.templates

        try:
            templates = prepare_client_templates()
        except Exception as error:
            if state.templates:
                print(f"Client template reload skipped: {error}")
                return state.templates
            raise

        server.client_template_state = ClientTemplateState(  # type: ignore[attr-defined]
            templates=templates,
            source_mtime_ns=get_source_artifact_mtime_ns(),
        )
        if state.source_mtime_ns is not None:
            print(f"Reloaded client templates from {SOURCE_ARTIFACT_PATH.name}")
        return templates


def build_client_html(
    auth_enabled: bool = False,
    auth_status_html: str | None = None,
) -> str:
    template = build_client_template(auth_enabled=auth_enabled)
    return render_client_html(template, auth_status_html=auth_status_html)


def validate_client_source_file(source_path: Path) -> str:
    wrapper_html = source_path.read_text(encoding="utf-8")
    _, mode = extract_client_html_and_mode(wrapper_html)
    public_template = build_client_template_from_wrapper_html(wrapper_html, auth_enabled=False)
    auth_template = render_client_html(
        build_client_template_from_wrapper_html(wrapper_html, auth_enabled=True),
        auth_status_html=build_status_badges_html(include_logout=True),
    )

    checks = {
        "利用者情報タブ": 'id="tab-patient"' in public_template,
        "口腔機能タブ": 'id="tab-oral"' in public_template,
        "MNAタブ": 'id="tab-mna"' in public_template,
        "総合評価タブ": 'id="tab-summary"' in public_template,
        "履歴タブ": 'id="tab-history"' in public_template,
        "記録 API": "const API_ROOT = '/api/records';" in public_template,
        "設定 API": "const SETTINGS_API_ROOT = '/api/settings';" in public_template,
        "タブ切替関数": "function showTab(id)" in public_template,
        "MNA選択関数": "function selectMNA(" in public_template,
        "保存関数": "function saveRecord()" in public_template or "async function saveRecord()" in public_template,
        "削除関数": "function deleteRecord(id)" in public_template or "async function deleteRecord(id)" in public_template,
        "初期化処理": "initializeApp();" in public_template,
        "認証バッジ注入": "ログアウト" in auth_template,
    }
    missing_items = [label for label, ok in checks.items() if not ok]
    if missing_items:
        raise RuntimeError("Validation checks failed: " + ", ".join(missing_items))

    return mode


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


def resolve_asset_path(request_path: str) -> Path | None:
    if not request_path.startswith("/assets/"):
        return None

    parts = request_path.lstrip("/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None

    candidate = (BASE_DIR / Path(*parts)).resolve()
    try:
        candidate.relative_to(ASSETS_DIR_RESOLVED)
    except ValueError:
        return None

    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def guess_asset_content_type(file_path: Path) -> str:
    return ASSET_CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")


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
        return get_live_client_templates(self.server)

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

        static_asset = HELP_STATIC_ROUTES.get(parsed.path)
        if static_asset:
            if not self.ensure_authenticated(api=False):
                return
            self.respond_file(static_asset[0], static_asset[1])
            return

        asset_path = resolve_asset_path(parsed.path)
        if asset_path:
            if not self.ensure_authenticated(api=False):
                return
            self.respond_file(asset_path, guess_asset_content_type(asset_path))
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
    parser.add_argument("--validate-client-html", nargs="?", const=SOURCE_ARTIFACT_PATH, type=Path)
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
    if args.validate_client_html is not None:
        try:
            mode = validate_client_source_file(args.validate_client_html)
        except Exception as error:
            raise SystemExit(f"Client HTML validation failed: {error}") from error
        print(f"Client HTML validation: OK ({mode})")
        print(f"Source: {args.validate_client_html}")
        return

    auth_config = build_auth_config(args)
    ensure_database(args.db)
    client_template_state = build_client_template_state()
    server = ThreadingHTTPServer((args.host, args.port), KoukuKinouHandler)
    server.daemon_threads = True
    server.db_path = args.db  # type: ignore[attr-defined]
    server.auth_config = auth_config  # type: ignore[attr-defined]
    server.client_template_state = client_template_state  # type: ignore[attr-defined]
    server.client_templates_lock = threading.Lock()  # type: ignore[attr-defined]
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