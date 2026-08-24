"""
UEBA Pipeline Orchestrator — yagona kirish nuqtasi.

Ketma-ketlik:
  Stage 0: collect    MongoDB -> raw_data.json            (har doim)
  Stage 1: train      raw_data.json -> baseline.json      (FAQAT baseline
                                                          mavjud bo'lmasa yoki
                                                          --retrain berilgan bo'lsa)
  Stage 2: score      baseline.json + raw_data.json -> results.json (har doim)
  Stage 3: dashboard  results.json -> dashboard.html      (har doim)

Ishlatish:
  python main.py            # pipeline; o'qitish faqat birinchi marta
  python main.py --retrain  # baseline yangidan o'qitiladi (qo'lda yangilash)
"""
import argparse
import json
import sys

from pipeline.utils import BASELINE_FILE


def run_pipeline(retrain=False):
    from pipeline.collector import collect_data
    from pipeline.scorer import score
    from pipeline.trainer import train
    from pipeline.visualizer import generate_dashboard

    print("=" * 50)
    print("UEBA PROCESSING PIPELINE STARTED")
    print("=" * 50)

    try:
        # Stage 0: MongoDB -> raw_data.json
        collect_data()

        # Stage 1: raw_data.json -> baseline.json
        if BASELINE_FILE.exists() and not retrain:
            with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                trained_at = json.load(f).get("meta", {}).get("trainedAt", "N/A")
            print(f"\nStage 1 (Train) SKIPPED: existing baseline in use (trained: {trained_at}). Retrain manually with: python main.py --retrain")
        else:
            train()

        # Stage 2: baseline.json + raw_data.json -> results.json
        score()

        # Stage 3: results.json -> dashboard.html
        generate_dashboard()

        print("=" * 50)
        print("PIPELINE SUCCESSFULLY COMPLETED!")
        print("Result: dashboard.html")
        print("=" * 50)

    except Exception as e:
        print(f"\n!!! PIPELINE FAILED !!!\nError: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="UEBA processing pipeline")
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="baseline yangidan o'qitiladi (default: mavjud baseline ishlatiladi)",
    )
    args = parser.parse_args()
    run_pipeline(retrain=args.retrain)


if __name__ == "__main__":
    main()
