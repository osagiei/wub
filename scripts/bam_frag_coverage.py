#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function
import six
import argparse
import tqdm
import os
import numpy as np
import pandas as pd
from collections import OrderedDict
from Bio import SeqIO
from wub.util import misc
from wub.util import parse as parse_util
from wub.vis import report
from wub.bam import stats as bam_stats

import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import seaborn as sns
warnings.resetwarnings()
_ = sns

# Parse command line arguments:
parser = argparse.ArgumentParser(
    description="""Produce aggregated and individual plots of fragment coverage.""")
parser.add_argument(
    '-f', metavar='reference', type=str, help="Reference fasta.", required=True)
parser.add_argument(
    '-c', metavar='region', type=str, help="BAM region (None).", required=False, default=None)
parser.add_argument(
    '-i', metavar='intervals', type=str, help="Length intervals ("").", required=False, default="")
parser.add_argument(
    '-b', metavar='bins', type=int, help="Number of bins (None = auto).", required=False, default=None)
parser.add_argument(
    '-x', action="store_true", help="Plot per-reference information.", default=False)
parser.add_argument(
    '-o', action="store_true", help="Do not take log of coverage.", default=False)
parser.add_argument(
    '-t', metavar='bam_tag', type=str, default=None, help="Dataset tag (BAM basename).", required=False)
parser.add_argument(
    '-q', metavar='aqual', type=int, default=0, help="Minimum alignment quality (0).")
parser.add_argument(
    '-l', metavar='cov80_tsv', type=str, help="Tab separated file with per-chromosome cov80 scores (None). Requires the -x option to be specified.", default=None)
parser.add_argument(
    '-g', metavar='glob_cov80_tsv', type=str, help="Tab separated file with global cov80 score (None).", default=None)
parser.add_argument(
    '-r', metavar='report_pdf', type=str, help="Report PDF (bam_frag_coverage.pdf).", default="bam_frag_coverage.pdf")
parser.add_argument(
    '-p', metavar='results_pickle', type=str, help="Save pickled results in this file (None).", default=None)
parser.add_argument(
    '-Q', action="store_true", help="Be quiet and do not show progress bars.", default=False)
parser.add_argument(
    'bam', metavar='bam', type=str, help="Input BAM file.")


def _set_properties_and_close(plotter, fig, title, xlab, ylab):
    """Utility method to set title, axis labels and close the figure.
    """
    plotter.plt.xlabel(xlab)
    plotter.plt.ylabel(ylab)
    plotter.plt.title(title)
    plotter.plt.legend(loc='best')
    plotter.pages.savefig(fig)
    plotter.plt.close(fig)


def _process_ref_coverage(plotter, cov, strand, scale_pos, scale_cov):
    """ Scale reference position and coverage. """
    x = np.arange(len(cov), dtype=float)
    if scale_pos:
        x = x / len(x)
    y = cov.astype(float)
    if scale_cov:
        y = y / np.sum(y)
    if strand == 'rev':
        pass
    return x, y


def _calculate_coverage_score(data, percent=80):
    """ Calculate fragment coverage score. """
    percent = float(percent) / 100
    return float(len(data[data > percent])) / len(data)


def _plot_frag_coverage(st, chroms, plotter, scale_pos=True, scale_cov=False, title="", bins=None, log_scale=True, hist_title=""):
    """ Plot fragment coverage over a reference. """
    fig = plotter.plt.figure()

    # Use average length as number of bins:
    if bins is None:
        bins = int(np.mean(list(chroms.values())))

    # Generate positions and scale:
    X = np.arange(bins, dtype=float)
    x = X / len(X)

    cov_fwd = np.zeros((bins), dtype=float)
    cov_rev = np.zeros((bins), dtype=float)
    ref_cov = []

    # Acumulate position-scaled coverage in coverage vectors:
    for chrom in chroms.keys():
        ref_cov.extend(st['ref_cov'][chrom])
        if chrom in st['frags_fwd']:
            fx, fy = _process_ref_coverage(
                plotter, cov=st['frags_fwd'][chrom], strand='fwd', scale_pos=scale_pos, scale_cov=scale_cov)
            cov_fwd += np.interp(x, fx, fy)
        if chrom in st['frags_rev']:
            rx, ry = _process_ref_coverage(
                plotter, cov=st['frags_rev'][chrom], strand='rev', scale_pos=scale_pos, scale_cov=scale_cov)
            cov_rev += np.interp(x, rx, ry)
    plot_fwd, plot_rev = cov_fwd, cov_rev
    if (np.sum(cov_fwd) + np.sum(cov_rev)) == 0:
        return {'global_cov_fwd': None, 'global_cov_rev': None, 'ref_cov': None}

    # Perform log transform of coverage:
    if log_scale:
        plot_fwd = np.log(plot_fwd + 1.0)
        plot_rev = np.log(plot_rev + 1.0)

    lwd = 0.8
    plotter.plt.plot(X, plot_fwd, '-', label='+', linewidth=lwd)
    plotter.plt.plot(X, plot_rev, '-', label='-', linewidth=lwd)

    ylab = "Fragment coverage"
    if log_scale:
        ylab = "log(" + ylab + "+1)"

    _set_properties_and_close(
        plotter, fig, title=title, xlab="Scaled position", ylab=ylab)

    # Plot reference coverage histogram:
    ref_cov = np.array(ref_cov, dtype=float)
    cov80_score = _calculate_coverage_score(ref_cov)
    plotter.plot_histograms({'dummy': ref_cov}, title="{} cov80={:.4f}".format(hist_title, cov80_score),
                            xlab="Reference coverage", ylab="Count", bins=100, legend=False)

    return {'global_cov_fwd': cov_fwd, 'global_cov_rev': cov_rev, 'ref_cov': ref_cov, 'cov80': cov80_score}


