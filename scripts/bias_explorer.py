#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import numpy as np
import pandas as pd
from wub.vis import report
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import seaborn as sns
warnings.resetwarnings()
_ = sns

# Parse command line arguments:
parser = argparse.ArgumentParser(
    description="""
    Simple tool for exploring biases in transcript counts. Takes as input count files generated by bam_count_reads.py (with the -z flag)
    and performs linear regression of log counts against transcript length and GC content.
    """)
parser.add_argument(
    '-r', metavar='report_pdf', type=str, help="Report PDF (bias_explorer.pdf).", default="bias_explorer.pdf")
parser.add_argument('-x', action="store_true",
                    help="Exclude transcripts with zero counts.", default=False)
parser.add_argument(
    'count_file', metavar='count_file', type=str, help="Input counts file with length ang GC content features.")


if __name__ == '__main__':
    args = parser.parse_args()

    data = pd.read_csv(args.count_file, sep="\t")
    data["logCount"] = np.log(np.array(data["Count"]) + 1.0)

    if args.x:
        data = data[data.Count > 0]

    plotter = report.Report(args.r)

    sns.jointplot("GC_content", "logCount", kind="reg", data=data)
    plotter.plt.tight_layout()
    plotter.pages.savefig()
    plotter.plt.clf()

    sns.jointplot("Length", "logCount", kind="reg", data=data)
    plotter.plt.tight_layout()
    plotter.pages.savefig()
    plotter.plt.clf()

    plotter.close()
