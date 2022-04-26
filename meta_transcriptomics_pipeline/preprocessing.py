import argparse
import imp
import subprocess
import os
import operator
import time
import re

def preprocessing(args: argparse.Namespace):
    dirpath = args.dirpath

    ##################### FASTP ########################

    generated_files = []

    out1 = dirpath + "/qc_1.fastq"
    out2 = dirpath + "/qc_2.fastq"
    generated_files.append(out1)
    generated_files.append(out2)

    fastp_path = "fastp"
    fastp_command = fastp_path +\
                    " --in1 " + args.inp1 +\
                    " --in2 " + args.inp2 +\
                    " --out1 " + out1 +\
                    " --out2 " + out2 +\
                    " --qualified_quality_phred  " + args.qualified_quality_phred +\
                    " --unqualified_percent_limit " + args.unqualified_percent_limit +\
                    " --length_required " + args.length_required +\
                    " --detect_adapter_for_pe" +\
                    " --thread " + str(args.threads)
                    # need to consider adapters, should we give the user a chance to add adatpers?

    start = time.time()
    new_command = subprocess.run(fastp_command, shell=True)
    if check_fail(fastp_path, new_command, [out1, out2]) is True: return None
    end = time.time()
    print("fastp took: " + str(end - start))

    #################################### SORTMERNA ############################
    aligned = dirpath + "/aligned"
    other = dirpath + "/other"
    
    sortmerna_path = 'sortmerna'
    sortmerna_command = sortmerna_path +\
                    " --ref " + args.sortmerna_index +\
                    " --aligned " + aligned +\
                    " --other " + other +\
                    " --fastx " +\
                    " --reads " + out1 + " --reads " + out2 +\
                    " --threads " + str(args.threads) +\
		            " --out2 TRUE " +\
		            " --paired_out TRUE" +\
                    " --best 1 " # 1 = all high candidate reference sequences will be searched for alignments

    start = time.time()
    new_command = subprocess.run(sortmerna_command, shell=True)
    if check_fail(sortmerna_path, new_command, [out1, out2, aligned + "_fwd.fastq", aligned + "_rev.fastq",  other + "_fwd.fastq", other + "_rev.fastq"]) is True: return None
    end = time.time()
    print("sortmerna took: " + str(end - start))
    #os.remove(aligned + "_fwd.fastq", aligned + ".log", aligned + "_rev.fastq")
    generated_files.append(other + "_fwd.fastq")
    generated_files.append(other + "_rev.fastq")

    ############################# SNAP HUMAN #############################
    human_out = dirpath + "/snap_human_out.sam"
    snap_path = 'snap-aligner'
    snap_human_command = snap_path + " paired " + args.snap_human_index + " " + other + "_fwd.fastq " + other + "_rev.fastq " +\
                    " -o " + human_out + " -t " + str(args.threads) + " -I "
    start = time.time()
    new_command = subprocess.run(snap_human_command, shell=True)
    if check_fail(snap_path, new_command, [generated_files]) is True: return None
    end = time.time()
    print("human subtraction via snap took: " + str(end - start))

    human_subtract_1 = dirpath + "/human_subtract1.fastq"
    human_subtract_2 = dirpath + "/human_subtract2.fastq"
    human_spare = dirpath + "/human_spare.fastq"

    # retrieving only human reads
    samtools_path = "samtools"
    samtools_human_subtract_command = samtools_path + " fastq  -f 4 -@ " + str(args.threads) +\
                        " -1 " + human_subtract_1 +\
                        " -2 " + human_subtract_2 +\
                        " -s " + human_spare + " " +\
                        human_out

    new_command = subprocess.run(samtools_human_subtract_command, shell=True)
    if check_fail(samtools_path, new_command, []) is True: return None
    generated_files.append(human_subtract_1 + ".fastq")
    generated_files.append(human_subtract_2 + ".fastq")
    generated_files.append(human_spare + ".fastq")

    # QUICK ALIGNMENT, JUST ALIGN REMAINING READS USING KRAKEN AGAINST KRAKEN_PLUS
    num_reads_bytes = subprocess.run(['grep', '-c', '.*', human_subtract_1], capture_output=True)
    num_reads_str = num_reads_bytes.stdout.decode('utf-8')
    num_reads = int(num_reads_str.replace('\n', ''))/4 # finally in int format, dividing by 4 because its in fastq format
    fast_mode_output = dirpath + "/fast_mode_output"
    kraken_command = "kraken2 --db " + args.kraken_db + " --threads " + str(args.threads) +\
                        " --output " + fast_mode_output + " --paired " + human_subtract_1 + " " + human_subtract_2
    
    new_command = subprocess.run(kraken_command, shell=True)    
    if check_fail("kraken", new_command, []) is True: return None
    kraken_res_out = dirpath + "/kraken_res_out"
    process_fast_mode_output(fast_mode_output, kraken_res_out, num_reads)
    fastAbundances = dirpath + "/fastAbundances.txt"
    get_lineage_info(kraken_res_out, fastAbundances, args.taxdump_location)
    fastAbundancesKrona = dirpath + "/fastAbundancesKrona.html"
    subprocess.run("ImportText.pl " + fastAbundances + " -o " + fastAbundancesKrona, shell=True)

    #################### MEGAHIT ###########################
    megahit_path = "megahit"
    contig_path = dirpath + "/megahit_out"
    megahit_command = megahit_path + " -1 " + human_subtract_1 +\
                        " -2 " + human_subtract_2 +\
                        " -o " + contig_path + " -t " + str(args.threads) # is an output directory 
    contigs = contig_path + "/final_contigs.fa"
    start = time.time()
    new_command = subprocess.run(megahit_command, shell=True)
    if check_fail(megahit_path, new_command, []) is True: return None
    end = time.time()
    print("assembly via megahit took: " + str(end - start))
    new_command = subprocess.run("mv " + contig_path + "/final.contigs.fa " + contigs, shell=True)

    # we must retrieve the unaligned reads
    bbwrap_path = "bbwrap.sh"
    reads_mapped_to_contigs_file = dirpath + "/reads_mapped_to_contigs.sam"
    align_reads_to_contigs_cmd = bbwrap_path + " ref=" + contigs +\
                                " in=" + human_subtract_1 +\
                                " in2=" + human_subtract_2 +\
                                " -out=" + reads_mapped_to_contigs_file  
    new_command = subprocess.run(align_reads_to_contigs_cmd, shell=True)
    if check_fail(bbwrap_path, new_command, []) is True: return None 

    # now lets retrieve the reads that did not align
    new_fwd = dirpath + "/new_fwd.fq"
    new_rev = dirpath + "/new_rev.fq"

    align_command = "samtools fastq -f4 -1 " + new_fwd +\
                    " -2 " + new_rev + " " + reads_mapped_to_contigs_file
    new_command = subprocess.run(align_command, shell=True)
    if check_fail(samtools_path, new_command, []) is True: return None 

    print("DONE")

    smaller_1 = dirpath + "/smaller_1.fq"
    smaller_2 = dirpath + "/smaller_2.fq"
    bigger_1 = dirpath + "/bigger_1.fq"
    bigger_2 = dirpath + "/bigger_2.fq"

    filter_files(new_fwd, bigger_1, smaller_1)
    filter_files(new_rev, bigger_2, smaller_2)

    # need to convert file above from fa to fq, simply done using seqtk
    seqtk_path = "seqtk"
    new_contigs = contig_path + "/final_contigs.fq"
    seqtk_command = seqtk_path + " seq -F '#' " + contigs + " > " + new_contigs
    new_command = subprocess.run(seqtk_command, shell=True)
    if check_fail(seqtk_path, new_command, []) is True: return None

    nt_combined_file = dirpath + "/nt_combined_file"