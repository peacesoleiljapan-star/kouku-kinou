from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import server


ORAL_FIELD_PROFILES = {
    "monitoring": {
        "q1": "2.はい",
        "q2": "1.いいえ",
        "q3": "1.いいえ",
        "q4": "2.片方だけできる",
        "q5": "3.良い",
        "q6": "3.ふつう",
        "q7": "1.ない",
        "q8": "2.多少ある",
        "q9": "2.多少ある",
        "q10": "3.ふつう",
        "a1": "2強い",
        "a2": "2強い",
        "a3": "2ある",
        "a4": "2ある",
        "rsst_time": "30",
        "rsst_count": "3",
        "rsst_judge": "2やや不十分",
        "bukubuku": "2やや不十分",
        "gugugu": "2やや不十分",
        "pa": "5.4",
        "ta": "5.1",
        "ka": "4.8",
        "dryness": "なし",
        "halitosis": "なし",
        "conversation": "できる",
        "toothbrushing": "あり",
    },
    "dry_mouth": {
        "q1": "1.いいえ",
        "q2": "1.いいえ",
        "q3": "2.はい",
        "q4": "1.面方でできる",
        "q5": "3.良い",
        "q6": "4.やや悪い",
        "q7": "1.ない",
        "q8": "2.多少ある",
        "q9": "2.多少ある",
        "q10": "3.ふつう",
        "a1": "2強い",
        "a2": "2強い",
        "a3": "2ある",
        "a4": "2ある",
        "rsst_time": "30",
        "rsst_count": "3",
        "rsst_judge": "2やや不十分",
        "bukubuku": "2やや不十分",
        "gugugu": "2やや不十分",
        "pa": "5.2",
        "ta": "5.0",
        "ka": "4.6",
        "dryness": "あり",
        "halitosis": "なし",
        "conversation": "できる",
        "toothbrushing": "あり",
    },
    "swallow_risk": {
        "q1": "2.はい",
        "q2": "2.はい",
        "q3": "1.いいえ",
        "q4": "2.片方だけできる",
        "q5": "4.あまり良くない",
        "q6": "4.やや悪い",
        "q7": "1.ない",
        "q8": "2.多少ある",
        "q9": "3.多い",
        "q10": "4.やや良い",
        "a1": "2強い",
        "a2": "2強い",
        "a3": "2ある",
        "a4": "2ある",
        "rsst_time": "30",
        "rsst_count": "2",
        "rsst_judge": "3不十分",
        "bukubuku": "2やや不十分",
        "gugugu": "3不十分",
        "pa": "4.9",
        "ta": "4.6",
        "ka": "4.2",
        "dryness": "あり",
        "halitosis": "あり",
        "conversation": "のむ",
        "toothbrushing": "あり",
    },
    "re_eval": {
        "q1": "2.はい",
        "q2": "2.はい",
        "q3": "2.はい",
        "q4": "3.どちらもできない",
        "q5": "5.良くない",
        "q6": "5.悪い",
        "q7": "2.強い",
        "q8": "1.ない",
        "q9": "3.多い",
        "q10": "5.乏しい",
        "a1": "3無し",
        "a2": "3無し",
        "a3": "3多い",
        "a4": "3多い",
        "rsst_time": "30",
        "rsst_count": "1",
        "rsst_judge": "3不十分",
        "bukubuku": "3不十分",
        "gugugu": "3不十分",
        "pa": "4.1",
        "ta": "3.9",
        "ka": "3.6",
        "dryness": "あり",
        "halitosis": "あり",
        "conversation": "のむ",
        "toothbrushing": "食べこぼし",
    },
    "completed": {
        "q1": "1.いいえ",
        "q2": "1.いいえ",
        "q3": "1.いいえ",
        "q4": "1.面方でできる",
        "q5": "2.とても良い",
        "q6": "1.よい",
        "q7": "1.ない",
        "q8": "3.多い",
        "q9": "1.最高に良い",
        "q10": "1.最高",
        "a1": "1強い",
        "a2": "1強い",
        "a3": "1ない",
        "a4": "1ない",
        "rsst_time": "30",
        "rsst_count": "4",
        "rsst_judge": "1できる",
        "bukubuku": "1できる",
        "gugugu": "1できる",
        "pa": "6.3",
        "ta": "6.1",
        "ka": "5.8",
        "dryness": "なし",
        "halitosis": "なし",
        "conversation": "できる",
        "toothbrushing": "あり",
    },
}


