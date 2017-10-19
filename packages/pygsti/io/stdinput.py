from __future__ import division, print_function, absolute_import, unicode_literals
#*****************************************************************
#    pyGSTi 0.9:  Copyright 2015 Sandia Corporation
#    This Software is released under the GPL license detailed
#    in the file "license.txt" in the top-level pyGSTi directory
#*****************************************************************
import re

""" Text-parsering classes and functions to read input files."""

import os as _os
import sys as _sys
import time as _time
import numpy as _np
import warnings as _warnings
from scipy.linalg import expm as _expm
from collections import OrderedDict as _OrderedDict

from .. import objects as _objs
from .. import tools as _tools

from .gstplyparser import GateStringParser


def get_display_progress_fn(showProgress):
    
    def is_interactive():
        import __main__ as main
        return not hasattr(main, '__file__')

    if is_interactive() and showProgress:
        try:
            from IPython.display import clear_output
            def display_progress(i,N,filename):
                _time.sleep(0.001); clear_output()
                print("Loading %s: %.0f%%" % (filename, 100.0*float(i)/float(N)))
                _sys.stdout.flush()
        except:
            def display_progress(i,N,f): pass
    else:
        def display_progress(i,N,f): pass
        
    return display_progress


class StdInputParser(object):
    """
    Encapsulates a text parser for reading GST input files.
    """

    #  Using a single parser. This speeds up parsing, however, it means the parser is NOT reentrant
    _string_parser = GateStringParser()

    def __init__(self):
        pass

    def parse_gatestring(self, s, lookup={}):
        """
        Parse a gate string (string in grammar)

        Parameters
        ----------
        s : string
            The string to parse.

        lookup : dict, optional
            A dictionary with keys == reflbls and values == tuples of gate labels
            which can be used for substitutions using the S<reflbl> syntax.

        Returns
        -------
        tuple of gate labels
            Representing the gate string.
        """
        self._string_parser.lookup = lookup
        gate_tuple = self._string_parser.parse(s)
        # print "DB: result = ",result
        # print "DB: stack = ",self.exprStack
        return gate_tuple

    def parse_dataline(self, s, lookup={}, expectedCounts=-1):
        """
        Parse a data line (dataline in grammar)

        Parameters
        ----------
        s : string
            The string to parse.

        lookup : dict, optional
            A dictionary with keys == reflbls and values == tuples of gate labels
            which can be used for substitutions using the S<reflbl> syntax.

        expectedCounts : int, optional
            The expected number of counts to accompany the gate string on this
            data line.  If < 0, no check is performed; otherwise raises ValueError
            if the number of counts does not equal expectedCounts.

        Returns
        -------
        gateStringTuple : tuple
            The gate string as a tuple of gate labels.
        gateStringStr : string
            The gate string as represented as a string in the dataline
        counts : list
            List of counts following the gate string.
        """

        # get counts from end of s
        parts = s.split();
        counts = []
        for p in reversed(parts):
            try:
                f = float(p)
            except:
                break
            counts.append(f)
        counts.reverse()  # because we appended them in reversed order
        totalCounts = len(counts)  # in case expectedCounts is less
        if len(counts) > expectedCounts >= 0:
            counts = counts[0:expectedCounts]

        nCounts = len(counts)
        if expectedCounts >= 0 and nCounts != expectedCounts:
            raise ValueError("Found %d count columns when %d were expected" % (nCounts, expectedCounts))
        if nCounts == len(parts):
            raise ValueError("No gatestring column found -- all columns look like data")

        gateStringStr = " ".join(parts[0:len(parts)-totalCounts])
        gateStringTuple = self.parse_gatestring(gateStringStr, lookup)
        return gateStringTuple, gateStringStr, counts

    def parse_dictline(self, s):
        """
        Parse a gatestring dictionary line (dictline in grammar)

        Parameters
        ----------
        s : string
            The string to parse.

        Returns
        -------
        gateStringLabel : string
            The user-defined label to represent this gate string.
        gateStringTuple : tuple
            The gate string as a tuple of gate labels.
        gateStringStr : string
            The gate string as represented as a string in the dictline.
        """
        label = r'\s*([a-zA-Z0-9_]+)\s+'
        match = re.match(label, s)
        if not match:
            raise ValueError("'{}' is not a valid dictline".format(s))
        gateStringLabel = match.group(1)
        gateStringStr = s[match.end():]
        gateStringTuple = self._string_parser.parse(gateStringStr)
        return gateStringLabel, gateStringTuple, gateStringStr

    def parse_stringfile(self, filename):
        """
        Parse a gatestring list file.

        Parameters
        ----------
        filename : string
            The file to parse.

        Returns
        -------
        list of GateStrings
            The gatestrings read from the file.
        """
        gatestring_list = [ ]
        with open(filename, 'r') as stringfile:
            for line in stringfile:
                line = line.strip()
                if len(line) == 0 or line[0] =='#': continue
                gatestring_list.append( _objs.GateString(self.parse_gatestring(line), line) )
        return gatestring_list

    def parse_dictfile(self, filename):
        """
        Parse a gatestring dictionary file.

        Parameters
        ----------
        filename : string
            The file to parse.

        Returns
        -------
        dict
           Dictionary with keys == gate string labels and values == GateStrings.
        """
        lookupDict = { }
        with open(filename, 'r') as dictfile:
            for line in dictfile:
                line = line.strip()
                if len(line) == 0 or line[0] =='#': continue
                label, tup, s = self.parse_dictline(line)
                lookupDict[ label ] = _objs.GateString(tup, s)
        return lookupDict

    def parse_datafile(self, filename, showProgress=True,
                       collisionAction="aggregate",
                       measurementGates=None):
        """
        Parse a data set file into a DataSet object.

        Parameters
        ----------
        filename : string
            The file to parse.

        showProgress : bool, optional
            Whether or not progress should be displayed

        collisionAction : {"aggregate", "keepseparate"}
            Specifies how duplicate gate sequences should be handled.  "aggregate"
            adds duplicate-sequence counts, whereas "keepseparate" tags duplicate-
            sequence data with by appending a final "#<number>" gate label to the
            duplicated gate sequence.

        measurementGates : dict, optional
            If not None, a dictrionary whose keys are user-defined "measurement
            labels" and whose values are lists if gate labels.  The gate labels 
            in each list define the set of gates which describe the the operation
            that is performed contingent on a *specific outcome* of the measurement
            labelled by the key.  For example, `{ 'Zmeasure': ['Gmz_0','Gmz_1'] }`.

        Returns
        -------
        DataSet
            A static DataSet object.
        """

        #Parse preamble -- lines beginning with # or ## until first non-# line
        preamble_directives = { }
        preamble_comments = []
        with open(filename, 'r') as datafile:
            for line in datafile:
                line = line.strip()
                if len(line) == 0 or line[0] != '#': break
                if line.startswith("## "):
                    parts = line[len("## "):].split("=")
                    if len(parts) == 2: # key = value
                        preamble_directives[ parts[0].strip() ] = parts[1].strip()
                elif line.startswith("#"):
                    preamble_comments.append(line[1:].strip())

        #Process premble
        orig_cwd = _os.getcwd()
        if len(_os.path.dirname(filename)) > 0: _os.chdir( _os.path.dirname(filename) ) #allow paths relative to datafile path
        try:
            if 'Lookup' in preamble_directives:
                lookupDict = self.parse_dictfile( preamble_directives['Lookup'] )
            else: lookupDict = { }
            if 'Columns' in preamble_directives:
                colLabels = [ l.strip() for l in preamble_directives['Columns'].split(",") ]
            else: colLabels = [ '1 count', 'count total' ] #  spamLabel (' frequency' | ' count') | 'count total' |  ?? 'T0' | 'Tf' ??
            spamLabels,fillInfo = self._extractLabelsFromColLabels(colLabels)
            nDataCols = len(colLabels)
        finally:
            _os.chdir(orig_cwd)

        #Read data lines of data file
        dataset = _objs.DataSet(spamLabels=spamLabels,collisionAction=collisionAction,
                                comment="\n".join(preamble_comments),
                                measurementGates=measurementGates)
        nLines  = 0
        with open(filename, 'r') as datafile:
            nLines = sum(1 for line in datafile)
        nSkip = int(nLines / 100.0)
        if nSkip == 0: nSkip = 1

        display_progress = get_display_progress_fn(showProgress)

        countDict = {}
        with open(filename, 'r') as inputfile:
            for (iLine,line) in enumerate(inputfile):
                if iLine % nSkip == 0 or iLine+1 == nLines: display_progress(iLine+1, nLines, filename)

                line = line.strip()
                if len(line) == 0 or line[0] == '#': continue
                try:
                    gateStringTuple, gateStringStr, valueList = self.parse_dataline(line, lookupDict, nDataCols)
                except ValueError as e:
                    raise ValueError("%s Line %d: %s" % (filename, iLine, str(e)))

                self._fillDataCountDict( countDict, fillInfo, valueList )
                if all([ (abs(v) < 1e-9) for v in list(countDict.values())]):
                    _warnings.warn( "Dataline for gateString '%s' has zero counts and will be ignored" % gateStringStr)
                    continue #skip lines in dataset file with zero counts (no experiments done)
                gateStr = _objs.GateString(gateStringTuple, gateStringStr, lookup=lookupDict)
                dataset.add_count_dict(gateStr, countDict)

        dataset.done_adding_data()
        return dataset

    def _extractLabelsFromColLabels(self, colLabels ):
        spamLabels = []; countCols = []; freqCols = []; impliedCountTotCol1Q = (-1,-1)
        for i,colLabel in enumerate(colLabels):
            if colLabel.endswith(' count'):
                spamLabel = colLabel[:-len(' count')]
                if spamLabel not in spamLabels: spamLabels.append( spamLabel )
                countCols.append( (spamLabel,i) )

            elif colLabel.endswith(' frequency'):
                if 'count total' not in colLabels:
                    raise ValueError("Frequency columns specified without count total")
                else: iTotal = colLabels.index( 'count total' )
                spamLabel = colLabel[:-len(' frequency')]
                if spamLabel not in spamLabels: spamLabels.append( spamLabel )
                freqCols.append( (spamLabel,i,iTotal) )

        if 'count total' in colLabels:
            if '1' in spamLabels and '0' not in spamLabels:
                spamLabels.append('0')
                impliedCountTotCol1Q = '0', colLabels.index( 'count total' )
            elif '0' in spamLabels and '1' not in spamLabels:
                spamLabels.append('1')
                impliedCountTotCol1Q = '1', colLabels.index( 'count total' )
            #TODO - add standard count completion for 2Qubit case?

        fillInfo = (countCols, freqCols, impliedCountTotCol1Q)
        return spamLabels, fillInfo


    def _fillDataCountDict(self, countDict, fillInfo, colValues):
        countCols, freqCols, impliedCountTotCol1Q = fillInfo

        for spamLabel,iCol in countCols:
            if colValues[iCol] > 0 and colValues[iCol] < 1:
                raise ValueError("Count column (%d) contains value(s) " % iCol +
                                 "between 0 and 1 - could this be a frequency?")
            countDict[spamLabel] = colValues[iCol]

        for spamLabel,iCol,iTotCol in freqCols:
            if colValues[iCol] < 0 or colValues[iCol] > 1.0:
                raise ValueError("Frequency column (%d) contains value(s) " % iCol +
                                 "outside of [0,1.0] interval - could this be a count?")
            countDict[spamLabel] = colValues[iCol] * colValues[iTotCol]

        if impliedCountTotCol1Q[1] >= 0:
            impliedSpamLabel, impliedCountTotCol = impliedCountTotCol1Q
            if impliedSpamLabel == '0':
                countDict['0'] = colValues[impliedCountTotCol] - countDict['1']
            else:
                countDict['1'] = colValues[impliedCountTotCol] - countDict['0']
        #TODO - add standard count completion for 2Qubit case?
        return countDict


    def parse_multidatafile(self, filename, showProgress=True,
                            collisionAction="aggregate"):
        """
        Parse a multiple data set file into a MultiDataSet object.

        Parameters
        ----------
        filename : string
            The file to parse.

        showProgress : bool, optional
            Whether or not progress should be displayed

        collisionAction : {"aggregate", "keepseparate"}
            Specifies how duplicate gate sequences should be handled.  "aggregate"
            adds duplicate-sequence counts, whereas "keepseparate" tags duplicate-
            sequence data with by appending a final "#<number>" gate label to the
            duplicated gate sequence.

        Returns
        -------
        MultiDataSet
            A MultiDataSet object.
        """

        #Parse preamble -- lines beginning with # or ## until first non-# line
        preamble_directives = { }
        preamble_comments = []
        with open(filename, 'r') as multidatafile:
            for line in multidatafile:
                line = line.strip()
                if len(line) == 0 or line[0] != '#': break
                if line.startswith("## "):
                    parts = line[len("## "):].split("=")
                    if len(parts) == 2: # key = value
                        preamble_directives[ parts[0].strip() ] = parts[1].strip()
                elif line.startswith("#"):
                    preamble_comments.append(line[1:].strip())


        #Process premble
        orig_cwd = _os.getcwd()
        if len(_os.path.dirname(filename)) > 0:
            _os.chdir( _os.path.dirname(filename) ) #allow paths relative to datafile path
        try:
            if 'Lookup' in preamble_directives:
                lookupDict = self.parse_dictfile( preamble_directives['Lookup'] )
            else: lookupDict = { }
            if 'Columns' in preamble_directives:
                colLabels = [ l.strip() for l in preamble_directives['Columns'].split(",") ]
            else: colLabels = [ 'dataset1 1 count', 'dataset1 count total' ]
            dsSpamLabels, fillInfo = self._extractLabelsFromMultiDataColLabels(colLabels)
            nDataCols = len(colLabels)
        finally:
            _os.chdir(orig_cwd)

        #Read data lines of data file
        datasets = _OrderedDict()
        for dsLabel,spamLabels in dsSpamLabels.items():
            datasets[dsLabel] = _objs.DataSet(spamLabels=spamLabels,
                                              collisionAction=collisionAction)

        dsCountDicts = _OrderedDict()
        for dsLabel in dsSpamLabels: dsCountDicts[dsLabel] = {}

        nLines = 0
        with open(filename, 'r') as datafile:
            nLines = sum(1 for line in datafile)
        nSkip = max(int(nLines / 100.0),1)

        display_progress = get_display_progress_fn(showProgress)

        with open(filename, 'r') as inputfile:
            for (iLine,line) in enumerate(inputfile):
                if iLine % nSkip == 0 or iLine+1 == nLines: display_progress(iLine+1, nLines, filename)

                line = line.strip()
                if len(line) == 0 or line[0] == '#': continue
                try:
                    gateStringTuple, gateStringStr, valueList = self.parse_dataline(line, lookupDict, nDataCols)
                except ValueError as e:
                    raise ValueError("%s Line %d: %s" % (filename, iLine, str(e)))

                gateStr = _objs.GateString(gateStringTuple, gateStringStr, lookup=lookupDict)
                self._fillMultiDataCountDicts(dsCountDicts, fillInfo, valueList)
                for dsLabel, countDict in dsCountDicts.items():                    
                    datasets[dsLabel].add_count_dict(gateStr, countDict)

        mds = _objs.MultiDataSet(comment="\n".join(preamble_comments))
        for dsLabel,ds in datasets.items():
            ds.done_adding_data()
            mds.add_dataset(dsLabel, ds)
        return mds


    #Note: spam labels must not contain spaces since we use spaces to separate
    # the spam label from the dataset label
    def _extractLabelsFromMultiDataColLabels(self, colLabels):
        dsSpamLabels = _OrderedDict()
        countCols = []; freqCols = []; impliedCounts1Q = []
        for i,colLabel in enumerate(colLabels):
            wordsInColLabel = colLabel.split() #split on whitespace into words
            if len(wordsInColLabel) < 3: continue #allow other columns we don't recognize

            if wordsInColLabel[-1] == 'count':
                spamLabel = wordsInColLabel[-2]
                dsLabel = wordsInColLabel[-3]
                if dsLabel not in dsSpamLabels:
                    dsSpamLabels[dsLabel] = [ spamLabel ]
                else: dsSpamLabels[dsLabel].append( spamLabel )
                countCols.append( (dsLabel,spamLabel,i) )

            elif wordsInColLabel[-1] == 'frequency':
                spamLabel = wordsInColLabel[-2]
                dsLabel = wordsInColLabel[-3]
                if '%s count total' % dsLabel not in colLabels:
                    raise ValueError("Frequency columns specified without" +
                                     "count total for dataset '%s'" % dsLabel)
                else: iTotal = colLabels.index( '%s count total' % dsLabel )

                if dsLabel not in dsSpamLabels:
                    dsSpamLabels[dsLabel] = [ spamLabel ]
                else: dsSpamLabels[dsLabel].append( spamLabel )
                freqCols.append( (dsLabel,spamLabel,i,iTotal) )

        for dsLabel,spamLabels in dsSpamLabels.items():
            if '%s count total' % dsLabel in colLabels:
                if '1' in spamLabels and '0' not in spamLabels:
                    dsSpamLabels[dsLabel].append('0')
                    iTotal = colLabels.index( '%s count total' % dsLabel )
                    impliedCounts1Q.append( (dsLabel, '0', iTotal) )
                if '0' in spamLabels and '1' not in spamLabels:
                    dsSpamLabels[dsLabel].append('1')
                    iTotal = colLabels.index( '%s count total' % dsLabel )
                    impliedCounts1Q.append( (dsLabel, '1', iTotal) )

            #TODO - add standard count completion for 2Qubit case?

        fillInfo = (countCols, freqCols, impliedCounts1Q)
        return dsSpamLabels, fillInfo


    def _fillMultiDataCountDicts(self, countDicts, fillInfo, colValues):
        countCols, freqCols, impliedCounts1Q = fillInfo

        for dsLabel,spamLabel,iCol in countCols:
            if colValues[iCol] > 0 and colValues[iCol] < 1:
                raise ValueError("Count column (%d) contains value(s) " % iCol +
                                 "between 0 and 1 - could this be a frequency?")
            countDicts[dsLabel][spamLabel] = colValues[iCol]

        for dsLabel,spamLabel,iCol,iTotCol in freqCols:
            if colValues[iCol] < 0 or colValues[iCol] > 1.0:
                raise ValueError("Frequency column (%d) contains value(s) " % iCol +
                                 "outside of [0,1.0] interval - could this be a count?")
            countDicts[dsLabel][spamLabel] = colValues[iCol] * colValues[iTotCol]

        for dsLabel,spamLabel,iTotCol in impliedCounts1Q:
            if spamLabel == '0':
                countDicts[dsLabel]['0'] = colValues[iTotCol] - countDicts[dsLabel]['1']
            elif spamLabel == '1':
                countDicts[dsLabel]['1'] = colValues[iTotCol] - countDicts[dsLabel]['0']

        #TODO - add standard count completion for 2Qubit case?
        return countDicts


    def parse_tddatafile(self, filename, showProgress=True):
        """ 
        Parse a data set file into a TDDataSet object.

        Parameters
        ----------
        filename : string
            The file to parse.

        showProgress : bool, optional
            Whether or not progress should be displayed

        Returns
        -------
        TDDataSet
            A static TDDataSet object.
        """

        #Parse preamble -- lines beginning with # or ## until first non-# line
        preamble_directives = _OrderedDict()
        for line in open(filename,'r'):
            line = line.strip()
            if len(line) == 0 or line[0] != '#': break
            if line.startswith("## "):
                parts = line[len("## "):].split("=")
                if len(parts) == 2: # key = value
                    preamble_directives[ parts[0].strip() ] = parts[1].strip()
        
        #Process premble
        orig_cwd = _os.getcwd()
        if len(_os.path.dirname(filename)) > 0: _os.chdir( _os.path.dirname(filename) ) #allow paths relative to datafile path
        try:
            if 'Lookup' in preamble_directives: 
                lookupDict = self.parse_dictfile( preamble_directives['Lookup'] )
            else: lookupDict = { }
        finally:
            _os.chdir(orig_cwd)

        spamLabelAbbrevs = _OrderedDict()
        for key,val in preamble_directives.items():
            if key == "Lookup": continue 
            spamLabelAbbrevs[key] = val
        spamLabels = spamLabelAbbrevs.values()

        #Read data lines of data file
        dataset = _objs.TDDataSet(spamLabels=spamLabels)
        nLines = sum(1 for line in open(filename,'r'))
        nSkip = int(nLines / 100.0)
        if nSkip == 0: nSkip = 1

        display_progress = get_display_progress_fn(showProgress)

        for (iLine,line) in enumerate(open(filename,'r')):
            if iLine % nSkip == 0 or iLine+1 == nLines: display_progress(iLine+1, nLines, filename)

            line = line.strip()
            if len(line) == 0 or line[0] == '#': continue
            try:
                parts = line.split()
                lastpart = parts[-1]
                gateStringStr = line[:-len(lastpart)].strip()
                gateStringTuple = self.parse_gatestring(gateStringStr, lookupDict)
                gateString = _objs.GateString(gateStringTuple, gateStringStr)
                timeSeriesStr = lastpart.strip()
            except ValueError as e:
                raise ValueError("%s Line %d: %s" % (filename, iLine, str(e)))

            seriesList = [ spamLabelAbbrevs[abbrev] for abbrev in timeSeriesStr ] #iter over characters in str
            timesList = list(range(len(seriesList))) #FUTURE: specify an offset and step??
            dataset.add_series_data(gateString, seriesList, timesList)
                
        dataset.done_adding_data()
        return dataset



