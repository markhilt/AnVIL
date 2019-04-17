import numpy as np
import pysam
from scipy.stats import t
import mappy as mp
import ipdb


# Included modules
import nuclseqTools as nt
import graph_building as gb
import mappy_alignment_tools as mat
import misc

def writePaths(outfilename, scaffolds):
    '''
    Writes the usable paths from the graph
    '''
    with open(outfilename+".paths.txt", "w") as pathsout:
        for k,v in scaffolds.items():
            pathsout.write("{}\t{}\n".format(k,v))

def countReads(contig,coords_to_check):
    '''
    To count the number of reads aligned to a region
    '''
    cov_arr = samfile.count_coverage(contig, coords_to_check[0],coords_to_check[1])
    cov = sum([sum(cov_arr[x]) for x in range(0,4,1)]) / 50
    return cov

def trimFasta(contig_side_to_trim):
    '''
    Given a fasta entry with side to trim, returns new start and end coordinates
    Input format: "tigs" or "tige"
    '''

    tig = contig_side_to_trim[:-1]
    side = contig_side_to_trim[-1]
    coords_at_a_time = 30
    mincov = 5

    if tig in fastafile.references:
        cov = 0
        coords_to_trim = 0

        if side == "s":
            coords_to_check = [0,coords_at_a_time]
            cov = countReads(tig,coords_to_check)

            while cov < mincov:
                coords_to_trim += coords_at_a_time # Update with new end coordinate
                coords_to_check = [x+coords_at_a_time for x in coords_to_check] # And move to next 10 coordinates
                cov = countReads(tig,coords_to_check)


        elif side == "e":
            stop = trimmed_fasta_coords[tig][1]
            coords_to_check = [stop-coords_at_a_time,stop]
            cov = countReads(tig,coords_to_check)

            while cov <= mincov:
                coords_to_trim = coords_to_trim - coords_at_a_time    # Update with new end coordinate
                coords_to_check = [x-coords_at_a_time for x in coords_to_check] # And move to next 10 coordinates
                cov = countReads(tig,coords_to_check)

    return (coords_to_trim)

def findBestAlignment(left_alignments, right_alignments):
    '''
    Given two lists of overlaps, returns the one that gives the shortest
    common superstring.
    '''
    # Start by picking any two alignments in the same orientation
    best = (left_alignments[0], [a for a in right_alignments if a.strand == left_alignments[0].strand][0])

    # Test every combination and return the one with the longest total
    # aligned length
    for l_aln in left_alignments:
        left_len = l_aln.mlen
        left_ori = l_aln.strand
        for r_aln in right_alignments:

            # Now we're only interested in alignments where middle contig
            # is in the same orientation as in the left alignment
            right_ori = r_aln.strand
            if right_ori == left_ori:

                # Test aligned length
                best_len = best[0].mlen + best[1].mlen
                current_len = l_aln.mlen + r_aln.mlen
                if current_len > best_len:
                    best = (l_aln, r_aln)

    return best