SAMPLE_RECORDS = [
    {
        "name": "青木 恒一",
        "furigana": "あおき こういち",
        "birthdate": "1938-04-12",
        "gender": "男",
        "eval_date": "2026-03-15",
        "weight": "52.4",
        "height": "160.2",
        "bmi": "20.4",
        "mna_score": 11,
        "mna_label": "At risk",
        "oral_continue": "継続管理",
        "comment": "食事量に波があるため、間食を含めて経過観察します。",
        "next_monitor": "2026-05-15",
        "staff": "山口 ST",
        "dentist": "青葉歯科",
        "denture": "あり",
        "oral_profile": "monitoring",
        "mna_scores": {"a": 2, "b": 2, "c": 2, "d": 2, "e": 2, "f": 1},
    },
    {
        "name": "青木 恒一",
        "furigana": "あおき こういち",
        "birthdate": "1938-04-12",
        "gender": "男",
        "eval_date": "2026-04-22",
        "weight": "53.1",
        "height": "160.2",
        "bmi": "20.7",
        "mna_score": 12,
        "mna_label": "良好",
        "oral_continue": "継続管理",
        "comment": "補食導入で体重が安定し、口腔清掃も自立して継続できています。",
        "next_monitor": "2026-06-22",
        "staff": "山口 ST",
        "dentist": "青葉歯科",
        "denture": "あり",
        "oral_profile": "monitoring",
        "mna_scores": {"a": 2, "b": 3, "c": 2, "d": 2, "e": 2, "f": 1},
    },
    {
        "name": "石田 花子",
        "furigana": "いしだ はなこ",
        "birthdate": "1941-09-08",
        "gender": "女",
        "eval_date": "2026-03-28",
        "weight": "45.2",
        "height": "149.8",
        "bmi": "20.1",
        "mna_score": 9,
        "mna_label": "At risk",
        "oral_continue": "継続管理",
        "comment": "義歯不適合感があり、軟菜中心で摂取しています。",
        "next_monitor": "2026-05-28",
        "staff": "佐藤 ST",
        "dentist": "ひまわり歯科",
        "denture": "あり",
        "oral_profile": "swallow_risk",
        "mna_scores": {"a": 1, "b": 2, "c": 2, "d": 2, "e": 1, "f": 1},
    },
    {
        "name": "石田 花子",
        "furigana": "いしだ はなこ",
        "birthdate": "1941-09-08",
        "gender": "女",
        "eval_date": "2026-04-24",
        "weight": "44.7",
        "height": "149.8",
        "bmi": "19.9",
        "mna_score": 10,
        "mna_label": "At risk",
        "oral_continue": "継続管理",
        "comment": "義歯調整後も食形態の調整が必要で、少量頻回食を提案しています。",
        "next_monitor": "2026-06-10",
        "staff": "佐藤 ST",
        "dentist": "ひまわり歯科",
        "denture": "あり",
        "oral_profile": "swallow_risk",
        "mna_scores": {"a": 2, "b": 2, "c": 2, "d": 2, "e": 1, "f": 1},
    },
    {
        "name": "梅原 正雄",
        "furigana": "うめはら まさお",
        "birthdate": "1936-01-19",
        "gender": "男",
        "eval_date": "2026-04-02",
        "weight": "42.0",
        "height": "157.0",
        "bmi": "17.0",
        "mna_score": 7,
        "mna_label": "低栄養",
        "oral_continue": "要再評価",
        "comment": "嚥下時の疲労が強く、食事量低下が続いています。早めの再評価が必要です。",
        "next_monitor": "2026-05-02",
        "staff": "高橋 ST",
        "dentist": "北町歯科",
        "denture": "なし",
        "oral_profile": "re_eval",
        "mna_scores": {"a": 1, "b": 1, "c": 1, "d": 2, "e": 2, "f": 0},
    },
    {
        "name": "大西 恒一",
        "furigana": "おおにし こういち",
        "birthdate": "1945-06-03",
        "gender": "男",
        "eval_date": "2026-04-10",
        "weight": "58.5",
        "height": "167.3",
        "bmi": "20.9",
        "mna_score": 13,
        "mna_label": "良好",
        "oral_continue": "評価終了",
        "comment": "栄養状態・口腔機能ともに安定しており、セルフケアも良好です。",
        "next_monitor": "2026-07-10",
        "staff": "伊藤 ST",
        "dentist": "南台歯科",
        "denture": "なし",
        "oral_profile": "completed",
        "mna_scores": {"a": 2, "b": 2, "c": 2, "d": 2, "e": 2, "f": 3},
        "mna_field_mode": "f2",
    },
    {
        "name": "大西 恒一",
        "furigana": "おおにし こういち",
        "birthdate": "1945-06-03",
        "gender": "男",
        "eval_date": "2026-04-25",
        "weight": "58.2",
        "height": "167.3",
        "bmi": "20.8",
        "mna_score": 13,
        "mna_label": "良好",
        "oral_continue": "評価終了",
        "comment": "終結前確認でも問題なく、通常モニタリングへ移行可能です。",
        "next_monitor": "2026-08-25",
        "staff": "伊藤 ST",
        "dentist": "南台歯科",
        "denture": "なし",
        "oral_profile": "completed",
        "mna_scores": {"a": 2, "b": 3, "c": 2, "d": 2, "e": 1, "f": 3},
        "mna_field_mode": "f2",
    },
    {
        "name": "小川 和美",
        "furigana": "おがわ かずみ",
        "birthdate": "1939-12-21",
        "gender": "女",
        "eval_date": "2026-04-12",
        "weight": "47.3",
        "height": "151.4",
        "bmi": "20.6",
        "mna_score": 8,
        "mna_label": "At risk",
        "oral_continue": "継続管理",
        "comment": "口腔乾燥と食欲低下があり、水分摂取の声かけを継続します。",
        "next_monitor": "2026-05-26",
        "staff": "山口 ST",
        "dentist": "さくら歯科",
        "denture": "あり",
        "oral_profile": "dry_mouth",
        "mna_scores": {"a": 1, "b": 1, "c": 1, "d": 2, "e": 2, "f": 1},
    },
    {
        "name": "加藤 恒一",
        "furigana": "かとう こういち",
        "birthdate": "1943-07-14",
        "gender": "男",
        "eval_date": "2026-04-18",
        "weight": "54.1",
        "height": "162.0",
        "bmi": "20.6",
        "mna_score": 11,
        "mna_label": "At risk",
        "oral_continue": "継続管理",
        "comment": "夕食時にむせがみられるため、一口量の調整を指導しています。",
        "next_monitor": "2026-05-30",
        "staff": "高橋 ST",
        "dentist": "中央歯科",
        "denture": "なし",
        "oral_profile": "swallow_risk",
        "mna_scores": {"a": 2, "b": 3, "c": 2, "d": 2, "e": 1, "f": 1},
    },
    {
        "name": "斎藤 光子",
        "furigana": "さいとう みつこ",
        "birthdate": "1937-10-30",
        "gender": "女",
        "eval_date": "2026-04-20",
        "weight": "40.8",
        "height": "148.2",
        "bmi": "18.6",
        "mna_score": 6,
        "mna_label": "低栄養",
        "oral_continue": "要再評価",
        "comment": "体重減少が続き、食後疲労も強いため医師連携を優先します。",
        "next_monitor": "2026-04-27",
        "staff": "佐藤 ST",
        "dentist": "みなみ歯科",
        "denture": "あり",
        "oral_profile": "re_eval",
        "mna_scores": {"a": 0, "b": 1, "c": 1, "d": 2, "e": 2, "f": 0},
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed kouku-kinou with 10 sample assessment records")
    parser.add_argument("--db", type=Path, default=Path("data/records.db"))
    parser.add_argument("--replace", action="store_true", help="Delete existing records before seeding")
    return parser.parse_args()


def build_oral_fields(sample: dict[str, object], oral_biko: str) -> dict[str, str]:
    profile_name = str(sample.get("oral_profile") or "monitoring")
    base_fields = dict(ORAL_FIELD_PROFILES.get(profile_name, ORAL_FIELD_PROFILES["monitoring"]))
    explicit_fields = sample.get("oral_fields") or {}
    if isinstance(explicit_fields, dict):
        base_fields.update({key: str(value) for key, value in explicit_fields.items()})
    base_fields.setdefault("oral_note1", oral_biko)
    base_fields.setdefault("oral_note2", oral_biko)
    return base_fields


def build_record(sample: dict[str, object]) -> dict[str, object]:
    oral_continue = str(sample["oral_continue"])
    oral_select_value = "なし（終了）" if "終了" in oral_continue else "あり（継続）"
    oral_eval1 = str(sample.get("oral_eval1") or ("なし" if "終了" in oral_continue else "あり"))
    oral_eval3 = str(sample.get("oral_eval3") or oral_select_value)
    oral_biko = str(sample.get("oral_biko") or sample["comment"])
    mna_scores = dict(sample.get("mna_scores") or {})
    mna_field_mode = str(sample.get("mna_field_mode") or "f1")
    oral_fields = build_oral_fields(sample, oral_biko)

    fields = {
        "name": sample["name"],
        "furigana": sample["furigana"],
        "birthdate": sample["birthdate"],
        "gender": sample["gender"],
        "weight": sample["weight"],
        "height": sample["height"],
        "bmi": sample["bmi"],
        "evalDate": sample["eval_date"],
        "serviceStart": "2025-04-01",
        "serviceEnd": "",
        "dentist": sample["dentist"],
        "denture": sample["denture"],
        "staff": sample["staff"],
        "oral_eval1": oral_eval1,
        "oral_eval2": oral_select_value,
        "oral_eval3": oral_eval3,
        "oral_biko": oral_biko,
        "summary_comment": sample["comment"],
        "next_monitor": sample["next_monitor"],
    }
    fields.update(oral_fields)
    return {
        "name": sample["name"],
        "furigana": sample["furigana"],
        "date": sample["eval_date"],
        "mnaScore": sample["mna_score"],
        "mnaLabel": sample["mna_label"],
        "oralContinue": sample["oral_continue"],
        "comment": sample["comment"],
        "nextMonitor": sample["next_monitor"],
        "weight": sample["weight"],
        "height": sample["height"],
        "bmi": sample["bmi"],
        "mnaScores": mna_scores,
        "mnaFieldMode": mna_field_mode,
        "fields": fields,
    }


def count_records(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]


def delete_existing_records(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM records")
        connection.commit()


def main() -> None:
    args = parse_args()
    server.ensure_database(args.db)

    existing_count = count_records(args.db)
    if existing_count and not args.replace:
        raise SystemExit(
            f"{args.db} には既に {existing_count} 件の記録があります。上書きする場合は --replace を付けてください。"
        )

    if args.replace:
        delete_existing_records(args.db)

    inserted_ids: list[int] = []
    for sample in SAMPLE_RECORDS:
        record = server.create_record(args.db, build_record(sample))
        inserted_ids.append(int(record["id"]))

    final_count = count_records(args.db)
    unique_patients = len({f"{sample['name']}::{sample['birthdate']}" for sample in SAMPLE_RECORDS})
    print(
        {
            "db": str(args.db),
            "inserted_records": len(inserted_ids),
            "final_count": final_count,
            "unique_patients": unique_patients,
        }
    )


if __name__ == "__main__":
    main()