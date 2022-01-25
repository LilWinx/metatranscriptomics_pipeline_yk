from ete3 import NCBITaxa
from getScientificNames import getScientificNames

def get_taxids(input_file):
    taxids = {}
    with open(input_file, "r") as f:
        for line in f:
            curr = line.split()
            taxid = curr[0]
            abundance = curr[1]
            taxids[taxid] = abundance

    return taxids

def get_lineage_info(input_file, output_file, taxids_location):
    taxids = get_taxids(input_file)
    ranks = ['superkingdom', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']
    ncbi = NCBITaxa()
    lst = []
    all_taxids = []

    for taxid in taxids.keys():
        # TODO, NEED A WAY TO DEAL WITH "UNKNOWN"
        if taxid == "Unknown":
            continue
        lineage = ncbi.get_lineage(taxid)
        lineage2ranks = ncbi.get_rank(lineage)
        ranks2lineage = dict((rank, taxid) for (taxid, rank) in lineage2ranks.items())
        sublst = []
        sublst.append(taxid)
        if taxid != "Unknown":
            all_taxids.append(int(taxid))
        for rank in ranks:
            r = ranks2lineage.get(rank, 'Unknown')
            if r != "Unknown":
                #print("RADIO")
                all_taxids.append(int(r))
                #print(all_taxids)
            sublst.append(r)
        
        lst.append(sublst)
    
    sci_names = getScientificNames(all_taxids, taxids_location) 

    wf = open(output_file, "w")
    for minlst in lst:
        inc = 1
        for item in minlst:
            if (inc < len(minlst)):
                wf.write(str(sci_names[str(item)]) + "\t")
            else: 
                wf.write(str(sci_names[str(item)]) + "\n")
            inc += 1

    wf.close()
