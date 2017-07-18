#!/usr/bin/env python3
import argparse
import os
import shutil
import nibabel
from glob import glob
from subprocess import Popen, PIPE
from shutil import rmtree
import subprocess
from warnings import warn


def run(command, env={}, ignore_errors=False):
    merged_env = os.environ
    merged_env.update(env)
    # DEBUG env triggers freesurfer to produce gigabytes of files
    merged_env.pop('DEBUG', None)
    process = Popen(command, stdout=PIPE, stderr=subprocess.STDOUT, shell=True, env=merged_env)
    while True:
        line = process.stdout.readline()
        line = str(line, 'utf-8')[:-1]
        print(line)
        if line == '' and process.poll() != None:
            break
    if process.returncode != 0 and not ignore_errors:
        raise Exception("Non zero return code: %d" % process.returncode)


__version__ = open('/version').read()

parser = argparse.ArgumentParser(description='FreeSurfer recon-all + custom template generation.')
parser.add_argument('bids_dir', help='The directory with the input dataset '
                                     'formatted according to the BIDS standard.')
parser.add_argument('output_dir', help='The directory where the output files '
                                       'should be stored. If you are running group level analysis '
                                       'this folder should be prepopulated with the results of the'
                                       'participant level analysis.')
parser.add_argument('analysis_level', help='Level of the analysis that will be performed. '
                                           'Multiple participant level analyses can be run independently '
                                           '(in parallel) using the same output_dir. ',
                    choices=['participant'])
parser.add_argument('--participant_label', help='The label of the participant that should be analyzed. The label '
                                                'corresponds to sub-<participant_label> from the BIDS spec '
                                                '(so it does not include "sub-"). If this parameter is not '
                                                'provided all subjects should be analyzed. Multiple '
                                                'participants can be specified with a space separated list.',
                    nargs="+")
parser.add_argument('--n_cpus', help='Number of CPUs/cores available to use.',
                    default=1, type=int)
parser.add_argument('--license_key',
                    help='FreeSurfer license key - letters and numbers after "*" in the email you received after registration. To register (for free) visit https://surfer.nmr.mgh.harvard.edu/registration.html',
                    required=True)
parser.add_argument('-v', '--version', action='version',
                    version='BIDS-App example version {}'.format(__version__))

args = parser.parse_args()

subjects_to_analyze = []
# only for a subset of subjects
if args.participant_label:
    subjects_to_analyze = args.participant_label
# for all subjects
else:
    subject_dirs = glob(os.path.join(args.output_dir, "sub-*"))
    subjects_to_analyze = list(set([os.path.basename(subject_dir).split("_")[0].split("-")[-1] for subject_dir in \
                                    subject_dirs]))

# workaround for https://mail.nmr.mgh.harvard.edu/pipermail//freesurfer/2016-July/046538.html
output_dir = os.path.abspath(args.output_dir)

# running participant level
if args.analysis_level == "participant":
    c = glob(os.path.join(output_dir, "*"))
    print("output_dir content: %s" % c)
    if not c:
        raise Exception("output dir empty %s" % output_dir)

    if not os.path.exists(os.path.join(output_dir, "fsaverage")):
        print("try to copy fsaverage folder %s" % output_dir)
        run("cp -rf " + os.path.join(os.environ["SUBJECTS_DIR"], "fsaverage") + " " + os.path.join(output_dir,
                                                                                                   "fsaverage"),
            ignore_errors=False)
    if not os.path.exists(os.path.join(output_dir, "lh.EC_average")):
        run("cp -rf " + os.path.join(os.environ["SUBJECTS_DIR"], "lh.EC_average") + " " + os.path.join(output_dir,
                                                                                                       "lh.EC_average"),
            ignore_errors=False)
    if not os.path.exists(os.path.join(output_dir, "rh.EC_average")):
        run("cp -rf " + os.path.join(os.environ["SUBJECTS_DIR"], "rh.EC_average") + " " + os.path.join(output_dir,
                                                                                                       "rh.EC_average"),
            ignore_errors=False)

    for subject_label in subjects_to_analyze:

        long_subjects = glob(os.path.join(output_dir, "sub-" + subject_label + "*.long.*"))
        long_subjects = [os.path.basename(s) for s in long_subjects]
        timepoints = sorted([l.split(".long.")[0] for l in long_subjects])

        if not timepoints:
            raise Exception("No timepoints found. Something went wrong: %s" % subject_label)
        else:
            print("Timepoints for subject found %s" % subject_label, timepoints)
        good_tps = []
        bad_tps = []

        for tp in timepoints:
            tp_label = tp.split("_")[-1].split("-")[-1]
            surf_dir = os.path.join(output_dir,
                                    "sub-{sub}_ses-{ses}.long.sub-{sub}".format(sub=subject_label, ses=tp_label),
                                    "surf")
            if (os.path.exists(os.path.join(surf_dir, "lh.pial_lgi"))) & (os.path.exists(os.path.join(surf_dir,
                                                                                                      "rh.pial_lgi"))):
                print("lh.pial_lgi and rh.pial_lgi exist for {sub} {tp}. NOT recomputing".format(sub=subject_label,
                                                                                                 tp=tp_label))
            else:
                cmd = "recon-all -long {tp} {base} " \
                      "-sd {output_dir} -localGI -parallel -openmp {n_cpus}".format(tp=tp, base="sub-" + subject_label,
                                                                                    output_dir=output_dir,
                                                                                    n_cpus=args.n_cpus)

                print("\n\n", "*" * 30, "\n", "running long LGI for %s" % tp)

                print(cmd)
                try:
                    run(cmd)

                    img_not_found = []
                    if not os.path.exists(os.path.join(surf_dir, "lh.pial_lgi")):
                        img_not_found.append("lh.pial_lgi")
                    if not os.path.exists(os.path.join(surf_dir, "rh.pial_lgi")):
                        img_not_found.append("rh.pial_lgi")

                    if img_not_found:
                        print("pial_lgi not found after calc for {sub} {tp}: {img}. Try other timpoints and "
                              "raiser Error later.".format(
                            sub=subject_label, tp=tp_label, img=" ".join(img_not_found)))
                        bad_tps.append(tp_label)
                    else:
                        print("pial_lgi and rh.pial_lgi calculated for {sub} {tp}".format(sub=subject_label, tp=tp_label))
                        good_tps.append(tp_label)
                except Exception:
                    print("Something failed with tp %s. Try other timepoints and raise Error later." % tp_label)
                    bad_tps.append(tp_label)

                if good_tps:
                    print("Timpoints succesfully processed for {sub}: {tps}".format(sub=subject_label, tps=" ".join(
                        good_tps)))
                if bad_tps:
                    raise Exception("Timpoints failed for {sub}: {tps}".format(sub=subject_label, tps=" ".join(
                        bad_tps)))
                else:
                    print("Everything seems fine")

