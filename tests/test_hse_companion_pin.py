import unittest
from lematerial_fetcher.fetcher.hse_releases import FILES

class CompanionPin(unittest.TestCase):
    def test_processed_labels_are_acquired_separately_from_ase_structures(self):
        spec = FILES['aims-processed-v1']
        self.assertEqual(spec.file_id, 54101633)
        self.assertEqual(spec.size, 1616363)
        self.assertEqual(spec.md5, '7e0a1e96801d2af2eee2bc92610c8fb9')
        self.assertEqual(spec.filename, 'processed_data.json')
