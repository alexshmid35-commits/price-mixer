"""Write a DataFrame snapshot to XLSX in a standalone process."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def write_snapshot(input_path, output_path):
    source = Path(input_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_pickle(source)
    if not isinstance(df, pd.DataFrame):
        raise TypeError("XLSX snapshot must contain a pandas DataFrame")
    df.to_excel(target, index=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate Price Mixer consolidated XLSX")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    write_snapshot(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
