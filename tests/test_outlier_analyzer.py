import unittest
from app.analyzers.outlier_analyzer import OutlierAnalyzer
import logging

class TestOutlierAnalyzer(unittest.TestCase):

    OUTLIER_JSON = {"metadata": {"algorithm": "Z_SCORE", "threshold": 3.0, "orderBy": "MEAN_ABS_DEV", "maxResults": 500,
                                 "count": 114}, "outlierValues": [
        {"de": "ldGXl6SEdqf", "deName": "Weight for age between middle and lower line (yellow)", "pe": "202007",
         "ou": "cgqkFdShPzg", "ouName": "Loreto Clinic", "coc": "psbwp3CQEhs", "cocName": "Fixed, >1y",
         "aoc": "HllvX50cXC0", "value": 1634.0, "mean": 328.22222222222223, "stdDev": 422.73992384192496,
         "absDev": 1305.7777777777778, "zScore": 3.0888442376359206, "lowerBound": 9.9975493035527,
         "upperBound": 1596.441993747997, "aocName": "default", "followup": False},
        {"de": "NLnXLV5YpZF", "deName": "Weight for age on or above middle line (green)", "pe": "202007",
         "ou": "cgqkFdShPzg", "ouName": "Loreto Clinic", "coc": "psbwp3CQEhs", "cocName": "Fixed, >1y",
         "aoc": "HllvX50cXC0", "value": -1582.0, "mean": 519.6386554621848, "stdDev": 350.6662262083907,
         "absDev": 1062.361344537815, "zScore": 3.0295513657665016, "lowerBound": -6.3600231629872,
         "upperBound": 1571.637334087357, "aocName": "default", "followup": False},
        {"de": "pikOziyCXbM", "deName": "OPV1 doses given", "pe": "202011", "ou": "tSBcgrTDdB8",
         "ouName": "Paramedical CHC", "coc": "Prlt0C1RF0s", "cocName": "Fixed, <1y", "aoc": "HllvX50cXC0",
         "value": -808.0, "mean": 113.37984496124031, "stdDev": 220.18865039850954, "absDev": 694.6201550387597,
         "zScore": 3.1546592150939565, "lowerBound": 80.1861062342883, "upperBound": 773.945796156769,
         "aocName": "default", "followup": False},
        {"de": "I78gJm4KBo7", "deName": "Penta2 doses given", "pe": "202010", "ou": "mzsOsz0NwNY",
         "ouName": "New Police Barracks CHC", "coc": "Prlt0C1RF0s", "cocName": "Fixed, <1y", "aoc": "HllvX50cXC0",
         "value": 751.0, "mean": 73.68217054263566, "stdDev": 194.02057688748857, "absDev": 677.3178294573644,
         "zScore": 3.490958744288948, "lowerBound": 508.37956011983005, "upperBound": 655.7439012051013,
         "aocName": "default", "followup": False},
        {"de": "tU7GixyHhsv", "deName": "Vitamin A given to < 5y", "pe": "202010", "ou": "cgqkFdShPzg",
         "ouName": "Loreto Clinic", "coc": "Prlt0C1RF0s", "cocName": "Fixed, <1y", "aoc": "HllvX50cXC0",
         "value": 830.0, "mean": 197.12605042016807, "stdDev": 204.18382534240962, "absDev": 632.8739495798319,
         "zScore": 3.099530281198929, "lowerBound": 15.4254256070608, "upperBound": 809.677526447397,
         "aocName": "default", "followup": False},
    ]}

    OUTLIER_JSON_FILTERED_VALUE_0 = {
        "metadata": {"algorithm": "Z_SCORE", "threshold": 3.0, "orderBy": "MEAN_ABS_DEV", "maxResults": 500,
                     "count": 114}, "outlierValues": [
            {"de": "ldGXl6SEdqf", "deName": "Weight for age between middle and lower line (yellow)", "pe": "202007",
             "ou": "cgqkFdShPzg", "ouName": "Loreto Clinic", "coc": "psbwp3CQEhs", "cocName": "Fixed, >1y",
             "aoc": "HllvX50cXC0", "value": 1634.0, "mean": 328.22222222222223, "stdDev": 422.73992384192496,
             "absDev": 1305.7777777777778, "zScore": 3.0888442376359206, "lowerBound": 9.9975493035527,
             "upperBound": 1596.441993747997, "aocName": "default", "followup": False},
            {"de": "I78gJm4KBo7", "deName": "Penta2 doses given", "pe": "202010", "ou": "mzsOsz0NwNY",
             "ouName": "New Police Barracks CHC", "coc": "Prlt0C1RF0s", "cocName": "Fixed, <1y",
             "aoc": "HllvX50cXC0",
             "value": 751.0, "mean": 73.68217054263566, "stdDev": 194.02057688748857, "absDev": 677.3178294573644,
             "zScore": 3.490958744288948, "lowerBound": 508.37956011983005, "upperBound": 655.7439012051013,
             "aocName": "default", "followup": False},
            {"de": "tU7GixyHhsv", "deName": "Vitamin A given to < 5y", "pe": "202010", "ou": "cgqkFdShPzg",
             "ouName": "Loreto Clinic", "coc": "Prlt0C1RF0s", "cocName": "Fixed, <1y", "aoc": "HllvX50cXC0",
             "value": 830.0, "mean": 197.12605042016807, "stdDev": 204.18382534240962, "absDev": 632.8739495798319,
             "zScore": 3.099530281198929, "lowerBound": 15.4254256070608, "upperBound": 809.677526447397,
             "aocName": "default", "followup": False},
        ]}

    OUTLIER_JSON_FILTERED_VALUE_1000 = {
        "metadata": {"algorithm": "Z_SCORE", "threshold": 3.0, "orderBy": "MEAN_ABS_DEV", "maxResults": 500,
                     "count": 114}, "outlierValues": [
            {"de": "ldGXl6SEdqf", "deName": "Weight for age between middle and lower line (yellow)", "pe": "202007",
             "ou": "cgqkFdShPzg", "ouName": "Loreto Clinic", "coc": "psbwp3CQEhs", "cocName": "Fixed, >1y",
             "aoc": "HllvX50cXC0", "value": 1634.0, "mean": 328.22222222222223, "stdDev": 422.73992384192496,
             "absDev": 1305.7777777777778, "zScore": 3.0888442376359206, "lowerBound": 9.9975493035527,
             "upperBound": 1596.441993747997, "aocName": "default", "followup": False},
        ]}

    def setUp(self):
        self.analyzer = OutlierAnalyzer(
            config={
                'server': {
                    'base_url': 'http://localhost',
                    'd2_token': 'fake-token',
                    'default_coc': 'HllvX50cXC0'
                }
            },
            base_url='http://localhost',
            headers={}
        )

    def _process(self, outlier_json, lower_bound, return_raw=None):
        kwargs = {} if return_raw is None else {'return_raw': return_raw}

        return self.analyzer._process_outlier_results(
            outlier_json, "vaYRah9aFHM", lower_bound, "PKEP8aBjv8Q", **kwargs
        )

    def test_false_and_blank_are_equivalent(self):
        for lower_bound in [0, 500, 2000]:
            with self.subTest(lower_bound=lower_bound):
                self.assertEqual(
                    self._process(self.OUTLIER_JSON, lower_bound),
                    self._process(self.OUTLIER_JSON, lower_bound, return_raw=False)
                )

    def test_data_values_unchanged_by_return_raw(self):
        for lower_bound in [0, 1000]:
            with self.subTest(lower_bound=lower_bound):
                self.assertEqual(
                    self._process(self.OUTLIER_JSON, lower_bound)['data_values'],
                    self._process(self.OUTLIER_JSON, lower_bound, return_raw=True)['data_values']
                )

    def test_raw_outliers_empty_when_not_returning_raw(self):
        for lower_bound in [0, 1000]:
            with self.subTest(lower_bound=lower_bound):
                self.assertEqual(self._process(self.OUTLIER_JSON, lower_bound)['raw_outliers'], [])

    def test_raw_outliers_filtered_by_lower_bound_0(self):
        self.assertEqual(self._process(self.OUTLIER_JSON, 0, return_raw=True)['raw_outliers'], self.OUTLIER_JSON_FILTERED_VALUE_0['outlierValues'])

    def test_raw_outliers_filtered_by_lower_bound_1000(self):
        self.assertEqual(self._process(self.OUTLIER_JSON, 1000, return_raw=True)['raw_outliers'], self.OUTLIER_JSON_FILTERED_VALUE_1000['outlierValues'])

if __name__ == "__main__":
    unittest.main()