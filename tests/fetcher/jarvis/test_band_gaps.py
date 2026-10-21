"""Synthetic schema fixtures, not recovered materials or gap accuracy evidence."""
import copy
import hashlib
import json
import unittest
from lematerial_fetcher.fetcher.jarvis.band_gaps import extract_band_gaps


def fixture():
    row = {'jid': 'JVASP-1', 'atoms': {'lattice_mat': [[4,0,0],[0,4,0],[0,0,4]], 'elements': ['Si','Si'], 'coords': [[0,0,0],[.25,.25,.25]], 'cartesian': False}, 'optb88vdw_bandgap': 0., 'mbj_bandgap': 1.5, 'magmom_oszicar': 0.}
    receipt = {'source':'jarvis_dft', 'release':'synthetic-only', 'artifact_kind':'synthetic_fixture', 'archive_sha256':'a'*64, 'raw_record_sha256': digest(row)}
    return row, receipt


def digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class GapTests(unittest.TestCase):
    def test_preserve_two_methods_zero_and_actual_geometry(self):
        row, receipt = fixture()
        labels = extract_band_gaps(row, receipt)
        self.assertEqual([r['value'] for r in labels], [0.,1.5])
        self.assertEqual([r['protocol']['functional'] for r in labels], ['optB88vdW','TBmBJ'])
        self.assertEqual(len({r['geometry_sha256'] for r in labels}), 1)
        self.assertEqual(len({r['calculation_id'] for r in labels}), 2)
        self.assertTrue(all(r['unit']=='eV' and r['artifact_kind']=='synthetic_fixture' for r in labels))
        self.assertIsNone(labels[0]['evidence']['nonmagnetic'])
        self.assertFalse(labels[0]['training_eligible'])
        self.assertEqual(labels[0]['atoms'], row['atoms'])

    def test_missing_null_and_na_are_not_zero_or_filled_from_other_method(self):
        for missing in [None, 'na', 'NA', '']:
            row, receipt = fixture(); row['mbj_bandgap'] = missing; receipt['raw_record_sha256'] = digest(row)
            labels = extract_band_gaps(row, receipt)
            self.assertIsNone(labels[1]['value'])
            self.assertFalse(labels[1]['label_mask'])
            self.assertTrue(labels[0]['label_mask'])

    def test_invalid_gap_is_flagged_and_raw_preserved(self):
        for value in [-1, True, '1.2', [1.2]]:
            row, receipt = fixture(); row['mbj_bandgap'] = value; receipt['raw_record_sha256'] = digest(row)
            result = extract_band_gaps(row, receipt)[1]
            self.assertIsNone(result['value']); self.assertEqual(result['raw_value'], value)
            self.assertIn('invalid_gap', result['reasons'])

    def test_wrong_binding_and_missing_basis_fail(self):
        row, receipt = fixture(); row['jid']='JVASP-2'
        with self.assertRaises(ValueError): extract_band_gaps(row,receipt)
        row, receipt = fixture(); del row['atoms']['cartesian']; receipt['raw_record_sha256']=digest(row)
        with self.assertRaises(ValueError): extract_band_gaps(row,receipt)

    def test_geometry_validation_and_no_mutation(self):
        for mutation in ['singular', 'count', 'bool', 'finite']:
            row, receipt = fixture()
            if mutation=='singular': row['atoms']['lattice_mat'][1]=[0,0,0]
            elif mutation=='count': row['atoms']['elements'].pop()
            elif mutation=='bool': row['atoms']['coords'][0][0]=True
            else: row['atoms']['coords'][0][0]=float('inf')
            if mutation=='finite':
                with self.assertRaises(ValueError): extract_band_gaps(row,receipt)
            else:
                receipt['raw_record_sha256']=digest(row)
                with self.assertRaises(ValueError): extract_band_gaps(row,receipt)
        row,receipt=fixture(); saved=copy.deepcopy(row); labels=extract_band_gaps(row,receipt)
        labels[0]['atoms']['elements'][0]='Na'; self.assertEqual(row,saved)

    def test_published_release_must_be_pinned_not_arbitrary(self):
        row,receipt=fixture(); receipt['artifact_kind']='published'
        with self.assertRaises(ValueError): extract_band_gaps(row,receipt)