def _evalElement(el, bComplex):
    myLocal = { 'pi': _np.pi, 'sqrt': _np.sqrt }
    exec( "element = %s" % el, {"__builtins__": None}, myLocal )
    return complex( myLocal['element'] ) if bComplex else float( myLocal['element'] )

def _evalRowList(rows, bComplex):
    return _np.array( [ [ _evalElement(x,bComplex) for x in r ] for r in rows ],
                     'complex' if bComplex else 'd' )

def read_gateset(filename):
    """
    Parse a gateset file into a GateSet object.

    Parameters
    ----------
    filename : string
        The file to parse.

    Returns
    -------
    GateSet
    """

    def add_current_label():
        if cur_format == "StateVec":
            ar = _evalRowList( cur_rows, bComplex=True )
            if ar.shape == (1,2):
                spam_vecs[cur_label] = _objs.basis.state_to_pauli_density_vec(ar[0,:])
            else: raise ValueError("Invalid state vector shape for %s: %s" % (cur_label,ar.shape))

        elif cur_format == "DensityMx":
            ar = _evalRowList( cur_rows, bComplex=True )
            if ar.shape == (2,2) or ar.shape == (4,4):
                spam_vecs[cur_label] = _objs.basis.stdmx_to_ppvec(ar)
            else: raise ValueError("Invalid density matrix shape for %s: %s" % (cur_label,ar.shape))

        elif cur_format == "PauliVec":
            spam_vecs[cur_label] = _np.transpose( _evalRowList( cur_rows, bComplex=False ) )

        elif cur_format == "UnitaryMx":
            ar = _evalRowList( cur_rows, bComplex=True )
            if ar.shape == (2,2):
                gs.gates[cur_label] = _objs.FullyParameterizedGate(
                        _tools.unitary_to_pauligate(ar))
            elif ar.shape == (4,4):
                gs.gates[cur_label] = _objs.FullyParameterizedGate(
                        _tools.unitary_to_pauligate(ar))
            else: raise ValueError("Invalid unitary matrix shape for %s: %s" % (cur_label,ar.shape))

        elif cur_format == "UnitaryMxExp":
            ar = _evalRowList( cur_rows, bComplex=True )
            if ar.shape == (2,2):
                gs.gates[cur_label] = _objs.FullyParameterizedGate(
                        _tools.unitary_to_pauligate( _expm(-1j * ar) ))
            elif ar.shape == (4,4):
                gs.gates[cur_label] = _objs.FullyParameterizedGate(
                        _tools.unitary_to_pauligate( _expm(-1j * ar) ))
            else: raise ValueError("Invalid unitary matrix exponent shape for %s: %s" % (cur_label,ar.shape))

        elif cur_format == "PauliMx":
            gs.gates[cur_label] = _objs.FullyParameterizedGate( _evalRowList( cur_rows, bComplex=False ) )


    gs = _objs.GateSet()
    spam_vecs = _OrderedDict(); spam_labels = _OrderedDict(); remainder_spam_label = ""
    identity_vec = _np.transpose( _np.array( [ _np.sqrt(2.0), 0,0,0] ) )  #default = 1-QUBIT identity vector

    basis_abbrev = "pp" #default assumed basis
    basis_dims = None

    state = "look for label"
    cur_label = ""; cur_format = ""; cur_rows = []
    with open(filename) as inputfile:
        for line in inputfile:
            line = line.strip()

            if len(line) == 0:
                state = "look for label"
                if len(cur_label) > 0:
                    add_current_label()
                    cur_label = ""; cur_rows = []
                continue

            if line[0] == "#":
                continue

            if state == "look for label":
                if line.startswith("SPAMLABEL "):
                    eqParts = line[len("SPAMLABEL "):].split('=')
                    if len(eqParts) != 2: raise ValueError("Invalid spam label line: ", line)
                    if eqParts[1].strip() == "remainder":
                        remainder_spam_label = eqParts[0].strip()
                    else:
                        spam_labels[ eqParts[0].strip() ] = [ s.strip() for s in eqParts[1].split() ]

                elif line.startswith("IDENTITYVEC "):  #Vectorized form of identity density matrix in whatever basis is used
                    if line != "IDENTITYVEC None":  #special case for designating no identity vector, so default is not used
                        identity_vec  = _np.transpose( _evalRowList( [ line[len("IDENTITYVEC "):].split() ], bComplex=False ) )

                elif line.startswith("BASIS "): # Line of form "BASIS <abbrev> [<dims>]", where optional <dims> is comma-separated integers
                    parts = line[len("BASIS "):].split()
                    basis_abbrev = parts[0]
                    if len(parts) > 1:
                        basis_dims = list(map(int, "".join(parts[1:]).split(",")))
                        if len(basis_dims) == 1: basis_dims = basis_dims[0]
                    elif gs.get_dimension() is not None:
                        basis_dims = int(round(_np.sqrt(gs.get_dimension())))
                    elif len(spam_vecs) > 0:
                        basis_dims = int(round(_np.sqrt(list(spam_vecs.values())[0].size)))
                    else:
                        raise ValueError("BASIS directive without dimension, and cannot infer dimension!")
                else:
                    cur_label = line
                    state = "expect format"

            elif state == "expect format":
                cur_format = line
                if cur_format not in ["StateVec", "DensityMx", "UnitaryMx", "UnitaryMxExp", "PauliVec", "PauliMx"]:
                    raise ValueError("Expected object format for label %s and got line: %s -- must specify a valid object format" % (cur_label,line))
                state = "read object"

            elif state == "read object":
                cur_rows.append( line.split() )

    if len(cur_label) > 0:
        add_current_label()

    #Try to infer basis dimension if none is given
    if basis_dims is None:
        if gs.get_dimension() is not None:
            basis_dims = int(round(_np.sqrt(gs.get_dimension())))
        elif len(spam_vecs) > 0:
            basis_dims = int(round(_np.sqrt(list(spam_vecs.values())[0].size)))
        else:
            raise ValueError("Cannot infer basis dimension!")

    #Set basis
    gs.basis = _objs.Basis(basis_abbrev, basis_dims)

    #Default SPAMLABEL directive if none are give and rho and E vectors are:
    if len(spam_labels) == 0 and "rho" in spam_vecs and "E" in spam_vecs:
        spam_labels['1'] = [ 'rho', 'E' ]
        spam_labels['0'] = [ 'rho', 'remainder' ] #NEW default behavior
        # OLD default behavior: remainder_spam_label = 'minus'
    if len(spam_labels) == 0: raise ValueError("Must specify rho and E or spam labels directly.")

    #Make SPAMs
     #get unique rho and E names
    rho_names = list(_OrderedDict.fromkeys( [ rho for (rho,E) in list(spam_labels.values()) ] ) ) #if this fails, may be due to malformatted
    E_names   = list(_OrderedDict.fromkeys( [ E   for (rho,E) in list(spam_labels.values()) ] ) ) #  SPAMLABEL line (not 2 items to right of = sign)
    if "remainder" in rho_names:
        del rho_names[ rho_names.index("remainder") ]
    if "remainder" in E_names:
        del E_names[ E_names.index("remainder") ]

    #Order E_names and rho_names using spam_vecs ordering
    #rho_names = sorted(rho_names, key=spam_vecs.keys().index)
    #E_names = sorted(E_names, key=spam_vecs.keys().index)

     #add vectors to gateset
    for rho_nm in rho_names: gs.preps[rho_nm] = spam_vecs[rho_nm]
    for E_nm   in E_names:   gs.effects[E_nm] = spam_vecs[E_nm]

    gs.povm_identity = identity_vec

     #add spam labels to gateset
    for spam_label in spam_labels:
        (rho_nm,E_nm) = spam_labels[spam_label]
        gs.spamdefs[spam_label] = (rho_nm , E_nm)

    if len(remainder_spam_label) > 0:
        gs.spamdefs[remainder_spam_label] = ('remainder', 'remainder')

    #Add default gauge group -- the full group because
    # we add FullyParameterizedGates above.
    gs.default_gauge_group = _objs.FullGaugeGroup(gs.dim)

    return gs
