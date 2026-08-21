"""
UEBA Pipeline Orchestrator
Ketma-ketlik: Collector -> Processor -> Visualizer
"""
import sys
from pipeline.collector import collect_data
from pipeline.processor import process_data
from visualize import generate_dashboard

def run_pipeline():
    print("="*50)
    print("UEBA PROCESSING PIPELINE STARTED")
    print("="*50)
    
    try:
        # Stage 1: MongoDB -> raw_data.json
        collect_data()
        
        # Stage 2: raw_data.json -> results.json (including username mapping)
        process_data()
        
        # Stage 3: results.json -> dashboard.html
        generate_dashboard("dashboard.html")
        
        print("="*50)
        print("PIPELINE SUCCESSFULLY COMPLETED!")
        print("Result: dashboard.html")
        print("="*50)
        
    except Exception as e:
        print(f"\n!!! PIPELINE FAILED !!!\nError: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_pipeline()