if __name__ == '__main__':
    args = parser.parse_args()
    verbose = not args.Q
    tag = args.t
    if tag is None:
        tag = os.path.basename(args.bam)

    plotter = report.Report(args.r)

    # Parse length intervals:
    intervals = parse_util.interval_string_to_tuples(args.i)

    # Laod reference lengths:
    references = SeqIO.index(args.f, format='fasta')
    chrom_lengths = {name: len(so) for name, so in six.iteritems(references)}

    # Parse fragments:
    st = bam_stats.frag_coverage(
        args.bam, chrom_lengths, args.c, args.q, verbose=verbose, ref_cov=True)

    res = {'chrom_covs': {}, 'tag': tag}

    # Plot global coverage:
    res['global_cov'] = _plot_frag_coverage(
        st, chrom_lengths, plotter, title="Global fragment coverage for {}".format(tag), hist_title="Global reference coverage for {}".format(tag), log_scale=not args.o, bins=args.b)

    # Plot coverage in intervals:
    for interval in intervals:
        # Filter transcripts falling in the specified
        # length interval:
        int_chroms = {}
        for ref, length in six.iteritems(chrom_lengths):
            if length < interval[0]:
                continue
            if interval[1] != 0 and length > interval[1]:
                continue
            int_chroms[ref] = length
        # Generate coverage plot:
        _plot_frag_coverage(
            st, int_chroms, plotter, title="Coverage in interval [{},{}) for {} ".format(interval[0], interval[1], tag), hist_title="Reference coverage in interval [{},{}) for {}".format(interval[0], interval[1], tag), log_scale=not args.o, bins=args.b)

    def _get_coverage(chrom, st):
        """ Utility function for sorting references by coverage. """
        cov = 0
        if chrom in st['frags_fwd']:
            cov += np.sum(st['frags_fwd'][chrom])
        if chrom in st['frags_rev']:
            cov += np.sum(st['frags_rev'][chrom])
        return cov

    if args.x:
        # Sort references by coverage (code could be nicer):
        sorted_chroms = OrderedDict()
        tmp = sorted(chrom_lengths.keys(),
                     key=lambda x: _get_coverage(x, st), reverse=True)
        for x in tmp:
            sorted_chroms[x] = chrom_lengths[x]
        chrom_lengths = sorted_chroms

        tr_iter = six.iteritems(chrom_lengths)
        if verbose:
            print('Plotting per-chromosome coverage:')
            tr_iter = tqdm.tqdm(tr_iter, total=len(chrom_lengths))

        # Plot per-reference coverage vectors.
        for chrom, length in tr_iter:
            res['chrom_covs'][chrom] = _plot_frag_coverage(
                st, {chrom: length}, plotter, title="Fragment coverage for {}:{}".format(tag, chrom), hist_title="Reference coverage for {}:{}".format(tag, chrom), log_scale=not args.o)

    plotter.close()

    # Dump results of parsing into output pickle:
    if args.p is not None:
        misc.pickle_dump(res, args.p)

    # Gather per-chromosome coverage scores:
    if args.l is not None:
        trs, cov80 = [], []
        for tr, r in res['chrom_covs'].items():
            trs.append(tr)
            if 'cov80' in r:
                cov80.append(r['cov80'])
            else:
                cov80.append(0.0)
        df = pd.DataFrame(OrderedDict([('Reference', trs), ('Cov80', cov80)]))
        df.to_csv(args.l, sep="\t", index=False)
    # Save global cov80 score:
    if args.g is not None:
        df = pd.DataFrame({'GlobalCov80': [res['global_cov']['cov80']]})
        df.to_csv(args.g, sep="\t", index=False)
