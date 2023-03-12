import argparse
import subprocess
import operator
import time
import os
from meta_transcriptomics_pipeline.helpers import check_fail
from meta_transcriptomics_pipeline.filter_files import filter_files
from meta_transcriptomics_pipeline.get_lineage_info import get_lineage_info

def process_fast_mode_output(kraken_out, outfile, total_reads):
    results = {}
    num_reads = 0
    with open(kraken_out, "r") as f:   
        for line in f:
            curr = line.split()
            taxid = curr[2]
            if taxid == 0:
                taxid == "Unknown"
            if taxid in results.keys():
                results[taxid] += 1
            else:
                results[taxid] = 1

            num_reads += 1

    for key in results.keys():
        results[key] = (results[key]/total_reads) * 100

    sorted_results = dict( sorted(results.items(), key=operator.itemgetter(1),reverse=True))
    wf = open(outfile, "w")

    print(sorted_results)

    for key in sorted_results.keys():
        wf.write(key + "\t" + str(sorted_results[key]) + "\n")
        wf.write(key + "\t" + str(sorted_results[key]) + "\n")

    wf.close()

def preprocessing(args: argparse.Namespace):
    dirpath = args.dirpath

    ##################### FASTP ########################

    generated_files = []

    qc1 = dirpath + "/qc_1.fastq"
    qc2 = dirpath + "/qc_2.fastq"
    generated_files.append(qc1)
    generated_files.append(qc2)

    fastp_path = "fastp"
    fastp_command = fastp_path +\
                    " --in1 " + args.inp1 +\
                    " --in2 " + args.inp2 +\
                    " --out1 " + qc1 +\
                    " --out2 " + qc2 +\
                    " -b 100 -B 100 " +\
                    " --qualified_quality_phred  " + args.qualified_quality_phred +\
                    " --unqualified_percent_limit " + args.unqualified_percent_limit +\
                    " --length_required " + args.length_required +\
                    " --low_complexity_filter " +\
                    " --detect_adapter_for_pe" +\
                    " --thread " + str(args.threads)
                    # need to consider adapters, should we give the user a chance to add adatpers?
                    # -b -B, means we want our reads/pairs to be at most 100 bases

    start = time.time()
    new_command = subprocess.run(fastp_command, shell=True)
    if check_fail(fastp_path, new_command, [qc1, qc2]) is True: return None
    end = time.time()
    print("fastp took: " + str(end - start))

    #################################### STAR HUMAN ###########################

    star_prefix = dirpath + "/star_"

    star_command = "STAR --genomeDir " + args.star_human_index + " --runThreadN " + str(args.threads) +\
                    " --readFilesIn " + qc1 + " " + qc2 + " --outFileNamePrefix " + star_prefix +\
                    " --outFilterMultimapNmax 99999 --outFilterScoreMinOverLread 0.5 --outFilterMatchNminOverLread 0.5" +\
                    " --outFilterMismatchNmax 999 --outSAMtype BAM SortedByCoordinate --outReadsUnmapped Fastx" +\
                    " --outSAMattributes Standard --quantMode TranscriptomeSAM GeneCounts --clip3pNbases 0"
    
    new_command = subprocess.run(star_command, shell=True)
    if check_fail("STAR", new_command, []) is True: return None

    star1 = star_prefix + "Unmapped_1.fastq"
    star2 = star_prefix + "Unmapped_2.fastq"

    os.rename(star_prefix + "Unmapped.out.mate1", star1)
    os.rename(star_prefix + "Unmapped.out.mate2", star2)

    #################################### SNAP HUMAN ###########################
    human_out = dirpath + "/snap_human_out.bam"
    snap_path = 'snap-aligner'
    snap_human_command = snap_path + " paired " + args.snap_human_index + " " + star1 + " " + star2 +\
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

    # using flag 12.
    # this flag means that we want reads where both its first and second pair failed to map
    # therefore, this treats reads pairs where only 1 read maps as human reads
    samtools_human_subtract_command = samtools_path + " fastq  -f 12 -@ " + str(args.threads) +\
                        " -1 " + human_subtract_1 +\
                        " -2 " + human_subtract_2 +\
                        " -s " + human_spare + " " +\
                        human_out

    new_command = subprocess.run(samtools_human_subtract_command, shell=True)
    if check_fail(samtools_path, new_command, []) is True: return None
    generated_files.append(human_subtract_1)
    generated_files.append(human_subtract_2)
    generated_files.append(human_spare)

    #################################### SORTMERNA ############################
    aligned = dirpath + "/aligned"
    noRna = dirpath + "/noRna"
    noRna1 = dirpath + "/noRna_fwd.fq"
    noRna2 = dirpath + "/noRna_rev.fq"
    
    sortmerna_path = 'sortmerna'
    sortmerna_command = sortmerna_path +\
                    " --ref " + args.sortmerna_rrna_database +\
                    " --aligned " + aligned +\
                    " --other " + noRna +\
                    " --fastx " +\
                    " --reads " + human_subtract_1 + " --reads " + human_subtract_2 +\
                    " --threads " + str(args.threads) +\
		            " --out2 TRUE " +\
		            " --paired_in TRUE"

    start = time.time()
    new_command = subprocess.run(sortmerna_command, shell=True)
    if check_fail(sortmerna_path, new_command, []) is True: return None
    end = time.time()
    print("sortmerna took: " + str(end - start))
    #os.remove(aligned + "_fwd.fastq", aligned + ".log", aligned + "_rev.fastq")
    generated_files.append(fullyQc + "_fwd.fastq")
    generated_files.append(fullyQc + "_rev.fastq")

    #################################### CLUMPIFY DEDUP #######################

    fullyQc = dirpath + "/fullyQc"
    fullyQc1 = dirpath + "/fullyQc_fwd.fq"
    fullyQc2 = dirpath + "/fullyQc_rev.fq"

    clumpify_command = "clumpify.sh  in1=" + noRna1 + " in2=" + noRna2 +\
                            " out1=" + fullyQc1 + " out2=" + fullyQc2 + " dedupe=t"
    
    new_command = subprocess.run(clumpify_command, shell=True)
    if check_fail("clumpify.sh", new_command, []) is True: return None

    # QUICK ALIGNMENT, JUST ALIGN REMAINING READS USING KRAKEN AGAINST KRAKEN_PLUS
    '''
    num_reads_bytes = subprocess.run(['grep', '-c', '.*', fullyQc1], stdout=subprocess.PIPE)
    num_reads_str = num_reads_bytes.stdout.decode('utf-8')
    num_reads = int(num_reads_str.replace('\n', ''))/4 # finally in int format, dividing by 4 because its in fastq format
    fast_mode_output = dirpath + "/fast_mode_output"
    kraken_command = "kraken2 --db " + args.kraken_db + " --threads " + str(args.threads) +\
                        " --output " + fast_mode_output + " --paired " + fullyQc1 + " " + fullyQc2
    
    new_command = subprocess.run(kraken_command, shell=True)    
    if check_fail("kraken", new_command, []) is True: return None
    kraken_res_out = dirpath + "/kraken_res_out"
    process_fast_mode_output(fast_mode_output, kraken_res_out, num_reads)
    fastAbundances = dirpath + "/fastAbundances.txt"
    get_lineage_info(kraken_res_out, fastAbundances, args.taxdump_location)
    fastAbundancesKrona = dirpath + "/fastAbundancesKrona.html"
    subprocess.run("ImportText.pl " + fastAbundances + " -o " + fastAbundancesKrona, shell=True)
    '''
    
    #################### MEGAHIT ###########################
    megahit_path = "megahit"
    contig_path = dirpath + "/megahit_out"
    megahit_command = megahit_path + " -1 " + fullyQc1 +\
                        " -2 " + fullyQc2 +\
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
                                " in=" + fullyQc1 +\
                                " in2=" + fullyQc2 +\
                                " -out=" + reads_mapped_to_contigs_file  
    new_command = subprocess.run(align_reads_to_contigs_cmd, shell=True)
    if check_fail(bbwrap_path, new_command, []) is True: return None 

    # now lets retrieve the reads that did not align
    new_fwd = dirpath + "/new_fwd.fq"
    new_rev = dirpath + "/new_rev.fq"

    # same principle here as the human mapping step
    align_command = "samtools fastq -f 12 -1 " + new_fwd +\
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

    # now lets align reads
    # need to merge paired end reads first though
    merged_pe = dirpath + "/merged_reads.fq"
    merge_command = "seqtk mergepe " + new_fwd + " " + new_rev + " > " + merged_pe
    new_command = subprocess.run(merge_command, shell=True)
    if check_fail("seqtk mergepe", new_command, []) is True: return False 

    combined_file = dirpath + "/combined_file.fq"
    subprocess.run("cat " + new_contigs + " > " + combined_file, shell=True)
    subprocess.run("cat " + merged_pe + " >> " + combined_file, shell=True)

    # need to convert above to fasta
    combined_file_fa = dirpath + "/combined_file.fa"
    seqtk_command = seqtk_path + " seq -a " + combined_file + " > " + combined_file_fa
    new_command = subprocess.run(seqtk_command, shell=True)
    if check_fail("seqtk", new_command, []) is True: return False 