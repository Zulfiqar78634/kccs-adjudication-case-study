#!/usr/bin/env python3
"""Standalone workbook inspection (same as `kccs-evidence inspect`)."""
import sys

from kccs_evidence.inspection import inspect, write_report

if __name__ == "__main__":
    wb = sys.argv[1] if len(sys.argv) > 1 else "data/KCCS_Sentinel_Reference_Data_Pack.xlsx"
    out = sys.argv[2] if len(sys.argv) > 2 else "artifacts/data_quality"
    print(write_report(inspect(wb), out))
