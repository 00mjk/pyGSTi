import unittest
import pygsti
import numpy as np
import pickle

from  pygsti.objects import DenseOperator
import pygsti.construction as pc
import scipy.sparse as sps

from ..testutils import BaseTestCase, compare_files, temp_files

class GateTestCase(BaseTestCase):

    def setUp(self):
        super(GateTestCase, self).setUp()

    def test_gatemap_methods(self):
        dummyGS = pygsti.objects.ExplicitOpModel(['Q0'])
        densemx = np.array([[1,0,0,0],
                        [0,1,0,0],
                        [0,0,0,1],
                        [0,0,-1,0]],'d')
        sparsemx = sps.csr_matrix(densemx, dtype='d')

        #build a list of gates to test
        gates_to_test = []

        gates_to_test.append( pygsti.objects.LindbladOp.from_operation_matrix(
            densemx,unitaryPostfactor=None,
            ham_basis="pp", nonham_basis="pp", param_mode="cptp",
            nonham_mode="all", truncate=True, mxBasis="pp") )

        gates_to_test.append( pygsti.objects.LindbladOp.from_operation_matrix(
            sparsemx,unitaryPostfactor=None,
            ham_basis="pp", nonham_basis="pp", param_mode="cptp",
            nonham_mode="all", truncate=True, mxBasis="pp") )

        gates_to_test.append( pygsti.objects.LindbladOp.from_operation_matrix(
            None,unitaryPostfactor=densemx,
            ham_basis="pp", nonham_basis="pp", param_mode="cptp",
            nonham_mode="all", truncate=True, mxBasis="pp") )

        gates_to_test.append( pygsti.objects.LindbladOp.from_operation_matrix(
            None, unitaryPostfactor=sparsemx,
            ham_basis="pp", nonham_basis="pp", param_mode="cptp",
            nonham_mode="all", truncate=True, mxBasis="pp") )

        ppBasis = pygsti.obj.Basis.cast("pp",4)
        gates_to_test.append( pygsti.objects.LindbladOp.from_operation_matrix(
            densemx,unitaryPostfactor=None,
            ham_basis=ppBasis, nonham_basis=ppBasis, param_mode="unconstrained",
            nonham_mode="diagonal", truncate=True, mxBasis="pp") )

        ppMxs = pygsti.tools.pp_matrices(2)
        testGate= pygsti.objects.LindbladOp.from_operation_matrix(
            densemx,unitaryPostfactor=None,
            ham_basis=ppMxs, nonham_basis=ppMxs, param_mode="unconstrained",
            nonham_mode="diagonal", truncate=True, mxBasis="pp")
        gates_to_test.append( testGate )

        gates_to_test.append(pygsti.objects.LindbladOp.from_operation_matrix(
            densemx,unitaryPostfactor=None,
            ham_basis=None, nonham_basis=ppMxs, param_mode="unconstrained",
            nonham_mode="diagonal", truncate=True, mxBasis="pp"))

        compGate = pygsti.objects.ComposedOp( [testGate, testGate, testGate] )
        dummyGS.operations['Gcomp'] = compGate # so to/from vector work in tests below
        gates_to_test.append( dummyGS.operations['Gcomp'] )

        embedGate = pygsti.objects.EmbeddedOp( [('Q0',)], ['Q0'], testGate)
        dummyGS.operations['Gembed'] = embedGate # so to/from vector work in tests below
        gates_to_test.append( dummyGS.operations['Gembed'] )

        dummyGS2 = pygsti.objects.ExplicitOpModel([('Q0',),('Q1',)]) # b/c will have different dim from dummyGS
        ppBasis2x2 = pygsti.obj.Basis.cast("pp",(4,4))
        embedGate2 = pygsti.objects.EmbeddedOp( [('Q0',),('Q1',)], ['Q0'], testGate) # 2 blocks
        dummyGS2.operations['Gembed2'] = embedGate2 # so to/from vector work in tests below
        gates_to_test.append( dummyGS2.operations['Gembed2'] )

        with self.assertRaises(ValueError):
            pygsti.objects.EmbeddedOp( [('L0','foobar')], ['Q0'], testGate)
        with self.assertRaises(ValueError):
            pygsti.objects.EmbeddedOp( [('Q0',),('Q1',)], ['Q0','Q1'], testGate) #labels correspond to diff blocks

        dummyGS.to_vector() #allocates & builds .gpindices for all gates
        dummyGS2.to_vector() #allocates & builds .gpindices for all gates

        for gate in gates_to_test:
            state = np.zeros( (4,1), 'd' )
            state[0] = state[3] = 1.0

            T = pygsti.objects.FullGaugeGroupElement(
                np.array( [ [0,1,0,0],
                            [1,0,0,0],
                            [0,0,1,0],
                            [0,0,0,1] ], 'd') )
            T2 = pygsti.objects.UnitaryGaugeGroupElement(
                np.array( [ [0,1,0,0],
                            [1,0,0,0],
                            [0,0,1,0],
                            [0,0,0,1] ], 'd') )

            #test LinearOperator methods
            self.assertTrue( gate.get_dimension() in  (4,8) ) # embedded op2 has dim==8
            gate.torep().acton( pygsti.objects.FullSPAMVec(state).torep("prep"))
            if hasattr(gate, '_slow_acton'):
                gate._slow_acton(state) # for EmbeddedGateMaps

            sparseMx = gate.tosparse()

            try:
                gate.transform(T)
            except NotImplementedError: pass #OK, as this is unallowed for some gate types
            except ValueError: pass #OK, as this is unallowed for some gate types

            try:
            #if isinstance(gate, pygsti.obj.LindbladOp):
                gate.transform(T2)
            except NotImplementedError: pass #OK, as this is unallowed for some gate types
            except ValueError: pass #OK, as this is unallowed for some gate types

            try:
                gate.depolarize(0.05)
                gate.depolarize([0.05,0.10,0.15])
            except NotImplementedError: pass #OK, as this is unallowed for some gate types
            except ValueError: pass #OK, as this is unallowed for some gate types

            try:
                gate.rotate([0.01,0.02,0.03],'gm')
            except NotImplementedError: pass #OK, as this is unallowed for some gate types
            except ValueError: pass #OK, as this is unallowed for some gate types

            nP = gate.num_params()
            op2 = gate.copy()
            #Dense only: self.assertTrue( np.allclose(gate,op2) )

            v = gate.to_vector()
            gate.from_vector(v)
            #Dense only: self.assertTrue( np.allclose(gate,op2) )

            s = pickle.dumps(gate)
            op2 = pickle.loads(s)

            #other methods
            s = str(gate)
            try:
                cgate = gate.compose(gate)
            except ValueError: pass #OK, as this is unallowed for some gate types
            except NotImplementedError: pass # still a TODO item for some types (ComposedOp)

    def test_convert(self):
        densemx = np.array([[1,0,0,0],
                            [0,1,0,0],
                            [0,0,0,1],
                            [0,0,-1,0]],'d')

        basis = pygsti.obj.Basis.cast("pp",4)
        lndgate = pygsti.objects.LindbladDenseOp.from_operation_matrix(
            densemx,unitaryPostfactor=densemx,
            ham_basis=basis, nonham_basis=basis, param_mode="cptp",
            nonham_mode="all", truncate=True, mxBasis=basis)
        g = pygsti.objects.operation.convert(lndgate,"CPTP",basis)
        self.assertTrue(g is lndgate) #should be trivial (no) conversion

    def test_eigenvalue_param_gate(self):
        mx = np.array( [[ 1,   0,     0,       0],
                        [ 0,   1,     0,       0],
                        [ 0,   0,     -1, -1e-10],
                        [ 0,   0,  1e-10,     -1]], 'd')
        # degenerate (to tol) -1 evals will generate *complex* evecs
        g1 = pygsti.objects.EigenvalueParamDenseOp(
            mx,includeOffDiagsInDegen2Blocks=False,
            TPconstrainedAndUnital=False)

        mx = np.array( [[ 1,   0,     0,       0],
                        [ 0,   1,     0,       0],
                        [ 0,   0,     -1,      0],
                        [ 0,   0,     0,      -1]], 'complex')
        # 2 degenerate real pairs of evecs => should add off-diag els
        g2 = pygsti.objects.EigenvalueParamDenseOp(
            mx,includeOffDiagsInDegen2Blocks=True,
            TPconstrainedAndUnital=False)
        self.assertEqual(g2.params, [[(1.0, (0, 0))], [(1.0, (1, 1))],
                                     [(1.0, (0, 1))], [(1.0, (1, 0))], # off diags blk 1
                                     [(1.0, (2, 2))], [(1.0, (3, 3))],
                                     [(1.0, (2, 3))], [(1.0, (3, 2))]]) # off diags blk 2


        mx = np.array( [[ 1,   -0.1,     0,      0],
                        [ 0.1,    1,     0,      0],
                        [ 0,      0,     1+1,   -0.1],
                        [ 0,      0,   0.1,      1+1]], 'complex')
        # complex pairs of evecs => make sure combined parameters work
        g3 = pygsti.objects.EigenvalueParamDenseOp(
            mx,includeOffDiagsInDegen2Blocks=True,
            TPconstrainedAndUnital=False)
        self.assertEqual(g3.params, [
            [(1.0, (0, 0)), (1.0, (1, 1))], # single param that is Re part of 0,0 and 1,1 els
            [(1j, (0, 0)), (-1j, (1, 1))],  # Im part of 0,0 and 1,1 els
            [(1.0, (2, 2)), (1.0, (3, 3))], # Re part of 2,2 and 3,3 els
            [(1j, (2, 2)), (-1j, (3, 3))]   # Im part of 2,2 and 3,3 els
        ])


        mx = np.array( [[ 1,   -0.1,     0,      0],
                        [ 0.1,    1,     0,      0],
                        [ 0,      0,     1,   -0.1],
                        [ 0,      0,   0.1,      1]], 'complex')
        # 2 degenerate complex pairs of evecs => should add off-diag els
        g4 = pygsti.objects.EigenvalueParamDenseOp(
            mx,includeOffDiagsInDegen2Blocks=True,
            TPconstrainedAndUnital=False)
        self.assertArraysAlmostEqual(g4.evals, [1.+0.1j, 1.+0.1j, 1.-0.1j, 1.-0.1j]) # Note: evals are sorted!
        self.assertEqual(g4.params,[
            [(1.0, (0, 0)), (1.0, (2, 2))], # single param that is Re part of 0,0 and 2,2 els (conj eval pair, since sorted)
            [(1j, (0, 0)), (-1j, (2, 2))],  # Im part of 0,0 and 2,2 els
            [(1.0, (1, 1)), (1.0, (3, 3))], # Re part of 1,1 and 3,3 els
            [(1j, (1, 1)), (-1j, (3, 3))],  # Im part of 1,1 and 3,3 els
            [(1.0, (0, 1)), (1.0, (2, 3))], # Re part of 0,1 and 2,3 els (upper triangle)
            [(1j, (0, 1)), (-1j, (2, 3))],  # Im part of 0,1 and 2,3 els (upper triangle); (0,1) and (2,3) must be conjugates
            [(1.0, (1, 0)), (1.0, (3, 2))], # Re part of 1,0 and 3,2 els (lower triangle)
            [(1j, (1, 0)), (-1j, (3, 2))]   # Im part of 1,0 and 3,2 els (lower triangle); (1,0) and (3,2) must be conjugates
        ])




if __name__ == '__main__':
    unittest.main(verbosity=2)