def orientByAlignment(left, middle, right):
    '''
    If orientation of a contig is unknown, i.e. edges connect both of its nodes
    in the linkgraph, try to find overlaps between the contig and its
    surrounding contigs.
    '''

    left_tig, left_dir = left[:-1], left[-1]
    middle_tig = middle[:-1] # Our goal here is to find middle_dir
    right_tig, right_dir = right[:-1], right[-1]

    if left_tig not in fastafile.references \
    or middle_tig not in fastafile.references \
    or right_tig not in fastafile.references:
        raise Exception("Linkgraph error: node not in graph")

    # First collect sequences
    left_seq = fastafile.fetch(reference=left_tig)
    middle_seq = fastafile.fetch(reference=middle_tig)
    right_seq = fastafile.fetch(reference=right_tig)

    # Fix orientation so we can look for the overlap between left_tig end,
    # middle_tig and right_tig start
    if left_dir == "r":
        left_seq = nt.reverse_complement(left_seq)
    if right_dir == "r":
        right_seq = nt.reverse_complement(right_seq)

    # Use mappy to find the best overlap between the three
    # First write the left and right sequences to a temp fasta on disk
    # and create an index from this
    with open("tmp.fasta", "w") as tmp:
        tmp.write(">{}\n".format(left_tig))
        tmp.write(left_seq)
        tmp.write("\n")
        tmp.write(">{}\n".format(right_tig))
        tmp.write(right_seq)

    idx = mp.Aligner(fn_idx_in="tmp.fasta", preset="asm5")

    # Align
    alignments = idx.map(middle_seq)
    left_aln_keep = [] # Left alignments to keep
    right_aln_keep = [] # Right alignments to keep

    # Iterate over alignments and search for overlapping ends
    if alignments:
        for aln in alignments:

            # Filter for alignments ending within the last 1 kb of left_tig
            if aln.ctg == left_tig \
            and aln.r_en > aln.ctg_len - 1000:

                # Then check if alignment is at the beginning or end of
                # middle_tig
                # Keep either way. Alignments not at the ends of middle
                # contig are discarded.
                if aln.q_st < 1000 or aln.q_en > len(middle_seq) - 1000:
                    left_aln_keep.append(aln)

            # Do same for right alignments
            if aln.ctg == right_tig \
            and aln.r_st < 1000:
                if aln.q_st < 1000 or aln.q_en > len(middle_seq) - 1000:
                    right_aln_keep.append(aln)

    # If alignments were found to both surrounding contigs
    if len(right_aln_keep) > 0 and len(left_aln_keep) > 0:
        best_alignment = findBestAlignment(left_aln_keep, right_aln_keep)
        if best_alignment[0].strand == -1:
            return middle_tig + "r"
        elif best_alignment[0].strand == 1:
            return middle_tig + "f"

    # If only one side has an overlap, use this to orient
    elif len(right_aln_keep) > 0 and len(left_aln_keep) == 0:

        # Choose the longest alignment as there might be alignments
        # to both sides of the middle contig
        best = right_aln_keep[0]
        for r in right_aln_keep:
            if r.mlen > best.mlen:
                best = r
        if best.strand == -1:
            return middle_tig + "r"
        elif best.strand == 1:
            return middle_tig + "f"

    # Do same for other side
    elif len(left_aln_keep) > 0 and len(right_aln_keep) == 0:
        best = left_aln_keep[0]
        for r in left_aln_keep:
            if r.mlen > best.mlen:
                best = r
        if best.strand == -1:
            return middle_tig + "r"
        elif best.strand == 1:
            return middle_tig + "f"

    # If no overlaps were found, return unknown orientation
    return middle_tig + "u"

# For now keep separate methods for orientation by alignment of first
# or last contig in a list
def orientByAlignmentFirst(first, right):
    first_tig = first[:-1] # Our goal here is to find first_dir
    right_tig, right_dir = right[:-1], right[-1]

    if first_tig not in fastafile.references \
    or right_tig not in fastafile.references:
        raise Exception("Linkgraph error: node not in graph")

    # First collect sequences
    first_seq = fastafile.fetch(reference=first_tig)
    right_seq = fastafile.fetch(reference=right_tig)

    # Fix orientation so we can look for the overlap between left_tig end,
    # middle_tig and right_tig start
    if right_dir == "r":
        right_seq = nt.reverse_complement(right_seq)

    # Use mappy to find the best overlap between the three
    # First write the left and right sequences to a temp fasta on disk
    # and create an index from this
    with open("tmp.fasta", "w") as tmp:
        tmp.write(">{}\n".format(right_tig))
        tmp.write(right_seq)

    idx = mp.Aligner(fn_idx_in="tmp.fasta", preset="asm5")

    # Align
    alignments = idx.map(first_seq)
    right_aln_keep = [] # Right alignments to keep

    # Iterate over alignments and search for overlapping ends
    if alignments:
        for aln in alignments:
            if aln.ctg == right_tig \
            and aln.r_st < 1000:
                if aln.q_st < 1000 or aln.q_en > len(first_seq) - 1000:
                    right_aln_keep.append(aln)

    # If only one side has an overlap, use this to orient
    elif len(right_aln_keep) > 0:

        # Choose the longest alignment as there might be alignments
        # to both sides of the middle contig
        best = right_aln_keep[0]
        for r in right_aln_keep:
            if r.mlen > best.mlen:
                best = r
        if best.strand == -1:
            return first_tig + "r"
        elif best.strand == 1:
            return first_tig + "f"

    # If no overlaps were found, return unknown orientation
    return first_tig + "u"


def orientByAlignmentLast(left, last):

    left_tig, left_dir = left[:-1], left[-1]
    last_tig = last[:-1] # Our goal here is to find last_dir

    if left_tig not in fastafile.references \
    or last_tig not in fastafile.references:
        raise Exception("Linkgraph error: node not in graph")

    # First collect sequences
    left_seq = fastafile.fetch(reference=left_tig)
    last_seq = fastafile.fetch(reference=last_tig)

    # Fix orientation so we can look for the overlap between left_tig end,
    # middle_tig and right_tig start
    if left_dir == "r":
        left_seq = nt.reverse_complement(left_seq)

    # Use mappy to find the best overlap between the three
    # First write the left and right sequences to a temp fasta on disk
    # and create an index from this
    with open("tmp.fasta", "w") as tmp:
        tmp.write(">{}\n".format(left_tig))
        tmp.write(left_seq)

    idx = mp.Aligner(fn_idx_in="tmp.fasta", preset="asm5")

    # Align
    alignments = idx.map(last_seq)
    left_aln_keep = [] # Left alignments to keep

    # Iterate over alignments and search for overlapping ends
    if alignments:
        for aln in alignments:

            # Filter for alignments ending within the last 1 kb of left_tig
            if aln.ctg == left_tig \
            and aln.r_en > aln.ctg_len - 1000:

                # Then check if alignment is at the beginning or end of
                # middle_tig
                # Keep either way. Alignments not at the ends of middle
                # contig are discarded.
                if aln.q_st < 1000 or aln.q_en > len(last_seq) - 1000:
                    left_aln_keep.append(aln)

    # If only one side has an overlap, use this to orient
    elif len(left_aln_keep) > 0:
        best = left_aln_keep[0]
        for r in left_aln_keep:
            if r.mlen > best.mlen:
                best = r
        if best.strand == -1:
            return last_tig + "r"
        elif best.strand == 1:
            return last_tig + "f"

    # If no overlaps were found, return unknown orientation
    return last_tig + "u"

def orient_scaffolds(scaffolds):
    '''
    Given a dict of scaffolds where some included conigs may be in "u"
    orientation, tries to orient these contigs, breaks the scaffolds if
    impossible, and returns scaffolds without u's.
    '''
    # Check if there is a contig of undetermined orientation.
    # In that case, try to find the orientation.
    scaffold_orientation = dict(scaffolds) # New dict to loop through as we need to mutate
    n_oriented = 0
    for linked_tig_ID,tig_list in scaffolds.items():
        for idx, tig in enumerate(tig_list):
            if tig[-1] == "u":
                #ipdb.set_trace()
                if tig == tig_list[0]:
                    oriented_tig = orientByAlignmentFirst(  tig_list[idx], \
                                                            tig_list[idx+1])
                elif tig == tig_list[-1]:
                    oriented_tig = orientByAlignmentLast(   tig_list[idx-1], \
                                                            tig_list[idx])
                else:
                    oriented_tig = orientByAlignment(   tig_list[idx-1], \
                                                        tig_list[idx], \
                                                        tig_list[idx+1])
                new_tig_list = scaffold_orientation[linked_tig_ID]
                new_tig_list[idx] = oriented_tig
                scaffold_orientation[linked_tig_ID] = new_tig_list
                if oriented_tig[-1] == "f" or oriented_tig[-1] == "r":
                    n_oriented += 1

    misc.printstatus("Tigs oriented by alignment: {}".format(str(n_oriented)))

    # Then do another passthrough where paths are broken at remaining u's
    final_scaffolds = {}
    nr = 1
    for linked_tig_ID,tig_list in scaffold_orientation.items():
        breakpos = [] # Collect indices where tig_list should be broken

        for idx, tig in enumerate(tig_list):
            if tig[-1] == "u":
                breakpos.append(idx)

        if len(breakpos) > 0:
            start = 0 # If more than one contig with u, we need to change start
            for p in breakpos:

                # Current path will end at current index with the same ID
                final_scaffolds["scaffold_"+str(nr)] = tig_list[start:p]
                nr += 1

                # Then add new path for the middle contig
                final_scaffolds["scaffold_"+str(nr)] = [tig_list[p][:-1]+"f"]
                nr += 1

                # Change start position
                start = p+1

            # When no more positions to break at, add remainder of tig_list
            final_scaffolds["scaffold_"+str(nr)] = tig_list[start:]
            nr += 1

        else:
            final_scaffolds["scaffold_"+str(nr)] = tig_list
            nr += 1

    return final_scaffolds


def buildLinkedScaffolds(scaffolds_to_merge):
    '''
    Last step of the pipeline is to merge the sequences in a given fasta file
    into the new scaffolds that were determined previously.
    '''
    # Next trim fasta sequences to be merged in low coverage regions
    # trimmed_fasta_coords is a dict with coords to keep from original fasta
    # Format: {contig: [start_coord, end_coord]}
    # Start by filling with old coords, which will then be changed
    global trimmed_fasta_coords
    trimmed_fasta_coords = {}
    for i in range(len(fastafile.references)):
        trimmed_fasta_coords[fastafile.references[i]] = [0, fastafile.lengths[i]]

    #ipdb.set_trace()
    # Then find new coordinates for all sequences to merge
    misc.printstatus("Trimming contig ends...")

    for edge in scaffolds_to_merge.values():
        if len(edge) > 1:
            for i in edge:
                tig = i[:-1]
                # Trim only sides where links are formed
                # If direction of node is unknown (last character in string == "u"),
                # trim both sides

                # If first connected node in forward orientation, trim last coordinate
                if i == edge[0] and i[-1] == "f":
                    trimmed_fasta_coords[tig] = [trimmed_fasta_coords[tig][0], \
                                                trimmed_fasta_coords[tig][1] + \
                                                trimFasta(tig+"e")]

                # If first connected node in reverse orientation, trim first coordinate
                elif i == edge[0] and i[-1] == "r":
                    trimmed_fasta_coords[tig] = [trimmed_fasta_coords[tig][0] + \
                                                trimFasta(tig+"s"), \
                                                trimmed_fasta_coords[tig][1]]

                # If last connected node in forward orientation, trim first coordinate
                elif i == edge[-1] and i[-1] == "f":
                    trimmed_fasta_coords[tig] = [trimmed_fasta_coords[tig][0] + \
                                                trimFasta(tig+"s"), \
                                                trimmed_fasta_coords[tig][1]]

                # If last connected node in reverse orientation, trim last coordinate
                elif i == edge[-1] and i[-1] == "r":
                    trimmed_fasta_coords[tig] = [trimmed_fasta_coords[tig][0], \
                                                trimmed_fasta_coords[tig][1] + \
                                                trimFasta(tig+"e")]

                # If node is connected at both sides or orientation is unknown, trim both sides
                else:
                    trimmed_fasta_coords[tig] = [trimmed_fasta_coords[tig][0] + \
                                                trimFasta(tig+"s"), \
                                                trimmed_fasta_coords[tig][1] + \
                                                trimFasta(tig+"e")]

    # Then walk through the linked_contigs dict, gradually building each contig from left to right.
    # Sequences to be merged are saved in merged_seqs in the format
    # {new_linked_contig_ID: "ATCG..." }
    merged_seqs = {}
    bed = {} # Collect coords to write bed.

    misc.printstatus("Building linked contigs.")

    # TODO write scaffolds and contigs seperately

    number_of_links = 0
    for key, value in scaffolds_to_merge.items():
        number_of_links += len(value)-1

    misc.printstatus("Number of links: {}".format(number_of_links))

    merges = 0
    gaps = 0

    for linked_tig_ID,tig_list in scaffolds_to_merge.items():
        # Go through every linked contig in the dict to align and merge the sequences
        # contained in the values

        newseq = []
        merged_coords = [] # Collect coords to write bed. Will be a list of tuples containing feature and its' length

        # If only one tig in the list, transfer it directly from input
        # fasta
        #ipdb.set_trace()
        if len(tig_list) == 1:
            merged_seqs[linked_tig_ID] = fastafile.fetch(reference=tig_list[0][:-1])
        else:
            starting_tig = None
            for next_tig in tig_list:

                # If starting_tig was not created before, i.e. if starting
                # from the first contig, assign these variables
                if starting_tig == None:
                    # Collect first contig
                    starting_tig = next_tig
                    # Collect name and direction of first contig
                    refname, refdirection = starting_tig[:-1], starting_tig[-1]

                    # And sequence
                    ref_fasta = fastafile.fetch(reference=refname, \
                                                start=trimmed_fasta_coords[refname][0], \
                                                end=trimmed_fasta_coords[refname][1])

                    # Reverse complement if necessary
                    if refdirection == "r":
                        ref_fasta = nt.reverse_complement(ref_fasta)

                # If tig_started == True, i.e. this is the second or more run through the loop,
                # there is already a starting point, i.e. newref.
                # Keep aligning and merging linked contigs to this one.
                # Reference is then the last contig visited in the iteration and query the current
                else:
                    # This path is taken when two sequences are to be aligned

                    # Collect next tig to be merged into the linked contig
                    queryname, querydirection = next_tig[:-1], next_tig[-1]
                    query_fasta = fastafile.fetch(  reference=queryname, \
                                                    start=trimmed_fasta_coords[queryname][0], \
                                                    end=trimmed_fasta_coords[queryname][1])

                    # Reverse complement if necessary
                    if querydirection == "r":
                        query_fasta = nt.reverse_complement(query_fasta)

                    # Align trimmed contig sequences using mappy
                    alignment = mat.findOverlap(ref_fasta,query_fasta)

                    # If the expected alignment was found, create the "consensus"
                    if alignment != None:
                        cons = mat.createConsensus(alignment,ref_fasta,query_fasta)

                        # To save some computing, only align to the last 100kb
                        # during the next round, unless we're at the last contig
                        # and there is no next round
                        if next_tig != tig_list[-1]:
                            ref_fasta = cons[-100000:]
                            newseq.append(cons[:-100000])

                        # In which case we append the whole sequence
                        else:
                            newseq.append(cons)
                        merges += 1

                    # If the correct alignment was not found, instead create scaffold by inserting 10*N:
                    else:
                        newseq.append(ref_fasta)
                        newseq.append("NNNNNNNNNN")

                        if next_tig != tig_list[-1]:
                            ref_fasta = query_fasta
                        else:
                            newseq.append(query_fasta)
                        gaps += 1

            # After merging every contig into the linked scaffold,
            # join the newseq list and add to the dict merged_seqs
            merged_seqs[linked_tig_ID] = ''.join(newseq)

    misc.printstatus("Number of aligned merges: {}".format(str(merges)))
    misc.printstatus("Number of gaps introduced: {}".format(str(gaps)))
    return merged_seqs

def main(input_fasta, input_bam, scaffolds):
    '''
    Controller for merge_fasta
    '''

    global fastafile
    global samfile
    fastafile = pysam.FastaFile(input_fasta)
    samfile = pysam.AlignmentFile(input_bam, "rb")

    # First try to find orientation of any u's
    oriented_scaffolds = orient_scaffolds(scaffolds)

    # Then merge final scaffolds
    linked_scaffolds = buildLinkedScaffolds(oriented_scaffolds)

    return linked_scaffolds, oriented_scaffolds
